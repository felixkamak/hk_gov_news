"""HTML page collector for Hong Kong government announcement pages."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector


DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})[./\-年](?P<m>\d{1,2})[./\-月](?P<d>\d{1,2})日?"),
    re.compile(r"(?P<d>\d{1,2})[./\-](?P<m>\d{1,2})[./\-](?P<y>20\d{2})"),
]


class PageCollector(BaseCollector):
    """Collect announcements from static HTML pages."""

    def parse(self) -> list[dict[str, Any]]:
        response = self.fetch()
        if response is None:
            return []

        html = self._decode_response(response)
        soup = BeautifulSoup(html, "lxml")
        kind = self.source.get("kind", "")

        if kind == "info_gov":
            items = self._parse_info_gov(soup)
        elif kind in {"immd_press", "immd_career"}:
            items = self._parse_generic_links(soup, require_date=(kind == "immd_press"))
        elif kind == "legco":
            items = self._parse_legco(soup)
        else:
            items = self._parse_generic_links(soup, require_date=False)

        return self._dedupe(items)

    @staticmethod
    def _decode_response(response: Any) -> str:
        """Prefer UTF-8 but fall back to Big5 for older Traditional Chinese pages."""
        content = response.content
        for encoding in ("utf-8", "big5", "hkscs", response.apparent_encoding or "utf-8"):
            try:
                return content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return response.text

    def _parse_info_gov(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            title = self._clean_text(link.get_text(" ", strip=True))
            if not title or not self._looks_like_content_link(href, title):
                continue
            items.append(self._make_item(title, href, link.parent.get_text(" ", strip=True)))
        return items

    def _parse_legco(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            title = self._clean_text(link.get_text(" ", strip=True))
            if not title or ".pdf" not in href.lower():
                continue
            surrounding = link.find_parent(["tr", "li", "p", "div"])
            context = surrounding.get_text(" ", strip=True) if surrounding else title
            items.append(self._make_item(title, href, context))
        return items

    def _parse_generic_links(self, soup: BeautifulSoup, require_date: bool) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for link in soup.find_all("a", href=True):
            title = self._clean_text(link.get_text(" ", strip=True))
            href = link["href"].strip()
            if not title or not self._looks_like_content_link(href, title):
                continue

            surrounding = link.find_parent(["tr", "li", "p", "div", "article", "section"])
            context = surrounding.get_text(" ", strip=True) if surrounding else title
            date = self._extract_date(context)
            if require_date and not date:
                continue

            items.append(self._make_item(title, href, context, published_date=date))
        return items

    def _make_item(
        self,
        title: str,
        href: str,
        context: str,
        published_date: str | None = None,
    ) -> dict[str, Any]:
        full_url = urljoin(self.source["url"], href)
        summary = self._clean_text(context)
        return {
            "title": title,
            "url": full_url,
            "published_date": published_date or self._extract_date(context),
            "summary": summary[:150],
            "source_name": self.source.get("source_name", self.source["name"]),
            "source_url": self.source["url"],
        }

    def _looks_like_content_link(self, href: str, title: str) -> bool:
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return False

        parsed = urlparse(urljoin(self.source["url"], href))
        if parsed.scheme not in {"http", "https"}:
            return False

        lowered = href.lower()
        allowed_ext = (".html", ".htm", ".pdf", ".action")
        has_allowed_ext = any(ext in lowered for ext in allowed_ext)
        if self.source.get("kind") == "info_gov":
            has_allowed_ext = has_allowed_ext or "/gia/general/" in lowered

        if not has_allowed_ext:
            return False

        # Skip common utility/navigation links.
        bad_words = {
            "主頁",
            "首頁",
            "返回",
            "列印",
            "English",
            "简体",
            "搜尋",
            "網站指南",
            "聯絡我們",
            "私隱政策",
        }
        if title in bad_words or len(title) < 3:
            return False

        return True

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
