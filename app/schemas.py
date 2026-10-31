from pydantic import BaseModel


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
    file_name: str
    file_sha256: str
    page_count: int
    parser_used: str
    markdown: str
    tables: list[TableOut]
    warnings: list[str]
    timings_ms: Timings
    llm: LLMPayload
