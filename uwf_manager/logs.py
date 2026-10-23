"""Registro local de actividad. Nunca debe impedir que el programa funcione."""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

LOGGER_NAME = "uwf_manager"


def log_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "UWFManager" / "logs"


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def setup_logging(directory: Path | None = None) -> Path | None:
    """Configura el archivo de registro. Devuelve su ruta o None si no fue posible."""
    logger = get_logger()
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.NullHandler())
    try:
        folder = directory or log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "uwf-manager.log"
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=512_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        return path
    except Exception:  # el registro es opcional
        return None
