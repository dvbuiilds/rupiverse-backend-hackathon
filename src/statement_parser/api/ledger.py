from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg_pool import ConnectionPool

from statement_parser import repositories as repo
from statement_parser.api.deps import get_pool, get_user_id
from statement_parser.errors import StatementError
from statement_parser.schemas import AccountBalanceOut, AccountOut, CategoryOut, TransactionOut
from statement_parser.services.importer import display_amount, paise

router = APIRouter(prefix="/v1", tags=["ledger"], dependencies=[Depends(get_user_id)])


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(pool: Annotated[ConnectionPool, Depends(get_pool)], user_id: Annotated[UUID, Depends(get_user_id)]):
    with pool.connection() as conn:
        rows = repo.list_accounts(conn, user_id)
    out = []
    for row in rows:
        account = repo.AccountRow(*row)
        stored = account.current_balance if account.current_balance is not None else account.opening_balance
        as_of = account.balance_as_of or account.opening_balance_date or date.today()
        out.append(
            AccountOut(
                id=str(account.id),
                name=account.display_name,
                type=account.account_type,
                institution=account.institution_name,
                last4=account.account_last4,
                opening_date=account.opening_balance_date,
                balance=AccountBalanceOut(
                    amount_paise=paise(display_amount(stored, account.account_type)), as_of=as_of
                ),
            )
        )
    return out


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(pool: Annotated[ConnectionPool, Depends(get_pool)], user_id: Annotated[UUID, Depends(get_user_id)]):
    with pool.connection() as conn:
        rows = repo.list_active_categories(conn, user_id)
    return [CategoryOut(id=slug, name=name, color=color, source=source) for slug, name, color, source in rows]


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    pool: Annotated[ConnectionPool, Depends(get_pool)],
    user_id: Annotated[UUID, Depends(get_user_id)],
    account_id: Annotated[str | None, Query(alias="accountId")] = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
):
    view = None
    if account_id is not None:
        try:
            view = UUID(account_id)
        except ValueError as exc:
            raise StatementError(400, "INVALID_REQUEST", "accountId must be a UUID.") from exc
    with pool.connection() as conn:
        rows = repo.list_transactions(conn, user_id, view, start, end, limit)
    out = []
    for txn_id, account, counter, kind, txn_date, _time, description, amount, slug in rows:
        # Seen from the chosen account: transfers are money in when the account is the counter side.
        shown = view or account
        value = paise(amount)
        if kind == "transfer":
            sign = 1 if counter == shown else -1
        else:
            sign = 1 if kind == "income" else -1
        out.append(
            TransactionOut(
                id=str(txn_id),
                account_id=str(shown),
                date=txn_date,
                description=description,
                amount_paise=sign * value,
                category_id=slug,
            )
        )
    return out
