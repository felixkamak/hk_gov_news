"""Fetch and extract full article body text from article URLs."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

ARTICLE_FETCH_TIMEOUT = 10
FETCH_DELAY_SECONDS = 1
SUMMARY_MAX_CHARS = 150
SUMMARY_MAX_SENTENCES = 3
IGNORE_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript"}
CONTENT_CLASS_KEYWORDS = ("content", "article", "main", "press", "body")
SENTENCE_PATTERN = re.compile(r"[^。！？!?]+[。！？!?]")

logger = logging.getLogger(__name__)


def enrich_articles_with_full_text(articles: list[dict[str, Any]]) -> None:
    """Fetch article pages and populate full_text and ai_summary_tc."""
    session = _build_session()
    fetched = 0
    skipped = 0
    failed = 0

    try:
        for article in articles:
            existing_text = str(article.get("full_text") or "").strip()
            if existing_text:
                skipped += 1
                if not str(article.get("ai_summary_tc") or "").strip():
                    article["ai_summary_tc"] = extract_summary(existing_text)
                continue

            url = str(article.get("url") or "").strip()
            if not url:
                article["full_text"] = ""
                article["ai_summary_tc"] = ""
                failed += 1
                continue

            time.sleep(FETCH_DELAY_SECONDS)
            full_text = fetch_full_text(url, session=session)
            article["full_text"] = full_text
            article["ai_summary_tc"] = extract_summary(full_text) if full_text else ""

            if full_text:
                fetched += 1
            else:
                failed += 1
    finally:
        session.close()

    logger.info(
        "Full text fetch complete: %s fetched, %s skipped (cached), %s empty/failed",
        fetched,
        skipped,
        failed,
    )


def fetch_full_text(url: str, session: requests.Session | None = None) -> str:
    """Fetch one article URL and return extracted body text, or empty on failure."""
    owns_session = session is None
    if session is None:
        session = _build_session()

    try:
        response = session.get(url, timeout=ARTICLE_FETCH_TIMEOUT)
        if response.status_code in {403, 404}:
            return ""
        response.raise_for_status()
        html = _decode_response(response)
        return extract_body_text(html)
    except requests.RequestException as exc:
        logger.warning("Failed to fetch full text for %s: %s", url, exc)
        return ""
    finally:
        if owns_session:
            session.close()


def extract_summary(text: str) -> str:
    """Extract the first three complete sentences, up to 150 characters."""
    text = _clean_text(text)
    if not text:
        return ""

    sentences = SENTENCE_PATTERN.findall(text)
    if not sentences:
        return text[:SUMMARY_MAX_CHARS]

    summary = "".join(sentences[:SUMMARY_MAX_SENTENCES])
    if len(summary) <= SUMMARY_MAX_CHARS:
        return summary

    truncated = summary[:SUMMARY_MAX_CHARS]
    for ending in ("。", "！", "？", "!", "?"):
        position = truncated.rfind(ending)
        if position > 0:
            return truncated[: position + 1]
    return truncated


def extract_body_text(html: str) -> str:
    """Extract readable article body text from HTML."""
    soup = BeautifulSoup(html, "lxml")

    for tag_name in IGNORE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    article = soup.find("article")
    if article is not None:
        text = _text_from_node(article)
        if text:
            return text

    best_text = ""
    for div in soup.find_all("div", class_=True):
        class_names = " ".join(div.get("class", [])).lower()
        if not any(keyword in class_names for keyword in CONTENT_CLASS_KEYWORDS):
            continue
        text = _text_from_node(div)
        if len(text) > len(best_text):
            best_text = text
    if best_text:
        return best_text

    main = soup.find("main") or soup.body
    if main is not None:
        paragraphs = [
            paragraph.get_text(" ", strip=True)
            for paragraph in main.find_all("p")
            if paragraph.get_text(" ", strip=True)
        ]
        if paragraphs:
            return _clean_text("\n".join(paragraphs))

    return ""


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-HK,zh-TW;q=0.9,en;q=0.7",
        }
    )
    return session


def _decode_response(response: requests.Response) -> str:
    content = response.content
    for encoding in ("utf-8", "big5", "hkscs", response.apparent_encoding or "utf-8"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return response.text


def _text_from_node(node: Any) -> str:
    paragraphs = [
        paragraph.get_text(" ", strip=True)
        for paragraph in node.find_all("p")
        if paragraph.get_text(" ", strip=True)
    ]
    if paragraphs:
        return _clean_text("\n".join(paragraphs))
    return _clean_text(node.get_text(" ", strip=True))


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
