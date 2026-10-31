from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile

from statement_parser.api.deps import get_import_service, get_parse_service, get_user_id
from statement_parser.errors import StatementError
from statement_parser.schemas import ErrorResponse, StatementImportResponse
from statement_parser.services.importer import StatementImportService
from statement_parser.services.pipeline import StatementParseService

router = APIRouter(prefix="/v1", tags=["statements"], dependencies=[Depends(get_user_id)])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Missing file, not a PDF, or over 10 MB."},
    404: {"model": ErrorResponse, "description": "No account with this ID."},
    422: {"model": ErrorResponse, "description": "Password missing or wrong, unreadable PDF, or not a statement."},
    500: {"model": ErrorResponse, "description": "Something went wrong. Try again."},
    503: {"model": ErrorResponse, "description": "STATEMENT_DATABASE_URL is not set."},
}


@router.post(
    "/accounts/{account_id}/statements",
    response_model=StatementImportResponse,
    responses=ERROR_RESPONSES,
)
def import_statement(
    account_id: str,
    file: Annotated[UploadFile, File(description="Statement PDF, 10 MB max")],
    importer: Annotated[StatementImportService, Depends(get_import_service)],
    parse_service: Annotated[StatementParseService, Depends(get_parse_service)],
    password: Annotated[str | None, Form(description="PDF password. Used only to open the file.")] = None,
) -> StatementImportResponse:
    try:
        account_uuid = UUID(account_id)
    except ValueError as exc:
        raise StatementError(404, "ACCOUNT_NOT_FOUND", "No account with this ID.") from exc
    account = importer.load_account(account_uuid)
    upload = parse_service.parse_document(file, password or None)
    return importer.import_statement(account, upload)
