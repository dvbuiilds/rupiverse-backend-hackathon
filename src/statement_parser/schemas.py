from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class TableOut(BaseModel):
    page_no: int | None
    columns: list[str]
    rows: list[list[str]]


class Timings(BaseModel):
    decrypt: int
    parse: int
    total: int


class LLMPayload(BaseModel):
    system_prompt: str
    user_content: str


class ExtractedTransaction(BaseModel):
    txn_date: date
    # Integer paise. Negative is money out (debit), positive is money in (credit, refund, payment).
    amount_paise: int
    narration: str
    merchant_raw: str | None


class StatementParseResult(BaseModel):
    file_name: str
    file_sha256: str
    page_count: int
    parser_used: str
    markdown: str
    tables: list[TableOut]
    warnings: list[str]
    timings_ms: Timings
    llm: LLMPayload
    transactions: list[ExtractedTransaction]
    # The saved statement_imports row. Null when nothing was saved (no Gemini key or no database).
    statement_import_id: UUID | None


TransactionType = Literal["expense", "income", "transfer"]
TransferKind = Literal["interbank", "account_transfer", "credit_card_payment", "cash_withdrawal", "other"]


class RowDecision(BaseModel):
    """What to do with one staged row. Transfers need a kind and a counter account; other types take neither."""

    row_number: int = Field(ge=1)
    skip: bool = False
    transaction_type: TransactionType | None = None
    transfer_kind: TransferKind | None = None
    counter_account_id: UUID | None = None
    category_id: UUID | None = None

    @model_validator(mode="after")
    def check_shape(self) -> Self:
        if self.skip:
            if any(
                v is not None
                for v in (self.transaction_type, self.transfer_kind, self.counter_account_id, self.category_id)
            ):
                raise ValueError("a skipped row takes no type, transfer, account or category")
            return self
        if self.transaction_type is None:
            raise ValueError("transaction_type is required unless skip is true")
        if self.transaction_type == "transfer":
            if self.transfer_kind is None or self.counter_account_id is None:
                raise ValueError("a transfer needs transfer_kind and counter_account_id")
            if self.category_id is not None:
                raise ValueError("a transfer cannot have a category")
        elif self.transfer_kind is not None or self.counter_account_id is not None:
            raise ValueError("only a transfer takes transfer_kind or counter_account_id")
        return self


class AcceptRequest(BaseModel):
    # The card or account the rows belong to. Staged rows carry no account of their own.
    account_id: UUID
    rows: list[RowDecision] = Field(min_length=1)


class AcceptResponse(BaseModel):
    statement_import_id: UUID
    accepted: int
    skipped: int
    # Rows still waiting for review. The import is completed when this reaches zero.
    pending: int


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Every error the API returns has this shape."""

    error: ErrorBody
