from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg.errors
from fastapi import APIRouter, Depends, File, Form, UploadFile

from statement_parser.api.deps import get_import_store, get_parse_service
from statement_parser.errors import StatementError
from statement_parser.schemas import (
    AcceptRequest,
    AcceptResponse,
    ErrorResponse,
    StatementParseResult,
)
from statement_parser.services.pipeline import StatementParseService
from statement_parser.services.store import ImportStore

router = APIRouter(prefix="/v1", tags=["statements"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"model": ErrorResponse, "description": "PDF is larger than the upload limit."},
    415: {"model": ErrorResponse, "description": "The upload is not a PDF."},
    422: {
        "model": ErrorResponse,
        "description": "Invalid request, missing or wrong password, too many pages, or the PDF could not be parsed.",
    },
    502: {"model": ErrorResponse, "description": "The language model could not extract transactions."},
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


@router.post(
    "/statement-imports/{import_id}/accept",
    response_model=AcceptResponse,
    responses={
        404: {"model": ErrorResponse, "description": "The import or the account was not found."},
        422: {"model": ErrorResponse, "description": "A row decision is invalid or does not fit the ledger rules."},
        503: {"model": ErrorResponse, "description": "STATEMENT_DATABASE_URL is not set."},
    },
)
def accept_import(
    import_id: UUID,
    body: AcceptRequest,
    store: Annotated[ImportStore, Depends(get_import_store)],
) -> AcceptResponse:
    # Writes the chosen rows to the transactions ledger. All of them succeed or none do.
    try:
        counts = store.accept_rows(import_id, body.account_id, body.rows)
    except LookupError as exc:
        raise StatementError(404, "NOT_FOUND", str(exc)) from exc
    except ValueError as exc:
        raise StatementError(422, "INVALID_REQUEST", str(exc)) from exc
    except (psycopg.errors.IntegrityError, psycopg.errors.RaiseException) as exc:
        # Covers a category of the wrong flow, a category or account from another user, and a row accepted twice.
        raise StatementError(
            422, "INVALID_REQUEST", "A category or account does not fit the ledger for these rows."
        ) from exc
    return AcceptResponse(
        statement_import_id=import_id,
        accepted=counts.accepted,
        skipped=counts.skipped,
        pending=counts.pending,
    )
