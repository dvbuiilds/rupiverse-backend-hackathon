# Rupiverse mobile app — MVP database schema

**Status:** Proposed schema to finalize for the mobile app build  
**Target:** PostgreSQL 15+  
**Scope:** Accounts and their metadata, statement uploads and review, categorized transactions, and fast date/category/account queries.

## Design decisions

1. **`transactions` is the canonical source for financial activity.** Income, expenses, and transfers are distinguished by a constrained transaction type. Charts and spend summaries query this table.
2. **A transfer is not an expense.** A transfer between two of the user's accounts is one row with a source and destination account. A transfer across different banks is marked as interbank. Credit-card repayments are transfers; card purchases are expenses on the card account.
3. **Transactions use a date and optional time.** Statement dates are reliable for month and date-range filters; transaction time is nullable because many statements do not provide it.
4. **Categories are separate from merchants and accounts.** A category can be system-seeded, user-defined, or AI-created. The transaction also records how its current category was assigned.
5. **Statement rows are staged before becoming transactions.** Users can review extracted data and suggested categories so extraction or classification errors do not distort charts.
6. **Every table has the six requested audit fields.** System-created or automated changes may have a null actor ID; timestamps remain populated.
7. **Use check constraints, not PostgreSQL ENUM types.** This keeps the initial schema easy to evolve while constraining stored values.

## Shared conventions

All tables use UUID primary keys and include these six columns:

| Column | Type | Rule |
| --- | --- | --- |
| `created_at` | `timestamptz` | `NOT NULL DEFAULT now()` |
| `created_by` | `uuid` | Nullable FK to `users.id`; null for system/automated creation |
| `updated_at` | `timestamptz` | `NOT NULL DEFAULT now()`; update on every change |
| `updated_by` | `uuid` | Nullable FK to `users.id`; null for system/automated change |
| `deleted_at` | `timestamptz` | Nullable; null means the row is active |
| `deleted_by` | `uuid` | Nullable FK to `users.id`; set with `deleted_at` |

Use `numeric(14,2)` for money, never floating point. Persist positive transaction amounts and use transaction type/direction to determine accounting effect. Use ISO 4217 `char(3)` currency codes, defaulting to `INR` for this build. Store instants in UTC; use the user's timezone when forming calendar-month and “last 90 days” ranges. For list and chart queries, filter out soft-deleted rows.

All user-owned tables below include `user_id uuid NOT NULL REFERENCES users(id)`. For tenant safety, give each user-owned table a unique key on `(user_id, id)` and use composite `(user_id, foreign_id)` references between user-owned rows. This prevents one user's record from referencing another user's account, tag, category, merchant, or transaction.

### Common field-value conventions

- Constrain string values with `CHECK` constraints.
- For each soft-deleted row, set `deleted_at` and `deleted_by` together; otherwise both are null.
- Keep `updated_at` current through the service/repository layer or a shared database trigger.
- `created_by`, `updated_by`, and `deleted_by` identify the acting app user when known. Do not invent a user identity for a background job.

## Tables

### 1. `users`

One row per app user. Authentication-specific fields can stay aligned with the authentication implementation.

| Column | Type | Rule / meaning |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `email` | `citext` or `varchar(320)` | Required; unique among active users |
| `display_name` | `varchar(120)` | Required |
| `base_currency` | `char(3)` | Required; default `INR` |
| `timezone` | `text` | Required; default `Asia/Kolkata` |
| Shared audit fields | — | Include all six fields; user-actor FKs may be null for initial/system creation |

Do not duplicate authentication tokens in the financial tables.

### 2. `accounts`

One row per bank account, credit card, cash account, or wallet shown in the app.

| Column | Type | Rule / meaning |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `user_id` | `uuid` | Required; owner |
| `display_name` | `varchar(100)` | Required; user-facing account label |
| `account_type` | `text` | Required; one of `bank`, `credit_card`, `cash`, `wallet`, `investment`, `other` |
| `account_purpose` | `text` | Optional; one of `salary`, `savings`, `expense`, `general`, `other` |
| `institution_name` | `varchar(100)` | Optional |
| `account_last4` | `char(4)` | Optional; digits only; never store the full number for this app |
| `currency` | `char(3)` | Required; default `INR` |
| `opening_balance` | `numeric(14,2)` | Required; default `0`; amount at `opening_balance_date` |
| `opening_balance_date` | `date` | Optional |
| `current_balance` | `numeric(14,2)` | Optional cached/latest known balance; exact decimal |
| `balance_as_of` | `date` | Optional; date the balance represents |
| `last_synced_at` | `timestamptz` | Optional; last successful statement/import sync |
| `balance_source` | `text` | Optional; `statement`, `calculated`, or `manual` |
| `is_archived` | `boolean` | Required; default `false` |
| Shared audit fields | — | Include all six fields |

