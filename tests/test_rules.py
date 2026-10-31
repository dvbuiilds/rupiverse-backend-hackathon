from datetime import date, time
from decimal import Decimal

from statement_parser.repositories import dedupe_key
from statement_parser.schemas import StatementImportResponse
from statement_parser.services.importer import display_amount, paise, select_new_rows, signed_paise
from statement_parser.services.llm import CategoryOption, ExtractedTxn, StatementExtraction, StatementMeta
from statement_parser.services.redact import redact
from statement_parser.services.validate import CheckedRow, check_extraction, parse_time, reconciles

FOOD = CategoryOption(id="food-id", slug="food", name="Food", flow_type="expense")
SALARY = CategoryOption(id="sal-id", slug="salary", name="Salary", flow_type="income")
CATS = {"food": FOOD, "salary": SALARY}


def txn(**overrides) -> ExtractedTxn:
    data = dict(
        row_number=1,
        transaction_date="2026-09-29",
        transaction_time=None,
        posted_date=None,
        description_raw="UPI-RAMESH-99887766",
        display_description="Ramesh",
        merchant_name="Ramesh",
        merchant_normalized="ramesh",
        amount=850.0,
        currency="INR",
        direction="debit",
        balance_after=None,
        suggested_type="expense",
        transfer_kind=None,
        category="food",
        confidence=0.9,
        bank_category_hint=None,
    )
    data.update(overrides)
    return ExtractedTxn(**data)


def extraction(items, **meta) -> StatementExtraction:
    fields = dict(
        institution_name="HDFC",
        card_product=None,
        account_last4=None,
        statement_type="credit_card",
        period_from="2026-09-01",
        period_to="2026-09-30",
        statement_date="2026-10-01",
        previous_balance=1000.0,
        closing_balance=1850.0,
        currency="INR",
    )
    fields.update(meta)
    return StatementExtraction(statement=StatementMeta(**fields), transactions=items)


def test_money_is_paise_and_signed():
    assert paise(Decimal("850.00")) == 85000
    assert paise(Decimal("0.10")) == 10
    row = check_extraction(extraction([txn()]), CATS).rows[0]
    assert signed_paise(row) == -85000  # debit is money out
    assert display_amount(Decimal("-1000"), "credit_card") == Decimal("1000")  # card owes a positive amount


def test_debit_and_credit_map_to_expense_and_income():
    result = check_extraction(
        extraction([txn(), txn(direction="credit", suggested_type="income", category="salary")]), CATS
    )
    assert [r.transaction_type for r in result.rows] == ["expense", "income"]
    assert result.rows[1].category is SALARY


def test_low_confidence_keeps_suggestion_but_not_category():
    row = check_extraction(extraction([txn(confidence=0.5)]), CATS).rows[0]
    assert row.suggested_category is FOOD
    assert row.category is None


def test_category_of_the_wrong_flow_is_dropped():
    row = check_extraction(extraction([txn(category="salary")]), CATS).rows[0]
    assert row.suggested_category is None and row.category is None


def test_transfer_has_no_category_and_defaults_kind():
    row = check_extraction(
        extraction([txn(suggested_type="transfer", transfer_kind=None, direction="credit", category="food")]), CATS
    ).rows[0]
    assert row.transaction_type == "transfer"
    assert row.transfer_kind == "other"
    assert row.category is None


def test_rows_with_bad_date_or_amount_are_rejected():
    result = check_extraction(extraction([txn(transaction_date="29/09/2026"), txn(amount=0.0), txn()]), CATS)
    assert result.rejected == 2
    assert len(result.rows) == 1


def test_midnight_is_no_time():
    assert parse_time("00:00") is None
    assert parse_time("13:45") == time(13, 45)


def test_reconciliation_card_and_bank():
    items = [txn(amount=850.0), txn(amount=150.0, direction="credit", suggested_type="income", category=None)]
    rows = check_extraction(extraction(items), CATS).rows
    assert reconciles(extraction(items), rows) is False  # 1000 + 850 - 150 = 1700, not the 1850 printed
    assert reconciles(extraction(items, closing_balance=1700.0), rows) is True
    assert (
        reconciles(extraction(items, statement_type="bank", closing_balance=1300.0, previous_balance=2000.0), rows)
        is True
    )


def test_select_new_rows_counts_identical_rows_by_ledger():
    rows = [
        CheckedRow(
            row_number=n,
            txn_date=date(2026, 9, 29),
            txn_time=None,
            posted_date=None,
            currency="INR",
            description_raw="CHAI",
            description="Chai",
            amount=Decimal("20"),
            direction="debit",
            balance_after=None,
            merchant_name=None,
            merchant_normalized=None,
            suggested_type="expense",
            transaction_type="expense",
            transfer_kind=None,
            suggested_category=None,
            category=None,
            confidence=0.9,
        )
        for n in (1, 2)
    ]
    key = dedupe_key(date(2026, 9, 29), "debit", Decimal("20"), "chai", None)
    # Two identical teas in the statement, one already in the ledger: only one is new.
    new, duplicates = select_new_rows(rows, {key: 1})
    assert len(new) == 1 and duplicates == 1
    # Nothing in the ledger: both are new (two real teas on the same day are legitimate).
    new, duplicates = select_new_rows(rows, {})
    assert len(new) == 2 and duplicates == 0


def test_redaction_masks_identifiers_and_keeps_amounts():
    text = "Name: JANE DOE\n\n# Statement\nCard 4123456789012345 mail jane@example.com phone 98765 43210\nUPI/RAMESH 850.00"
    out = redact(text)
    assert "JANE" not in out
    assert "4123456789012345" not in out and "2345" in out
    assert "jane@example.com" not in out and "98765 43210" not in out
    assert "850.00" in out and "RAMESH" in out


def test_response_uses_contract_field_names():
    body = {
        "statement": {
            "id": "st_1",
            "fileName": "x.pdf",
            "sizeBytes": 1,
            "periodStart": None,
            "periodEnd": None,
            "status": "skipped",
        },
        "summary": {
            "transactionsAdded": 0,
            "duplicatesIgnored": 0,
            "skippedBeforeOpeningDate": 0,
            "skipReason": "NO_TRANSACTIONS",
        },
        "balance": {"previousPaise": 1, "amountPaise": 2, "asOf": "2026-09-30"},
        "transactions": [],
    }
    model = StatementImportResponse.model_validate(body)
    assert model.model_dump(by_alias=True, mode="json") == body
