"""Shared collector logic: HTTP fetching, logging, and persistence."""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import requests

from config import LOG_DIR, LOG_FILE, POLITE_DELAY_SECONDS, REQUEST_RETRIES, REQUEST_TIMEOUT


def setup_logging() -> None:
    """Configure file and console logging once for the whole application."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if logging.getLogger().handlers:
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


class BaseCollector(ABC):
    """Abstract collector with retrying HTTP fetch and polite throttling."""

    def __init__(self, source: dict[str, Any]):
        self.source = source
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-HK,zh-TW;q=0.9,en;q=0.7",
            }
        )

    def fetch(self, url: str | None = None) -> requests.Response | None:
        """Fetch a URL with retry on connection failures and 5xx responses."""
        target_url = url or self.source["url"]
        time.sleep(POLITE_DELAY_SECONDS)

        for attempt in range(1, REQUEST_RETRIES + 1):
            try:
                response = self.session.get(target_url, timeout=REQUEST_TIMEOUT)
                self.logger.info(
                    "GET %s -> HTTP %s (attempt %s/%s)",
                    target_url,
                    response.status_code,
                    attempt,
                    REQUEST_RETRIES,
                )

                if response.status_code in {403, 404}:
                    return None
                if response.status_code >= 500 and attempt < REQUEST_RETRIES:
                    time.sleep(attempt)
                    continue

                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                self.logger.warning(
                    "GET %s failed on attempt %s/%s: %s",
                    target_url,
                    attempt,
                    REQUEST_RETRIES,
                    exc,
                )
                if attempt < REQUEST_RETRIES:
                    time.sleep(attempt)

        return None

    @abstractmethod
    def parse(self) -> list[dict[str, Any]]:
        """Return normalized article dictionaries."""

    def save(self, items: list[dict[str, Any]], output_path: str | Path) -> None:
        """Persist collected items as UTF-8 JSON."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=2)
