from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    max_pdf_mb: int = 20
    docling_ocr: bool = False
    # Docling output shorter than this is treated as a failed parse and pdfplumber is tried.
    fallback_min_chars: int = 200
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_prefix": "STATEMENT_"}


settings = Settings()
