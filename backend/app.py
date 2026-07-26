from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from typing import Any

from aiohttp import web

from .catalogue import Catalogue
from .config import AppConfig, DatabaseConfig
from .database import load_catalogue, test_connection
from .domain import VEHICLE_FIELDS, ExtractionResult
from .llm import MAX_BATCH_SIZE, LLMExtractor, LLMServiceError
from .nlp import NLPExtractor


LOGGER = logging.getLogger("automatch")
APP_CONFIG_KEY: web.AppKey[AppConfig] = web.AppKey("config", AppConfig)
SERVICE_KEY: web.AppKey["CatalogueService"] = web.AppKey("catalogue_service")
LLM_EXTRACTOR_KEY: web.AppKey[LLMExtractor] = web.AppKey(
    "llm_extractor", LLMExtractor
)
VALID_MODES = {"NLP", "LLM", "HYBRID"}
NLP_COMPONENTS = (
    "spaCy en_core_web_md, Named Entity Recognition (NER), exact catalogue matching, "
    "PostgreSQL aliases, restricted fuzzy matching"
)
LLM_COMPONENTS = "gpt-5.6-luna, benchmarked long prompt, strict structured output"


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class CatalogueService:
    def __init__(self, config: DatabaseConfig, nlp_extractor: NLPExtractor) -> None:
        self.config = config
        self.nlp_extractor = nlp_extractor
        self.catalogue: Catalogue | None = None
        self.connected = False
        self.database_name: str | None = None
        self.message = "Catalogue has not been loaded."
        self._reload_lock = asyncio.Lock()
        self._nlp_lock = asyncio.Lock()

    async def reload(self) -> None:
        async with self._reload_lock:
            records, aliases, connection_info = await asyncio.to_thread(self._load)
            catalogue = Catalogue(records, aliases)
            await asyncio.to_thread(
                self.nlp_extractor.configure, catalogue, aliases
            )
            self.catalogue = catalogue
            self.connected = True
            self.database_name = str(connection_info["database"])
            self.message = f"Loaded {len(records):,} vehicle records."

    def _load(self):
        connection_info = test_connection(self.config)
        records, aliases = load_catalogue(self.config)
        return records, aliases, connection_info

    async def extract_nlp(self, query: str):
        async with self._nlp_lock:
            return await asyncio.to_thread(self.nlp_extractor.extract, query)

    def mark_offline(self, message: str) -> None:
        self.connected = False
        self.catalogue = None
        self.message = message

    def status(self) -> dict[str, Any]:
        record_count = len(self.catalogue.records) if self.catalogue else 0
        return {
            "connected": self.connected,
            "database": self.database_name,
            "host": self.config.effective_host if self.connected else None,
            "catalogue_records": record_count,
            "catalogue_loaded": self.catalogue is not None,
            "nlp_ready": self.nlp_extractor.configured,
            "nlp_model": self.nlp_extractor.model_name,
            "message": self.message,
        }


@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except ApiError as exc:
        return web.json_response({"message": exc.message}, status=exc.status)
    except web.HTTPException:
        raise
    except Exception:
        LOGGER.exception("Unhandled request failure for %s", request.path)
        return web.json_response(
            {"message": "The server could not complete the request."}, status=500
        )


