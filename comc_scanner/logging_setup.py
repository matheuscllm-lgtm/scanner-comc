"""Minimal logging configuration (uses `rich` for pretty output if installed)."""
from __future__ import annotations

import logging


def setup_logging(level: int = logging.INFO) -> None:
    try:
        from rich.logging import RichHandler  # type: ignore

        handler: logging.Handler = RichHandler(rich_tracebacks=True, show_path=False)
        fmt = "%(message)s"
    except Exception:
        handler = logging.StreamHandler()
        fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, handlers=[handler], force=True)
