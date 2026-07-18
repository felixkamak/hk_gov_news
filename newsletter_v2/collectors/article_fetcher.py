import re

from bs4 import BeautifulSoup, NavigableString, Tag

from newsletter_v2.collectors.base_collector import BaseCollector

_DATE_TIME_DIV_PATTERN = re.compile(r"香港時間")


class ArticleFetcher(BaseCollector):
    """Fetch full text of a single info.gov.hk press release article."""

    def __init__(self, article_url: str = ""):
        super().__init__(
            {
                "name": "info_gov_hk_article",
                "url": article_url,
            }
        )
        self.article_url = article_url

    def fetch_article(self, url: str | None = None) -> dict | None:
        target_url = url or self.article_url
        if not target_url:
            self.logger.warning("No article URL provided")
            return None

        response = self.fetch(url=target_url)
        if response is None:
            return None

        soup = BeautifulSoup(response.content, "html.parser")
        pressrelease = soup.select_one("#pressrelease")
        if pressrelease is None:
            self.logger.warning("No #pressrelease found on %s", target_url)
            return None

        headline = self._extract_headline(soup)
        body_text = self._extract_body_text(pressrelease)

        return {
            "headline": headline,
            "body_text": body_text,
            "url": target_url,
        }

    def parse(self) -> list[dict]:
        result = self.fetch_article()
        return [result] if result else []

    def _extract_headline(self, soup: BeautifulSoup) -> str:
        headline_el = soup.select_one("#PRHeadlineSpan") or soup.select_one("#PRHeadline")
        if headline_el is None:
            return ""
        return headline_el.get_text(strip=True)

    def _extract_body_text(self, pressrelease: Tag) -> str:
        self._strip_trailing_footer(pressrelease)

        for br in pressrelease.find_all("br"):
            br.replace_with(NavigableString("\n"))

        text = pressrelease.get_text()
        lines = [line.rstrip() for line in text.splitlines()]
        return "\n".join(lines).strip()

    def _strip_trailing_footer(self, pressrelease: Tag) -> None:
        child_divs = [
            child
            for child in pressrelease.children
            if isinstance(child, Tag) and child.name == "div"
        ]
        if len(child_divs) < 2:
            return

        wan_div = child_divs[-2]
        date_div = child_divs[-1]
        if wan_div.get_text(strip=True) != "完":
            return
        if not _DATE_TIME_DIV_PATTERN.search(date_div.get_text()):
            return

        wan_div.decompose()
        date_div.decompose()
