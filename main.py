"""Entry point for the Hong Kong government news aggregator."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from collectors.base_collector import setup_logging
from collectors.jobs_collector import JobsCollector
from collectors.page_collector import PageCollector
from collectors.rss_collector import RSSCollector
from config import HTML_PAGES, JOB_SOURCE, OUTPUT_DIR, RSS_FEEDS
from processor.classifier import classify_articles_batch


logger = logging.getLogger(__name__)


def main() -> None:
    """Run every collector, classify new articles, and save JSON outputs."""
    setup_logging()
    started = time.time()

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        scraped = run_collectors()
        previous_by_id = load_previous_articles()
        articles = normalize_and_dedupe(scraped, previous_by_id)
        classify_new_articles(articles, previous_by_id)
        all_path, urgent_path = save_outputs(articles)

        urgent_count = sum(1 for item in articles if item["priority"] == "urgent")
        elapsed = int(time.time() - started)
        print(f"{urgent_count} urgent items | {len(articles)} total items | {elapsed} seconds")
        logger.info("Saved %s and %s", all_path, urgent_path)
        logger.info("Total runtime: %s seconds", elapsed)
    except Exception as exc:
        # The scheduler should get a clean process exit even if an unexpected edge case appears.
        logger.exception("Unhandled top-level error suppressed: %s", exc)
        elapsed = int(time.time() - started)
        print(f"0 urgent items | 0 total items | {elapsed} seconds")


def run_collectors() -> list[dict[str, Any]]:
    """Run all configured collectors; one failure never blocks the rest."""
    collected: list[dict[str, Any]] = []
    collector_specs: list[tuple[type, dict[str, Any]]] = []

    collector_specs.extend((RSSCollector, source) for source in RSS_FEEDS)
    collector_specs.extend((PageCollector, source) for source in HTML_PAGES)
    collector_specs.append((JobsCollector, JOB_SOURCE))

    for collector_cls, source in collector_specs:
        try:
            logger.info("Starting collector: %s", source["name"])
            items = collector_cls(source).parse()
            logger.info("Collector %s returned %s items", source["name"], len(items))
            collected.extend(items)
        except Exception as exc:
            logger.exception("Collector failed for %s: %s", source.get("name", source.get("url")), exc)
            continue

    return collected


def load_previous_articles() -> dict[str, dict[str, Any]]:
    """Load the latest all_news files so existing classifications can be reused."""
    previous: dict[str, dict[str, Any]] = {}
    for path in sorted(OUTPUT_DIR.glob("all_news_*.json")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("id"):
                        previous[item["id"]] = item
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read previous output %s: %s", path, exc)
    return previous


def normalize_and_dedupe(
    raw_items: list[dict[str, Any]],
    previous_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert collector records into the exact output schema and dedupe by URL."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    seen: set[str] = set()
    articles: list[dict[str, Any]] = []

    for raw in raw_items:
        url = str(raw.get("url") or "").strip()
        title = clean_text(str(raw.get("title") or ""))
        if not url or not title:
            continue

        article_id = hashlib.md5(url.encode("utf-8")).hexdigest()
        if article_id in seen:
            continue
        seen.add(article_id)

        previous = previous_by_id.get(article_id, {})
        articles.append(
            {
                "id": article_id,
                "title": title,
                "url": url,
                "published_date": normalize_date(raw.get("published_date") or raw.get("closing_date") or ""),
                "scraped_date": now,
                "source_name": clean_text(str(raw.get("source_name") or "")),
                "source_url": str(raw.get("source_url") or ""),
                "summary": clean_text(str(raw.get("summary") or ""))[:150],
                "department_tag": previous.get("department_tag", ""),
                "priority": previous.get("priority", raw.get("preclassified_priority", "")),
                "category": previous.get("category", ""),
                "ai_summary_tc": previous.get("ai_summary_tc", ""),
                "_needs_classification": article_id not in previous_by_id,
                "_preclassified_priority": raw.get("preclassified_priority", ""),
            }
        )

    return articles


def classify_new_articles(
    articles: list[dict[str, Any]],
    previous_by_id: dict[str, dict[str, Any]],
) -> None:
    """Classify only URLs missing from previous all_news outputs."""
    to_classify = [article for article in articles if article.pop("_needs_classification", False)]

    if not to_classify:
        logger.info("No new articles require classification.")
        for article in articles:
            article.pop("_preclassified_priority", None)
        return

    logger.info("Classifying %s new articles", len(to_classify))
    classifications = classify_articles_batch(to_classify, force_default_on_failure=True)
    for article, classification in zip(to_classify, classifications):
        article["department_tag"] = classification["department_tag"]
        article["priority"] = classification["priority"]
        article["category"] = classification["category"]
        article["ai_summary_tc"] = classification["summary_tc"]

    # Ensure any malformed or missing fields are still valid before saving.
    for article in articles:
        article["department_tag"] = article.get("department_tag") or infer_department_from_source(article)
        article["priority"] = article.get("priority") or "normal"
        article["category"] = article.get("category") or "其他"
        article["ai_summary_tc"] = article.get("ai_summary_tc") or ""
        article.pop("_preclassified_priority", None)


def save_outputs(articles: list[dict[str, Any]]) -> tuple[Path, Path]:
    """Save all records and urgent-only records for today's run."""
    today = datetime.now().strftime("%Y-%m-%d")
    all_path = OUTPUT_DIR / f"all_news_{today}.json"
    urgent_path = OUTPUT_DIR / f"urgent_{today}.json"

    cleaned = [strip_internal_fields(article) for article in articles]
    urgent = [article for article in cleaned if article["priority"] == "urgent"]

    with all_path.open("w", encoding="utf-8") as fh:
        json.dump(cleaned, fh, ensure_ascii=False, indent=2)
    with urgent_path.open("w", encoding="utf-8") as fh:
        json.dump(urgent, fh, ensure_ascii=False, indent=2)

    return all_path, urgent_path


def strip_internal_fields(article: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in article.items() if not key.startswith("_")}


def normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return text[:10]


def infer_department_from_source(article: dict[str, Any]) -> str:
    text = f"{article.get('source_name', '')} {article.get('source_url', '')} {article.get('title', '')}".lower()
    if "入境" in text or "immd" in text:
        return "入境事務處"
    if "公務員" in text or "csb" in text:
        return "公務員事務局"
    if "立法會" in text or "legco" in text:
        return "立法會"
    if "保安局" in text:
        return "保安局"
    return "其他"


def clean_text(text: str) -> str:
    return " ".join(text.split())


if __name__ == "__main__":
    main()
