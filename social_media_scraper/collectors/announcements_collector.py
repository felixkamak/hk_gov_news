"""Collector for exam schedules and government announcement pages."""

from __future__ import annotations

import re
from datetime import date
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

# Context markers that indicate a NON-Hong-Kong (overseas) exam sitting.
# Application windows sitting next to these must never be attached to the HK round.
_OVERSEAS_MARKERS = (
    "香港以外",
    "以外地區",
    "海外",
    "七個城市",
    "北京",
    "上海",
    "倫敦",
    "紐約",
    "多倫多",
    "溫哥華",
    "悉尼",
)

# CSB rewords this page freely (e.g. 暫定於 -> 擬於, 下一次 -> 是次). Match on any
# of these round markers / lead-in verbs instead of a single hard-coded word, so a
# harmless rewrite never makes the HK exam item silently vanish again.
_ROUND_MARKERS = ("下一次", "是次", "另一輪", "本輪", "新一輪", "年終")
_LEADIN_VERBS = ("暫定於", "擬於", "將於", "定於", "於")

# City list used to positively identify the overseas paragraph.
_OVERSEAS_CITIES = ("北京", "上海", "倫敦", "紐約", "多倫多", "溫哥華", "悉尼")


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
        """Emit the HK sitting and the overseas sitting as separate, independent items.

        The overseas round is parsed by a dedicated method so the HK mis-stitch
        guard (which discards overseas application windows) stays intact while the
        overseas registration window is still surfaced on its own.
        """
        text = self._csb_exam_prose(soup)
        return self._parse_hk_cre(text) + self._parse_overseas_cre_sitting(text)

    def _parse_hk_cre(self, text: str) -> list[dict[str, Any]]:
        exam_date = self._extract_next_cre_exam_date(text)
        app_start, app_end = self._extract_application_window(text)
        closed = self._hk_application_closed(text)

        # If the HK application window has already closed, never emit a fake
        # "報名中" window — surface the exam as a prep-stage item instead.
        if closed:
            app_start, app_end = "", ""

        if not exam_date and not (app_start and app_end):
            return []

        # Open HK application window (future) -> report the window.
        if app_start and app_end and not closed:
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

        # Exam date known but application closed (or no valid window) -> prep item.
        if exam_date and closed:
            summary = (
                f"下一次綜合招聘考試暫定 {exam_date}；"
                f"香港試場報名已結束，考生現處備考階段。"
            )
            title = "綜合招聘考試（下一輪）"
        elif exam_date:
            summary = f"下一次綜合招聘考試暫定 {exam_date}。"
            title = "綜合招聘考試（下一輪）"
        else:
            return []

        return [
            self._make_item(
                title=title,
                url=self.source["url"],
                published_date="",
                summary=summary,
                closing_date="",
                content_type="exam",
            )
        ]

    def _parse_overseas_cre_sitting(self, text: str) -> list[dict[str, Any]]:
        """Surface the香港以外 (overseas) CRE round as its own item.

        This is the round that matters most to mainland xiaohongshu readers
        (Beijing / Shanghai centres) and is the one the pipeline used to drop
        entirely because the HK guard filters out any overseas application window.
        """
        # Only proceed if the page actually describes an overseas sitting.
        if not (any(m in text for m in ("香港以外", "以外地區")) and any(c in text for c in _OVERSEAS_CITIES)):
            return []

        exam_date = self._extract_overseas_exam_date(text)
        app_start, app_end = self._extract_overseas_application_window(text)
        if not exam_date and not (app_start and app_end):
            return []

        cities = "、".join(c for c in _OVERSEAS_CITIES if c in text)
        date_part = f"境外場暫定 {exam_date} 舉行" if exam_date else "境外場"
        if cities:
            date_part += f"（{cities}）"

        if app_start and app_end:
            try:
                window_open = date.fromisoformat(app_end) >= date.today()
            except ValueError:
                window_open = True
            if window_open:
                summary = f"{date_part}；報名 {app_start} 至 {app_end}。"
                return [
                    self._make_item(
                        title="綜合招聘考試（境外場）報名",
                        url=self.source["url"],
                        published_date="",
                        summary=summary,
                        closing_date=app_end,
                        content_type="exam",
                    )
                ]
            summary = f"{date_part}；報名 {app_start} 至 {app_end} 已結束，考生現處備考階段。"
        else:
            summary = f"{date_part}。詳情將於稍後公布。"

        return [
            self._make_item(
                title="綜合招聘考試（境外場）",
                url=self.source["url"],
                published_date="",
                summary=summary,
                closing_date=app_end,
                content_type="exam",
            )
        ]

    @staticmethod
    def _extract_overseas_exam_date(text: str) -> str:
        """The overseas sitting date: a CRE date directly followed, within the SAME
        sentence, by an overseas marker AND 舉行 (e.g. "暫定於2026年12月5日在香港以外
        的七個城市舉行"). Staying inside one sentence prevents a nearby HK-section date
        (e.g. the 9月21日 email-notice date) from bleeding into the overseas heading."""
        for match in _CN_DATE.finditer(text):
            seg = text[match.end() :].split("。")[0][:60]
            if any(m in seg for m in _OVERSEAS_MARKERS) and "舉行" in seg:
                return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        return ""

    def _extract_overseas_application_window(self, text: str) -> tuple[str, str]:
        """The overseas application window: same shape as the HK one, but the
        overseas-context requirement is INVERTED — we keep only windows that DO
        sit next to overseas markers (香港以外, 七個城市, 北京 ...)."""
        for match in re.finditer(
            r"(?:申請日期|報名)[^。；]{0,30}?(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(?:至|由)?\s*"
            r"(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日",
            text,
        ):
            context = text[max(0, match.start() - 50) : match.end() + 5]
            if not any(marker in context for marker in _OVERSEAS_MARKERS):
                continue  # this is the HK window, handled elsewhere
            y1, m1, d1 = match.group(1), match.group(2), match.group(3)
            y2 = match.group(4) or y1
            m2, d2 = match.group(5), match.group(6)
            return self._format_cn_date(y1, m1, d1), self._format_cn_date(y2, m2, d2)
        return "", ""

    @staticmethod
    def _hk_application_closed(text: str) -> bool:
        """True when the page states the HK application period has already ended."""
        for match in re.finditer(r"申請期已[^。；]{0,40}?完結", text):
            window = text[max(0, match.start() - 40) : match.end()]
            if "以外" not in window:  # ignore overseas-round wording
                return True
        return False

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
        """Return the next Hong Kong CRE sitting date.

        Robust to CSB rewordings: the sitting date is any CRE date whose nearby
        context (a) mentions 綜合招聘, (b) carries a round marker OR a lead-in verb,
        and (c) is NOT an overseas sitting. This survives "是次綜合招聘考試擬於
        2026年10月3日" just as well as the old "下一次…暫定於…" phrasing, while the
        overseas guard keeps the 12月 境外場 date from being mistaken for the HK one.
        """
        for match in _CN_DATE.finditer(text):
            window = text[max(0, match.start() - 45) : match.end() + 12]
            if "綜合招聘" not in window:
                continue
            if any(marker in window for marker in _OVERSEAS_MARKERS):
                continue  # this is the overseas sitting, not the HK one
            has_round = any(marker in window for marker in _ROUND_MARKERS)
            has_verb = any(verb in window for verb in _LEADIN_VERBS)
            if has_round or has_verb:
                return self._format_cn_date(match.group(1), match.group(2), match.group(3))
        return ""

    def _extract_application_window(self, text: str) -> tuple[str, str]:
        """Parse the HK CRE application window (申請日期為2026年7月25日至8月7日).

        Two guards prevent the notorious mis-stitch bug:
        1. Context filter -- a window sitting next to overseas markers (香港以外,
           七個城市, 北京 ...) belongs to the year-end overseas sitting, NOT the
           HK round, so it is skipped.
        2. Future check -- a window whose end date is already in the past is
           never surfaced as an open application.
        """
        today = date.today()
        for match in re.finditer(
            r"(?:申請日期|報名)[^。；]{0,30}?(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(?:至|由)?\s*"
            r"(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日",
            text,
        ):
            context = text[max(0, match.start() - 50) : match.end() + 5]
            if any(marker in context for marker in _OVERSEAS_MARKERS):
                continue
            y1, m1, d1 = match.group(1), match.group(2), match.group(3)
            y2 = match.group(4) or y1
            m2, d2 = match.group(5), match.group(6)
            start = self._format_cn_date(y1, m1, d1)
            end = self._format_cn_date(y2, m2, d2)
            try:
                if date.fromisoformat(end) < today:
                    continue
            except ValueError:
                continue
            return start, end
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
        seen: set[tuple[str, str]] = set()
        unique: list[dict[str, Any]] = []
        for item in items:
            url = str(item.get("url") or "")
            title = str(item.get("title") or "")
            # Key on (url, title): one page can legitimately yield several items
            # (e.g. 949.html emits both the HK sitting and the overseas sitting),
            # so keying on url alone would silently drop the second one.
            key = (url, title)
            if not (url or title) or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique
