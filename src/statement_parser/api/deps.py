from fastapi import Request

from statement_parser.errors import StatementError
from statement_parser.services.pipeline import StatementParseService
from statement_parser.services.store import ImportStore


def get_parse_service(request: Request) -> StatementParseService:
    return request.app.state.parse_service


def get_import_store(request: Request) -> ImportStore:
    store: ImportStore | None = request.app.state.import_store
    if store is None:
        raise StatementError(503, "DATABASE_UNAVAILABLE", "Database is not configured (STATEMENT_DATABASE_URL).")
    return store
