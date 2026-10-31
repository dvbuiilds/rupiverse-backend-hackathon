import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str) -> None:
    # basicConfig does nothing if the root logger already has handlers, so an embedding host keeps its own setup.
    logging.basicConfig(level=level, format=LOG_FORMAT)
