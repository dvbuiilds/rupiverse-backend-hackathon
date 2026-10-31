import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, time
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from psycopg_pool import ConnectionPool

from statement_parser import repositories as repo
from statement_parser.errors import StatementError
from statement_parser.schemas import (
    BalanceOut,
    StatementImportResponse,
    StatementOut,
    SummaryOut,
    TransactionOut,
)
from statement_parser.services.llm import CategoryOption, GeminiExtractor
from statement_parser.services.pipeline import ParsedUpload
from statement_parser.services.validate import CheckedRow, check_extraction, parse_date, reconciles

logger = logging.getLogger(__name__)


def select_new_rows(rows: list[CheckedRow], ledger: dict) -> tuple[list[CheckedRow], int]:
    """Returns the rows to add and the duplicate count. Each key may add only what the ledger lacks."""
    keys = [_row_key(r) for r in rows]
    wanted = Counter(keys)
    allowed = {k: max(0, n - ledger.get(k, 0)) for k, n in wanted.items()}
    taken: Counter = Counter()
    new: list[CheckedRow] = []
    for row, key in zip(rows, keys, strict=True):
        if taken[key] < allowed[key]:
            new.append(row)
            taken[key] += 1
    return new, len(rows) - len(new)


def _row_key(row: CheckedRow) -> tuple:
    return repo.dedupe_key(row.txn_date, row.direction, row.amount, row.description_raw, row.balance_after)


