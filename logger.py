import logging
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

LOG_FILE = "harness.log"

logger = logging.getLogger("harness")
logger.setLevel(logging.INFO)

if not logger.handlers:
    # File handler
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

def log_event(message: str, level: str = "info"):
    lvl = level.lower()
    if lvl == "error":
        logger.error(message)
    elif lvl == "warning":
        logger.warning(message)
    else:
        logger.info(message)
