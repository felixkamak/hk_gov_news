"""AO / EO news tracker: wider info.gov.hk headline net + article body text.

Reuses InfoGovHkCollector's index-page handling (link finding, date parsing,
decoding) but applies the AO/EO topic map instead of the policy allowlist, and
can fetch each article's body so weekly reports can be summarised.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.info_gov_hk_collector import INFO_GOV_HK_BASE, InfoGovHkCollector
from config import AO_EO_BODY_MAX_CHARS, AO_EO_EXCLUDE_KEYWORDS, AO_EO_TOPICS

# Containers tried in order when extracting a press release's body text.
BODY_SELECTORS = ("#pressrelease", "span#pressrelease", "#contentBody", "#content")

# Arrest headlines are usually phrased "拘四人" / "拘捕3名" rather than a fixed word.
EXCLUDE_PATTERNS = (re.compile(r"拘[一二三四五六七八九十百兩\d]+[人名]"),)


def classify_title(title: str) -> list[str]:
    """Return matching AO/EO topic keys (empty if excluded or no match)."""
    if any(bad in title for bad in AO_EO_EXCLUDE_KEYWORDS):
        return []
    if any(pattern.search(title) for pattern in EXCLUDE_PATTERNS):
        return []
    return [
        topic
        for topic, keywords in AO_EO_TOPICS.items()
        if any(keyword in title for keyword in keywords)
    ]


def extract_body(html: str, max_chars: int = AO_EO_BODY_MAX_CHARS) -> str:
    """Pull readable body text from an info.gov.hk press-release page."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    node = None
    for selector in BODY_SELECTORS:
        node = soup.select_one(selector)
        if node is not None and node.get_text(strip=True):
            break
        node = None
    if node is None:
        node = soup.body or soup
    text = node.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:max_chars]


class AoEoNewsCollector(InfoGovHkCollector):
    """Parse one info.gov.hk daily index page into AO/EO-tagged items."""

    def parse(self) -> list[dict[str, Any]]:
        response = self.fetch()
        if response is None:
            return []

        soup = BeautifulSoup(self._decode(response), "html.parser")
        published_date = self._parse_page_date(soup) or self.source.get("date", "")
        source_url = self.source["url"]

        links = self._find_news_links(soup)
        if not links:
            self.logger.warning("No news list found on %s", source_url)
            return []

        items: list[dict[str, Any]] = []
        for link in links:
            title = link.get_text(strip=True)
            if not title or len(title) < 4:
                continue
            topics = classify_title(title)
            if not topics:
                continue
            items.append(
                {
                    "title": title,
                    "url": urljoin(INFO_GOV_HK_BASE, link["href"]),
                    "published_date": published_date,
                    "source_name": self.source.get("source_name", "政府新聞處"),
                    "source_url": source_url,
                    "content_type": "ao_eo_news",
                    "topics": topics,
                    "body": "",
                    "body_ok": False,
                }
            )

        self.logger.info("Parsed %d AO/EO item(s) from %s", len(items), source_url)
        return items

    def fetch_body(self, url: str) -> str:
        """Fetch one article and return its body text ('' on failure)."""
        response = self.fetch(url)
        if response is None:
            return ""
        return extract_body(self._decode(response))
