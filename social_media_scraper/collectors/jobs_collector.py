"""Collector for government job vacancy pages."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from collectors.base_collector import BaseCollector
from config import POLITE_DELAY_SECONDS, REQUEST_RETRIES, REQUEST_TIMEOUT, URGENT_KEYWORDS

CSB_JOB_LIST_URL = "https://csboa1.csb.gov.hk/csboa/jve/JVE_001_text.action?languageType=1"
CSB_JOB_LIST_URLS = [
    "https://csboa1.csb.gov.hk/csboa/jve/JVE_001_text.action?languageType=1",
    "https://csboa2.csb.gov.hk/csboa/jve/JVE_001_text.action?languageType=1",
]
# Fail fast on a dead mirror (Errno 101 / SSL) then try the next host.
CSB_CONNECT_TIMEOUT = 5

TITLE_BLOCKLIST = {
    "職位名稱",
    "部門",
    "薪酬",
    "學歷要求",
    "刊登日期",
    "截止申請日期",
    "經互聯網遞交申請",
    "職位編號",
}

TARGET_TITLES = [
    "入境事務助理員",
    "入境主任",
    "入境事務主任",
    "助理文書主任",
    "文員",
    "文書助理",
    "二級文員",
    "二級私人秘書",
    "私人秘書",
    "海關督察",
    "關員",
    "懲教",
    "消防",
    "警務",
    "督察",
]

DATE_HEADER_MARKERS = ("日/月/年", "日 / 月 / 年", "DD/MM/YYYY")


class JobsCollector(BaseCollector):
    """Collect job postings; CSB uses the JVE table layout with gate-page handling."""

    def parse(self) -> list[dict[str, Any]]:
        if self._is_csb_job_system():
            items = self._parse_csb_job_system()
        else:
            items = self._parse_generic_site()
        return self._dedupe(items)

    def _is_csb_job_system(self) -> bool:
        for url in self._csb_candidate_urls():
            lowered = url.lower()
            if "csboa" in lowered and "csb.gov.hk" in lowered and "jve" in lowered:
                return True
        return False

    def _csb_candidate_urls(self) -> list[str]:
        urls = self.source.get("urls")
        if isinstance(urls, list) and urls:
            return [str(u) for u in urls if u]
        primary = self.source.get("url") or CSB_JOB_LIST_URL
        # Prefer configured primary; fall back to the known mirror list.
        ordered = [str(primary)]
        for url in CSB_JOB_LIST_URLS:
            if url not in ordered:
                ordered.append(url)
        return ordered

    def _parse_csb_job_system(self) -> list[dict[str, Any]]:
        """Try each JVE mirror in order; return jobs from the first that parses."""
        for url in self._csb_candidate_urls():
            try:
                self.logger.info("Trying CSB JVE host: %s", url)
                html = self._load_csb_job_list_html(url)
                if not html:
                    self.logger.warning("CSB JVE host yielded no HTML: %s", url)
                    continue

                soup = BeautifulSoup(html, "lxml")
                items = self._parse_csb_table_rows(soup, base_url=url)
                if not items:
                    items = self._parse_csb_mega_row(soup, base_url=url)

                if not items:
                    self.logger.warning("CSB JVE host had HTML but 0 parseable jobs: %s", url)
                    continue

                matched = [
                    item for item in items if self._matches_target_title(item.get("title", ""))
                ]
                self.logger.info(
                    "CSB JVE host %s parsed %s jobs (%s target matches)",
                    url,
                    len(items),
                    len(matched),
                )
                return matched
            except Exception as exc:
                self.logger.warning("CSB JVE host failed, trying next: %s (%s)", url, exc)
                continue

        return []

    def _load_csb_job_list_html(self, url: str) -> str:
        """Fetch the job list, submitting notice-page continue forms when needed."""
        time.sleep(POLITE_DELAY_SECONDS)

        for _ in range(4):
            response = self._session_get(url)
            if response is None:
                return ""

            html = self._decode_response(response)
            soup = BeautifulSoup(html, "lxml")
            if self._count_parseable_job_rows(soup) > 0:
                return html

            continued = self._submit_notice_continue(soup, response.url)
            if continued is None:
                return html
            time.sleep(POLITE_DELAY_SECONDS)

        return html

    def _csb_timeout(self) -> tuple[int, int]:
        return (CSB_CONNECT_TIMEOUT, REQUEST_TIMEOUT)

    def _session_get(self, url: str) -> requests.Response | None:
        for attempt in range(1, REQUEST_RETRIES + 1):
            try:
                response = self.session.get(url, timeout=self._csb_timeout())
                self.logger.info(
                    "GET %s -> HTTP %s (attempt %s/%s)",
                    url,
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
                    url,
                    attempt,
                    REQUEST_RETRIES,
                    exc,
                )
                if attempt < REQUEST_RETRIES:
                    time.sleep(attempt)
        return None

    def _submit_notice_continue(self, soup: BeautifulSoup, page_url: str) -> requests.Response | None:
        """POST or GET the maintenance/important-notice continue action."""
        timeout = self._csb_timeout()
        for form in soup.find_all("form"):
            submit_control = self._find_continue_control(form)
            if submit_control is None:
                continue

            action = urljoin(page_url, form.get("action") or page_url)
            method = (form.get("method") or "get").lower()
            payload = self._form_payload(form, submit_control)

            try:
                if method == "post":
                    response = self.session.post(action, data=payload, timeout=timeout)
                else:
                    response = self.session.get(action, params=payload, timeout=timeout)
                self.logger.info("Notice continue %s -> HTTP %s", action, response.status_code)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                self.logger.warning("Notice continue failed for %s: %s", action, exc)

        for link in soup.find_all("a", href=True):
            label = self._clean_text(link.get_text(" ", strip=True))
            if not self._is_continue_label(label):
                continue
            href = urljoin(page_url, link["href"])
            try:
                response = self.session.get(href, timeout=timeout)
                self.logger.info("Notice continue link %s -> HTTP %s", href, response.status_code)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                self.logger.warning("Notice continue link failed for %s: %s", href, exc)

        return None

    @staticmethod
    def _find_continue_control(form: Tag) -> Tag | None:
        for control in form.find_all(["input", "button"]):
            label = f"{control.get('value', '')} {control.get_text(' ', strip=True)}"
            if JobsCollector._is_continue_label(label):
                return control
        return None

    @staticmethod
    def _is_continue_label(text: str) -> bool:
        lowered = text.lower()
        return (
            "繼續" in text
            or "continue" in lowered
            or "明白" in text
            or "proceed" in lowered
            or "i understand" in lowered
        )

    @staticmethod
    def _form_payload(form: Tag, submit_control: Tag) -> dict[str, str]:
        payload: dict[str, str] = {}
        for field in form.find_all("input"):
            name = field.get("name")
            if not name or field.get("type") == "submit":
                continue
            payload[name] = field.get("value", "")
        submit_name = submit_control.get("name")
        if submit_name:
            payload[submit_name] = submit_control.get("value", "")
        return payload

    def _parse_csb_table_rows(
        self, soup: BeautifulSoup, base_url: str | None = None
    ) -> list[dict[str, Any]]:
        base = base_url or self.source.get("url", CSB_JOB_LIST_URL)
        items: list[dict[str, Any]] = []

        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 7:
                continue
            item = self._parse_csb_row(cells, base)
            if item:
                items.append(item)

        return items

    def _parse_csb_mega_row(
        self, soup: BeautifulSoup, base_url: str | None = None
    ) -> list[dict[str, Any]]:
        """Fallback when all vacancies are rendered inside one wide table row."""
        base = base_url or self.source.get("url", CSB_JOB_LIST_URL)
        items: list[dict[str, Any]] = []

        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 16:
                continue

            start = 1 if cells[0].find("a") and len(cells[0].get_text(strip=True)) > 80 else 0
            for index in range(start, len(cells), 8):
                chunk = cells[index : index + 8]
                if len(chunk) < 8:
                    break
                item = self._parse_csb_row(chunk, base)
                if item:
                    items.append(item)

        return items

    def _parse_csb_row(self, cells: list[Tag], base_url: str) -> dict[str, Any] | None:
        layout = self._detect_csb_layout(cells)
        if layout is None:
            return None

        title_cell = cells[layout["title"]]
        title_link = title_cell.find("a", href=True)
        if title_link is None:
            return None

        title = self._clean_text(title_link.get_text(" ", strip=True))
        if title in TITLE_BLOCKLIST or len(title) < 3:
            return None

        department = self._clean_text(cells[layout["department"]].get_text(" ", strip=True))
        if department in TITLE_BLOCKLIST:
            return None
        if department == title:
            return None

        job_id = self._clean_text(cells[layout["job_id"]].get_text(" ", strip=True))
        detail_link = cells[layout["job_id"]].find("a", href=True)
        detail_url = urljoin(base_url, detail_link["href"]) if detail_link else ""
        if not detail_url:
            return None

        salary = self._clean_text(cells[layout["salary"]].get_text(" ", strip=True))
        published_raw = self._clean_text(cells[layout["published"]].get_text(" ", strip=True))
        closing_raw = self._clean_text(cells[layout["closing"]].get_text(" ", strip=True))

        published_date = self._parse_date(published_raw)
        closing_date = self._parse_closing_date(closing_raw)

        priority = "urgent" if any(keyword in title for keyword in URGENT_KEYWORDS) else "normal"
        summary = (
            f"職位: {title}; 部門: {department}; 職位編號: {job_id}; "
            f"薪酬: {salary}; 截止: {closing_date or closing_raw}"
        )

        return {
            "title": title,
            "url": detail_url,
            "department": department,
            "job_id": job_id,
            "salary": salary,
            "published_date": published_date,
            "closing_date": closing_date,
            "source_name": self.source.get("source_name", "公務員事務局"),
            "source_url": base_url,
            "content_type": "job",
            "preclassified_priority": priority,
            "summary": summary[:150],
            "is_urgent": priority == "urgent",
        }

    @staticmethod
    def _detect_csb_layout(cells: list[Tag]) -> dict[str, int] | None:
        """Detect 9-column (with checkbox) or 8-column CSB table layouts."""
        if len(cells) >= 8:
            title_idx = 2
            title_link = cells[title_idx].find("a", href=True) if len(cells) > title_idx else None
            title_text = title_link.get_text(strip=True) if title_link else ""
            job_id_text = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            if title_link and title_text and not title_text.isdigit() and job_id_text.isdigit():
                return {
                    "department": 1,
                    "title": 2,
                    "job_id": 3,
                    "salary": 4,
                    "published": 6,
                    "closing": 7,
                }

        if len(cells) >= 7:
            title_idx = 1
            title_link = cells[title_idx].find("a", href=True)
            title_text = title_link.get_text(strip=True) if title_link else ""
            job_id_text = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            if title_link and title_text and not title_text.isdigit() and job_id_text.isdigit():
                return {
                    "department": 0,
                    "title": 1,
                    "job_id": 2,
                    "salary": 3,
                    "published": 5,
                    "closing": 6,
                }

        return None

    def _count_parseable_job_rows(self, soup: BeautifulSoup) -> int:
        count = 0
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 7:
                continue
            layout = self._detect_csb_layout(cells)
            if layout and cells[layout["title"]].find("a", href=True):
                count += 1
        return count

    @staticmethod
    def _parse_date(text: str) -> str:
        if not text or any(marker in text for marker in DATE_HEADER_MARKERS):
            return ""

        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text.strip())
        if match:
            day, month, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            return f"{year:04d}-{month:02d}-{day:02d}"

        match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if match:
            day, month, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            return f"{year:04d}-{month:02d}-{day:02d}"

        return ""

    @staticmethod
    def _parse_closing_date(text: str) -> str:
        if not text:
            return ""
        if any(marker in text for marker in DATE_HEADER_MARKERS):
            return ""
        if "全年" in text or "另行通知" in text:
            return "全年接受申請"
        if re.search(r"\d{1,2}/\d{1,2}/\d{4}", text):
            return JobsCollector._parse_date(text.split()[0])
        return ""

    @staticmethod
    def _matches_target_title(title: str) -> bool:
        return any(keyword in title for keyword in TARGET_TITLES)

    def _parse_generic_site(self) -> list[dict[str, Any]]:
        """Parse non-CSB recruitment pages with lightweight link extraction."""
        response = self.fetch()
        if response is None:
            return []

        soup = BeautifulSoup(self._decode_response(response), "lxml")
        items: list[dict[str, Any]] = []
        for link in soup.find_all("a", href=True):
            title = self._clean_text(link.get_text(" ", strip=True))
            if len(title) < 3 or not self._looks_like_recruitment(title):
                continue

            url = urljoin(self.source["url"], link["href"])
            context = link.find_parent(["tr", "li", "p", "div"])
            summary = self._clean_text(context.get_text(" ", strip=True)) if context else title
            priority = "urgent" if any(keyword in title for keyword in URGENT_KEYWORDS) else "normal"
            items.append(
                {
                    "title": title,
                    "url": url,
                    "department": "",
                    "job_id": "",
                    "salary": "",
                    "published_date": self._parse_date(summary),
                    "closing_date": self._parse_closing_date(summary),
                    "source_name": self.source.get("source_name", self.source["name"]),
                    "source_url": self.source["url"],
                    "content_type": "job",
                    "preclassified_priority": priority,
                    "summary": summary[:150],
                    "is_urgent": priority == "urgent",
                }
            )
        return items

    @staticmethod
    def _looks_like_recruitment(text: str) -> bool:
        signals = ["招聘", "空缺", "職位", "招募", "投考", "督察", "文員", "主任", "助理"]
        return any(signal in text for signal in signals)

    @staticmethod
    def _decode_response(response: Any) -> str:
        for encoding in ("utf-8", "big5", "hkscs", response.apparent_encoding or "utf-8"):
            try:
                return response.content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return response.text

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
