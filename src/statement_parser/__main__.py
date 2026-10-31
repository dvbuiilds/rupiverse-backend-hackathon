import uvicorn

from statement_parser.config import settings


def main() -> None:
    uvicorn.run(
        "statement_parser.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
