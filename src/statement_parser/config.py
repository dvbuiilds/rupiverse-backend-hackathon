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
    max_pdf_mb: int = 20
    max_pages: int = 50

    # Parsing
    docling_ocr: bool = False
    # Docling output shorter than this is treated as a failed parse and pdfplumber is tried.
    fallback_min_chars: int = 200
    # Docling keeps large models in memory during a conversion, so cap how many run at once.
    max_concurrent_parses: int = 2

    # Extraction (Gemini). Without a key the endpoint still parses the PDF but returns no transactions.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_s: float = 120.0

    # Storage (Postgres). Without a URL the endpoint still returns results but saves nothing.
    database_url: SecretStr | None = None
    # Owner of every saved import. Stands in for the authenticated user until auth exists.
    dev_user_id: UUID | None = None


settings = Settings()
