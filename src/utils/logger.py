import sys
from pathlib import Path
from loguru import logger
from config.settings import settings


def setup_logger() -> None:
    """Configure the logging system using loguru."""
    log_path = Path(settings.LOG_PATH)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stdout,
        format=log_format,
        level=settings.LOG_LEVEL,
        colorize=True,
    )

    logger.add(
        log_path / "stocker_trader_{time:YYYY-MM-DD}.log",
        format=log_format,
        level=settings.LOG_LEVEL,
        rotation="00:00",
        retention="30 days",
        compression="zip",
    )

    logger.add(
        log_path / "errors_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="ERROR",
        rotation="00:00",
        retention="90 days",
        compression="zip",
    )

    logger.add(
        log_path / "trades_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="INFO",
        rotation="00:00",
        retention="365 days",
        filter=lambda record: "trade" in record["extra"],
    )


def get_logger(name: str = "stocker_trader"):
    """Get a logger instance with the given name."""
    return logger.bind(name=name)


trade_logger = logger.bind(trade=True)
