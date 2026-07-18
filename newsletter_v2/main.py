from newsletter_v2.collectors.article_fetcher import ArticleFetcher
from newsletter_v2.collectors.info_gov_hk_collector import (
    InfoGovHkCollector,
    TODAY_SOURCE,
    build_backfill_sources,
)
from newsletter_v2.config import OUTPUT_DIR
from newsletter_v2.summarizer import run_summarization


def run_daily() -> list[dict]:
    """Fetch today's press releases, fetch bodies, summarize, and save outputs."""
    collector = InfoGovHkCollector(TODAY_SOURCE)
    items = collector.parse()

    fetcher = ArticleFetcher()
    for item in items:
        article = fetcher.fetch_article(item["url"])
        item["body_text"] = article["body_text"] if article else ""

    output_path = OUTPUT_DIR / "newsletter_triggers.json"
    collector.save(items, output_path)

    run_summarization()
    return items


def run_backfill(days_back: int = 30) -> list[dict]:
    """
    Collect historical press releases for the given number of days.

    Run this manually ONCE to seed history — not on a recurring schedule.
    Daily collection should use run_daily() instead.
    """
    all_items = []
    sources = build_backfill_sources(days_back=days_back)

    for source in sources:
        collector = InfoGovHkCollector(source)
        items = collector.parse()
        all_items.extend(items)

    output_path = OUTPUT_DIR / "newsletter_backfill.json"
    InfoGovHkCollector(TODAY_SOURCE).save(all_items, output_path)
    return all_items


if __name__ == "__main__":
    run_daily()
