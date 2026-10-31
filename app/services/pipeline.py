import tempfile
import time
from pathlib import Path
from typing import Literal

from fastapi import UploadFile

from app.config import settings
from app.errors import StatementError
from app.schemas import StatementParseResult, TableOut, Timings
from app.services.decrypt import decrypt_pdf
from app.services.intake import save_upload
from app.services.llm import LLMProcessor, NoopProcessor
from app.services.parsers.base import ParsedDocument
from app.services.parsers.docling_parser import DoclingParser
from app.services.parsers.pdfplumber_parser import PdfPlumberParser

DOCLING = DoclingParser()
PDFPLUMBER = PdfPlumberParser()
LLM: LLMProcessor = NoopProcessor()


def run_parse(
    upload: UploadFile,
    password: str | None,
    parser_name: Literal["docling", "pdfplumber"] = "docling",
) -> StatementParseResult:
    total_start = time.perf_counter()
    warnings: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        source, file_sha256 = save_upload(upload, tmp_dir)

        decrypt_start = time.perf_counter()
        plain = decrypt_pdf(source, tmp_dir, password or None)
        decrypt_ms = int((time.perf_counter() - decrypt_start) * 1000)

        parse_start = time.perf_counter()
        parsed = _parse_with_fallback(plain, parser_name, warnings)
        parse_ms = int((time.perf_counter() - parse_start) * 1000)

    # The password and the PDF are gone once the temp directory closes.
    return StatementParseResult(
        file_name=upload.filename or "statement.pdf",
        file_sha256=file_sha256,
        page_count=parsed.page_count,
        parser_used=parsed.parser,
        markdown=parsed.markdown,
        tables=[TableOut(page_no=t.page_no, columns=t.columns, rows=t.rows) for t in parsed.tables],
        warnings=warnings,
        timings_ms=Timings(
            decrypt=decrypt_ms,
            parse=parse_ms,
            total=int((time.perf_counter() - total_start) * 1000),
        ),
        llm=LLM.build_payload(parsed),
    )


def _parse_with_fallback(pdf_path: Path, parser_name: str, warnings: list[str]) -> ParsedDocument:
    if parser_name == "pdfplumber":
        return PDFPLUMBER.parse(pdf_path)

    docling_result: ParsedDocument | None = None
    try:
        docling_result = DOCLING.parse(pdf_path)
    except Exception as exc:
        warnings.append(f"Docling failed ({type(exc).__name__}); used pdfplumber instead.")
    else:
        if len(docling_result.markdown.strip()) >= settings.fallback_min_chars:
            return docling_result
        warnings.append(
            f"Docling output was under {settings.fallback_min_chars} characters; used pdfplumber instead."
        )

    try:
        return PDFPLUMBER.parse(pdf_path)
    except Exception as exc:
        if docling_result is not None:
            warnings.append(f"pdfplumber failed ({type(exc).__name__}); kept Docling output.")
            return docling_result
        raise StatementError(422, "PARSE_FAILED", "Neither Docling nor pdfplumber could parse this PDF.") from exc
