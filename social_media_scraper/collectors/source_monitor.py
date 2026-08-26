"""Snapshot + diff monitor for CSB 招聘事宜 reference pages.

Rationale
---------
The bespoke exam parsers only surface facts we explicitly taught them to find.
Anything new that CSB adds — a new notice, a reworded clause, a brand-new
sub-page — is invisible until a human happens to notice. This module removes
that blind spot with a generic safety net:

1. Snapshot every watched page section-by-section, hash each section, and store
   the whole thing (page-keyed) in one committed file.
2. On each run, diff the fresh snapshot against the previous one. Any added /
   modified / removed section becomes a `source_update`.
3. Also watch the recruit hub (7.html) link list, so a brand-new sub-page is
   flagged the moment it appears — catching events no parser was written for.

Only changes that hit a relevance keyword (or a brand-new page) are promoted to
the agent-facing feed; everything else is captured but kept quiet, so legal /
boilerplate edits never create noise.

Pure functions operate on HTML strings so the diff logic is fully unit-testable
without network access; SourceMonitor is the thin fetch wrapper used in prod.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)

_HEADING_TAGS = re.compile(r"^h[1-6]$")
_SENTINEL = "\x00H\x00"  # marks where a heading was, so flat text can be split
_DROP_TAGS = ("script", "style", "noscript", "nav", "header", "footer")


def _normalize(text: str) -> str:
    """Collapse whitespace and drop volatile-but-meaningless tokens.

    Emails, facebook embeds and .pdf hrefs change or reorder without any real
    news value; stripping them before hashing prevents false 'modified' hits.
    """
    text = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", " ", text)
    text = re.sub(r"https?://(?:www\.)?facebook\.com\S*", " ", text, flags=re.I)
    text = re.sub(r"\S+\.pdf\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _main_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()
    return soup


def extract_sections(html: str) -> list[dict[str, str]]:
    """Split a page into {heading, text, hash} sections keyed by their heading."""
    soup = _main_soup(html)
    body = soup.find("body") or soup

    # Replace each heading with a sentinel carrying its title, then flatten.
    for h in body.find_all(_HEADING_TAGS):
        title = h.get_text(" ", strip=True)
        h.insert_before(f"{_SENTINEL}{title}{_SENTINEL}")
        h.decompose()

    flat = body.get_text(" ", strip=True)
    sections: list[dict[str, str]] = []

    # Split into [pre, title1, body1, title2, body2, ...]
    parts = flat.split(_SENTINEL)
    # parts[0] is any preamble before the first heading; then title/body pairs.
    if parts and parts[0].strip():
        body_text = _normalize(parts[0])
        if body_text:
            sections.append(_section("（前言）", body_text))
    i = 1
    while i < len(parts):
        title = parts[i].strip()
        body_text = _normalize(parts[i + 1]) if i + 1 < len(parts) else ""
        i += 2
        if not title and not body_text:
            continue
        sections.append(_section(title or "（無標題）", body_text))
    return sections


def _section(heading: str, text: str) -> dict[str, str]:
    return {"heading": heading, "text": text, "hash": _hash(heading + "\n" + text)}


def extract_links(html: str, base_url: str) -> list[str]:
    """All csb.gov.hk recruit-related links on the page (hub discovery signal)."""
    soup = _main_soup(html)
    body = soup.find("body") or soup
    links: set[str] = set()
    for a in body.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0].strip()
        low = href.lower()
        if "csb.gov.hk" in low and ("/recruit/" in low or "jve" in low):
            links.add(href)
    return sorted(links)


def snapshot_page(html: str, url: str, *, capture_links: bool = False) -> dict[str, Any]:
    snap: dict[str, Any] = {"url": url, "sections": extract_sections(html)}
    if capture_links:
        snap["links"] = extract_links(html, url)
    return snap


# --------------------------------------------------------------------------- #
# Diffing                                                                      #
# --------------------------------------------------------------------------- #

def _excerpt(text: str, limit: int = 150) -> str:
    return text[:limit]


def _is_relevant(heading: str, excerpt: str, change_type: str, keywords: list[str]) -> bool:
    # A brand-new sub-page is always worth a human glance.
    if change_type in ("new_page",):
        return True
    blob = f"{heading} {excerpt}"
    return any(kw in blob for kw in keywords)


def _update_item(
    url: str, heading: str, excerpt: str, change_type: str, keywords: list[str]
) -> dict[str, Any]:
    labels = {
        "added": "官方頁新增段落",
        "modified": "官方頁段落更新",
        "removed": "官方頁段落刪除",
        "new_page": "招聘事宜新增頁面",
        "removed_page": "招聘事宜移除頁面",
    }
    return {
        "title": f"{labels.get(change_type, '官方頁變更')}：{heading}"[:120],
        "url": url,
        "change_type": change_type,
        "heading": heading,
        "excerpt": excerpt,
        "is_relevant": _is_relevant(heading, excerpt, change_type, keywords),
        "source_name": "公務員事務局",
        "content_type": "source_update",
    }


def build_source_updates(
    previous: dict[str, Any],
    current: dict[str, Any],
    keywords: list[str],
) -> list[dict[str, Any]]:
    """Diff current snapshot against previous; return source_update items.

    A page absent from `previous` is treated as a freshly-baselined page: its
    sections are stored but NOT emitted, so the first run never floods the feed.
    """
    updates: list[dict[str, Any]] = []
    for url, page in current.items():
        prev_page = previous.get(url)
        if prev_page is None:
            continue  # baseline only

        prev_secs = {s["heading"]: s for s in prev_page.get("sections", [])}
        curr_headings = {s["heading"] for s in page.get("sections", [])}

        for sec in page.get("sections", []):
            prev_sec = prev_secs.get(sec["heading"])
            if prev_sec is None:
                updates.append(
                    _update_item(url, sec["heading"], _excerpt(sec["text"]), "added", keywords)
                )
            elif prev_sec.get("hash") != sec["hash"]:
                updates.append(
                    _update_item(url, sec["heading"], _excerpt(sec["text"]), "modified", keywords)
                )

        for heading, prev_sec in prev_secs.items():
            if heading not in curr_headings:
                updates.append(
                    _update_item(url, heading, _excerpt(prev_sec.get("text", "")), "removed", keywords)
                )

        # Hub link-set diff (only pages that captured links).
        prev_links = set(prev_page.get("links", []))
        curr_links = set(page.get("links", []))
        for link in sorted(curr_links - prev_links):
            updates.append(_update_item(link, link, "", "new_page", keywords))
        for link in sorted(prev_links - curr_links):
            updates.append(_update_item(link, link, "", "removed_page", keywords))

    return updates


# --------------------------------------------------------------------------- #
# Persistence + prod fetch wrapper                                             #
# --------------------------------------------------------------------------- #

def load_snapshot(path: str | Path) -> dict[str, Any]:
    try:
        with Path(path).open(encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data.get("pages", data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.info("No usable snapshot at %s", path)
    return {}


def save_snapshot(path: str | Path, snapshot: dict[str, Any], generated_date: str = "") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(
            {"generated_date": generated_date, "pages": snapshot},
            fh,
            ensure_ascii=False,
            indent=2,
        )


class SourceMonitor(BaseCollector):
    """Thin fetch wrapper: pull each watched page and build the current snapshot."""

    def __init__(self, monitor_sources: list[dict[str, Any]], hub_url: str = ""):
        super().__init__({"url": hub_url or (monitor_sources[0]["url"] if monitor_sources else "")})
        self.monitor_sources = monitor_sources
        self.hub_url = hub_url

    def parse(self) -> list[dict[str, Any]]:  # BaseCollector requires it; unused here
        return []

    def collect_snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for src in self.monitor_sources:
            url = src["url"]
            response = self.fetch(url)
            if response is None:
                logger.warning("Monitor fetch failed, skipping %s", url)
                continue
            html = self._decode(response)
            snapshot[url] = snapshot_page(html, url, capture_links=src.get("is_hub", False))
        return snapshot

    @staticmethod
    def _decode(response: Any) -> str:
        for encoding in ("utf-8", "big5", "hkscs", response.apparent_encoding or "utf-8"):
            try:
                return response.content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return response.text
