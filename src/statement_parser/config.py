from typing import Literal
from uuid import UUID

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Read from STATEMENT_* environment variables, or from a .env file in the working directory."""

    model_config = SettingsConfigDict(env_prefix="STATEMENT_", env_file=".env", extra="ignore")

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Intake limits
    max_pdf_mb: int = 10
    max_pages: int = 50

    # Parsing
    docling_ocr: bool = False
    # Docling output shorter than this is treated as a failed parse and pdfplumber is tried.
    fallback_min_chars: int = 200
    # Docling keeps large models in memory during a conversion, so cap how many run at once.
    max_concurrent_parses: int = 2

    # Extraction (Gemini). Without a key, the statement import endpoint fails with INTERNAL.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_s: float = 120.0
    # Categories are only set on a row when the model is at least this sure.
    category_confidence_threshold: float = 0.8

    # Storage (Postgres). Without a URL the import and ledger endpoints return 503.
    database_url: SecretStr | None = None
    # Owner of all data. Stands in for per-user auth until a JWT check exists.
    demo_user_id: UUID | None = None


settings = Settings()
