from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.app import (
    APP_CONFIG_KEY,
    LLM_EXTRACTOR_KEY,
    SERVICE_KEY,
    _process_batch,
    match_vehicle,
)
from backend.catalogue import Catalogue
from backend.config import AppConfig, DatabaseConfig, DEFAULT_OPENAI_BASE_URL
from backend.domain import ExtractionResult, VehicleRecord
from backend.llm import LLMBatchExtraction, LLMExtraction


FIELDS = {
    "make": "Toyota",
    "model": "Corolla",
    "badge": "Ascent",
    "transmission_type": "Automatic",
    "fuel_type": "Petrol",
    "drive_type": "FWD",
}


class FakeRequest:
    def __init__(self, app, payload) -> None:
        self.app = app
        self._payload = payload

    async def json(self):
        return self._payload


class FakeService:
    def __init__(self, extraction: ExtractionResult) -> None:
        self.catalogue = Catalogue(
            [VehicleRecord(id="vehicle-1", listing_count=1, **FIELDS)]
        )
        self.extraction = extraction
        self.nlp_extractor = SimpleNamespace(model_name="en_core_web_md")

    async def extract_nlp(self, query: str) -> ExtractionResult:
        return self.extraction


class FakeLLM:
    configured = True
    model = "gpt-5.6-luna"

    def __init__(self) -> None:
        self.calls = 0
        self.batch_sizes: list[int] = []
        self.active_batches = 0
        self.max_active_batches = 0

    async def extract(self, query: str) -> LLMExtraction:
        self.calls += 1
        return LLMExtraction(
            extraction=ExtractionResult(
                vehicle_present=True,
                is_complete=True,
                fields=FIELDS,
            ),
            cost_usd=0.001234,
            input_tokens=600,
            output_tokens=100,
        )

    async def extract_batch(self, queries: list[str]) -> LLMBatchExtraction:
        self.batch_sizes.append(len(queries))
        self.active_batches += 1
        self.max_active_batches = max(self.max_active_batches, self.active_batches)
        await asyncio.sleep(0.01)
        self.active_batches -= 1
        extraction = ExtractionResult(
            vehicle_present=True,
            is_complete=True,
            fields=FIELDS,
        )
        return LLMBatchExtraction(
            extractions=tuple(extraction for _ in queries),
            cost_usd=0.001 * len(queries),
            input_tokens=10 * len(queries),
            output_tokens=2 * len(queries),
            latency_ms=25.0,
        )


def config() -> AppConfig:
    return AppConfig(
        host="127.0.0.1",
        port=8080,
        openai_api_key="test",
        openai_model="gpt-5.6-luna",
        openai_base_url=DEFAULT_OPENAI_BASE_URL,
        reasoning_effort="none",
        request_timeout_seconds=60,
        max_query_chars=4000,
        static_dir=Path("/tmp"),
        database=DatabaseConfig(),
    )


class HybridRoutingTests(unittest.TestCase):
    def test_complete_nlp_skips_llm(self) -> None:
        nlp_extraction = ExtractionResult(
            vehicle_present=True,
            is_complete=True,
            fields=FIELDS,
        )
        llm = FakeLLM()
        app = {
            APP_CONFIG_KEY: config(),
            SERVICE_KEY: FakeService(nlp_extraction),
            LLM_EXTRACTOR_KEY: llm,
        }

        response = asyncio.run(
            match_vehicle(FakeRequest(app, {"query": "Toyota Corolla", "mode": "HYBRID"}))
        )
        payload = json.loads(response.text)

        self.assertEqual(payload["source"], "HYBRID_NLP")
        self.assertEqual(payload["llm_cost_usd"], 0.0)
        self.assertEqual(llm.calls, 0)

    def test_nlp_returns_zero_cost(self) -> None:
        nlp_extraction = ExtractionResult(
            vehicle_present=True,
            is_complete=True,
            fields=FIELDS,
        )
        llm = FakeLLM()
        app = {
            APP_CONFIG_KEY: config(),
            SERVICE_KEY: FakeService(nlp_extraction),
            LLM_EXTRACTOR_KEY: llm,
        }

        response = asyncio.run(
            match_vehicle(FakeRequest(app, {"query": "Toyota Corolla", "mode": "NLP"}))
        )
        payload = json.loads(response.text)

        self.assertEqual(payload["source"], "NLP")
        self.assertEqual(payload["llm_cost_usd"], 0.0)
        self.assertEqual(llm.calls, 0)

    def test_incomplete_nlp_calls_llm_and_returns_cost(self) -> None:
        nlp_extraction = ExtractionResult(
            vehicle_present=True,
            is_complete=False,
            fields={**FIELDS, "badge": None},
        )
        llm = FakeLLM()
        app = {
            APP_CONFIG_KEY: config(),
            SERVICE_KEY: FakeService(nlp_extraction),
            LLM_EXTRACTOR_KEY: llm,
        }

        response = asyncio.run(
            match_vehicle(FakeRequest(app, {"query": "Toyota Corolla", "mode": "HYBRID"}))
        )
        payload = json.loads(response.text)

        self.assertEqual(payload["source"], "HYBRID_LLM")
        self.assertEqual(payload["llm_cost_usd"], 0.001234)
        self.assertEqual(llm.calls, 1)

    def test_file_llm_uses_async_batches_of_at_most_50(self) -> None:
        nlp_extraction = ExtractionResult(
            vehicle_present=True,
            is_complete=True,
            fields=FIELDS,
        )
        llm = FakeLLM()
        app = {
            APP_CONFIG_KEY: config(),
            SERVICE_KEY: FakeService(nlp_extraction),
            LLM_EXTRACTOR_KEY: llm,
        }
        items = [(index, f"Toyota Corolla {index}") for index in range(1, 121)]

        records, request_count = asyncio.run(_process_batch(app, items, "LLM"))

        self.assertEqual(request_count, 3)
        self.assertEqual(sorted(llm.batch_sizes), [20, 50, 50])
        self.assertGreaterEqual(llm.max_active_batches, 2)
        self.assertEqual([record["row_number"] for record in records], list(range(1, 121)))
        self.assertEqual({record["model_name"] for record in records}, {"gpt-5.6-luna"})
        self.assertAlmostEqual(
            sum(record["llm_cost_usd"] for record in records),
            0.12,
        )


if __name__ == "__main__":
    unittest.main()
