from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg

from statement_parser.services.llm import CategoryOption

# The "Unlinked account" seeded in sql/seed.sql. Card bill payments are transfers to or from it.
PLACEHOLDER_ACCOUNT_ID = UUID("00000000-0000-0000-0000-0000000000a0")


@dataclass(frozen=True)
class AccountRow:
    id: UUID
    display_name: str
    account_type: str
    institution_name: str | None
    account_last4: str | None
    opening_balance: Decimal
    opening_balance_date: date | None
    current_balance: Decimal | None
    balance_as_of: date | None


_ACCOUNT_COLUMNS = (
    "id, display_name, account_type, institution_name, account_last4, opening_balance, "
    "opening_balance_date, current_balance, balance_as_of"
)


def check_demo_user(conn: psycopg.Connection, user_id: UUID) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)).fetchone() is not None


def fetch_account(conn, user_id: UUID, account_id: UUID, lock: bool = False) -> AccountRow | None:
    sql = (
        f"SELECT {_ACCOUNT_COLUMNS} FROM accounts "
        "WHERE user_id = %s AND id = %s AND deleted_at IS NULL AND NOT is_archived"
    )
    if lock:
        sql += " FOR UPDATE"
    row = conn.execute(sql, (user_id, account_id)).fetchone()
    return AccountRow(*row) if row else None


def placeholder_exists(conn, user_id: UUID) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM accounts WHERE user_id = %s AND id = %s AND deleted_at IS NULL",
            (user_id, PLACEHOLDER_ACCOUNT_ID),
        ).fetchone()
        is not None
    )


def list_categories(conn, user_id: UUID) -> list[CategoryOption]:
    rows = conn.execute(
        "SELECT id, slug, name, flow_type FROM categories WHERE user_id = %s AND deleted_at IS NULL AND is_active",
        (user_id,),
    ).fetchall()
    return [CategoryOption(id=str(r[0]), slug=r[1], name=r[2], flow_type=r[3]) for r in rows]


def ledger_counts(conn, user_id: UUID, account_id: UUID, start: date, end: date) -> dict:
    """How many imported rows the account already has, per duplicate key, inside the date range."""
    rows = conn.execute(
        """
        SELECT ir.transaction_date, ir.direction, ir.amount, ir.description_raw, ir.balance_after
        FROM transactions t
        JOIN import_rows ir ON ir.user_id = t.user_id AND ir.id = t.import_row_id
        WHERE t.user_id = %s AND ir.account_id = %s AND t.deleted_at IS NULL
          AND ir.transaction_date BETWEEN %s AND %s
        """,
        (user_id, account_id, start, end),
    ).fetchall()
    counts: dict = {}
    for txn_date, direction, amount, narration, balance in rows:
        key = dedupe_key(txn_date, direction, amount, narration or "", balance)
        counts[key] = counts.get(key, 0) + 1
    return counts


def dedupe_key(txn_date, direction, amount, narration: str, balance_after) -> tuple:
    """Same date, direction, amount, narration (letters and digits only, case ignored) and running balance."""
    normalized = "".join(ch for ch in narration.upper() if ch.isalnum())
    return (
        txn_date,
        direction,
        Decimal(amount),
        normalized,
        Decimal(balance_after) if balance_after is not None else None,
    )


def upsert_merchant(conn, user_id: UUID, display_name: str, normalized_name: str) -> UUID:
    return conn.execute(
        """
        INSERT INTO merchants (user_id, display_name, normalized_name, created_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, normalized_name) WHERE deleted_at IS NULL
        DO UPDATE SET display_name = merchants.display_name
        RETURNING id
        """,
        (user_id, display_name, normalized_name, user_id),
    ).fetchone()[0]


def insert_import(conn, user_id: UUID, account_id: UUID, file_sha256: str) -> UUID:
    return conn.execute(
        """
        INSERT INTO statement_imports (
            user_id, account_id, file_sha256, file_format, statement_type, status, created_by
        )
        VALUES (%s, %s, %s, 'pdf', 'unknown', 'processing', %s)
        RETURNING id
        """,
        (user_id, account_id, file_sha256, user_id),
    ).fetchone()[0]


def mark_import_failed(conn, user_id: UUID, import_id: UUID, message: str) -> None:
    conn.execute(
        "UPDATE statement_imports SET status = 'failed', error_message = %s WHERE user_id = %s AND id = %s",
        (message, user_id, import_id),
    )


def complete_import(
    conn, user_id: UUID, import_id: UUID, statement_type: str, period_from, period_to, row_count: int
) -> None:
    conn.execute(
        """
        UPDATE statement_imports
        SET status = 'completed', statement_type = %s, period_from = %s, period_to = %s, row_count = %s
        WHERE user_id = %s AND id = %s
        """,
        (statement_type, period_from, period_to, row_count, user_id, import_id),
    )


