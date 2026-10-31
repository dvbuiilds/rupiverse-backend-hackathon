# API reference

Interactive docs are served at `/docs` while the server runs.

## `POST /v1/statements/parse`

Form fields:

| Field      | Required | Description                                   |
| ---------- | -------- | --------------------------------------------- |
| `file`     | yes      | Credit card statement PDF                     |
| `password` | no       | PDF password, if the file is encrypted        |
| `parser`   | no       | `docling` (default) or `pdfplumber`           |

Response (200): `file_name`, `file_sha256`, `page_count`, `parser_used`, `markdown`, `tables`, `warnings`, `timings_ms`, and `llm` (the system prompt and user content that would go to the model).

## `GET /healthz`

Returns `{"status": "ok", "docling_converter_ready": true}`.

## Errors

Every error uses this shape:

```json
{"error": {"code": "PDF_PASSWORD_REQUIRED", "message": "This PDF is encrypted. Send its password."}}
```

| Code                                                                 | Status |
| -------------------------------------------------------------------- | ------ |
| `FILE_TOO_LARGE`                                                     | 413    |
| `NOT_A_PDF`                                                          | 415    |
| `INVALID_REQUEST`                                                    | 422    |
| `PDF_PASSWORD_REQUIRED`, `PDF_PASSWORD_INVALID`                      | 422    |
| `TOO_MANY_PAGES`, `PARSE_FAILED`                                     | 422    |
| `INTERNAL_ERROR`                                                     | 500    |
