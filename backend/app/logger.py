import sys
import os
from loguru import logger

# Remove default handler
logger.remove()

# Determine logs directory (project root / logs)
_LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
os.makedirs(_LOGS_DIR, exist_ok=True)

# Console handler — colored, concise
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",
    colorize=True,
)

# File handler — daily rotation, 30-day retention, thread-safe
logger.add(
    os.path.join(_LOGS_DIR, "backend-{time:YYYY-MM-DD}.log"),
    format="[{time:YYYY-MM-DD HH:mm:ss.SSS}] [{level: <8}] [{name}:{function}:{line}] {message}",
    level="DEBUG",
    rotation="00:00",
    retention="30 days",
    enqueue=True,
    encoding="utf-8",
)
