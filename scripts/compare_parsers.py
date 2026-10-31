"""Run Docling and pdfplumber on every statement in a folder and write the outputs to out/.

Usage: uv run python scripts/compare_parsers.py ../Statements
"""

import json
import sys
import tempfile
from pathlib import Path

from passwords import load_passwords

from statement_parser.config import settings
from statement_parser.errors import StatementError
from statement_parser.parsers.docling_parser import DoclingParser
from statement_parser.parsers.pdfplumber_parser import PdfPlumberParser
from statement_parser.services.decrypt import decrypt_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    folder = Path(sys.argv[1])
    out_dir = PROJECT_ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    passwords = load_passwords(folder / "passwords.txt")
    parsers = [DoclingParser(ocr=settings.docling_ocr), PdfPlumberParser()]

    print(f"{'file':<42} {'parser':<11} {'pages':>5} {'chars':>7} {'tables':>6} {'rows':>5} {'ms':>7}")
    for pdf in sorted(folder.glob("*.pdf")):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                plain = decrypt_pdf(pdf, Path(tmp), passwords.get(pdf.name), settings.max_pages)
                for parser in parsers:
                    parsed = parser.parse(plain)
                    (out_dir / f"{pdf.stem}.{parser.name}.md").write_text(parsed.markdown, encoding="utf-8")
                    if parser.name == "docling":
                        tables = [{"page_no": t.page_no, "columns": t.columns, "rows": t.rows} for t in parsed.tables]
                        (out_dir / f"{pdf.stem}.tables.json").write_text(json.dumps(tables, indent=2), encoding="utf-8")
                    rows = sum(len(t.rows) for t in parsed.tables)
                    print(
                        f"{pdf.name[:42]:<42} {parser.name:<11} {parsed.page_count:>5} "
                        f"{len(parsed.markdown):>7} {len(parsed.tables):>6} {rows:>5} {parsed.elapsed_ms:>7}"
                    )
        except StatementError as exc:
            print(f"{pdf.name[:42]:<42} {exc.code}: {exc.message}")


if __name__ == "__main__":
    main()
