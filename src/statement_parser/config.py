from typing import Literal

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


settings = Settings()
