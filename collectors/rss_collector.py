"""RSS feed collector."""

from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

from collectors.base_collector import BaseCollector


class RSSCollector(BaseCollector):
    """Collect news from RSS feeds using feedparser."""

    def parse(self) -> list[dict[str, Any]]:
        response = self.fetch()
        if response is None:
            return []

        feed = feedparser.parse(response.content)
        items: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for entry in feed.entries:
            url = (entry.get("link") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            items.append(
                {
                    "title": (entry.get("title") or "").strip(),
                    "url": url,
                    "published_date": self._parse_date(entry),
                    "summary": self._clean_summary(entry.get("summary") or ""),
                    "source_name": self.source.get("source_name", self.source["name"]),
                    "source_url": self.source["url"],
                }
            )

        return items

    @staticmethod
    def _parse_date(entry: Any) -> str:
        raw = entry.get("published") or entry.get("updated") or ""
        if raw:
            try:
                return parsedate_to_datetime(raw).date().isoformat()
            except (TypeError, ValueError, IndexError, OverflowError):
                pass
        if entry.get("published_parsed"):
            return datetime(*entry.published_parsed[:6]).date().isoformat()
        return ""

    @staticmethod
    def _clean_summary(summary: str) -> str:
        return " ".join(summary.split())[:150]
