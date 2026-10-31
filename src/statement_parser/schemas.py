from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


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


class StatementParseResult(BaseModel):
    """Dev endpoint result: the parsed text and the redacted payload the import endpoint sends to the model."""

    file_name: str
    file_sha256: str
    page_count: int
    parser_used: str
    markdown: str
    tables: list[TableOut]
    warnings: list[str]
    timings_ms: Timings
    llm: LLMPayload


class CamelModel(BaseModel):
    """Contract models: snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class StatementOut(CamelModel):
    id: str
    file_name: str
    size_bytes: int
    period_start: date | None
    period_end: date | None
    status: Literal["imported", "skipped"]


SkipReason = Literal["ALL_BEFORE_OPENING_DATE", "ALL_DUPLICATES", "NO_TRANSACTIONS"]


class SummaryOut(CamelModel):
    transactions_added: int
    duplicates_ignored: int
    skipped_before_opening_date: int
    skip_reason: SkipReason | None


class BalanceOut(CamelModel):
    previous_paise: int
    amount_paise: int
    as_of: date


class TransactionOut(CamelModel):
    id: str
    account_id: str
    date_: date = Field(alias="date")
    description: str | None
    amount_paise: int
    category_id: str | None


class StatementImportResponse(CamelModel):
    statement: StatementOut
    summary: SummaryOut
    balance: BalanceOut
    transactions: list[TransactionOut]


class AccountBalanceOut(CamelModel):
    amount_paise: int
    as_of: date


class AccountOut(CamelModel):
    id: str
    name: str
    type: str = Field(serialization_alias="type")
    institution: str | None
    last4: str | None
    opening_date: date | None
    balance: AccountBalanceOut


class CategoryOut(CamelModel):
    id: str
    name: str
    color: str
    source: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Every error the API returns has this shape."""

    error: ErrorBody
