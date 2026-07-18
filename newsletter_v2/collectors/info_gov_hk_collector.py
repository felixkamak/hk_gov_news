from datetime import date, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from newsletter_v2.collectors.base_collector import BaseCollector

INFO_GOV_HK_BASE = "https://www.info.gov.hk"
TODAY_URL = f"{INFO_GOV_HK_BASE}/gia/general/ctoday.htm"

TODAY_SOURCE = {
    "name": "info_gov_hk_today",
    "source_name": "政府新聞處",
    "url": TODAY_URL,
}

JOB_EXCLUSION_KEYWORDS = [
    "招聘",
    "請人",
    "職位空缺",
    "招考",
    "聘請",
]


def build_historical_url(target_date: date) -> str:
    year_month = target_date.strftime("%Y%m")
    day = target_date.strftime("%d")
    return f"{INFO_GOV_HK_BASE}/gia/general/{year_month}/{day}c.htm"


def build_backfill_sources(
    days_back: int,
    anchor_date: date | None = None,
) -> list[dict]:
    """
    Build source dicts for historical backfill.

    NOT intended to run on a recurring schedule — use this manually/once
    to seed historical data, then rely on run_daily() going forward.
    """
    anchor = anchor_date or date.today()
    sources = []
    for offset in range(days_back):
        target_date = anchor - timedelta(days=offset)
        sources.append(
            {
                "name": f"info_gov_hk_{target_date.isoformat()}",
                "source_name": "政府新聞處",
                "url": build_historical_url(target_date),
            }
        )
    return sources


class InfoGovHkCollector(BaseCollector):
    def parse(self) -> list[dict]:
        response = self.fetch()
        if response is None:
            return []

        soup = BeautifulSoup(response.content, "html.parser")
        published_date = self._parse_page_date(soup)
        source_url = self.source["url"]
        source_name = self.source.get("source_name", "政府新聞處")

        items = []
        list_container = soup.select_one("#contentBody ul.list.fontSize1")
        if list_container is None:
            self.logger.warning("No news list found on %s", source_url)
            return []

        for link in list_container.select("li > a[href]"):
            title = link.get_text(strip=True)
            if not title:
                continue

            if any(keyword in title for keyword in JOB_EXCLUSION_KEYWORDS):
                self.logger.info("Skipping recruitment headline: %s", title)
                continue

            absolute_url = urljoin(INFO_GOV_HK_BASE, link["href"])
            items.append(
                {
                    "title": title,
                    "url": absolute_url,
                    "published_date": published_date,
                    "summary": "",
                    "source_name": source_name,
                    "source_url": source_url,
                    "content_type": "policy_news",
                }
            )

        self.logger.info("Parsed %d item(s) from %s", len(items), source_url)
        return items

    def _parse_page_date(self, soup: BeautifulSoup) -> str:
        header_banner = soup.select_one("#headerBanner")
        if header_banner is None:
            self.logger.warning("No headerBanner found; published_date will be empty")
            return ""

        raw_date = header_banner.get_text(strip=True)
        try:
            day, month, year = raw_date.split("-")
            return f"{year}-{month}-{day}"
        except ValueError:
            self.logger.warning("Could not parse date from headerBanner: %r", raw_date)
            return ""
