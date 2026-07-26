from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from .config import AppConfig
from .domain import VEHICLE_FIELDS, ExtractionResult
from .prompt import BATCH_VEHICLE_ENTITY_PROMPT


MAX_BATCH_SIZE = 50
MAX_OUTPUT_TOKENS_PER_ROW = 130
MIN_MAX_OUTPUT_TOKENS = 1_200
PROMPT_CACHE_KEY_PREFIX = "vehicle-entity-long-batch50-v1"

INPUT_USD_PER_MILLION = 1.00
CACHED_INPUT_USD_PER_MILLION = 0.10
OUTPUT_USD_PER_MILLION = 6.00
CACHE_WRITE_MULTIPLIER = 1.25
LONG_CONTEXT_INPUT_TOKENS = 272_000


def build_extraction_schema(batch_size: int) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["results"],
        "properties": {
            "results": {
                "type": "array",
                "minItems": batch_size,
                "maxItems": batch_size,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["record_id", *VEHICLE_FIELDS],
                    "properties": {
                        "record_id": {"type": "integer"},
                        **{
                            field: {"type": ["string", "null"]}
                            for field in VEHICLE_FIELDS
                        },
                    },
                },
            }
        },
    }


@dataclass(frozen=True, slots=True)
class LLMExtraction:
    extraction: ExtractionResult
    cost_usd: float | None
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class LLMBatchExtraction:
    extractions: tuple[ExtractionResult, ...]
    cost_usd: float | None
    input_tokens: int
    output_tokens: int
    latency_ms: float


class LLMServiceError(RuntimeError):
    def __init__(self, status: int, public_message: str) -> None:
        super().__init__(public_message)
        self.status = status
        self.public_message = public_message


