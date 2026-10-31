from typing import Protocol

from statement_parser.schemas import LLMPayload
from statement_parser.parsers.base import ParsedDocument

SYSTEM_PROMPT = """You extract transactions from a credit card statement.
Return a JSON array. Each item has:
- txn_date: ISO date (YYYY-MM-DD)
- amount: positive number, no currency symbol
- direction: "debit" for purchases, fees and interest; "credit" for payments and refunds
- narration: the description as printed on the statement
- merchant_raw: the merchant name, or null if there is none
Skip totals, opening and closing balances, reward summaries and card-limit lines."""


class LLMProcessor(Protocol):
    def build_payload(self, parsed: ParsedDocument) -> LLMPayload: ...


class NoopProcessor:
    """Builds the exact payload an LLM would receive, without calling a model."""

    def build_payload(self, parsed: ParsedDocument) -> LLMPayload:
        return LLMPayload(system_prompt=SYSTEM_PROMPT, user_content=parsed.markdown)
