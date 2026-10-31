from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import settings
from app.errors import StatementError
from app.services.parsers.docling_parser import get_converter


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_converter()
    yield


app = FastAPI(
    title="Statement Parser POC",
    version="0.1.0",
    description="Upload a credit card statement PDF with its password and get back parsed content.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(router)


@app.exception_handler(StatementError)
async def statement_error_handler(_: Request, exc: StatementError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "docling_converter_ready": get_converter.cache_info().currsize == 1}
