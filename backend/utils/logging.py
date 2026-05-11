"""
Loguru logging configuration with PII masking.
Masks email, phone, and DNI fields before any log record is emitted.
Configures rotating file logs (max 10 MB, keep last 5 files).
"""

import re
import sys
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    pass  # type: ignore[reportMissingTypeStubs]

# Patterns to detect and mask PII in log messages
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
        "[EMAIL REDACTED]",
    ),
    (
        re.compile(r"\b\d{7,12}\b"),  # phone / DNI (7-12 digit numbers)
        "[PII REDACTED]",
    ),
]


def _mask_pii(record: "Any") -> bool:
    """
    Mutate the log record to redact any detected PII.

    Args:
    ----
        record: Loguru log record dictionary.

    Returns:
    -------
        Always True (allows the record to proceed to handlers).

    """
    message: str = record["message"]
    for pattern, replacement in _PII_PATTERNS:
        message = pattern.sub(replacement, message)
    record["message"] = message
    return True


def setup_logging(log_level: str = "INFO", log_file: str = "logs/app.log") -> None:
    """
    Configure Loguru handlers with PII masking and log rotation.

    Args:
    ----
        log_level: Minimum log level to emit (e.g. 'DEBUG', 'INFO').
        log_file: Path to the rotating log file.

    """
    logger.remove()

    # Console handler (structured for CloudWatch ingestion in production)
    logger.add(
        sys.stdout,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "{message}"
        ),
        filter=_mask_pii,
        colorize=True,
        enqueue=True,
    )

    # Rotating file handler
    logger.add(
        log_file,
        level=log_level,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        filter=_mask_pii,
        rotation="10 MB",
        retention=5,
        compression="zip",
        enqueue=True,
    )
