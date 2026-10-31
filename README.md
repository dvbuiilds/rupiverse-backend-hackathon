# Rupiverse Backend: Statement Parser

Backend service for the Rupiverse hackathon project. The current build is the **statement parser**: a FastAPI service that takes a password-protected credit card statement PDF, decrypts it in memory, extracts its text and tables with [Docling](https://github.com/docling-project/docling) (pdfplumber as a fallback), and returns the content plus the exact payload that would be sent to an LLM.

## Quick start

Prerequisites: Git and [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 for you if it is missing.

```bash
brew install uv                 # macOS; see docs.astral.sh/uv for other platforms
git clone https://github.com/dvbuiilds/rupiverse-backend-hackathon.git
cd rupiverse-backend-hackathon
uv sync                         # creates .venv and installs locked dependencies
uv run uvicorn statement_parser.main:app --reload
```

Open http://localhost:8000/docs to try the endpoint in the browser.

The first parse downloads Docling's layout and table models from Hugging Face. This happens once and makes the first request slow.

## Try it with your own statements

Keep your statements **outside** this repo, for example in a sibling `../Statements` folder. Add a `passwords.txt` next to them with one `<file name> = <password>` line per PDF:

```text
HDFC_statement_oct.pdf = your-pdf-password
```

Then, with the server running:

```bash
uv run python scripts/demo_api.py ../Statements
```

To compare the Docling and pdfplumber output for each statement (no server needed), run:

```bash
uv run python scripts/compare_parsers.py ../Statements
```

This writes the results to `out/`. The folder is git-ignored because it contains real statement data.

## API

### `POST /v1/statements/parse`

Form fields:

| Field      | Required | Description                                                  |
| ---------- | -------- | ------------------------------------------------------------ |
| `file`     | yes      | Credit card statement PDF                                    |
| `password` | no       | PDF password, if the file is encrypted                       |
| `parser`   | no       | `docling` (default) or `pdfplumber`                          |

```bash
curl -X POST http://localhost:8000/v1/statements/parse \
  -F "file=@/path/to/statement.pdf" \
  -F "password=your-pdf-password" \
  -F "parser=docling"
```

The response includes `file_sha256`, `page_count`, `parser_used`, `markdown`, `tables`, `warnings`, `timings_ms`, and `llm` (the system prompt and user content that would go to the model).

Errors use this shape: `{"error": {"code": "...", "message": "..."}}`.

| Code                                                            | Status |
| --------------------------------------------------------------- | ------ |
| `FILE_TOO_LARGE`                                                | 413    |
| `NOT_A_PDF`                                                     | 415    |
| `PDF_PASSWORD_REQUIRED`, `PDF_PASSWORD_INVALID`, `PARSE_FAILED` | 422    |

### `GET /healthz`

Returns `{"status": "ok", "docling_converter_ready": ...}`.

## Configuration

Settings are read from environment variables with the `STATEMENT_` prefix:

| Variable                     | Default                      | Purpose                                                          |
| ---------------------------- | ---------------------------- | ---------------------------------------------------------------- |
| `STATEMENT_MAX_PDF_MB`       | `20`                         | Upload size limit                                                |
| `STATEMENT_DOCLING_OCR`      | `false`                      | Enable OCR for scanned PDFs (statements are normally digital)    |
| `STATEMENT_FALLBACK_MIN_CHARS` | `200`                      | Docling output shorter than this falls back to pdfplumber        |
| `STATEMENT_CORS_ORIGINS`     | `["http://localhost:3000"]`  | JSON list of allowed browser origins                             |

## Project layout

```text
app/
  main.py              FastAPI app, CORS, error handler, /healthz
  config.py            Settings (STATEMENT_* env vars)
  errors.py            StatementError, returned as the JSON error shape
  schemas.py           Response models
  api/routes.py        POST /v1/statements/parse
  services/
    intake.py          Streams the upload to a temp dir, checks size and PDF signature
    decrypt.py         Decrypts the PDF with pikepdf
    pipeline.py        Decrypt -> parse (with fallback) -> response
    llm.py             Builds the LLM payload (stub, no model call yet)
    parsers/           Docling (primary) and pdfplumber (backup)
scripts/
  demo_api.py          Uploads every statement in a folder to the running API
  compare_parsers.py   Runs both parsers locally and writes out/
  passwords.py         Reads passwords.txt
docs/
  database-schema.md   Proposed PostgreSQL schema for the mobile MVP (not implemented yet)
pyproject.toml, uv.lock  Dependencies (uv)
```

## Notes and limitations

- **No auth yet.** Production needs a JWT check in `app/api/routes.py`, and the user ID from the token should scope any stored data.
- **Passwords and statements are not stored.** The uploaded PDF and its decrypted copy live in a temp directory that is deleted when the request ends. Passwords are used in memory only and are never logged.
- **The LLM step is a stub.** `app/services/llm.py` builds the payload but does not call a model.
- **Never commit statements or passwords.** `.gitignore` already excludes `*.pdf`, `passwords.txt`, `out/`, and `.venv/`.
