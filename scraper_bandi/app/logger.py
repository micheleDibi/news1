"""Loguru setup: console (colored) + file daily-rotated.

DEBUG ovunque (allineato a backend/app/logger.py).
"""
import os
import sys
from pathlib import Path

from loguru import logger

# Rimuovi l'handler di default
logger.remove()

# Console handler
logger.add(
    sys.stderr,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    ),
    level="DEBUG",
    colorize=True,
)

# File handler
_LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger.add(
    str(_LOGS_DIR / "scraper-bandi-{time:YYYY-MM-DD}.log"),
    format="[{time:YYYY-MM-DD HH:mm:ss.SSS}] [{level: <8}] [{name}:{function}:{line}] {message}",
    level="DEBUG",
    rotation="00:00",
    retention="30 days",
    enqueue=True,
    encoding="utf-8",
)

__all__ = ["logger"]
