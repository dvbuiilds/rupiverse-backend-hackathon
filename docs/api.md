# API reference

Interactive docs are served at `/docs` while the server runs.

## `POST /v1/statements/parse`

Form fields:

| Field      | Required | Description                                   |
| ---------- | -------- | --------------------------------------------- |
| `file`     | yes      | Credit card statement PDF                     |
| `password` | no       | PDF password, if the file is encrypted        |
| `parser`   | no       | `docling` (default) or `pdfplumber`           |

Response (200): `file_name`, `file_sha256`, `page_count`, `parser_used`, `markdown`, `tables`, `warnings`, `timings_ms`, `llm` (the system prompt and user content sent to the model), `transactions`, and `statement_import_id`.

Each item in `transactions` has `txn_date` (ISO date), `amount_paise` (integer; negative is money out, positive is money in), `narration`, and `merchant_raw` (or `null`). Without `STATEMENT_GEMINI_API_KEY`, `transactions` is `[]` and `warnings` says why.

`statement_import_id` is the UUID of the saved `statement_imports` row, whose rows are in `import_rows` with `review_status = 'pending'`. It is `null` when nothing was saved: no Gemini key, or no `STATEMENT_DATABASE_URL`. A warning says which. Re-uploading the same file creates a new import each time.

## `POST /v1/statement-imports/{import_id}/accept`

Writes the chosen staged rows to the `transactions` ledger. Nothing is accepted automatically. The request is all-or-nothing: if any row is rejected, no row is written.

Body (JSON):

```json
{
  "account_id": "9f0c...",
  "rows": [
    {"row_number": 1, "transaction_type": "expense", "category_id": "4a1e..."},
    {"row_number": 2, "transaction_type": "transfer", "transfer_kind": "credit_card_payment", "counter_account_id": "7b2d..."},
    {"row_number": 3, "skip": true}
  ]
}
```

- `account_id` is the account the rows belong to (the card, for a card statement). Staged rows have no account of their own.
- Each row is either `skip: true` or has a `transaction_type` of `expense`, `income` or `transfer`.
- A transfer needs `transfer_kind` (`interbank`, `account_transfer`, `credit_card_payment`, `cash_withdrawal` or `other`) and `counter_account_id`, and cannot have a category. Other types take neither.
- `category_id` is optional. Its flow must match the type.

Response (200): `statement_import_id`, `accepted`, `skipped`, and `pending` (rows still waiting). The import becomes `completed` when `pending` is 0.

Errors: 404 `NOT_FOUND` for an unknown import or an account that is not the user's. 422 `INVALID_REQUEST` for a bad row decision, a row that is already accepted, or a category that does not fit the ledger. 503 `DATABASE_UNAVAILABLE` when `STATEMENT_DATABASE_URL` is not set.

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
| `EXTRACTION_FAILED`                                                  | 502    |
| `NOT_FOUND`                                                          | 404    |
| `DATABASE_UNAVAILABLE`                                               | 503    |
| `INTERNAL_ERROR`                                                     | 500    |
