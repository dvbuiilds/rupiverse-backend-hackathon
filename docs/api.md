# API reference

Interactive docs are served at `/docs` while the server runs.
The contract the mobile app builds against is `statement-import-contract.md` in the parent folder.

## `POST /v1/accounts/{accountId}/statements`

Uploads one statement PDF to an account, extracts the transactions with Gemini, and adds the new ones to the ledger.

Form fields (`multipart/form-data`):

| Field      | Required | Description                                          |
| ---------- | -------- | ---------------------------------------------------- |
| `file`     | yes      | `application/pdf`, 10 MB max                         |
| `password` | no       | Only used to open the file. Never logged or stored.  |

Response (200), in the contract's camelCase:

```json
{
  "statement": {"id": "5f1c...", "fileName": "HDFC_Sep.pdf", "sizeBytes": 219136,
                "periodStart": "2026-09-01", "periodEnd": "2026-09-30", "status": "imported"},
  "summary": {"transactionsAdded": 42, "duplicatesIgnored": 0, "skippedBeforeOpeningDate": 0, "skipReason": null},
  "balance": {"previousPaise": 3845000, "amountPaise": 3978200, "asOf": "2026-09-30"},
  "transactions": [
    {"id": "9b2e...", "accountId": "c1...", "date": "2026-09-29", "description": "Ramesh",
     "amountPaise": -85000, "categoryId": "food"}
  ]
}
```

- `amountPaise` is negative for money out of the account, positive for money in.
- `balance.amountPaise` is the amount owed for a card (positive).
- `categoryId` is a slug from `GET /v1/categories`, or `null` when the model is not confident (under 0.8).
- `status: "skipped"` is a normal 200 with `transactions: []` and a `skipReason`: `NO_TRANSACTIONS`, `ALL_BEFORE_OPENING_DATE` or `ALL_DUPLICATES`.

Rules:
- Rows dated on or before the account's `opening_balance_date` are not stored.
- Dedupe key: date, direction, amount, narration (letters and digits, ignoring case) and running balance. Re-uploading a statement adds nothing. Two identical rows in one statement are both kept.
- Card bill payments are transfers through the "Unlinked account", so they are not income or expense.
- The card's balance is updated only when the statement is not older than the balance already stored.

Errors:

| Status | Code | When |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` | Missing file, not a PDF, over 10 MB |
| 401 | `UNAUTHENTICATED` | Missing or wrong token |
| 404 | `ACCOUNT_NOT_FOUND` | Unknown or non-UUID account, or an archived account |
| 422 | `PASSWORD_REQUIRED` / `WRONG_PASSWORD` | Encrypted PDF with no or wrong password |
| 422 | `UNREADABLE_PDF` | Scanned or damaged PDF |
| 422 | `UNRECOGNISED_STATEMENT` | Not a bank or card statement, or the card's last 4 digits do not match the account |
| 500 | `INTERNAL` | Model failure, rate limit, or anything else. Try again |
| 503 | `DATABASE_UNAVAILABLE` | `STATEMENT_DATABASE_URL` is not set |

## `GET /v1/accounts`

Lists the user's active accounts (the "Unlinked account" is left out). `balance.amountPaise` is the card's amount owed.

## `GET /v1/categories`

Lists active categories. `id` is the slug the app stores.

## `GET /v1/transactions`

Query: `accountId` (optional UUID), `from` and `to` (optional `YYYY-MM-DD`), `limit` (1 to 500, default 200).
Returns the same item shape as the import, newest first. With `accountId`, amounts are signed from that account's side.

## `POST /v1/statements/parse` (dev tool)

Parses a PDF and returns the text and tables, without calling the model. `llm` shows the system prompt and the redacted text the import endpoint would send. Form fields: `file`, `password`, `parser` (`docling` or `pdfplumber`).

## `GET /healthz`

Returns `{"status": "ok", "docling_converter_ready": true}`. No token needed.

## Error shape

Every error:

```json
{"error": {"code": "WRONG_PASSWORD", "message": "The PDF password is incorrect."}}
```
