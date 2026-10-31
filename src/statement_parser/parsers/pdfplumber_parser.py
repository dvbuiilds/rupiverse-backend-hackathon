import time
from pathlib import Path

import pdfplumber

from statement_parser.parsers.base import ParsedDocument, ParsedTable


class PdfPlumberParser:
    name = "pdfplumber"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        start = time.perf_counter()
        sections = []
        tables = []

        with pdfplumber.open(pdf_path) as pdf:
            for number, page in enumerate(pdf.pages, start=1):
                sections.append(f"## Page {number}\n\n{page.extract_text() or ''}")
                for raw in page.extract_tables():
                    if not raw:
                        continue
                    header, *body = raw
                    tables.append(
                        ParsedTable(
                            page_no=number,
                            columns=[cell or "" for cell in header],
                            rows=[[cell or "" for cell in row] for row in body],
                        )
                    )
            page_count = len(pdf.pages)

        return ParsedDocument(
            parser=self.name,
            markdown="\n\n".join(sections),
            page_count=page_count,
            tables=tables,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
        )
