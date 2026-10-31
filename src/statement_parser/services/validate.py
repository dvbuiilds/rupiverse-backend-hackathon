import re
from dataclasses import dataclass
from datetime import date, time
from decimal import ROUND_HALF_UP, Decimal

from statement_parser.config import settings
from statement_parser.services.llm import CategoryOption, StatementExtraction

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_PAISE = Decimal("0.01")


@dataclass(frozen=True)
class CheckedRow:
    """One extracted row that passed the checks, in the form the ledger stores it."""

    row_number: int
    txn_date: date
    txn_time: time | None
    posted_date: date | None
    currency: str
    description_raw: str
    description: str
    amount: Decimal  # positive
    direction: str  # debit or credit
    balance_after: Decimal | None
    merchant_name: str | None
    merchant_normalized: str | None
    suggested_type: str
    transaction_type: str  # expense, income or transfer
    transfer_kind: str | None
    suggested_category: CategoryOption | None  # kept even when confidence is too low to set the category
    category: CategoryOption | None  # set only when confident enough
    confidence: float


@dataclass(frozen=True)
class CheckResult:
    rows: list[CheckedRow]
    rejected: int


def check_extraction(extraction: StatementExtraction, categories: dict[str, CategoryOption]) -> CheckResult:
    rows: list[CheckedRow] = []
    rejected = 0
    for number, item in enumerate(extraction.transactions, start=1):
        row = _check_row(number, item, categories)
        if row is None:
            rejected += 1
        else:
            rows.append(row)
    return CheckResult(rows=rows, rejected=rejected)


def _check_row(number: int, item, categories: dict[str, CategoryOption]) -> CheckedRow | None:
    txn_date = parse_date(item.transaction_date)
    amount = Decimal(str(item.amount)).quantize(_PAISE, rounding=ROUND_HALF_UP)
    if txn_date is None or amount <= 0:
        return None

    # A debit is an expense, a credit is income, unless the model marked it as a transfer.
    if item.suggested_type == "transfer":
        transaction_type = "transfer"
        transfer_kind = item.transfer_kind or "other"
    else:
        transaction_type = "expense" if item.direction == "debit" else "income"
        transfer_kind = None

    suggested = categories.get(item.category) if item.category else None
    if suggested is not None and (transaction_type == "transfer" or suggested.flow_type != transaction_type):
        suggested = None
    confident = suggested is not None and item.confidence >= settings.category_confidence_threshold

    description_raw = item.description_raw.strip()
    return CheckedRow(
        row_number=number,
        txn_date=txn_date,
        txn_time=parse_time(item.transaction_time),
        posted_date=parse_date(item.posted_date),
        currency=item.currency if _CURRENCY.match(item.currency) else "INR",
        description_raw=description_raw,
        description=(item.display_description or description_raw).strip()[:200] or None,
        amount=amount,
        direction=item.direction,
        balance_after=Decimal(str(item.balance_after)).quantize(_PAISE) if item.balance_after is not None else None,
        merchant_name=(item.merchant_name or "").strip()[:120] or None,
        merchant_normalized=(item.merchant_normalized or "").strip().lower()[:120] or None,
        suggested_type=item.suggested_type,
        transaction_type=transaction_type,
        transfer_kind=transfer_kind,
        suggested_category=suggested,
        category=suggested if confident else None,
        confidence=min(max(item.confidence, 0.0), 1.0),
    )


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_time(text: str | None) -> time | None:
    # 00:00 is what a missing time looks like, so it is treated as no time.
    if not text:
        return None
    try:
        value = time.fromisoformat(text)
    except ValueError:
        return None
    return None if value == time(0, 0) else value


def reconciles(extraction: StatementExtraction, rows: list[CheckedRow]) -> bool | None:
    """Previous balance plus or minus the rows reaches the closing balance, within Rs 1. None if numbers are missing."""
    meta = extraction.statement
    if meta.previous_balance is None or meta.closing_balance is None:
        return None
    debits = sum((r.amount for r in rows if r.direction == "debit"), Decimal(0))
    credits = sum((r.amount for r in rows if r.direction == "credit"), Decimal(0))
    previous = Decimal(str(meta.previous_balance))
    closing = Decimal(str(meta.closing_balance))
    # A card owes more after purchases; a bank balance goes down after a debit.
    expected = previous + debits - credits if meta.statement_type == "credit_card" else previous - debits + credits
    return abs(expected - closing) <= Decimal(1)
