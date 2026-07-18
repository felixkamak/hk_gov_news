"""Keyword-based article classification."""

from __future__ import annotations

from typing import Any

from config import URGENT_TITLE_KEYWORDS


def classify_article(title: str, summary: str, source: str) -> dict[str, str]:
    """Classify one article using keyword rules."""
    return classify_articles_batch(
        [{"title": title, "summary": summary, "source_name": source}],
        force_default_on_failure=True,
    )[0]


def classify_articles_batch(
    articles: list[dict[str, Any]],
    force_default_on_failure: bool = True,
) -> list[dict[str, str]]:
    """Classify articles using keyword rules only."""
    del force_default_on_failure
    return [_default_classification(article, apply_urgent_rules=True) for article in articles]


def _default_classification(article: dict[str, Any], apply_urgent_rules: bool) -> dict[str, str]:
    classification = {
        "department_tag": _infer_department(article),
        "priority": "normal",
        "category": _infer_category(article),
        "summary_tc": "",
    }
    if apply_urgent_rules:
        _apply_urgent_rules(article, classification)
    return classification


def _infer_department(article: dict[str, Any]) -> str:
    text = f"{article.get('title', '')} {article.get('summary', '')} {article.get('source_name', '')}"
    if "入境" in text or "immd" in str(article.get("source_url", "")).lower():
        return "入境事務處"
    if "公務員" in text or "csb" in str(article.get("source_url", "")).lower():
        return "公務員事務局"
    if "保安局" in text:
        return "保安局"
    if "立法會" in text or "legco" in str(article.get("source_url", "")).lower():
        return "立法會"
    return "其他"


def _infer_category(article: dict[str, Any]) -> str:
    text = f"{article.get('title', '')} {article.get('summary', '')}"
    if any(word in text for word in ["招聘", "職位", "空缺", "截止申請"]):
        return "招聘"
    if any(word in text for word in ["考試", "筆試", "面試", "成績公布"]):
        return "考試"
    if "統計" in text:
        return "統計"
    if any(word in text for word in ["拘捕", "檢控", "執法"]):
        return "執法"
    if any(word in text for word in ["政策", "措施", "計劃"]):
        return "政策"
    return "其他"


def _apply_urgent_rules(article: dict[str, Any], classification: dict[str, str]) -> None:
    text = f"{article.get('title', '')} {article.get('summary', '')}"
    if article.get("preclassified_priority") == "urgent" or article.get("_preclassified_priority") == "urgent":
        classification["priority"] = "urgent"
        return
    if any(keyword in text for keyword in URGENT_TITLE_KEYWORDS):
        classification["priority"] = "urgent"