`account_type` describes the financial instrument; `account_purpose` describes why the user uses it. For example, a salary deposit account is `bank` + `salary`, while a credit card is `credit_card` + `expense`. “Expense” is also a transaction type/flow, not an account instrument.

The current balance is a displayed snapshot, not the source of spending analytics. Use a consistent convention: positive balances are money the user has; credit-card liabilities are negative amounts owed. For this MVP, update the balance from a statement closing balance when available or calculate it from the opening balance and accepted transactions. `last_synced_at` records import/sync time; it is not the statement period end date.

### 3. `account_tags`

Multiple custom tags per account, such as “personal”, “work”, or “travel”. Do not store a single tag string or array on `accounts`.

| Column | Type | Rule / meaning |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `user_id` | `uuid` | Required; owner |
| `account_id` | `uuid` | Required; FK to `accounts` in the same user scope |
| `tag` | `varchar(40)` | Required; trimmed and non-empty |
| Shared audit fields | — | Include all six fields |

Unique index: `(user_id, account_id, lower(tag))`. If the app later needs shared tag definitions or tag colors, split this into `tags` and an account/tag join table; do not add that indirection unless needed now.

### 4. `categories`

One row per income or expense category. Keep the initial hierarchy shallow; categories are used for transaction grouping and charts.

| Column | Type | Rule / meaning |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `user_id` | `uuid` | Required; owner |
| `parent_id` | `uuid` | Optional; parent category from same user |
| `name` | `varchar(60)` | Required |
| `flow_type` | `text` | Required; `income` or `expense` |
| `created_via` | `text` | Required; `system`, `user`, or `ai` |
| `is_active` | `boolean` | Required; default `true`; set false instead of deleting a category with history |
| Shared audit fields | — | Include all six fields |

Require category names to be unique per user, parent, and `flow_type` (case-insensitive). A child must have the same `flow_type` as its parent. Keep `category_id` nullable on a transaction when classification is unknown; show it as “Needs review” in the app rather than silently forcing a misleading category.

Suggested v1 seed categories:

| Flow | Categories |
| --- | --- |
| Expense | Food & groceries; Transport; Housing & utilities; Shopping; Health; Travel; Entertainment & subscriptions; Financial charges; Cash & ATM; Other expenses |
| Income | Salary; Refunds; Interest & investment income; Other income |

Add child categories only when they materially improve a user-facing answer. Payment rails (UPI, card, netbanking) are not spending categories.

### 5. `merchants`

One row per normalized merchant per user. This supports display and reuse of a user's previously confirmed category.

| Column | Type | Rule / meaning |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `user_id` | `uuid` | Required; owner |
| `display_name` | `varchar(120)` | Required; display form, e.g. `Blue Tokai` |
| `normalized_name` | `varchar(120)` | Required; normalized comparison/search form |
| `default_category_id` | `uuid` | Optional; last user-confirmed/default category from same user |
| Shared audit fields | — | Include all six fields |

Unique constraint: `(user_id, normalized_name)`. A merchant default is a suggestion, not a guarantee: a merchant can sell products from different categories, and users must be able to override it.

### 6. `statement_imports`

One row per uploaded statement/import attempt. Passwords are never stored. Do not retain the original file by default once review is complete.

| Column | Type | Rule / meaning |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `user_id` | `uuid` | Required; owner |
| `account_id` | `uuid` | Optional until account is confirmed; same user |
| `file_sha256` | `char(64)` | Required; exact-file duplicate detection |
| `file_format` | `text` | Required; e.g. `pdf`, `csv`, `xlsx` |
| `statement_type` | `text` | Required; `bank`, `credit_card`, `mixed`, or `unknown` |
| `period_from` | `date` | Optional statement period start |
| `period_to` | `date` | Optional statement period end |
| `status` | `text` | Required; `processing`, `needs_review`, `completed`, `failed`, `cancelled` |
| `row_count` | `integer` | Required; default `0` |
| `error_message` | `text` | Optional, sanitized; never include password or sensitive statement contents |
| Shared audit fields | — | Include all six fields |

