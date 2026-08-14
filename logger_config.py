"""
Centralized logging. One dedicated "agent" logger with a plain format;
noisy third-party libraries (httpx, langchain, groq's HTTP stack) are
pinned to CRITICAL so only the agent's own short status lines
([INFO] / [DONE] / [WARN] / [FAILED] / [RECOVERED]) reach the console.
"""
from __future__ import annotations

import logging

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("agent")

    if _CONFIGURED:
        return logger

    logger.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False

    for noisy_logger in ("httpx", "httpcore", "openai", "urllib3", "groq",
                          "langchain", "langchain_core", "langsmith", "uvicorn.access"):
        logging.getLogger(noisy_logger).setLevel(logging.CRITICAL)

    _CONFIGURED = True
    return logger


logger = setup_logging()
