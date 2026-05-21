"""Collector for the Civil Service Bureau job vacancy system."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector
from config import URGENT_JOB_KEYWORDS


class JobsCollector(BaseCollector):
    """Collect job postings and flag targeted vacancies as urgent."""

    def parse(self) -> list[dict[str, Any]]:
        response = self.fetch()
        if response is None:
            return []

        soup = BeautifulSoup(self._decode_response(response), "lxml")
        items = self._parse_tables(soup)
        if not items:
            items = self._parse_links(soup)
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
            if len(cells) < 2:
                continue

            row_text = " | ".join(cells)
            if not self._looks_like_job(row_text):
                continue

            link = row.find("a", href=True)
            title = self._pick_title(cells, link.get_text(" ", strip=True) if link else "")
            if not title:
                continue

            url = urljoin(self.source["url"], link["href"]) if link else self.source["url"]
            department = self._extract_labeled_value(row_text, ["部門", "Department"]) or self._safe_cell(cells, 1)
            grade = self._extract_labeled_value(row_text, ["職系", "Grade", "職級"]) or ""
            closing_date = self._extract_labeled_value(row_text, ["截止", "Closing"]) or self._extract_date(row_text)

            items.append(self._make_job_item(title, url, department, grade, closing_date, row_text))
        return items

    def _parse_links(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for link in soup.find_all("a", href=True):
            title = self._clean_text(link.get_text(" ", strip=True))
            if not title or not self._looks_like_job(title):
                continue
            context = link.find_parent(["tr", "li", "p", "div"])
            summary = self._clean_text(context.get_text(" ", strip=True)) if context else title
            items.append(
                self._make_job_item(
                    title=title,
                    url=urljoin(self.source["url"], link["href"]),
                    department="",
                    grade="",
                    closing_date=self._extract_date(summary),
                    summary=summary,
                )
            )
        return items

    def _make_job_item(
        self,
        title: str,
        url: str,
        department: str,
        grade: str,
        closing_date: str,
        summary: str,
    ) -> dict[str, Any]:
        urgent = any(keyword in title for keyword in URGENT_JOB_KEYWORDS)
        enriched_summary = (
            f"職位: {title}; 部門: {department}; 職系/職級: {grade}; 截止日期: {closing_date}. {summary}"
        )
        return {
            "title": title,
            "url": url,
            "published_date": closing_date,
            "summary": enriched_summary[:150],
            "source_name": self.source.get("source_name", self.source["name"]),
            "source_url": self.source["url"],
            "department": department,
            "grade": grade,
            "closing_date": closing_date,
            "preclassified_priority": "urgent" if urgent else "normal",
        }

    @staticmethod
    def _looks_like_job(text: str) -> bool:
        signals = ["職位", "空缺", "招聘", "薪酬", "截止", "部門", "助理", "主任", "文書", "秘書"]
        return any(signal in text for signal in signals)

    @staticmethod
    def _pick_title(cells: list[str], linked_text: str) -> str:
        if linked_text and len(linked_text) >= 3:
            return linked_text
        for cell in cells:
            if any(word in cell for word in ["主任", "助理", "文書", "秘書", "Officer", "Assistant", "Clerk"]):
                return cell
        return cells[0] if cells else ""

    @staticmethod
    def _extract_labeled_value(text: str, labels: list[str]) -> str:
        for label in labels:
            match = re.search(rf"{re.escape(label)}\s*[:：]?\s*([^|;；]+)", text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

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
    def _safe_cell(cells: list[str], index: int) -> str:
        return cells[index] if len(cells) > index else ""

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
