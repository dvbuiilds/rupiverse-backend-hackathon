"""One tiny call to Gemini, to check the key, the quota and the response schema. Sends no statement data.

Usage: uv run python scripts/check_gemini.py
"""

from google import genai
from google.genai import types

from statement_parser.config import settings
from statement_parser.services.llm import SYSTEM_PROMPT, StatementExtraction

SAMPLE = "HDFC Bank Credit Card Statement. Period 01/09/2026 to 30/09/2026. Total due Rs 850.00. No transactions."


def main() -> None:
    if settings.gemini_api_key is None:
        raise SystemExit("STATEMENT_GEMINI_API_KEY is not set.")
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=f"<categories>\nfood: Food (expense)\n</categories>\n<statement>\n{SAMPLE}\n</statement>",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=StatementExtraction,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        ),
    )
    parsed = StatementExtraction.model_validate_json(response.text)
    kind = parsed.statement.statement_type
    rows = len(parsed.transactions)
    print(f"ok model={settings.gemini_model} statement_type={kind} rows={rows}")


if __name__ == "__main__":
    main()
