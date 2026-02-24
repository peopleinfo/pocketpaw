import logging
import sys
from typing import Optional

from ..config import settings


def setup_logger(name: Optional[str] = None) -> logging.Logger:
    """Setup and configure logger."""
    _logger = logging.getLogger(name or __name__)

    if _logger.handlers:
        return _logger

    log_level = logging.DEBUG if settings.debug else logging.INFO
    _logger.setLevel(log_level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)
    _logger.propagate = False

    return _logger


logger = setup_logger("ai-fastapi")
