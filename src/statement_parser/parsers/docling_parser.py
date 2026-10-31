import time
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption

from statement_parser.parsers.base import ParsedDocument, ParsedTable


class DoclingParser:
    name = "docling"

    def __init__(self, *, ocr: bool) -> None:
        # Statements are digital PDFs, so OCR stays off unless configured.
        options = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True)
        options.table_structure_options.mode = TableFormerMode.ACCURATE
        self._converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
        self.ready = False

    def warm_up(self) -> None:
        """Load the layout and table models now, so the first request does not pay for the download and load."""
        self._converter.initialize_pipeline(InputFormat.PDF)
        self.ready = True

    def parse(self, pdf_path: Path) -> ParsedDocument:
        start = time.perf_counter()
        document = self._converter.convert(pdf_path).document

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
