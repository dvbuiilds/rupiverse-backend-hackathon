import time
from functools import lru_cache
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption

from statement_parser.config import settings
from statement_parser.parsers.base import ParsedDocument, ParsedTable


@lru_cache(maxsize=1)
def get_converter() -> DocumentConverter:
    # Built once and reused. Statements are digital PDFs, so OCR stays off unless configured.
    options = PdfPipelineOptions(do_ocr=settings.docling_ocr, do_table_structure=True)
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


class DoclingParser:
    name = "docling"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        start = time.perf_counter()
        document = get_converter().convert(pdf_path).document

        tables = []
        for table in document.tables:
            frame = table.export_to_dataframe(doc=document)
            page_no = table.prov[0].page_no if table.prov else None
            tables.append(
                ParsedTable(
                    page_no=page_no,
                    columns=[str(column) for column in frame.columns],
                    rows=frame.astype(str).values.tolist(),
                )
            )

        return ParsedDocument(
            parser=self.name,
            markdown=document.export_to_markdown(),
            page_count=len(document.pages),
            tables=tables,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
        )
