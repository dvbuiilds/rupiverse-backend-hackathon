import logging
import time
from dataclasses import dataclass
from typing import Literal

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from statement_parser.errors import StatementError
from statement_parser.schemas import LLMPayload
from statement_parser.services.redact import redact

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 4  # one try, plus three retries on HTTP 429

SYSTEM_PROMPT = """You read the text of one bank or credit card statement and return structured JSON.

Input: <categories> lists the only category slugs you may use, each with its flow (expense or income).
<statement> holds text extracted from the PDF. Personal identifiers are already masked.

Statement fields:
- institution_name, card_product, account_last4 (the last 4 digits of the card or account number, or null).
- statement_type: "credit_card", "bank", "mixed", or "unknown". Use "unknown" if this is not a bank or card statement, and return no transactions.
- period_from, period_to, statement_date: ISO YYYY-MM-DD, or null.
- previous_balance, closing_balance: positive amounts. For a card, these are the amounts owed.
- currency: ISO code, INR unless printed otherwise.

Transaction rows:
- Keep purchases, fees, interest, GST on fees, payments, refunds and cashback. Skip totals, opening and closing balance lines, reward and GST invoice tables, card limits, and summary tables.
- Keep in-list lines such as "GST ON FUEL SURCHARGE" as transactions.
- Drop repeated page headers. Repair rows the PDF extraction split or merged; lower confidence when you infer a value.
- transaction_date: ISO. posted_date: ISO or null. transaction_time: HH:MM 24-hour, or null if not printed. Never invent a time.
- amount: positive number, no symbols or separators.
- direction: "debit" for money out, "credit" for money in. Read it from "+", "Cr", "Dr", "CR", "DR". A bare "C" before an amount is a mis-decoded rupee sign: "C 222.00" is a debit, "+ C 30.00" is a credit.
- description_raw: the narration as printed.
- display_description: a short clean name, at most 200 characters. Remove UPI/ prefixes, VPAs, phone numbers, reference numbers, RSP*, PVT LTD and city suffixes.
- merchant_name: display name such as "Swiggy Instamart", or null. merchant_normalized: lowercase key. Variants of one merchant get the same key. Null if there is no merchant.
- balance_after: running balance printed on the row, or null.
- suggested_type: "transfer" for card bill payments (PAYMENT RECEIVED, MB/IB PAYMENT, BBPS), account transfers and cash withdrawals. "income" for salary, refunds, cashback and interest. Otherwise "expense".
- transfer_kind: for transfers only: "credit_card_payment", "account_transfer", "interbank", "cash_withdrawal" or "other". Null otherwise.
- category: a slug from <categories> whose flow matches suggested_type. Null for transfers, and when unsure. Payment rails (UPI, NEFT, IMPS) are never categories.
  Fuel surcharge and GST lines are "fees". Cashback is "other_income". Merchant refunds are "refunds".
- confidence: 0 to 1. Choose null over a weak guess.
- bank_category_hint: a category column printed by the bank (for example Axis MERCHANT CATEGORY), or null.
"""


class ExtractedTxn(BaseModel):
    row_number: int
    transaction_date: str
    transaction_time: str | None
    posted_date: str | None
    description_raw: str
    display_description: str
    merchant_name: str | None
    merchant_normalized: str | None
    amount: float
    currency: str
    direction: Literal["debit", "credit"]
    balance_after: float | None
    suggested_type: Literal["expense", "income", "transfer"]
    transfer_kind: Literal["credit_card_payment", "account_transfer", "interbank", "cash_withdrawal", "other"] | None
    category: str | None
    confidence: float
    bank_category_hint: str | None


class StatementMeta(BaseModel):
    institution_name: str | None
    card_product: str | None
    account_last4: str | None
    statement_type: Literal["bank", "credit_card", "mixed", "unknown"]
    period_from: str | None
    period_to: str | None
    statement_date: str | None
    previous_balance: float | None
    closing_balance: float | None
    currency: str


class StatementExtraction(BaseModel):
    statement: StatementMeta
    transactions: list[ExtractedTxn]


@dataclass(frozen=True)
class CategoryOption:
    id: str
    slug: str
    name: str
    flow_type: str


def build_payload(markdown: str) -> LLMPayload:
    """The system prompt and the redacted statement text, returned by the dev parse endpoint for inspection."""
    return LLMPayload(system_prompt=SYSTEM_PROMPT, user_content=redact(markdown))


class GeminiExtractor:
    """Sends the redacted statement text to Gemini and returns the structured reply."""

    def __init__(self, api_key: str, model: str, timeout_s: float, client: genai.Client | None = None) -> None:
        self._model = model
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
        )

    def extract(self, statement_text: str, categories: list[CategoryOption]) -> StatementExtraction:
        category_lines = "\n".join(f"{c.slug}: {c.name} ({c.flow_type})" for c in categories)
        contents = f"<categories>\n{category_lines}\n</categories>\n<statement>\n{redact(statement_text)}\n</statement>"
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=StatementExtraction,
            max_output_tokens=32768,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        )
        response = self._generate(contents, config)
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None or candidate.finish_reason != types.FinishReason.STOP:
            logger.warning("Gemini reply was cut off or empty")
            raise _extraction_failed()
        if isinstance(response.parsed, StatementExtraction):
            return response.parsed
        try:
            return StatementExtraction.model_validate_json(response.text or "")
        except ValueError as exc:
            # Logs the exception type only: its message can echo statement text.
            logger.warning("Gemini reply did not match the schema: %s", type(exc).__name__)
            raise _extraction_failed() from exc

    def _generate(self, contents: str, config: types.GenerateContentConfig) -> types.GenerateContentResponse:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._client.models.generate_content(model=self._model, contents=contents, config=config)
            except errors.ClientError as exc:
                if exc.code == 429 and attempt < MAX_ATTEMPTS:
                    time.sleep(5 * attempt)
                    continue
                logger.warning("Gemini rejected the request: HTTP %s", exc.code)
                raise _extraction_failed() from exc
            except Exception as exc:
                logger.warning("Gemini call failed: %s", type(exc).__name__)
                raise _extraction_failed() from exc
        raise _extraction_failed()


def _extraction_failed() -> StatementError:
    return StatementError(
        500, "INTERNAL", "Could not read the transactions from this statement. Try again in a minute."
    )
