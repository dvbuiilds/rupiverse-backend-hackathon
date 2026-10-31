from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile

from statement_parser.api.deps import get_parse_service
from statement_parser.schemas import ErrorResponse, StatementParseResult
from statement_parser.services.pipeline import StatementParseService

router = APIRouter(prefix="/v1", tags=["statements"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"model": ErrorResponse, "description": "PDF is larger than the upload limit."},
    415: {"model": ErrorResponse, "description": "The upload is not a PDF."},
    422: {
        "model": ErrorResponse,
        "description": "Invalid request, missing or wrong password, too many pages, or the PDF could not be parsed.",
    },
}


@router.post("/statements/parse", response_model=StatementParseResult, responses=ERROR_RESPONSES)
def parse_statement(
    file: Annotated[UploadFile, File(description="Credit card statement PDF")],
    service: Annotated[StatementParseService, Depends(get_parse_service)],
    password: Annotated[str | None, Form(description="PDF password, if the file is encrypted")] = None,
    parser: Annotated[Literal["docling", "pdfplumber"], Form(description="Parser to use")] = "docling",
) -> StatementParseResult:
    # Sync on purpose: FastAPI runs it in a threadpool, so Docling's CPU work does not block the event loop.
    return service.parse_upload(file, password, parser)
