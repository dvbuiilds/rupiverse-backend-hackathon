# Rupiverse Backend: Statement Parser

FastAPI service that takes a password-protected credit card statement PDF, decrypts it in memory, extracts text and tables with [Docling](https://github.com/docling-project/docling) (pdfplumber as fallback), and returns the content plus the payload that would go to an LLM.

## Quick start

Prerequisites: Git and [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 if it is missing.

```bash
uv sync                          # creates .venv and installs locked dependencies
uv run statement-parser          # starts the server on 127.0.0.1:8000
```

Open http://127.0.0.1:8000/docs to try the endpoint. The server loads Docling's models at startup, so the first request is not slow.

## Configuration

Settings come from environment variables with the `STATEMENT_` prefix, or from a `.env` file in the working directory.

| Variable | Default | Purpose |
| --- | --- | --- |
| `STATEMENT_HOST` | `127.0.0.1` | Bind address |
| `STATEMENT_PORT` | `8000` | Port |
| `STATEMENT_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `STATEMENT_CORS_ORIGINS` | `["http://localhost:3000"]` | JSON list of allowed browser origins |
| `STATEMENT_MAX_PDF_MB` | `20` | Upload size limit |
| `STATEMENT_MAX_PAGES` | `50` | Page limit |
| `STATEMENT_DOCLING_OCR` | `false` | OCR for scanned PDFs (statements are normally digital) |
| `STATEMENT_FALLBACK_MIN_CHARS` | `200` | Docling output shorter than this falls back to pdfplumber |
| `STATEMENT_MAX_CONCURRENT_PARSES` | `2` | Docling conversions allowed at once |
| `STATEMENT_GEMINI_API_KEY` | unset | Gemini API key. Without it, parsing still works but `transactions` is empty |
| `STATEMENT_GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model used for extraction |
| `STATEMENT_GEMINI_TIMEOUT_S` | `120` | Seconds to wait for Gemini |
| `STATEMENT_DATABASE_URL` | unset | Postgres URL. Without it, extracted rows are returned but not saved |
| `STATEMENT_DEV_USER_ID` | unset | ID of the `users` row that owns saved imports. Required with `STATEMENT_DATABASE_URL` |

## Database

The schema is in [sql/001_mvp_schema.sql](sql/001_mvp_schema.sql) and needs PostgreSQL 15 or newer. Apply it once to an empty database:

```bash
psql "$STATEMENT_DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/001_mvp_schema.sql
```

Create the user who owns the imports, then put its ID in `STATEMENT_DEV_USER_ID`. The server checks that the user exists at startup:

```sql
INSERT INTO users (email, display_name) VALUES ('you@example.com', 'You') RETURNING id;
```

## API

Full reference: [docs/api.md](docs/api.md). Short version:

```bash
curl -X POST http://127.0.0.1:8000/v1/statements/parse \
  -F "file=@/path/to/statement.pdf" \
  -F "password=your-pdf-password" \
  -F "parser=docling"
```

Every error has the shape `{"error": {"code": "...", "message": "..."}}`.

## Try it with your own statements

Keep statements **outside** this repo, for example in a sibling `../Statements` folder, with a `passwords.txt` next to them (one `<file name> = <password>` line per PDF).

```bash
uv run python scripts/demo_api.py ../Statements          # needs the server running
uv run python scripts/compare_parsers.py ../Statements   # no server needed, writes out/
```

`out/` is git-ignored because it contains real statement data.

## Project layout

```text
src/statement_parser/
  main.py              App factory, lifespan (loads Docling), error handlers
  __main__.py          `statement-parser` entry point
  config.py            Settings
  errors.py            StatementError (returned as the JSON error shape)
  logging_config.py    Log setup
  schemas.py           Request/response models
  api/
    deps.py            Injects the parse service
    health.py          GET /healthz
    routes.py          POST /v1/statements/parse
  services/
    pipeline.py        StatementParseService: intake -> decrypt -> parse -> response
    intake.py          Streams the upload to a temp dir, checks size and PDF signature
    decrypt.py         Decrypts with pikepdf, enforces the page limit
    llm.py             Gemini extraction and the payload sent to the model
    store.py           Saves imports, stages rows, and accepts rows into the ledger
  parsers/             Docling (primary) and pdfplumber (fallback)
sql/                   Database schema, applied with psql
scripts/               Dev helpers (demo client, parser comparison)
docs/                  API reference, proposed database schema
```

## Notes and limitations

- **No auth yet.** Production needs a JWT check in `api/routes.py`, and the user ID from the token should scope any stored data.
- **Passwords and statements are not stored.** The upload and its decrypted copy live in a temp directory deleted when the request ends. Logs record the file hash and counts, never the filename, password or transaction text.
- **Parsed statement text is sent to Google's Gemini API** for extraction (`services/llm.py`). The password and the PDF itself are not sent. Only the extracted text leaves the server.
- **Extracted rows are staged in Postgres** (`statement_imports` and `import_rows`) when `STATEMENT_DATABASE_URL` is set. The file name and password are not saved, but the narration is, so restrict access to that database.
- **Nothing reaches the ledger until a row is accepted.** `POST /v1/statement-imports/{id}/accept` writes the chosen rows to `transactions`. Rows are never accepted automatically.
- **Never commit statements or passwords.** `.gitignore` excludes `*.pdf`, `passwords.txt`, `out/`, `.env`, and `.venv/`.
