"""Dedicated collector for Immigration Department press releases."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector


DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})[./\-年](?P<m>\d{1,2})[./\-月](?P<d>\d{1,2})日?"),
    re.compile(r"(?P<d>\d{1,2})[./\-](?P<m>\d{1,2})[./\-](?P<y>20\d{2})"),
]
PRESS_RELEASE_PATH = "/press/press-releases/"
FILENAME_DATE = re.compile(r"/press-releases/(\d{8})")


class ImmdNewsCollector(BaseCollector):
    """Collect press releases from the IMMD press release listing page."""

    def parse(self) -> list[dict[str, Any]]:
        response = self.fetch()
        if response is None:
            return []

        html = self._decode_response(response)
        soup = BeautifulSoup(html, "lxml")
        return self._dedupe(self._parse_press_releases(soup))

    def _parse_press_releases(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in soup.find_all("tr"):
            link = row.find("a", href=True)
            if link is None:
                continue

            href = link["href"].strip()
            if PRESS_RELEASE_PATH not in href:
                continue

            title = self._clean_text(link.get_text(" ", strip=True))
            if not title:
                continue

            context = self._clean_text(row.get_text(" ", strip=True))
            published_date = self._extract_date(context) or self._extract_date_from_url(href)

            items.append(
                {
                    "title": title,
                    "url": urljoin(self.source["url"], href),
                    "published_date": published_date,
                    "summary": context[:150],
                    "source_name": "入境事務處",
                    "source_url": self.source["url"],
                    "department_tag": "入境事務處",
                }
            )
        return items

    @staticmethod
    def _decode_response(response: Any) -> str:
        content = response.content
        for encoding in ("utf-8", "big5", "hkscs", response.apparent_encoding or "utf-8"):
            try:
                return content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return response.text

    @staticmethod
    def _extract_date(text: str) -> str:
        for pattern in DATE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            parts = {key: int(value) for key, value in match.groupdict().items()}
            try:
                return datetime(parts["y"], parts["m"], parts["d"]).date().isoformat()
            except ValueError:
                return ""
        return ""

    @staticmethod
    def _extract_date_from_url(href: str) -> str:
        match = FILENAME_DATE.search(href)
        if not match:
            return ""
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
        except ValueError:
            return ""

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in items:
            url = item.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            unique.append(item)
        return unique
