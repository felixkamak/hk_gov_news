"""Collector for info.gov.hk daily government press releases (policy news).

Ported into the social_media_scraper package from newsletter_v2. Differences:
- Uses this package's BaseCollector (retrying fetch, polite delay).
- Applies the Option-3 relevance allowlist (公務員 + 考試時事) so only headlines
  useful to AceGovHK's audience survive; everything else is dropped.
- Defensive list-container selection with fallbacks, because info.gov.hk markup
  drifts over time.
- Carries a per-source `date` so week-bucketing stays correct even when the page
  banner date cannot be parsed.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector
from config import (
    POLICY_ALLOW_KEYWORDS,
    POLICY_EXCLUDE_KEYWORDS,
    URGENT_KEYWORDS,
)

INFO_GOV_HK_BASE = "https://www.info.gov.hk"
TODAY_URL = f"{INFO_GOV_HK_BASE}/gia/general/ctoday.htm"


def build_historical_url(target_date: date) -> str:
    """URL for a specific day's press-release index: /gia/general/YYYYMM/DDc.htm."""
    year_month = target_date.strftime("%Y%m")
    day = target_date.strftime("%d")
    return f"{INFO_GOV_HK_BASE}/gia/general/{year_month}/{day}c.htm"


def build_backfill_sources(
    days_back: int,
    anchor_date: date | None = None,
) -> list[dict[str, Any]]:
    """Source dicts for the last `days_back` days (today first).

    Day 0 uses the stable ctoday.htm URL; earlier days use dated historical URLs.
    Each source carries an explicit `date` used as a published-date fallback.
    """
    anchor = anchor_date or date.today()
    sources: list[dict[str, Any]] = []
    for offset in range(max(days_back, 1)):
        target_date = anchor - timedelta(days=offset)
        url = TODAY_URL if offset == 0 else build_historical_url(target_date)
        sources.append(
            {
                "name": f"info_gov_hk_{target_date.isoformat()}",
                "source_name": "政府新聞處",
                "url": url,
                "date": target_date.isoformat(),
            }
        )
    return sources


class InfoGovHkCollector(BaseCollector):
    """Parse one info.gov.hk daily index page into filtered policy-news items."""

    def parse(self) -> list[dict[str, Any]]:
        response = self.fetch()
        if response is None:
            return []

        soup = BeautifulSoup(self._decode(response), "html.parser")
        published_date = self._parse_page_date(soup) or self.source.get("date", "")
        source_url = self.source["url"]
        source_name = self.source.get("source_name", "政府新聞處")

        links = self._find_news_links(soup)
        if not links:
            self.logger.warning("No news list found on %s", source_url)
            return []

        items: list[dict[str, Any]] = []
        for link in links:
            title = link.get_text(strip=True)
            if not title or len(title) < 4:
                continue
            if not self._is_relevant(title):
                continue

            absolute_url = urljoin(INFO_GOV_HK_BASE, link["href"])
            category = self._categorise(title)
            urgent = any(keyword in title for keyword in URGENT_KEYWORDS)
            items.append(
                {
                    "title": title,
                    "url": absolute_url,
                    "published_date": published_date,
                    "summary": "",
                    "source_name": source_name,
                    "source_url": source_url,
                    "content_type": "policy_news",
                    "category": category,
                    "is_urgent": urgent,
                }
            )

        self.logger.info(
            "Parsed %d relevant policy item(s) from %s", len(items), source_url
        )
        return items

    # -- relevance -----------------------------------------------------------

    @staticmethod
    def _is_relevant(title: str) -> bool:
        """Keep only allowlisted headlines that are not on the exclusion list."""
        if any(bad in title for bad in POLICY_EXCLUDE_KEYWORDS):
            return False
        return any(good in title for good in POLICY_ALLOW_KEYWORDS)

    @staticmethod
    def _categorise(title: str) -> str:
        """Coarse tag so downstream content can pick an angle."""
        civil = (
            "公務員", "公職", "編制", "常額", "職系", "首長級", "政務主任",
            "政務官", "行政主任", "薪酬", "薪級", "頂薪", "增薪", "退休金",
            "公積金", "任命", "委任", "出任", "就任", "常任秘書長",
        )
        security = (
            "基本法", "國家安全", "國安法", "國安", "一國兩制", "愛國者",
            "憲法", "人大", "政協", "政制", "選舉",
        )
        if any(k in title for k in civil):
            return "civil_service"
        if any(k in title for k in security):
            return "security_law"
        return "policy"

    # -- markup handling -----------------------------------------------------

    def _find_news_links(self, soup: BeautifulSoup) -> list[Any]:
        """Locate the press-release <a> links with several fallbacks.

        info.gov.hk markup has drifted before; try the known container first,
        then progressively looser selectors, and finally filter loose anchors
        by their href shape (dated article paths).
        """
        selectors = [
            "#contentBody ul.list.fontSize1",
            "#contentBody ul.list",
            "#contentBody ul",
            "ul.list.fontSize1",
        ]
        for selector in selectors:
            container = soup.select_one(selector)
            if container is not None:
                links = container.select("li > a[href]") or container.select("a[href]")
                if links:
                    return links

        # Last resort: any anchor pointing at a dated GIA article path.
        dated = re.compile(r"/gia/general/\d{6}/\d{2}/", re.I)
        return [a for a in soup.select("a[href]") if dated.search(a.get("href", ""))]

    def _parse_page_date(self, soup: BeautifulSoup) -> str:
        """Read DD-MM-YYYY from #headerBanner and normalise to ISO."""
        header_banner = soup.select_one("#headerBanner")
        if header_banner is None:
            return ""
        raw = header_banner.get_text(strip=True)
        match = re.search(r"(\d{1,2})-(\d{1,2})-(20\d{2})", raw)
        if not match:
            return ""
        day, month, year = match.group(1), match.group(2), match.group(3)
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    @staticmethod
    def _decode(response: Any) -> str:
        for encoding in ("utf-8", "big5", "hkscs", response.apparent_encoding or "utf-8"):
            try:
                return response.content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return response.text