class LLMExtractor:
    def __init__(self, config: AppConfig) -> None:
        self.model = config.openai_model
        self.reasoning_effort = config.reasoning_effort
        self._semaphore = asyncio.Semaphore(8)
        self._client: AsyncOpenAI | None = None
        if config.openai_api_key:
            self._client = AsyncOpenAI(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url,
                timeout=config.request_timeout_seconds,
                max_retries=2,
            )

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def extract(self, query: str) -> LLMExtraction:
        batch = await self.extract_batch([query])
        return LLMExtraction(
            extraction=batch.extractions[0],
            cost_usd=batch.cost_usd,
            input_tokens=batch.input_tokens,
            output_tokens=batch.output_tokens,
        )

    async def extract_batch(self, queries: list[str]) -> LLMBatchExtraction:
        if self._client is None:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        if not queries or len(queries) > MAX_BATCH_SIZE:
            raise ValueError(
                f"LLM batches must contain between 1 and {MAX_BATCH_SIZE} queries."
            )

        record_ids = list(range(1, len(queries) + 1))
        user_batch = json.dumps(
            [
                {"record_id": record_id, "text": query}
                for record_id, query in zip(record_ids, queries)
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        request: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": "system", "content": BATCH_VEHICLE_ENTITY_PROMPT},
                {"role": "user", "content": user_batch},
            ],
            "max_output_tokens": max(
                MIN_MAX_OUTPUT_TOKENS,
                len(queries) * MAX_OUTPUT_TOKENS_PER_ROW,
            ),
            "store": False,
            "prompt_cache_key": f"{PROMPT_CACHE_KEY_PREFIX}:{self.model}",
            "text": {
                "verbosity": "low",
                "format": {
                    "type": "json_schema",
                    "name": "vehicle_entity_batch",
                    "strict": True,
                    "schema": build_extraction_schema(len(queries)),
                },
            },
        }
        if self.reasoning_effort:
            request["reasoning"] = {"effort": self.reasoning_effort}

        started = time.perf_counter()
        try:
            async with self._semaphore:
                response = await self._client.responses.create(**request)
        except AuthenticationError as exc:
            raise LLMServiceError(502, "OpenAI rejected the configured API key.") from exc
        except PermissionDeniedError as exc:
            raise LLMServiceError(
                502, "The OpenAI project cannot access the configured model."
            ) from exc
        except NotFoundError as exc:
            raise LLMServiceError(
                502, f"OpenAI model {self.model!r} is unavailable."
            ) from exc
        except RateLimitError as exc:
            raise LLMServiceError(429, "OpenAI rate limit reached. Try again shortly.") from exc
        except APITimeoutError as exc:
            raise LLMServiceError(504, "OpenAI did not respond before the timeout.") from exc
        except APIConnectionError as exc:
            raise LLMServiceError(502, "Could not connect to the OpenAI API.") from exc
        except BadRequestError as exc:
            raise LLMServiceError(
                502, "OpenAI rejected the extraction request configuration."
            ) from exc
        except APIError as exc:
            raise LLMServiceError(502, "OpenAI could not complete the extraction.") from exc

        latency_ms = (time.perf_counter() - started) * 1_000
        if not response.output_text:
            raise RuntimeError("The LLM returned an empty extraction.")
        try:
            payload = json.loads(response.output_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("The LLM returned invalid structured output.") from exc

        usage = response.usage
        return LLMBatchExtraction(
            extractions=self._validate_batch(payload, record_ids),
            cost_usd=self._calculate_cost(usage),
            input_tokens=int(usage.input_tokens or 0) if usage else 0,
            output_tokens=int(usage.output_tokens or 0) if usage else 0,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _calculate_cost(usage: Any) -> float | None:
        if usage is None:
            return None

        input_tokens = int(usage.input_tokens or 0)
        output_tokens = int(usage.output_tokens or 0)
        details = usage.input_tokens_details
        cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)
        cache_write_tokens = int(getattr(details, "cache_write_tokens", 0) or 0)
        uncached_tokens = max(0, input_tokens - cached_tokens - cache_write_tokens)
        input_multiplier = 2.0 if input_tokens > LONG_CONTEXT_INPUT_TOKENS else 1.0
        output_multiplier = 1.5 if input_tokens > LONG_CONTEXT_INPUT_TOKENS else 1.0

        input_cost = (
            uncached_tokens * INPUT_USD_PER_MILLION
            + cached_tokens * CACHED_INPUT_USD_PER_MILLION
            + cache_write_tokens
            * INPUT_USD_PER_MILLION
            * CACHE_WRITE_MULTIPLIER
        )
        output_cost = output_tokens * OUTPUT_USD_PER_MILLION
        return (
            input_cost * input_multiplier + output_cost * output_multiplier
        ) / 1_000_000

    @staticmethod
    def _validate_batch(
        payload: Any, expected_record_ids: list[int]
    ) -> tuple[ExtractionResult, ...]:
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or len(results) != len(expected_record_ids):
            raise RuntimeError("The LLM extraction has an invalid shape.")

        by_record_id: dict[int, ExtractionResult] = {}
        for result in results:
            if not isinstance(result, dict):
                raise RuntimeError("The LLM extraction has an invalid shape.")
            record_id = result.get("record_id")
            if isinstance(record_id, bool) or not isinstance(record_id, int):
                raise RuntimeError("The LLM extraction returned an invalid record ID.")
            if record_id in by_record_id:
                raise RuntimeError("The LLM extraction returned a duplicate record ID.")

            fields: dict[str, str | None] = {}
            for field in VEHICLE_FIELDS:
                value = result.get(field)
                if value is not None and not isinstance(value, str):
                    raise RuntimeError(f"The LLM returned an invalid {field} value.")
                fields[field] = value

            by_record_id[record_id] = ExtractionResult(
                vehicle_present=any(value is not None for value in fields.values()),
                is_complete=True,
                fields=fields,
            )

        if set(by_record_id) != set(expected_record_ids):
            raise RuntimeError("The LLM extraction returned unexpected record IDs.")
        return tuple(by_record_id[record_id] for record_id in expected_record_ids)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
