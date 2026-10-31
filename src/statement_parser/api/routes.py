from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile

from statement_parser.api.deps import get_parse_service, get_user_id
from statement_parser.schemas import ErrorResponse, StatementParseResult
from statement_parser.services.pipeline import StatementParseService

router = APIRouter(prefix="/v1", tags=["statements"], dependencies=[Depends(get_user_id)])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Missing file, not a PDF, over 10 MB, or too many pages."},
    422: {"model": ErrorResponse, "description": "Password missing or wrong, or the PDF could not be read."},
}


@router.post("/statements/parse", response_model=StatementParseResult, responses=ERROR_RESPONSES)
def parse_statement(
    file: Annotated[UploadFile, File(description="Credit card statement PDF")],
    service: Annotated[StatementParseService, Depends(get_parse_service)],
    password: Annotated[str | None, Form(description="PDF password, if the file is encrypted")] = None,
    parser: Annotated[Literal["docling", "pdfplumber"], Form(description="Parser to use")] = "docling",
) -> StatementParseResult:
    # Dev endpoint: parses only. Sync on purpose, so Docling's CPU work runs in the threadpool.
    return service.parse_upload(file, password, parser)
