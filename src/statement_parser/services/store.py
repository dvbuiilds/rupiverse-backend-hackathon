from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from psycopg_pool import ConnectionPool

from statement_parser.schemas import ExtractedTransaction, RowDecision

_INSERT_IMPORT = """
    INSERT INTO statement_imports (user_id, file_sha256, file_format, statement_type, status, row_count, created_by)
    VALUES (%(user_id)s, %(file_sha256)s, 'pdf', 'credit_card', 'needs_review', %(row_count)s, %(user_id)s)
    RETURNING id
"""

# Currency is INR for this build. The PDF's file name and password are never stored.
_INSERT_ROW = """
    INSERT INTO import_rows (
        user_id, import_id, row_number, transaction_date, description_raw, amount, currency, direction,
        review_status, created_by
    )
    VALUES (
        %(user_id)s, %(import_id)s, %(row_number)s, %(transaction_date)s, %(description_raw)s, %(amount)s,
        'INR', %(direction)s, 'pending', %(user_id)s
    )
"""

_ACTIVE_ACCOUNT = """
    SELECT 1 FROM accounts WHERE user_id = %s AND id = %s AND deleted_at IS NULL AND NOT is_archived
"""

_OWN_IMPORT = """
    SELECT 1 FROM statement_imports WHERE user_id = %s AND id = %s AND deleted_at IS NULL
"""

_PENDING_ROW = """
    SELECT id, amount, currency, transaction_date, description_raw
    FROM import_rows
    WHERE user_id = %s AND import_id = %s AND row_number = %s
      AND review_status IN ('pending', 'needs_review') AND deleted_at IS NULL
"""

_SET_ROW_STATUS = """
    UPDATE import_rows SET review_status = %s WHERE user_id = %s AND id = %s
"""

_INSERT_TRANSACTION = """
    INSERT INTO transactions (
        user_id, transaction_type, transfer_kind, amount, currency, transaction_date, account_id,
        counter_account_id, category_id, description, transaction_source, import_row_id, category_source,
        created_by
    )
    VALUES (
        %(user_id)s, %(transaction_type)s, %(transfer_kind)s, %(amount)s, %(currency)s, %(transaction_date)s,
        %(account_id)s, %(counter_account_id)s, %(category_id)s, %(description)s, 'statement_import',
        %(import_row_id)s, CASE WHEN %(category_id)s::uuid IS NULL THEN NULL ELSE 'manual' END, %(user_id)s
    )
    RETURNING id
"""

_LINK_ROW = """
    UPDATE import_rows SET review_status = 'accepted', transaction_id = %s WHERE user_id = %s AND id = %s
"""

_COUNT_PENDING = """
    SELECT count(*) FROM import_rows
    WHERE user_id = %s AND import_id = %s AND review_status IN ('pending', 'needs_review') AND deleted_at IS NULL
"""

_COMPLETE_IMPORT = """
    UPDATE statement_imports SET status = 'completed' WHERE user_id = %s AND id = %s
"""


@dataclass(frozen=True)
class AcceptCounts:
    accepted: int
    skipped: int
    pending: int


class ImportStore:
    """Saves each statement import and its extracted rows as staging data, and accepts rows into the ledger."""

    def __init__(self, pool: ConnectionPool, user_id: UUID) -> None:
        self._pool = pool
        self._user_id = user_id

    def check_user(self) -> None:
        # Run at startup so a wrong STATEMENT_DEV_USER_ID fails fast instead of on the first upload.
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM users WHERE id = %s AND deleted_at IS NULL",
                (self._user_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("STATEMENT_DEV_USER_ID does not match an active user in the database.")

    def save_import(self, file_sha256: str, transactions: list[ExtractedTransaction]) -> UUID:
        # One transaction: either the import and all its rows are stored, or none are.
        with self._pool.connection() as conn:
            import_id = conn.execute(
                _INSERT_IMPORT,
                {"user_id": self._user_id, "file_sha256": file_sha256, "row_count": len(transactions)},
            ).fetchone()[0]
            with conn.cursor() as cur:
                cur.executemany(
                    _INSERT_ROW,
                    [
                        {
                            "user_id": self._user_id,
                            "import_id": import_id,
                            "row_number": number,
                            "transaction_date": item.txn_date,
                            "description_raw": item.narration,
                            # Stored as a positive amount; direction carries the sign.
                            "amount": Decimal(abs(item.amount_paise)).scaleb(-2),
                            "direction": "debit" if item.amount_paise < 0 else "credit",
                        }
                        for number, item in enumerate(transactions, start=1)
                    ],
                )
        return import_id

    def accept_rows(self, import_id: UUID, account_id: UUID, decisions: list[RowDecision]) -> AcceptCounts:
        # One transaction: every decision is applied or none are, so a failed batch leaves the review queue unchanged.
        with self._pool.connection() as conn:
            if conn.execute(_ACTIVE_ACCOUNT, (self._user_id, account_id)).fetchone() is None:
                raise LookupError("account_id does not match an active account")
            if conn.execute(_OWN_IMPORT, (self._user_id, import_id)).fetchone() is None:
                raise LookupError("statement import not found")

            accepted = skipped = 0
            for decision in decisions:
                row = conn.execute(_PENDING_ROW, (self._user_id, import_id, decision.row_number)).fetchone()
                if row is None:
                    raise ValueError(f"row {decision.row_number} is not waiting for review")
                row_id, amount, currency, txn_date, description = row
                if decision.skip:
                    conn.execute(_SET_ROW_STATUS, ("skipped", self._user_id, row_id))
                    skipped += 1
                    continue
                transaction_id = conn.execute(
                    _INSERT_TRANSACTION,
                    {
                        "user_id": self._user_id,
                        "account_id": account_id,
                        "import_row_id": row_id,
                        "transaction_type": decision.transaction_type,
                        "transfer_kind": decision.transfer_kind,
                        "counter_account_id": decision.counter_account_id,
                        "category_id": decision.category_id,
                        "amount": amount,
                        "currency": currency,
                        "transaction_date": txn_date,
                        # The ledger description is capped at 200 characters; the raw narration stays on the import row.
                        "description": (description or "")[:200] or None,
                    },
                ).fetchone()[0]
                conn.execute(_LINK_ROW, (transaction_id, self._user_id, row_id))
                accepted += 1

            pending = conn.execute(_COUNT_PENDING, (self._user_id, import_id)).fetchone()[0]
            if pending == 0:
                conn.execute(_COMPLETE_IMPORT, (self._user_id, import_id))
        return AcceptCounts(accepted=accepted, skipped=skipped, pending=pending)
