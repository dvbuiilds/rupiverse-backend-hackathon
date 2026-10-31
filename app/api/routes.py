from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, UploadFile

from app.schemas import StatementParseResult
from app.services.pipeline import run_parse

router = APIRouter(prefix="/v1")


@router.post("/statements/parse", response_model=StatementParseResult)
def parse_statement(
    file: Annotated[UploadFile, File(description="Credit card statement PDF")],
    password: Annotated[str | None, Form(description="PDF password, if the file is encrypted")] = None,
    parser: Annotated[Literal["docling", "pdfplumber"], Form(description="Parser to use")] = "docling",
) -> StatementParseResult:
    # Sync on purpose: FastAPI runs it in a threadpool, so Docling's CPU work does not block the event loop.
    return run_parse(file, password, parser)
