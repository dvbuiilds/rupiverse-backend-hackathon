import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool

from statement_parser import __version__, repositories
from statement_parser.api.health import router as health_router
from statement_parser.api.ledger import router as ledger_router
from statement_parser.api.routes import router as parse_router
from statement_parser.api.statements import router as statements_router
from statement_parser.config import settings
from statement_parser.errors import StatementError
from statement_parser.logging_config import configure_logging
from statement_parser.parsers.docling_parser import DoclingParser
from statement_parser.parsers.pdfplumber_parser import PdfPlumberParser
from statement_parser.services.importer import StatementImportService
from statement_parser.services.llm import GeminiExtractor
from statement_parser.services.pipeline import StatementParseService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Models load here, so a broken install or missing model fails at startup rather than on the first upload.
    docling = DoclingParser(ocr=settings.docling_ocr)
    docling.warm_up()
    app.state.parse_service = StatementParseService(settings, docling, PdfPlumberParser())

    app.state.demo_user_id = settings.demo_user_id

    pool = None
    app.state.import_service = None
    if settings.database_url is not None:
        if settings.demo_user_id is None:
            raise RuntimeError("STATEMENT_DEMO_USER_ID must be set when STATEMENT_DATABASE_URL is set.")
        pool = ConnectionPool(settings.database_url.get_secret_value(), min_size=1, max_size=4, open=True)
        with pool.connection() as conn:
            if not repositories.check_demo_user(conn, settings.demo_user_id):
                raise RuntimeError("STATEMENT_DEMO_USER_ID does not match an active user in the database.")
        extractor = None
        if settings.gemini_api_key is not None:
            extractor = GeminiExtractor(
                api_key=settings.gemini_api_key.get_secret_value(),
                model=settings.gemini_model,
                timeout_s=settings.gemini_timeout_s,
            )
        app.state.import_service = StatementImportService(pool, extractor, settings.demo_user_id)
    app.state.pool = pool
    logger.info("Statement parser %s ready", __version__)
    try:
        yield
    finally:
        if pool is not None:
            pool.close()


async def statement_error_handler(_: Request, exc: StatementError) -> JSONResponse:
    logger.info("Request rejected: %s", exc.code)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    message = "; ".join(f"{'.'.join(str(part) for part in err['loc'][1:])}: {err['msg']}" for err in exc.errors())
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "INVALID_REQUEST", "message": message}},
    )


async def unhandled_error_handler(_: Request, _exc: Exception) -> JSONResponse:
    # Starlette re-raises after this handler, so uvicorn still logs the traceback.
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL", "message": "Something went wrong. Try again later."}},
    )


def create_app() -> FastAPI:
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Statement Parser",
        version=__version__,
        description="Upload a credit card statement PDF with its password and import the transactions.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(parse_router)
    app.include_router(statements_router)
    app.include_router(ledger_router)

    app.add_exception_handler(StatementError, statement_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    return app


app = create_app()
