"""Collector for exam schedules and government announcement pages."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector
from config import URGENT_KEYWORDS


class AnnouncementsCollector(BaseCollector):
    """Collect exam dates, format changes, and application window announcements."""

    def parse(self) -> list[dict[str, Any]]:
        response = self.fetch()
        if response is None:
            return []

        soup = BeautifulSoup(self._decode_response(response), "lxml")
        items = self._parse_tables(soup)
        if not items:
            items = self._parse_links(soup)
        if not items:
            items = self._parse_page_text(soup)
        return self._dedupe(items)

    @staticmethod
    def _decode_response(response: Any) -> str:
        for encoding in ("utf-8", "big5", "hkscs", response.apparent_encoding or "utf-8"):
            try:
                return response.content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return response.text

    def _parse_tables(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in soup.find_all("tr"):
            cells = [self._clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["td", "th"])]
            cells = [cell for cell in cells if cell]
            if len(cells) < 1:
                continue

            row_text = " | ".join(cells)
            if not self._looks_relevant(row_text):
                continue

            link = row.find("a", href=True)
            title = self._pick_title(cells, link.get_text(" ", strip=True) if link else "")
            if not title:
                title = cells[0]
            url = urljoin(self.source["url"], link["href"]) if link else self.source["url"]
            published_date = self._extract_date(row_text)
            items.append(self._make_item(title, url, published_date, row_text))
        return items

    def _parse_links(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for link in soup.find_all("a", href=True):
            title = self._clean_text(link.get_text(" ", strip=True))
            if not title or len(title) < 4:
                continue
            context = link.find_parent(["tr", "li", "p", "div"])
            summary = self._clean_text(context.get_text(" ", strip=True)) if context else title
            if not self._looks_relevant(f"{title} {summary}"):
                continue
            items.append(
                self._make_item(
                    title=title,
                    url=urljoin(self.source["url"], link["href"]),
                    published_date=self._extract_date(summary),
                    summary=summary,
                )
            )
        return items

    def _parse_page_text(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Fallback: treat the page itself as one announcement when it is exam-focused."""
        body = soup.find("body")
        if body is None:
            return []
        text = self._clean_text(body.get_text(" ", strip=True))
        if not self._looks_relevant(text):
            return []
        title = self._clean_text(soup.title.get_text(strip=True) if soup.title else self.source["name"])
        return [
            self._make_item(
                title=title,
                url=self.source["url"],
                published_date=self._extract_date(text),
                summary=text[:300],
            )
        ]

    def _make_item(
        self,
        title: str,
        url: str,
        published_date: str,
        summary: str,
    ) -> dict[str, Any]:
        combined = f"{title} {summary}"
        content_type = "exam" if self._looks_like_exam(combined) else "announcement"
        urgent = any(keyword in combined for keyword in URGENT_KEYWORDS)
        return {
            "title": title,
            "url": url,
            "published_date": published_date,
            "summary": summary[:150],
            "source_name": self.source.get("source_name", self.source["name"]),
            "source_url": self.source["url"],
            "content_type": content_type,
            "is_urgent": urgent,
        }

    @staticmethod
    def _looks_like_exam(text: str) -> bool:
        signals = ["基本法", "國安法", "BLNST", "CRE", "考試", "筆試", "測試", "開考", "報名"]
        return any(signal in text for signal in signals)

    @staticmethod
    def _looks_relevant(text: str) -> bool:
        signals = [
            "考試",
            "筆試",
            "面試",
            "基本法",
            "國安法",
            "BLNST",
            "CRE",
            "截止",
            "報名",
            "開考",
            "申請",
            "公布",
            "通知",
            "安排",
            "日期",
        ]
        return any(signal in text for signal in signals)

    @staticmethod
    def _pick_title(cells: list[str], linked_text: str) -> str:
        if linked_text and len(linked_text) >= 3:
            return linked_text
        for cell in cells:
            if any(word in cell for word in ["考試", "測試", "BLNST", "CRE", "基本法"]):
                return cell
        return cells[0] if cells else ""

    @staticmethod
    def _extract_date(text: str) -> str:
        match = re.search(r"(20\d{2})[./\-年](\d{1,2})[./\-月](\d{1,2})日?", text)
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        match = re.search(r"(\d{1,2})[./\-](\d{1,2})[./\-](20\d{2})", text)
        if match:
            return f"{int(match.group(3)):04d}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"
        return ""

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in items:
            key = item.get("url") or item.get("title", "")
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique
