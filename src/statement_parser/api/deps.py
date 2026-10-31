from uuid import UUID

from fastapi import Request
from psycopg_pool import ConnectionPool

from statement_parser.errors import StatementError
from statement_parser.services.importer import StatementImportService
from statement_parser.services.pipeline import StatementParseService


def get_user_id(request: Request) -> UUID:
    """No auth yet. All data belongs to the demo user."""
    return request.app.state.demo_user_id


def get_parse_service(request: Request) -> StatementParseService:
    return request.app.state.parse_service


def get_pool(request: Request) -> ConnectionPool:
    pool: ConnectionPool | None = request.app.state.pool
    if pool is None:
        raise StatementError(503, "DATABASE_UNAVAILABLE", "Database is not configured (STATEMENT_DATABASE_URL).")
    return pool


def get_import_service(request: Request) -> StatementImportService:
    get_pool(request)
    return request.app.state.import_service
