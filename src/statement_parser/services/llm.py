import logging
from datetime import date
from decimal import Decimal
from typing import Literal

import httpx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from statement_parser.errors import StatementError
from statement_parser.parsers.base import ParsedDocument
from statement_parser.schemas import ExtractedTransaction, LLMPayload

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract transactions from a credit card statement.
Return a JSON array. Each item has:
- txn_date: ISO date (YYYY-MM-DD)
- amount: positive number, no currency symbol
- direction: "debit" for purchases, fees and interest; "credit" for payments and refunds
- narration: the description as printed on the statement
- merchant_raw: the merchant name, or null if there is none
Skip totals, opening and closing balances, reward summaries and card-limit lines."""

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_EXTRACTION_FAILED_MESSAGE = "The transactions could not be extracted from this statement. Try again."

# Gemini's response schema (OpenAPI subset). Constrains the reply to the JSON array described in SYSTEM_PROMPT.
RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "txn_date": {"type": "STRING", "description": "ISO date, YYYY-MM-DD"},
            "amount": {"type": "NUMBER", "description": "Positive amount, no currency symbol"},
            "direction": {"type": "STRING", "enum": ["debit", "credit"]},
            "narration": {"type": "STRING"},
            "merchant_raw": {"type": "STRING", "nullable": True},
        },
        "required": ["txn_date", "amount", "direction", "narration", "merchant_raw"],
    },
}


class _ModelTransaction(BaseModel):
    """One item as the model returns it, before conversion to the API's signed paise."""

    txn_date: date
    # Money has two decimals. A reply with finer amounts is rejected rather than rounded into a wrong value.
    amount: Decimal = Field(gt=0, multiple_of=Decimal("0.01"))
    direction: Literal["debit", "credit"]
    narration: str
    merchant_raw: str | None


_MODEL_TRANSACTIONS = TypeAdapter(list[_ModelTransaction])


def build_payload(parsed: ParsedDocument) -> LLMPayload:
    """The exact system prompt and user content sent to the model, returned with the result for inspection."""
    return LLMPayload(system_prompt=SYSTEM_PROMPT, user_content=parsed.markdown)


class GeminiExtractor:
    """Sends the statement text to Gemini and returns the transactions it found."""

    def __init__(self, api_key: str, model: str, timeout_s: float, client: httpx.Client | None = None) -> None:
        self._model = model
        self._url = GEMINI_URL.format(model=model)
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_s)

    def extract(self, parsed: ParsedDocument) -> list[ExtractedTransaction]:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": parsed.markdown}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
            },
        }
        # The key travels in a header, not the URL, so no request log can contain it.
        try:
            response = self._client.post(self._url, headers={"x-goog-api-key": self._api_key}, json=body)
            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            items = _MODEL_TRANSACTIONS.validate_json(text)
        except httpx.HTTPStatusError as exc:
            logger.warning("Gemini returned HTTP %d", exc.response.status_code)
            raise StatementError(502, "EXTRACTION_FAILED", _EXTRACTION_FAILED_MESSAGE) from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            # Logs the exception type only: its message can echo statement text.
            logger.warning("Gemini reply could not be read: %s", type(exc).__name__)
            raise StatementError(502, "EXTRACTION_FAILED", _EXTRACTION_FAILED_MESSAGE) from exc

        transactions = [_to_extracted(item) for item in items]
        logger.info("extracted transactions=%d model=%s", len(transactions), self._model)
        return transactions


def _to_extracted(item: _ModelTransaction) -> ExtractedTransaction:
    paise = int((item.amount * 100).to_integral_value())
    if item.direction == "debit":
        paise = -paise
    return ExtractedTransaction(
        txn_date=item.txn_date,
        amount_paise=paise,
        narration=item.narration,
        merchant_raw=item.merchant_raw,
    )
