"""Upload every statement in a folder to the running API, using passwords.txt from that folder.

Usage: uv run python scripts/demo_api.py ../Statements [http://localhost:8000]
"""

import sys
from pathlib import Path

import httpx

from passwords import load_passwords

folder = Path(sys.argv[1])
base_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
passwords = load_passwords(folder / "passwords.txt")

for pdf in sorted(folder.glob("*.pdf")):
    with pdf.open("rb") as handle:
        response = httpx.post(
            f"{base_url}/v1/statements/parse",
            files={"file": (pdf.name, handle, "application/pdf")},
            data={"password": passwords.get(pdf.name, "")},
            timeout=600,
        )
    if response.status_code == 200:
        body = response.json()
        print(
            f"{pdf.name}: 200 parser={body['parser_used']} pages={body['page_count']} "
            f"tables={len(body['tables'])} ms={body['timings_ms']['total']} warnings={body['warnings']}"
        )
    else:
        print(f"{pdf.name}: {response.status_code} {response.json()['error']}")