Index `(user_id, file_sha256)` to identify an exact previously imported file and prompt the user to skip or re-import it; do not make it unique if re-imports are allowed. Similar-looking files are not proof of duplication; never silently discard one based on approximate text similarity.

### 7. `import_rows`

One row per extracted candidate transaction. These rows remain staging data until accepted.

| Column | Type | Rule / meaning |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `user_id` | `uuid` | Required; owner |
| `import_id` | `uuid` | Required; statement import from same user |
| `row_number` | `integer` | Required; positive source row/page sequence |
| `account_id` | `uuid` | Optional until confirmed; same user |
| `transaction_date` | `date` | Required when extraction succeeds |
| `transaction_time` | `time` | Optional; only when present in the statement |
| `posted_date` | `date` | Optional |
| `description_raw` | `text` | Optional source narration for review/classification; sensitive, restrict access and retention |
| `merchant_id` | `uuid` | Optional; normalized merchant from same user |
| `amount` | `numeric(14,2)` | Required; greater than zero |
| `currency` | `char(3)` | Required; ISO code |
| `direction` | `text` | Required; `debit` or `credit` |
| `balance_after` | `numeric(14,2)` | Optional statement running balance |
| `suggested_type` | `text` | Optional; `expense`, `income`, or `transfer` |
| `suggested_category_id` | `uuid` | Optional suggested category from same user |
| `category_source` | `text` | Optional; `import`, `rule`, `merchant_memory`, or `ai` |
| `category_confidence` | `numeric(4,3)` | Optional, range 0 to 1 |
| `review_status` | `text` | Required; `pending`, `needs_review`, `accepted`, `skipped` |
| `transaction_id` | `uuid` | Optional; accepted canonical transaction from same user |
| Shared audit fields | — | Include all six fields |

Unique constraint: `(user_id, import_id, row_number)`. Repeated date/amount/description values are not unique because two legitimate transactions can be identical. Keep raw narration only as long as needed for review and classification; never log it or send it to external enrichment.

An extracted debit is not automatically an expense: it can be a transfer or card-bill payment. An extracted credit can be income, a refund, or an account transfer. Use account context/rules and user review before committing ambiguous rows.

### 8. `transactions`

The canonical ledger. All transaction lists, charts, and spending aggregations query this table.

| Column | Type | Rule / meaning |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `user_id` | `uuid` | Required; owner |
| `transaction_type` | `text` | Required; `expense`, `income`, or `transfer` |
| `transfer_kind` | `text` | Optional; `interbank`, `account_transfer`, `credit_card_payment`, `cash_withdrawal`, `other`; required only for transfers |
| `amount` | `numeric(14,2)` | Required; greater than zero |
| `currency` | `char(3)` | Required; ISO code; matches account currency in v1 |
| `transaction_date` | `date` | Required; canonical calendar date for date-range/month queries |
| `transaction_time` | `time` | Optional; do not fabricate if unavailable |
| `posted_date` | `date` | Optional bank/card posting date |
| `account_id` | `uuid` | Required; account from which activity is viewed / transfer source |
| `counter_account_id` | `uuid` | Optional; destination account for transfers, same user |
| `category_id` | `uuid` | Optional; same-user category; null for transfers or unresolved classification |
| `merchant_id` | `uuid` | Optional; same-user merchant |
| `description` | `varchar(200)` | Optional sanitized display description; do not copy unnecessary account/person identifiers |
| `transaction_source` | `text` | Required; `manual`, `statement_import`, or `other` |
| `import_row_id` | `uuid` | Optional provenance to accepted import row |
| `category_source` | `text` | Optional; `manual`, `rule`, `merchant_memory`, `ai`, or `import` |
| `ai_suggested_category_id` | `uuid` | Optional; same-user category suggested by AI |
| `ai_confidence` | `numeric(4,3)` | Optional, range 0 to 1 |
| `linked_transaction_id` | `uuid` | Optional same-user transaction; use for refund/fee relationship |
| `note` | `text` | Optional user note |
| Shared audit fields | — | Include all six fields |

#### Transaction rules