async def _json_object(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise ApiError(400, "A JSON request body is required.") from exc
    if not isinstance(payload, dict):
        raise ApiError(400, "The JSON request body must be an object.")
    return payload


async def health(request: web.Request) -> web.Response:
    service = request.app[SERVICE_KEY]
    return web.json_response(
        {
            "status": "ok",
            "llm_configured": request.app[LLM_EXTRACTOR_KEY].configured,
            "nlp_configured": service.nlp_extractor.configured,
            "nlp_model": service.nlp_extractor.model_name,
            "catalogue_loaded": service.catalogue is not None,
        }
    )


async def match_vehicle(request: web.Request) -> web.Response:
    payload = await _json_object(request)
    query = str(payload.get("query") or "").strip()
    mode = str(payload.get("mode") or "HYBRID").upper()
    config = request.app[APP_CONFIG_KEY]
    _validate_query(query, mode, config)
    return web.json_response(await _match_query(request.app, query, mode))


def _validate_query(query: str, mode: str, config: AppConfig) -> None:
    if not query:
        raise ApiError(400, "Enter a vehicle description.")
    if len(query) > config.max_query_chars:
        raise ApiError(
            400,
            f"Vehicle descriptions are limited to {config.max_query_chars} characters.",
        )
    if mode not in VALID_MODES:
        raise ApiError(400, "Mode must be NLP, LLM, or HYBRID.")


def _catalogue(app: web.Application) -> Catalogue:
    catalogue = app[SERVICE_KEY].catalogue
    if catalogue is None:
        raise ApiError(
            503,
            "The PostgreSQL catalogue is not loaded. Check the server .env settings.",
        )
    return catalogue


def _model_metadata(app: web.Application, source: str) -> tuple[str, str]:
    if source in {"NLP", "HYBRID_NLP"}:
        return app[SERVICE_KEY].nlp_extractor.model_name, NLP_COMPONENTS
    return app[LLM_EXTRACTOR_KEY].model, LLM_COMPONENTS


def _match_payload(
    app: web.Application,
    *,
    query: str,
    mode: str,
    source: str,
    extraction: ExtractionResult,
    latency_ms: float,
    llm_cost_usd: float | None = 0.0,
    llm_input_tokens: int = 0,
    llm_output_tokens: int = 0,
    llm_batch_number: int | None = None,
    llm_batch_size: int | None = None,
) -> dict[str, Any]:
    decision = _catalogue(app).match(extraction)
    model_name, components_used = _model_metadata(app, source)
    return {
        "query": query,
        "mode": mode,
        "vehicle_id": decision.vehicle_id,
        "confidence": decision.confidence,
        "status": decision.status,
        "is_complete": decision.is_complete,
        "is_decisive": decision.is_decisive,
        "source": source,
        "model_name": model_name,
        "components_used": components_used,
        "fields": decision.fields,
        "latency_ms": round(latency_ms, 1),
        "llm_cost_usd": (
            round(llm_cost_usd, 8) if llm_cost_usd is not None else None
        ),
        "llm_input_tokens": llm_input_tokens,
        "llm_output_tokens": llm_output_tokens,
        "llm_batch_number": llm_batch_number,
        "llm_batch_size": llm_batch_size,
        "error": None,
    }


async def _extract_nlp(app: web.Application, query: str) -> ExtractionResult:
    try:
        return await app[SERVICE_KEY].extract_nlp(query)
    except Exception as exc:
        LOGGER.exception("spaCy extraction failed")
        raise ApiError(503, "The en_core_web_md NLP model is unavailable.") from exc


async def _match_query(
    app: web.Application, query: str, mode: str
) -> dict[str, Any]:
    _catalogue(app)
    started = time.perf_counter()
    extraction: ExtractionResult | None = None
    source = mode
    llm_cost_usd: float | None = 0.0
    llm_input_tokens = 0
    llm_output_tokens = 0

    if mode in {"NLP", "HYBRID"}:
        extraction = await _extract_nlp(app, query)
        if mode == "NLP":
            source = "NLP"
        elif extraction.is_complete:
            source = "HYBRID_NLP"
        else:
            extraction = None
            source = "HYBRID_LLM"

    if extraction is None:
        extractor = app[LLM_EXTRACTOR_KEY]
        if not extractor.configured:
            raise ApiError(503, "OPENAI_API_KEY is not configured on the server.")
        try:
            llm_result = await extractor.extract(query)
            extraction = llm_result.extraction
            llm_cost_usd = llm_result.cost_usd
            llm_input_tokens = llm_result.input_tokens
            llm_output_tokens = llm_result.output_tokens
        except LLMServiceError as exc:
            LOGGER.exception("OpenAI extraction request failed")
            raise ApiError(exc.status, exc.public_message) from exc
        except Exception as exc:
            LOGGER.exception("LLM extraction failed")
            raise ApiError(502, "The LLM returned an invalid extraction.") from exc

    return _match_payload(
        app,
        query=query,
        mode=mode,
        source=source,
        extraction=extraction,
        latency_ms=(time.perf_counter() - started) * 1_000,
        llm_cost_usd=llm_cost_usd,
        llm_input_tokens=llm_input_tokens,
        llm_output_tokens=llm_output_tokens,
        llm_batch_number=1 if source in {"LLM", "HYBRID_LLM"} else None,
        llm_batch_size=1 if source in {"LLM", "HYBRID_LLM"} else None,
    )


def _error_payload(
    app: web.Application,
    *,
    query: str,
    mode: str,
    source: str,
    message: str,
    latency_ms: float,
    batch_number: int | None = None,
    batch_size: int | None = None,
) -> dict[str, Any]:
    model_name, components_used = _model_metadata(app, source)
    return {
        "query": query,
        "mode": mode,
        "vehicle_id": None,
        "confidence": 0,
        "status": "ERROR",
        "is_complete": False,
        "is_decisive": False,
        "source": source,
        "model_name": model_name,
        "components_used": components_used,
        "fields": {field: None for field in VEHICLE_FIELDS},
        "latency_ms": round(latency_ms, 1),
        "llm_cost_usd": 0.0,
        "llm_input_tokens": 0,
        "llm_output_tokens": 0,
        "llm_batch_number": batch_number,
        "llm_batch_size": batch_size,
        "error": message,
    }


def _allocate_integer(total: int, count: int) -> list[int]:
    quotient, remainder = divmod(total, count)
    return [quotient + (1 if index < remainder else 0) for index in range(count)]


async def _match_llm_items(
    app: web.Application,
    items: list[tuple[int, str]],
    *,
    mode: str,
    source: str,
) -> tuple[list[dict[str, Any]], int]:
    if not items:
        return [], 0

    extractor = app[LLM_EXTRACTOR_KEY]
    config = app[APP_CONFIG_KEY]
    chunks = [
        items[start : start + MAX_BATCH_SIZE]
        for start in range(0, len(items), MAX_BATCH_SIZE)
    ]
    semaphore = asyncio.Semaphore(max(1, config.batch_llm_concurrency))

    async def run_chunk(
        batch_number: int, chunk: list[tuple[int, str]]
    ) -> list[dict[str, Any]]:
        started = time.perf_counter()
        if not extractor.configured:
            return [
                {
                    "row_number": row_number,
                    **_error_payload(
                        app,
                        query=query,
                        mode=mode,
                        source=source,
                        message="OPENAI_API_KEY is not configured on the server.",
                        latency_ms=0.0,
                        batch_number=batch_number,
                        batch_size=len(chunk),
                    ),
                }
                for row_number, query in chunk
            ]

        try:
            async with semaphore:
                batch_result = await extractor.extract_batch(
                    [query for _, query in chunk]
                )
        except Exception as exc:
            LOGGER.exception("LLM batch extraction failed")
            message = (
                exc.public_message
                if isinstance(exc, LLMServiceError)
                else "The LLM could not complete this query batch."
            )
            elapsed_ms = (time.perf_counter() - started) * 1_000
            return [
                {
                    "row_number": row_number,
                    **_error_payload(
                        app,
                        query=query,
                        mode=mode,
                        source=source,
                        message=message,
                        latency_ms=elapsed_ms,
                        batch_number=batch_number,
                        batch_size=len(chunk),
                    ),
                }
                for row_number, query in chunk
            ]

        count = len(chunk)
        costs = [
            (batch_result.cost_usd / count if batch_result.cost_usd is not None else None)
            for _ in chunk
        ]
        input_tokens = _allocate_integer(batch_result.input_tokens, count)
        output_tokens = _allocate_integer(batch_result.output_tokens, count)
        return [
            {
                "row_number": row_number,
                **_match_payload(
                    app,
                    query=query,
                    mode=mode,
                    source=source,
                    extraction=extraction,
                    latency_ms=batch_result.latency_ms,
                    llm_cost_usd=cost,
                    llm_input_tokens=input_token_count,
                    llm_output_tokens=output_token_count,
                    llm_batch_number=batch_number,
                    llm_batch_size=count,
                ),
            }
            for (
                (row_number, query),
                extraction,
                cost,
                input_token_count,
                output_token_count,
            ) in zip(
                chunk,
                batch_result.extractions,
                costs,
                input_tokens,
                output_tokens,
            )
        ]

    chunk_results = await asyncio.gather(
        *(run_chunk(number, chunk) for number, chunk in enumerate(chunks, start=1))
    )
    return [row for chunk in chunk_results for row in chunk], len(chunks)


async def _process_batch(
    app: web.Application, items: list[tuple[int, str]], mode: str
) -> tuple[list[dict[str, Any]], int]:
    _catalogue(app)
    if mode == "LLM":
        return await _match_llm_items(app, items, mode=mode, source="LLM")

    async def run_nlp(row_number: int, query: str):
        started = time.perf_counter()
        try:
            extraction = await app[SERVICE_KEY].extract_nlp(query)
            return row_number, query, extraction, (time.perf_counter() - started) * 1_000, None
        except Exception as exc:
            LOGGER.exception("spaCy batch extraction failed")
            return row_number, query, None, (time.perf_counter() - started) * 1_000, exc

    nlp_results = await asyncio.gather(
        *(run_nlp(row_number, query) for row_number, query in items)
    )
    records: list[dict[str, Any]] = []
    llm_items: list[tuple[int, str]] = []
    for row_number, query, extraction, latency_ms, error in nlp_results:
        if mode == "HYBRID" and (error is not None or not extraction.is_complete):
            llm_items.append((row_number, query))
            continue
        if error is not None or extraction is None:
            records.append(
                {
                    "row_number": row_number,
                    **_error_payload(
                        app,
                        query=query,
                        mode=mode,
                        source="NLP",
                        message="The NLP model could not process this query.",
                        latency_ms=latency_ms,
                    ),
                }
            )
            continue
        records.append(
            {
                "row_number": row_number,
                **_match_payload(
                    app,
                    query=query,
                    mode=mode,
                    source="NLP" if mode == "NLP" else "HYBRID_NLP",
                    extraction=extraction,
                    latency_ms=latency_ms,
                ),
            }
        )

    llm_records, llm_requests = await _match_llm_items(
        app, llm_items, mode=mode, source="HYBRID_LLM"
    )
    records.extend(llm_records)
    records.sort(key=lambda record: record["row_number"])
    return records, llm_requests


def _batch_statistics(
    records: list[dict[str, Any]], processing_ms: float, llm_requests: int
) -> dict[str, Any]:
    total = len(records)
    statuses = Counter(str(record["status"]) for record in records)
    sources = Counter(str(record["source"]) for record in records)
    models = Counter(str(record["model_name"]) for record in records)
    field_coverage = {
        field: round(
            100
            * sum(record["fields"].get(field) is not None for record in records)
            / total,
            2,
        )
        for field in VEHICLE_FIELDS
    }
    complete = sum(bool(record["is_complete"]) for record in records)
    decisive = sum(bool(record["is_decisive"]) for record in records)
    return {
        "total_queries": total,
        "matched_queries": statuses.get("MATCHED", 0),
        "match_rate_percent": round(100 * statuses.get("MATCHED", 0) / total, 2),
        "complete_queries": complete,
        "complete_percent": round(100 * complete / total, 2),
        "decisive_queries": decisive,
        "decisive_percent": round(100 * decisive / total, 2),
        "error_queries": statuses.get("ERROR", 0),
        "average_confidence": round(
            sum(float(record["confidence"]) for record in records) / total, 2
        ),
        "processing_ms": round(processing_ms, 1),
        "average_record_latency_ms": round(
            sum(float(record["latency_ms"]) for record in records) / total, 1
        ),
        "llm_requests": llm_requests,
        "total_llm_cost_usd": round(
            sum(float(record["llm_cost_usd"] or 0.0) for record in records), 8
        ),
        "llm_input_tokens": sum(int(record["llm_input_tokens"]) for record in records),
        "llm_output_tokens": sum(int(record["llm_output_tokens"]) for record in records),
        "status_counts": dict(sorted(statuses.items())),
        "source_counts": dict(sorted(sources.items())),
        "model_counts": dict(sorted(models.items())),
        "field_coverage_percent": field_coverage,
    }


async def match_file(request: web.Request) -> web.Response:
    config = request.app[APP_CONFIG_KEY]
    if not request.content_type.startswith("multipart/"):
        raise ApiError(400, "Upload a plain-text file as multipart form data.")

    reader = await request.multipart()
    mode = "HYBRID"
    file_name = "queries.txt"
    file_bytes: bytes | None = None
    async for part in reader:
        if part.name == "mode":
            mode = (await part.text()).strip().upper()
        elif part.name == "file":
            file_name = (part.filename or file_name).replace("\\", "/").rsplit("/", 1)[-1]
            file_bytes = await part.read(decode=False)

    if mode not in VALID_MODES:
        raise ApiError(400, "Mode must be NLP, LLM, or HYBRID.")
    if file_bytes is None:
        raise ApiError(400, "Attach a plain-text query file.")
    if len(file_bytes) > config.max_upload_bytes:
        raise ApiError(413, f"The uploaded file exceeds {config.max_upload_bytes} bytes.")
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(400, "The query file must be UTF-8 plain text.") from exc

    items = [
        (line_number, line.strip())
        for line_number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    if not items:
        raise ApiError(400, "The query file contains no non-empty lines.")
    if len(items) > config.max_batch_rows:
        raise ApiError(
            400,
            f"The query file contains more than {config.max_batch_rows:,} queries.",
        )
    for line_number, query in items:
        if "\x00" in query:
            raise ApiError(400, f"Line {line_number} contains an invalid null character.")
        if len(query) > config.max_query_chars:
            raise ApiError(
                400,
                f"Line {line_number} exceeds the {config.max_query_chars}-character limit.",
            )

    started = time.perf_counter()
    records, llm_requests = await _process_batch(request.app, items, mode)
    processing_ms = (time.perf_counter() - started) * 1_000
    return web.json_response(
        {
            "file_name": file_name,
            "mode": mode,
            "statistics": _batch_statistics(records, processing_ms, llm_requests),
            "records": records,
        }
    )


async def database_status(request: web.Request) -> web.Response:
    return web.json_response(request.app[SERVICE_KEY].status())


async def spa_fallback(request: web.Request) -> web.StreamResponse:
    static_dir = request.app[APP_CONFIG_KEY].static_dir.resolve()
    requested = (static_dir / request.match_info.get("path", "")).resolve()
    if static_dir == requested or static_dir in requested.parents:
        if requested.is_file():
            return web.FileResponse(requested)
    index = static_dir / "index.html"
    if not index.is_file():
        raise ApiError(503, "The Nuxt frontend has not been built.")
    return web.FileResponse(index)


async def api_not_found(request: web.Request) -> web.Response:
    return web.json_response({"message": "API endpoint not found."}, status=404)


async def startup(app: web.Application) -> None:
    service = app[SERVICE_KEY]
    try:
        await service.reload()
        LOGGER.info(service.message)
    except Exception as exc:
        LOGGER.warning("PostgreSQL catalogue was not loaded at startup: %s", exc)
        service.mark_offline(
            "PostgreSQL is unavailable. Check the database values in .env."
        )


async def cleanup(app: web.Application) -> None:
    await app[LLM_EXTRACTOR_KEY].close()


def create_app(config: AppConfig | None = None) -> web.Application:
    config = config or AppConfig.from_environment()
    app = web.Application(
        middlewares=[error_middleware],
        client_max_size=config.max_upload_bytes + 256 * 1024,
    )
    app[APP_CONFIG_KEY] = config
    app[SERVICE_KEY] = CatalogueService(config.database, NLPExtractor())
    app[LLM_EXTRACTOR_KEY] = LLMExtractor(config)

    app.router.add_get("/api/health", health)
    app.router.add_post("/api/match", match_vehicle)
    app.router.add_post("/api/match/file", match_file)
    app.router.add_get("/api/status/database", database_status)
    app.router.add_route("*", "/api/{path:.*}", api_not_found)
    app.router.add_get("/{path:.*}", spa_fallback)
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    return app


def main() -> None:
    logging.basicConfig(
        level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = AppConfig.from_environment()
    web.run_app(create_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
