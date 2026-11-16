"""Configure console and UTF-8 file logging for the application."""

import logging
import time
from pathlib import Path


def setup_logging(log_dir: Path, level: str = "INFO", *, verbose: bool = False) -> logging.Logger:
    """Configure application logging; callers must never log credentials."""
    name = "DEBUG" if verbose else level.upper()
    levels = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING,
              "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}
    if name not in levels:
        raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("rl_analyzer")
    logger.setLevel(levels[name])
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    formatter.converter = time.gmtime
    console = logging.StreamHandler()
    file_handler = logging.FileHandler(log_dir / "rl_analyzer.log", encoding="utf-8")
    for handler in (console, file_handler):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger
