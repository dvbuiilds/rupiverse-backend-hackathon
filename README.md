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
| `STATEMENT_MAX_PDF_MB` | `10` | Upload size limit |
| `STATEMENT_MAX_PAGES` | `50` | Page limit |
| `STATEMENT_DOCLING_OCR` | `false` | OCR for scanned PDFs (statements are normally digital) |
| `STATEMENT_FALLBACK_MIN_CHARS` | `200` | Docling output shorter than this falls back to pdfplumber |
| `STATEMENT_MAX_CONCURRENT_PARSES` | `2` | Docling conversions allowed at once |
| `STATEMENT_GEMINI_API_KEY` | unset | Gemini API key. Without it, imports fail with `INTERNAL` |
| `STATEMENT_GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model used for extraction |
| `STATEMENT_GEMINI_TIMEOUT_S` | `120` | Seconds to wait for Gemini |
| `STATEMENT_DATABASE_URL` | unset | Postgres URL. Without it, the import and ledger endpoints return 503 |
| `STATEMENT_DEMO_USER_ID` | unset | ID of the `users` row that owns all data. Required with `STATEMENT_DATABASE_URL` |

## Database

The schema is in [sql/001_mvp_schema.sql](sql/001_mvp_schema.sql) and needs PostgreSQL 15 or newer. Apply it once to an empty database:

```bash
psql "$STATEMENT_DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/001_mvp_schema.sql
```

Load the dummy data (demo user, card accounts, the "Unlinked account" placeholder, 16 categories). It is safe to run again:

```bash
psql "$STATEMENT_DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/seed.sql
```

The seeded demo user is `00000000-0000-0000-0000-000000000001`; set `STATEMENT_DEMO_USER_ID` to it. The cards have no last 4 digits in the seed. Set `account_last4` on a card to turn on the check that the PDF is for that card.

## API

Full reference: [docs/api.md](docs/api.md). Short version:

```bash
curl -X POST http://127.0.0.1:8000/v1/accounts/<account-id>/statements \
  -F "file=@/path/to/statement.pdf" \
  -F "password=your-pdf-password"
```

Every error has the shape `{"error": {"code": "...", "message": "..."}}`.

## Try it with your own statements

Keep statements **outside** this repo, for example in a sibling `../Statements` folder, with a `passwords.txt` next to them (one `<file name> = <password>` line per PDF).

```bash
uv run python scripts/demo_import.py ../Statements "file.pdf=<account-id>"   # full import into an account
uv run python scripts/check_gemini.py                    # one tiny Gemini call to check the key and schema
uv run python scripts/compare_parsers.py ../Statements   # no server needed, writes out/
uv run pytest                                            # unit tests, no network
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
  schemas.py           Request/response models (contract shapes are camelCase)
  repositories.py     SQL for accounts, categories, imports, transactions and balances
  api/
    deps.py            DB pool and services
    health.py          GET /healthz
    routes.py          POST /v1/statements/parse (dev)
    statements.py      POST /v1/accounts/{id}/statements
    ledger.py          GET /v1/accounts, /v1/categories, /v1/transactions
  services/
    pipeline.py        StatementParseService: intake -> decrypt -> parse
    intake.py          Streams the upload to a temp dir, checks size and PDF signature
    decrypt.py         Decrypts with pikepdf, enforces the page limit
    redact.py          Masks identifiers before text goes to the model
    llm.py             Gemini extraction (google-genai) and its prompt
    validate.py        Row checks, category rules, transfer shape, reconciliation
    importer.py        Import flow: opening date, dedupe, transfers, merchants, balance
  parsers/             Docling (primary) and pdfplumber (fallback)
sql/                   Schema (001_mvp_schema.sql) and dummy seed data (seed.sql), applied with psql
scripts/               Dev helpers (demo clients, Gemini check, parser comparison)
tests/                 Unit tests for the import rules
docs/                  API reference, proposed database schema
```

## Notes and limitations

- **No auth yet.** All data belongs to `STATEMENT_DEMO_USER_ID`.
- **Passwords and statements are not stored.** The upload and its decrypted copy live in a temp directory deleted when the request ends. Logs record the file hash and counts, never the filename, password or transaction text.
- **Redacted statement text is sent to Google's Gemini API** for extraction (`services/llm.py`). The password and the PDF itself are not sent. Merchant names and amounts are sent, so check the free-tier data terms before using real statements.
- **Imports are saved directly.** Each import writes `statement_imports`, `import_rows` (the rows added) and `transactions`. The file name and password are not saved, but the narration is, so restrict access to that database.
- **Card numbers are masked before the model call.** Digit runs of 9 or more keep only the last 4 digits, and emails and phone numbers are removed. UPI payee names are kept, since categorization needs them.
- **Never commit statements or passwords.** `.gitignore` excludes `*.pdf`, `passwords.txt`, `out/`, `.env`, and `.venv/`.
