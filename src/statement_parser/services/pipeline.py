import logging
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import UploadFile

from statement_parser.config import Settings
from statement_parser.errors import StatementError
from statement_parser.parsers.base import ParsedDocument
from statement_parser.parsers.docling_parser import DoclingParser
from statement_parser.parsers.pdfplumber_parser import PdfPlumberParser
from statement_parser.schemas import StatementParseResult, TableOut, Timings
from statement_parser.services.decrypt import decrypt_pdf
from statement_parser.services.intake import save_upload
from statement_parser.services.llm import build_payload

logger = logging.getLogger(__name__)

ParserName = Literal["docling", "pdfplumber"]


@dataclass(frozen=True)
class ParsedUpload:
    """A readable statement. The PDF itself is already gone; only its text and hash are kept."""

    file_name: str
    file_sha256: str
    size_bytes: int
    document: ParsedDocument
    warnings: list[str]
    decrypt_ms: int
    parse_ms: int


class StatementParseService:
    """Upload -> decrypt -> parse (with fallback). Built once at startup and shared by requests."""

    def __init__(self, settings: Settings, docling: DoclingParser, pdfplumber: PdfPlumberParser) -> None:
        self._settings = settings
        self._docling = docling
        self._pdfplumber = pdfplumber
        self._docling_slots = threading.BoundedSemaphore(settings.max_concurrent_parses)

    @property
    def docling_ready(self) -> bool:
        return self._docling.ready

    def parse_document(
        self, upload: UploadFile, password: str | None, parser_name: ParserName = "docling"
    ) -> ParsedUpload:
        warnings: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            source, file_sha256, size = save_upload(upload, tmp_dir, self._settings.max_pdf_mb)

            decrypt_start = time.perf_counter()
            plain = decrypt_pdf(source, tmp_dir, password, self._settings.max_pages)
            decrypt_ms = _elapsed_ms(decrypt_start)

            parse_start = time.perf_counter()
            document = self._parse_with_fallback(plain, parser_name, warnings)
            parse_ms = _elapsed_ms(parse_start)
        # The password and the PDF are gone once the temp directory closes.

        if len(document.markdown.strip()) < self._settings.fallback_min_chars:
            raise StatementError(422, "UNREADABLE_PDF", "Couldn't read this PDF. It may be a scan.")
        logger.info("parsed sha256=%s parser=%s pages=%d", file_sha256, document.parser, document.page_count)
        return ParsedUpload(
            file_name=upload.filename or "statement.pdf",
            file_sha256=file_sha256,
            size_bytes=size,
            document=document,
            warnings=warnings,
            decrypt_ms=decrypt_ms,
            parse_ms=parse_ms,
        )

    def parse_upload(
        self, upload: UploadFile, password: str | None, parser_name: ParserName = "docling"
    ) -> StatementParseResult:
        """Dev endpoint: parse only, and show the redacted text that the import endpoint would send to the model."""
        total_start = time.perf_counter()
        parsed = self.parse_document(upload, password, parser_name)
        doc = parsed.document
        return StatementParseResult(
            file_name=parsed.file_name,
            file_sha256=parsed.file_sha256,
            page_count=doc.page_count,
            parser_used=doc.parser,
            markdown=doc.markdown,
            tables=[TableOut(page_no=t.page_no, columns=t.columns, rows=t.rows) for t in doc.tables],
            warnings=parsed.warnings,
            timings_ms=Timings(decrypt=parsed.decrypt_ms, parse=parsed.parse_ms, total=_elapsed_ms(total_start)),
            llm=build_payload(doc.markdown),
        )

    def _parse_with_fallback(self, pdf_path: Path, parser_name: ParserName, warnings: list[str]) -> ParsedDocument:
        if parser_name == "pdfplumber":
            try:
                return self._pdfplumber.parse(pdf_path)
            except Exception as exc:
                logger.warning("pdfplumber failed", exc_info=True)
                raise StatementError(422, "UNREADABLE_PDF", "The PDF could not be parsed.") from exc

        docling_result: ParsedDocument | None = None
        try:
            docling_result = self._parse_docling(pdf_path)
        except Exception as exc:
            logger.warning("Docling failed; falling back to pdfplumber", exc_info=True)
            warnings.append(f"Docling failed ({type(exc).__name__}); used pdfplumber instead.")
        else:
            if len(docling_result.markdown.strip()) >= self._settings.fallback_min_chars:
                return docling_result
            warnings.append(
                f"Docling output was under {self._settings.fallback_min_chars} characters; used pdfplumber instead."
            )

        try:
            return self._pdfplumber.parse(pdf_path)
        except Exception as exc:
            if docling_result is not None:
                logger.warning("pdfplumber failed; keeping Docling output", exc_info=True)
                warnings.append(f"pdfplumber failed ({type(exc).__name__}); kept Docling output.")
                return docling_result
            logger.warning("Docling and pdfplumber both failed", exc_info=True)
            raise StatementError(422, "UNREADABLE_PDF", "Neither Docling nor pdfplumber could parse this PDF.") from exc

    def _parse_docling(self, pdf_path: Path) -> ParsedDocument:
        with self._docling_slots:
            return self._docling.parse(pdf_path)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
