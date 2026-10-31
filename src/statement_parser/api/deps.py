from fastapi import Request

from statement_parser.services.pipeline import StatementParseService


def get_parse_service(request: Request) -> StatementParseService:
    return request.app.state.parse_service
