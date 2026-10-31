"""Run Docling and pdfplumber on every statement in a folder and write the outputs to out/.

Usage: uv run python scripts/compare_parsers.py ../Statements
"""

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.errors import StatementError  # noqa: E402
from app.services.decrypt import decrypt_pdf  # noqa: E402
from app.services.parsers.docling_parser import DoclingParser  # noqa: E402
from app.services.parsers.pdfplumber_parser import PdfPlumberParser  # noqa: E402
from passwords import load_passwords  # noqa: E402

folder = Path(sys.argv[1])
out_dir = PROJECT_ROOT / "out"
out_dir.mkdir(exist_ok=True)
passwords = load_passwords(folder / "passwords.txt")
parsers = [DoclingParser(), PdfPlumberParser()]

print(f"{'file':<42} {'parser':<11} {'pages':>5} {'chars':>7} {'tables':>6} {'rows':>5} {'ms':>7}")
for pdf in sorted(folder.glob("*.pdf")):
    try:
        with tempfile.TemporaryDirectory() as tmp:
            plain = decrypt_pdf(pdf, Path(tmp), passwords.get(pdf.name))
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
