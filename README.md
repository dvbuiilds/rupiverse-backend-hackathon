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
    llm.py             Builds the LLM payload (stub, no model call yet)
  parsers/             Docling (primary) and pdfplumber (fallback)
scripts/               Dev helpers (demo client, parser comparison)
docs/                  API reference, proposed database schema
```

## Notes and limitations

- **No auth yet.** Production needs a JWT check in `api/routes.py`, and the user ID from the token should scope any stored data.
- **Passwords and statements are not stored.** The upload and its decrypted copy live in a temp directory deleted when the request ends. Logs record the file hash, never the filename or password.
- **The LLM step is a stub.** `services/llm.py` builds the payload but does not call a model.
- **Never commit statements or passwords.** `.gitignore` excludes `*.pdf`, `passwords.txt`, `out/`, `.env`, and `.venv/`.
