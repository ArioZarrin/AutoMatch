from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"


def normalize_openai_base_url(value: str | None) -> str:
    base_url = (value or "").strip() or DEFAULT_OPENAI_BASE_URL
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "OPENAI_BASE_URL must be an absolute http:// or https:// URL."
        )
    return base_url.rstrip("/")


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    host: str = ""
    port: int = 5432
    database: str = ""
    username: str = ""
    password: str = ""
    ssl_mode: str = "prefer"
    vehicle_table: str = "public.vehicle"
    listing_table: str = "public.listing"
    alias_table: str | None = None
    running_in_docker: bool = False

    @property
    def effective_host(self) -> str:
        if self.host:
            return self.host
        return "host.docker.internal" if self.running_in_docker else "localhost"

    @classmethod
    def from_environment(cls) -> "DatabaseConfig":
        return cls(
            host=os.getenv("POSTGRES_HOST", "").strip(),
            port=int(os.getenv("POSTGRES_PORT", "5432") or "5432"),
            database=os.getenv("POSTGRES_DB", "").strip(),
            username=os.getenv("POSTGRES_USER", "").strip(),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            ssl_mode=os.getenv("POSTGRES_SSL_MODE", "prefer").strip() or "prefer",
            vehicle_table=os.getenv("POSTGRES_VEHICLE_TABLE", "public.vehicle").strip(),
            listing_table=os.getenv("POSTGRES_LISTING_TABLE", "public.listing").strip(),
            alias_table=os.getenv("POSTGRES_ALIAS_TABLE", "").strip() or None,
            running_in_docker=os.getenv("RUNNING_IN_DOCKER", "0") == "1",
        )

@dataclass(frozen=True, slots=True)
class AppConfig:
    host: str
    port: int
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    reasoning_effort: str | None
    request_timeout_seconds: float
    max_query_chars: int
    static_dir: Path
    database: DatabaseConfig
    max_batch_rows: int = 5_000
    max_upload_bytes: int = 5 * 1024 * 1024
    batch_llm_concurrency: int = 4

    @classmethod
    def from_environment(cls) -> "AppConfig":
        return cls(
            host=os.getenv("APP_HOST", "0.0.0.0"),
            port=int(os.getenv("APP_PORT", "8080")),
            openai_api_key=(
                os.getenv("OPENAI_API_KEY")
                or os.getenv("OPEN_AI_API_KEY")
                or ""
            ).strip(),
            openai_model=DEFAULT_OPENAI_MODEL,
            openai_base_url=normalize_openai_base_url(
                os.getenv("OPENAI_BASE_URL")
            ),
            reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "none").strip() or None,
            request_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "60")),
            max_query_chars=int(os.getenv("MAX_QUERY_CHARS", "4000")),
            static_dir=Path(
                os.getenv("STATIC_DIR", str(PROJECT_ROOT / "frontend" / ".output" / "public"))
            ),
            database=DatabaseConfig.from_environment(),
            max_batch_rows=int(os.getenv("MAX_BATCH_ROWS", "5000")),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))),
            batch_llm_concurrency=int(os.getenv("BATCH_LLM_CONCURRENCY", "4")),
        )
