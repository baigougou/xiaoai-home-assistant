import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logging(log_level: str = "INFO", log_file: str = "config/app.log"):
    logger = logging.getLogger("xiaoai_ha_bridge")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    if getattr(logger, "_xiaoai_configured", False):
        return logger

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.propagate = False
    logger._xiaoai_configured = True

    return logger
