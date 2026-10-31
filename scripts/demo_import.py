"""Import statements into named accounts, using passwords.txt from the statements folder.

Usage (server running):
  uv run python scripts/demo_import.py ../Statements "HDFC.pdf=<account-uuid>" ["Axis.pdf=<account-uuid>" ...]
Account IDs come from GET /v1/accounts. Prints counts only, never transaction text.
"""

import os
import sys
from pathlib import Path

import httpx
from passwords import load_passwords


def main() -> None:
    folder = Path(sys.argv[1])
    pairs = dict(arg.split("=", 1) for arg in sys.argv[2:])
    base_url = os.environ.get("STATEMENT_BASE_URL", "http://127.0.0.1:8000")
    passwords = load_passwords(folder / "passwords.txt")

    for name, account_id in pairs.items():
        with (folder / name).open("rb") as handle:
            response = httpx.post(
                f"{base_url}/v1/accounts/{account_id}/statements",
                files={"file": (name, handle, "application/pdf")},
                data={"password": passwords.get(name, "")},
                timeout=600,
            )
        if response.status_code == 200:
            body = response.json()
            print(f"{name}: {body['statement']['status']} {body['summary']}")
        else:
            print(f"{name}: {response.status_code} {response.json()['error']['code']}")


if __name__ == "__main__":
    main()
