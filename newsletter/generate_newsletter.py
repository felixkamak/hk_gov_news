"""Generate a daily Traditional Chinese newsletter from scraped government news."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
NEWSLETTER_OUTPUT_DIR = Path(__file__).resolve().parent / "output"

DEPARTMENTS = [
    "入境事務處",
    "公務員事務局",
    "保安局",
    "立法會",
    "政務/政策",
    "其他",
]

DEPARTMENT_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "立法會",
        ["立法會", "議員", "法案", "條例", "legco"],
    ),
    (
        "公務員事務局",
        [
            "公務員",
            "文書",
            "秘書",
            "招聘考試",
            "基本法",
            "國安法測試",
            "BLNST",
            "CRE",
            "ACO",
            "綜合招聘",
            "csb",
        ],
    ),
    (
        "保安局",
        [
            "保安",
            "警務",
            "消防",
            "懲教",
            "海關",
            "出入境",
            "國家安全",
            "維護國安",
        ],
    ),
    (
        "入境事務處",
        [
            "入境",
            "簽證",
            "護照",
            "居留",
            "外傭",
            "人才來港",
            "非法勞工",
            "邊境",
            "口岸",
            "immd",
        ],
    ),
    (
        "政務/政策",
        ["行政長官", "司長", "局長", "施政", "規劃", "諮詢", "五年規劃"],
    ),
]

EXCLUDE_TITLE_KEYWORDS = [
    "醫院",
    "病人",
    "嬰兒",
    "泳灘",
    "天氣",
    "天文台",
    "雨",
    "颱風",
    "油污",
    "交通意外",
    "火警",
]


def find_today_news_file(today: str) -> Path:
    """Return today's dated all_news.json, with legacy and latest fallbacks."""
    dated_path = OUTPUT_DIR / today / "all_news.json"
    if dated_path.exists():
        return dated_path

    legacy_path = OUTPUT_DIR / f"all_news_{today}.json"
    if legacy_path.exists():
        return legacy_path

    dated_candidates = sorted(OUTPUT_DIR.glob("*/all_news.json"))
    if dated_candidates:
        return dated_candidates[-1]

    legacy_candidates = sorted(OUTPUT_DIR.glob("all_news_*.json"))
    if legacy_candidates:
        return legacy_candidates[-1]

    raise FileNotFoundError(f"No news output files found in {OUTPUT_DIR}")


def load_articles(path: Path, today: str) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array in {path}")
    articles = [item for item in data if isinstance(item, dict)]
    attach_full_text(articles, today)
    return articles


def attach_full_text(articles: list[dict[str, Any]], today: str) -> None:
    """Load full_text from dated article files when missing in JSON."""
    articles_dir = OUTPUT_DIR / today / "articles"
    if not articles_dir.exists():
        return

    for article in articles:
        if str(article.get("full_text") or "").strip():
            continue
        article_id = str(article.get("id") or "").strip()
        if not article_id:
            continue
        text_path = articles_dir / f"{article_id}.txt"
        if text_path.exists():
            article["full_text"] = text_path.read_text(encoding="utf-8")


def article_search_text(article: dict[str, Any]) -> str:
    parts = [
        article.get("title"),
        article.get("summary"),
        article.get("ai_summary_tc"),
        article.get("full_text"),
        article.get("source_name"),
        article.get("source_url"),
    ]
    return " ".join(str(part or "").strip() for part in parts if part)


def is_relevant(article: dict[str, Any]) -> bool:
    title = str(article.get("title") or "")
    return not any(keyword in title for keyword in EXCLUDE_TITLE_KEYWORDS)


def classify_department(article: dict[str, Any]) -> str:
    text = article_search_text(article)
    lowered = text.lower()
    for department, keywords in DEPARTMENT_KEYWORDS:
        for keyword in keywords:
            if keyword.isascii():
                if keyword.lower() in lowered:
                    return department
            elif keyword in text:
                return department
    return "其他"


def filter_today_articles(articles: list[dict[str, Any]], today: str) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for article in articles:
        if article.get("category") == "招聘":
            continue
        if article.get("published_date") != today:
            continue
        if not is_relevant(article):
            continue
        filtered.append(article)
    return filtered


def one_line_summary(article: dict[str, Any]) -> str:
    ai_summary = str(article.get("ai_summary_tc") or "").strip()
    if ai_summary:
        return ai_summary
    summary = str(article.get("summary") or "").strip()
    return summary[:50]


def format_article(article: dict[str, Any]) -> str:
    title = str(article.get("title") or "").strip()
    url = str(article.get("url") or "").strip()
    summary = one_line_summary(article)
    if summary:
        return f"**[{title}]({url})**\n{summary}"
    return f"**[{title}]({url})**"


def format_department_section(name: str, articles: list[dict[str, Any]]) -> str:
    if not articles:
        return ""
    body = "\n\n".join(format_article(article) for article in articles)
    return f"## {name}\n\n{body}"


def group_by_department(articles: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = {department: [] for department in DEPARTMENTS}
    for article in articles:
        department = classify_department(article)
        grouped[department].append(article)
    return grouped


def build_newsletter(articles: list[dict[str, Any]], today: str) -> str:
    grouped = group_by_department(articles)
    sections: list[str] = [f"# 香港政府新聞通訊 {today}", ""]

    for department in DEPARTMENTS:
        section = format_department_section(department, grouped[department])
        if section:
            sections.append(section)
            sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def main() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    NEWSLETTER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        news_path = find_today_news_file(today)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    articles = filter_today_articles(load_articles(news_path, today), today)
    newsletter = build_newsletter(articles, today)

    output_path = NEWSLETTER_OUTPUT_DIR / f"newsletter_{today}.md"
    output_path.write_text(newsletter, encoding="utf-8")

    print(newsletter, end="")
    print(f"\nSaved to {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
