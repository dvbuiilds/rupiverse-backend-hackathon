from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ParsedTable:
    page_no: int | None
    columns: list[str]
    rows: list[list[str]]


@dataclass
class ParsedDocument:
    parser: str
    markdown: str
    page_count: int
    tables: list[ParsedTable]
    elapsed_ms: int


class StatementParser(Protocol):
    name: str

    def parse(self, pdf_path: Path) -> ParsedDocument: ...