def insert_import_row(
    conn, user_id: UUID, import_id: UUID, account_id: UUID, row, merchant_id, category: CategoryOption | None
) -> UUID:
    return conn.execute(
        """
        INSERT INTO import_rows (
            user_id, import_id, row_number, account_id, transaction_date, transaction_time, posted_date,
            description_raw, merchant_id, amount, currency, direction, balance_after, suggested_type,
            suggested_category_id, category_source, category_confidence, review_status, created_by
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'accepted', %s)
        RETURNING id
        """,
        (
            user_id,
            import_id,
            row.row_number,
            account_id,
            row.txn_date,
            row.txn_time,
            row.posted_date,
            row.description_raw,
            merchant_id,
            row.amount,
            row.currency,
            row.direction,
            row.balance_after,
            row.suggested_type,
            row.suggested_category.id if row.suggested_category else None,
            "ai" if row.suggested_category else None,
            row.confidence,
            user_id,
        ),
    ).fetchone()[0]


def insert_transaction(
    conn, user_id: UUID, import_row_id: UUID, account_id: UUID, counter_id, row, merchant_id
) -> UUID:
    return conn.execute(
        """
        INSERT INTO transactions (
            user_id, transaction_type, transfer_kind, amount, currency, transaction_date, transaction_time,
            posted_date, account_id, counter_account_id, category_id, merchant_id, description,
            transaction_source, import_row_id, category_source, ai_suggested_category_id, ai_confidence, created_by
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'statement_import', %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            user_id,
            row.transaction_type,
            row.transfer_kind,
            row.amount,
            row.currency,
            row.txn_date,
            row.txn_time,
            row.posted_date,
            account_id,
            counter_id,
            row.category.id if row.category else None,
            merchant_id,
            row.description,
            import_row_id,
            "ai" if row.category else None,
            row.suggested_category.id if row.suggested_category else None,
            row.confidence,
            user_id,
        ),
    ).fetchone()[0]


def link_import_row(conn, user_id: UUID, import_row_id: UUID, transaction_id: UUID) -> None:
    conn.execute(
        "UPDATE import_rows SET transaction_id = %s WHERE user_id = %s AND id = %s",
        (transaction_id, user_id, import_row_id),
    )


def update_account_balance(conn, user_id: UUID, account_id: UUID, stored: Decimal, as_of: date) -> None:
    conn.execute(
        """
        UPDATE accounts
        SET current_balance = %s, balance_as_of = %s, last_synced_at = now(), balance_source = 'statement'
        WHERE user_id = %s AND id = %s
        """,
        (stored, as_of, user_id, account_id),
    )


# Read queries for the ledger endpoints.


def list_accounts(conn, user_id: UUID):
    return conn.execute(
        f"SELECT {_ACCOUNT_COLUMNS} FROM accounts "
        "WHERE user_id = %s AND id <> %s AND deleted_at IS NULL AND NOT is_archived ORDER BY display_name",
        (user_id, PLACEHOLDER_ACCOUNT_ID),
    ).fetchall()


def list_active_categories(conn, user_id: UUID):
    return conn.execute(
        "SELECT slug, name, color, created_via FROM categories "
        "WHERE user_id = %s AND deleted_at IS NULL AND is_active ORDER BY flow_type, name",
        (user_id,),
    ).fetchall()


def list_transactions(conn, user_id: UUID, account_id: UUID | None, start: date | None, end: date | None, limit: int):
    return conn.execute(
        """
        SELECT t.id, COALESCE(ir.account_id, t.account_id), t.counter_account_id, t.transaction_type,
               t.transaction_date, t.transaction_time, t.description, t.amount, c.slug
        FROM transactions t
        LEFT JOIN import_rows ir ON ir.user_id = t.user_id AND ir.id = t.import_row_id
        LEFT JOIN categories c ON c.user_id = t.user_id AND c.id = t.category_id
        WHERE t.user_id = %(user_id)s AND t.deleted_at IS NULL
          AND (%(account_id)s::uuid IS NULL
               OR COALESCE(ir.account_id, t.account_id) = %(account_id)s
               OR t.counter_account_id = %(account_id)s)
          AND (%(start)s::date IS NULL OR t.transaction_date >= %(start)s)
          AND (%(end)s::date IS NULL OR t.transaction_date <= %(end)s)
        ORDER BY t.transaction_date DESC, t.transaction_time DESC NULLS LAST, t.id
        LIMIT %(limit)s
        """,
        {"user_id": user_id, "account_id": account_id, "start": start, "end": end, "limit": limit},
    ).fetchall()
