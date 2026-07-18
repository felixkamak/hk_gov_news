"""Collector for exam schedules and government announcement pages."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector
from config import URGENT_KEYWORDS


# Full Chinese date: 2026年7月25日 (spaces optional)
_CN_DATE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")

_JUNK_TEXT_MARKERS = (
    "服務承諾",
    "參考視頻",
    "參考試題",
    "舉行考試日期",
)


class AnnouncementsCollector(BaseCollector):
    """Collect exam dates, format changes, and application window announcements."""

    def parse(self) -> list[dict[str, Any]]:
        response = self.fetch()
        if response is None:
            return []

        soup = BeautifulSoup(self._decode_response(response), "lxml")
        if self._is_csb_exam_page():
            items = self._parse_csb_exam_page(soup)
        else:
            items = self._parse_tables(soup)
            if not items:
                items = self._parse_links(soup)
            if not items:
                items = self._parse_page_text(soup)
        return self._dedupe(items)

    def _is_csb_exam_page(self) -> bool:
        url = str(self.source.get("url", "")).lower()
        return "csb.gov.hk" in url and ("/cre/949" in url or "/2934" in url)

    def _parse_csb_exam_page(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Prose-only extraction for CRE / Digital BLNST pages (no table/link scrape)."""
        url = str(self.source.get("url", "")).lower()
        if "/2934" in url:
            return self._build_blnst_item(soup)
        if "/cre/949" in url:
            return self._parse_cre_exam_page(soup)
        return []

    def _build_blnst_item(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Digital BLNST runs year-round — emit one stable item, never weather/table junk."""
        text = self._csb_exam_prose(soup)
        if "基本法" not in text and "BLNST" not in text.upper() and "數碼化" not in text:
            return []
        return [
            self._make_item(
                title="數碼化基本法及香港國安法測試（全年）",
                url=self.source["url"],
                published_date="",
                summary=(
                    "數碼化「基本法及香港國安法測試」全年逢星期一至五於稅務大樓舉行，"
                    "先到先得，可預約未來八星期內時段。"
                ),
                closing_date="全年接受申請",
                content_type="exam",
            )
        ]

    def _parse_cre_exam_page(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        text = self._csb_exam_prose(soup)
        exam_date = self._extract_next_cre_exam_date(text)
        app_start, app_end = self._extract_application_window(text)

        if not exam_date and not (app_start and app_end):
            return []

        if app_start and app_end:
            if exam_date:
                summary = (
                    f"下一次綜合招聘考試暫定 {exam_date}；"
                    f"申請日期 {app_start} 至 {app_end}。"
                )
            else:
                summary = f"綜合招聘考試申請日期 {app_start} 至 {app_end}。"
            return [
                self._make_item(
                    title="綜合招聘考試（下一輪）報名",
                    url=self.source["url"],
                    published_date="",
                    summary=summary,
                    closing_date=app_end,
                    content_type="exam",
                )
            ]

        return [
            self._make_item(
                title="綜合招聘考試（下一輪）報名",
                url=self.source["url"],
                published_date="",
                summary=f"下一次綜合招聘考試暫定 {exam_date}。",
                closing_date="",
                content_type="exam",
            )
        ]

    def _csb_exam_prose(self, soup: BeautifulSoup) -> str:
        """Main-content prose with weather sections and obvious junk stripped."""
        working = BeautifulSoup(str(soup), "lxml")
        for tag in working(["script", "style", "noscript"]):
            tag.decompose()

        # Drop weather-arrangement blocks when they appear as discrete elements.
        for node in list(working.find_all(string=re.compile(r"惡劣天氣"))):
            parent = node.find_parent(["div", "section", "article", "li", "tr", "table"])
            if parent is not None:
                parent.decompose()

        text = self._clean_text(working.get_text(" ", strip=True))
        # Fallback: strip weather section from flat text if still present.
        text = re.sub(r"惡劣天氣.*?(?=申請資格|考試場次|數碼化「基本法|綜合招聘|查詢|$)", "", text)
        for marker in _JUNK_TEXT_MARKERS:
            # Soft-remove table-header style fragments so date parsers ignore them.
            text = text.replace(marker, " ")
        # Never treat emails / social / pdfs as content signals.
        text = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", " ", text)
        text = re.sub(r"https?://(?:www\.)?facebook\.com\S*", " ", text, flags=re.I)
        text = re.sub(r"\S+\.pdf\b", " ", text, flags=re.I)
        return self._clean_text(text)

    def _extract_next_cre_exam_date(self, text: str) -> str:
        """Prefer the next Hong Kong CRE sitting (暫定 / 下一次), not past rounds."""
        patterns = [
            r"下一次綜合招聘考試暫定於\s*" + _CN_DATE.pattern,
            r"下一次.*?綜合招聘考試.*?暫定於\s*" + _CN_DATE.pattern,
            r"綜合招聘考試暫定於\s*" + _CN_DATE.pattern,
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return self._format_cn_date(match.group(1), match.group(2), match.group(3))

        # Nearby context: 下一次 … 2026年10月3日
        for match in _CN_DATE.finditer(text):
            start = max(0, match.start() - 40)
            window = text[start : match.end() + 10]
            if "下一次" in window and "綜合招聘" in window:
                return self._format_cn_date(match.group(1), match.group(2), match.group(3))
            if "暫定" in window and "綜合招聘" in window and "以外" not in window:
                return self._format_cn_date(match.group(1), match.group(2), match.group(3))
        return ""

    def _extract_application_window(self, text: str) -> tuple[str, str]:
        """Parse 申請日期為2026年7月25日至8月7日 (end may omit year)."""
        for match in re.finditer(
            r"(?:申請日期|報名)[^。；]{0,30}?(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*至\s*"
            r"(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日",
            text,
        ):
            y1, m1, d1 = match.group(1), match.group(2), match.group(3)
            y2 = match.group(4) or y1
            m2, d2 = match.group(5), match.group(6)
            return (
                self._format_cn_date(y1, m1, d1),
                self._format_cn_date(y2, m2, d2),
            )
        return "", ""

    @staticmethod
    def _format_cn_date(year: str, month: str, day: str) -> str:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

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
            if self._is_junk_announcement(row_text, ""):
                continue
            if not self._looks_relevant(row_text):
                continue

            link = row.find("a", href=True)
            href = link["href"] if link else ""
            if self._is_junk_href(href):
                continue
            title = self._pick_title(cells, link.get_text(" ", strip=True) if link else "")
            if not title:
                title = cells[0]
            if self._is_junk_announcement(title, row_text):
                continue
            url = urljoin(self.source["url"], href) if link else self.source["url"]
            published_date = self._extract_date(row_text)
            items.append(self._make_item(title, url, published_date, row_text))
        return items

    def _parse_links(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if self._is_junk_href(href):
                continue
            title = self._clean_text(link.get_text(" ", strip=True))
            if not title or len(title) < 4:
                continue
            context = link.find_parent(["tr", "li", "p", "div"])
            summary = self._clean_text(context.get_text(" ", strip=True)) if context else title
            if self._is_junk_announcement(title, summary):
                continue
            if not self._looks_relevant(f"{title} {summary}"):
                continue
            items.append(
                self._make_item(
                    title=title,
                    url=urljoin(self.source["url"], href),
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
        if self._is_junk_announcement("", text):
            return []
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
        closing_date: str = "",
        content_type: str | None = None,
    ) -> dict[str, Any]:
        combined = f"{title} {summary}"
        resolved_type = content_type or ("exam" if self._looks_like_exam(combined) else "announcement")
        urgent = any(keyword in combined for keyword in URGENT_KEYWORDS)
        return {
            "title": title,
            "url": url,
            "published_date": published_date,
            "summary": summary[:150],
            "source_name": self.source.get("source_name", self.source["name"]),
            "source_url": self.source["url"],
            "content_type": resolved_type,
            "closing_date": closing_date,
            "is_urgent": urgent,
        }

    @staticmethod
    def _is_junk_href(href: str) -> bool:
        lowered = (href or "").strip().lower()
        if not lowered:
            return False
        if lowered.startswith("mailto:") or "@" in lowered:
            return True
        if "facebook.com" in lowered:
            return True
        if lowered.endswith(".pdf") or ".pdf?" in lowered:
            return True
        return False

    @staticmethod
    def _is_junk_announcement(title: str, summary: str) -> bool:
        combined = f"{title} {summary}"
        if re.search(r"[\w.+-]+@[\w.-]+\.\w+", combined):
            return True
        if "惡劣天氣" in combined:
            return True
        if any(marker in combined for marker in _JUNK_TEXT_MARKERS):
            return True
        if "facebook.com" in combined.lower():
            return True
        return False

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
        match = _CN_DATE.search(text)
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        match = re.search(r"(20\d{2})[./\-](\d{1,2})[./\-](\d{1,2})", text)
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        match = re.search(r"(\d{1,2})[./\-](\d{1,2})[./\-](20\d{2})", text)
        if match:
            return f"{int(match.group(3)):04d}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
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