- `expense` and `income`: `counter_account_id` is null; `transfer_kind` is null. A category may be null only while unclassified/under review.
- `transfer`: `counter_account_id` is required and differs from `account_id`; `category_id` is null. `transfer_kind` is required.
- When a category is present, its `flow_type` must match the transaction (`expense` or `income`); transfers cannot have a category.
- A `credit_card_payment` is a transfer from the bank account to the credit-card account. Do not also count it as an expense.
- An interbank transfer between the user's own accounts is one transfer row with both accounts. Mark it `interbank` when the institutions differ. It is not income or spending.
- A card purchase is an expense on the credit-card account and is categorized normally.
- A merchant refund is an income transaction linked to its original expense where possible. For net-spend-by-category, subtract linked refunds from the original category; avoid treating a card bill payment as a refund.
- `category_source` describes only how the category was assigned. `transaction_source` describes how the ledger row entered the app.
- The final transaction's account, category, merchant, linked transaction, and import row must belong to the same `user_id`.
- Add a unique partial index on `(user_id, import_row_id)` where `import_row_id IS NOT NULL`, so one accepted staging row cannot create duplicate ledger transactions.

## Indexes for mobile screens and charts

Create indexes on active rows (partial index with `deleted_at IS NULL`) where practical:

| Table | Index | Supports |
| --- | --- | --- |
| `accounts` | `(user_id, is_archived, display_name)` | Account list |
| `account_tags` | `(user_id, account_id)` | Account tag display/filter |
| `categories` | `(user_id, flow_type, parent_id, name)` | Category picker and expense/income grouping |
| `merchants` | `(user_id, normalized_name)` | Merchant/category suggestion |
| `statement_imports` | `(user_id, file_sha256)` | Exact file duplicate check |
| `import_rows` | `(user_id, import_id, review_status, row_number)` | Import review queue |
| `transactions` | `(user_id, transaction_date DESC)` | Ledger, month and date-range filters |
| `transactions` | `(user_id, transaction_type, transaction_date)` | Income/expense/transfer totals over time |
| `transactions` | `(user_id, category_id, transaction_date)` | Category charts and drill-down |
| `transactions` | `(user_id, account_id, transaction_date)` | Account-specific history |
| `transactions` | `(user_id, merchant_id, transaction_date)` | Merchant history |

For every query, filter by the authenticated `user_id` and `deleted_at IS NULL`. Use half-open date ranges (`transaction_date >= start AND transaction_date < end`) for calendar months and custom ranges. “This month”, “last month”, and “last 90 days” are date-range calculations in the user's timezone, not stored filter types. Apply time-of-day filters against `transaction_time` only when it is present.

## Common aggregation semantics

- **Expense by category:** sum `amount` where `transaction_type = 'expense'`, grouped by `category_id`, for the selected date range. Exclude transfers. Return uncategorized expenses separately so totals reconcile.
- **Income:** sum `amount` where `transaction_type = 'income'`.
- **Transfers:** query separately by `transfer_kind` or accounts; never include them in income/expense chart totals.
- **Account balance:** use `current_balance` for the account card, with `balance_as_of` and `last_synced_at` visible as freshness metadata. Derive or refresh it from the opening balance, statement balance, and accepted ledger entries.
- **Category filters:** join `transactions.category_id` to `categories`; use the category tree only when the UI requests parent-category rollups.
- **Time-of-day filters:** only apply when `transaction_time` exists. Statement imports often provide a date but no exact time.

Example shape for monthly expense aggregation:

```sql
SELECT c.id, c.name, COALESCE(SUM(t.amount), 0) AS total_amount, t.currency
FROM transactions AS t
LEFT JOIN categories AS c
  ON c.user_id = t.user_id AND c.id = t.category_id
WHERE t.user_id = :authenticated_user_id
  AND t.deleted_at IS NULL
  AND t.transaction_type = 'expense'
  AND t.transaction_date >= :month_start
  AND t.transaction_date < :next_month_start
GROUP BY c.id, c.name, t.currency
ORDER BY total_amount DESC;
```

## Build now vs defer

**Build now:** these tables, shared audit fields, checks/foreign keys, account/category/transaction screens' query indexes, statement-row review, and category aggregation semantics.

**Defer:** budgets, recurring transactions, Account Aggregator consent, balance-history snapshots, advanced classifier training, external merchant scraping, and a separate transfer table. None is needed to answer the current “where did I spend?” questions.

**Final implementation choice:** keep the existing v3 `transactions` + `categories` direction, add explicit account tags and statement staging, and use the schema above as the mobile MVP contract. The schema deliberately avoids over-specializing categories or importing sensitive raw statement data into the permanent ledger.
