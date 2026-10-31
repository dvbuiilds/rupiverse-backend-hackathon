from typing import Annotated

from fastapi import APIRouter, Depends

from statement_parser.api.deps import get_parse_service
from statement_parser.services.pipeline import StatementParseService

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz(service: Annotated[StatementParseService, Depends(get_parse_service)]) -> dict:
    return {"status": "ok", "docling_converter_ready": service.docling_ready}