def paise(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def display_amount(stored: Decimal, account_type: str) -> Decimal:
    """Cards store the balance as a negative number (owed); the API returns the amount owed as positive."""
    return -stored if account_type == "credit_card" else stored


def signed_paise(row: CheckedRow) -> int:
    """Money out of the uploaded account is negative, money in is positive."""
    value = paise(row.amount)
    return -value if row.direction == "debit" else value


@dataclass(frozen=True)
class StatementImportService:
    pool: ConnectionPool
    extractor: GeminiExtractor | None
    user_id: UUID

    def load_account(self, account_id: UUID) -> repo.AccountRow:
        with self.pool.connection() as conn:
            account = repo.fetch_account(conn, self.user_id, account_id)
        if account is None:
            raise StatementError(404, "ACCOUNT_NOT_FOUND", "No account with this ID.")
        return account

    def import_statement(self, account: repo.AccountRow, upload: ParsedUpload) -> StatementImportResponse:
        if self.extractor is None:
            raise StatementError(503, "EXTRACTION_UNAVAILABLE", "Set STATEMENT_GEMINI_API_KEY to import statements.")
        import_id = self._open_import(account.id, upload.file_sha256)
        try:
            return self._run(import_id, account, upload)
        except StatementError as exc:
            self._fail(import_id, exc.code)
            raise
        except Exception as exc:
            logger.exception("statement import failed")
            self._fail(import_id, "INTERNAL")
            raise StatementError(
                500, "INTERNAL", "Something went wrong while saving this statement. Try again."
            ) from exc

    def _run(self, import_id: UUID, account: repo.AccountRow, upload: ParsedUpload) -> StatementImportResponse:
        categories = self._categories()
        extraction = self.extractor.extract(upload.document.markdown, list(categories.values()))
        meta = extraction.statement
        if meta.statement_type == "unknown":
            raise StatementError(422, "UNRECOGNISED_STATEMENT", "This PDF is not a bank or card statement.")
        if meta.account_last4 and account.account_last4 and meta.account_last4 != account.account_last4:
            raise StatementError(
                422, "UNRECOGNISED_STATEMENT", f"This statement is for a card ending {meta.account_last4}."
            )

        checked = check_extraction(extraction, categories)
        if checked.rejected:
            logger.info("rejected rows=%d", checked.rejected)
        if reconciles(extraction, checked.rows) is False:
            logger.warning("statement does not reconcile sha256=%s", upload.file_sha256)

        with self.pool.connection() as conn:
            return self._store(conn, import_id, account, extraction, checked.rows, upload)

    def _store(self, conn, import_id, account, extraction, rows, upload) -> StatementImportResponse:
        uid = self.user_id
        meta = extraction.statement
        # Rows on or before the opening date are not stored, so nothing is counted twice.
        kept = [r for r in rows if account.opening_balance_date is None or r.txn_date > account.opening_balance_date]
        before_opening = len(rows) - len(kept)

        period_from, period_to = _period(meta, kept or rows)
        ledger = {}
        if kept:
            start = min(r.txn_date for r in kept)
            end = max(r.txn_date for r in kept)
            ledger = repo.ledger_counts(conn, uid, account.id, start, end)
        new_rows, duplicates = select_new_rows(kept, ledger)

        placeholder = None
        if any(r.transaction_type == "transfer" for r in new_rows):
            if not repo.placeholder_exists(conn, uid):
                raise StatementError(500, "INTERNAL", "The Unlinked account is missing. Run sql/seed.sql.")
            placeholder = repo.PLACEHOLDER_ACCOUNT_ID

        added: list[tuple[UUID, CheckedRow]] = []
        for row in new_rows:
            merchant_id = None
            if row.merchant_normalized:
                merchant_id = repo.upsert_merchant(
                    conn, uid, row.merchant_name or row.merchant_normalized, row.merchant_normalized
                )
            import_row_id = repo.insert_import_row(
                conn, uid, import_id, account.id, row, merchant_id, row.suggested_category
            )
            if row.transaction_type == "transfer":
                # Money into the card: the placeholder pays it. Money out: the card pays the placeholder.
                if row.direction == "credit":
                    account_id, counter_id = placeholder, account.id
                else:
                    account_id, counter_id = account.id, placeholder
            else:
                account_id, counter_id = account.id, None
            transaction_id = repo.insert_transaction(conn, uid, import_row_id, account_id, counter_id, row, merchant_id)
            repo.link_import_row(conn, uid, import_row_id, transaction_id)
            added.append((transaction_id, row))

        repo.complete_import(conn, uid, import_id, meta.statement_type, period_from, period_to, len(new_rows))

        previous_stored = account.current_balance if account.current_balance is not None else account.opening_balance
        as_of_candidate = parse_date(meta.statement_date) or period_to
        balance_as_of = account.balance_as_of
        current_stored = previous_stored
        if (
            meta.closing_balance is not None
            and as_of_candidate
            and (balance_as_of is None or as_of_candidate >= balance_as_of)
        ):
            closing = Decimal(str(meta.closing_balance)).quantize(Decimal("0.01"))
            current_stored = -closing if account.account_type == "credit_card" else closing
            repo.update_account_balance(conn, uid, account.id, current_stored, as_of_candidate)
            balance_as_of = as_of_candidate
        balance_as_of = balance_as_of or account.opening_balance_date or period_to or date.today()

        if new_rows:
            status, reason = "imported", None
        elif not rows:
            status, reason = "skipped", "NO_TRANSACTIONS"
        elif not kept:
            status, reason = "skipped", "ALL_BEFORE_OPENING_DATE"
        else:
            status, reason = "skipped", "ALL_DUPLICATES"

        added.sort(
            key=lambda pair: (pair[1].txn_date, pair[1].txn_time or time(0, 0), pair[1].row_number), reverse=True
        )
        transactions = [_response_row(txn_id, account.id, row) for txn_id, row in added]
        logger.info("import added=%d duplicates=%d before_opening=%d", len(new_rows), duplicates, before_opening)
        return StatementImportResponse(
            statement=StatementOut(
                id=str(import_id),
                file_name=upload.file_name,
                size_bytes=upload.size_bytes,
                period_start=period_from,
                period_end=period_to,
                status=status,
            ),
            summary=SummaryOut(
                transactions_added=len(new_rows),
                duplicates_ignored=duplicates,
                skipped_before_opening_date=before_opening,
                skip_reason=reason,
            ),
            balance=BalanceOut(
                previous_paise=paise(display_amount(previous_stored, account.account_type)),
                amount_paise=paise(display_amount(current_stored, account.account_type)),
                as_of=balance_as_of,
            ),
            transactions=transactions,
        )

    def _categories(self) -> dict[str, CategoryOption]:
        with self.pool.connection() as conn:
            return {c.slug: c for c in repo.list_categories(conn, self.user_id)}

    def _open_import(self, account_id: UUID, file_sha256: str) -> UUID:
        with self.pool.connection() as conn:
            return repo.insert_import(conn, self.user_id, account_id, file_sha256)

    def _fail(self, import_id: UUID, code: str) -> None:
        with self.pool.connection() as conn:
            repo.mark_import_failed(conn, self.user_id, import_id, code)


def _period(meta, rows: list[CheckedRow]) -> tuple[date | None, date | None]:
    start = parse_date(meta.period_from)
    end = parse_date(meta.period_to)
    if start is None and end is None and rows:
        start = min(r.txn_date for r in rows)
        end = max(r.txn_date for r in rows)
    if start and end and start > end:
        return None, None
    return start, end


def _response_row(transaction_id: UUID, account_id: UUID, row: CheckedRow) -> TransactionOut:
    return TransactionOut(
        id=str(transaction_id),
        account_id=str(account_id),
        date=row.txn_date,
        description=row.description,
        amount_paise=signed_paise(row),
        category_id=row.category.slug if row.category else None,
    )
