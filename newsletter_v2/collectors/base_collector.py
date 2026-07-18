import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

import requests

from newsletter_v2.config import (
    LOG_FILE,
    POLITE_DELAY_SECONDS,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
)


def _setup_logger(class_name: str) -> logging.Logger:
    logger = logging.getLogger(class_name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


class BaseCollector(ABC):
    def __init__(self, source: dict):
        self.source = source
        self.logger = _setup_logger(self.__class__.__name__)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
            }
        )

    def fetch(self, url: str | None = None) -> requests.Response | None:
        target_url = url or self.source["url"]
        last_exception = None

        for attempt in range(1, REQUEST_RETRIES + 1):
            time.sleep(POLITE_DELAY_SECONDS)
            try:
                self.logger.info("Fetching %s (attempt %d/%d)", target_url, attempt, REQUEST_RETRIES)
                response = self.session.get(target_url, timeout=REQUEST_TIMEOUT)

                if response.status_code in (403, 404):
                    self.logger.warning(
                        "Received %d for %s; skipping", response.status_code, target_url
                    )
                    return None

                response.raise_for_status()
                return response

            except requests.exceptions.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code and 500 <= status_code < 600:
                    last_exception = exc
                    self.logger.warning(
                        "Server error %s on attempt %d/%d for %s",
                        status_code,
                        attempt,
                        REQUEST_RETRIES,
                        target_url,
                    )
                else:
                    raise

            except requests.exceptions.RequestException as exc:
                last_exception = exc
                self.logger.warning(
                    "Request failed on attempt %d/%d for %s: %s",
                    attempt,
                    REQUEST_RETRIES,
                    target_url,
                    exc,
                )

            if attempt < REQUEST_RETRIES:
                backoff = attempt
                self.logger.info("Retrying in %d second(s)...", backoff)
                time.sleep(backoff)

        self.logger.error(
            "All %d attempts failed for %s: %s", REQUEST_RETRIES, target_url, last_exception
        )
        return None

    @abstractmethod
    def parse(self) -> list[dict]:
        pass

    def save(self, items: list[dict], output_path: Path | str) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        self.logger.info("Saved %d item(s) to %s", len(items), path)
