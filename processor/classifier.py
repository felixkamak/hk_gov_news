"""Anthropic-powered article classification."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from config import ANTHROPIC_MODEL, BASE_DIR, CLASSIFIER_BATCH_SIZE, URGENT_TITLE_KEYWORDS


logger = logging.getLogger(__name__)
load_dotenv(BASE_DIR / ".env")

VALID_DEPARTMENTS = {"入境事務處", "公務員事務局", "保安局", "立法會", "其他"}
VALID_PRIORITIES = {"urgent", "normal"}
VALID_CATEGORIES = {"招聘", "考試", "政策", "執法", "統計", "其他"}


def classify_article(title: str, summary: str, source: str) -> dict[str, str]:
    """Classify one article. Kept for direct callers; batching is used by main."""
    return classify_articles_batch(
        [{"title": title, "summary": summary, "source_name": source}],
        force_default_on_failure=False,
    )[0]


def classify_articles_batch(
    articles: list[dict[str, Any]],
    force_default_on_failure: bool = True,
) -> list[dict[str, str]]:
    """Classify articles in batches of 10 using Claude."""
    results: list[dict[str, str]] = []
    for start in range(0, len(articles), CLASSIFIER_BATCH_SIZE):
        batch = articles[start : start + CLASSIFIER_BATCH_SIZE]
        results.extend(_classify_one_batch(batch, force_default_on_failure))
    return results


def _classify_one_batch(
    articles: list[dict[str, Any]],
    force_default_on_failure: bool,
) -> list[dict[str, str]]:
    if not articles:
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY is not set; using default classifications.")
        return [_default_classification(article, apply_urgent_rules=not force_default_on_failure) for article in articles]

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1600,
            temperature=0,
            system=(
                "你是香港政府新聞分類器。只輸出 JSON array，不要加入解釋文字。"
                "每個輸入項目必須回傳一個同順序分類。"
            ),
            messages=[
                {
                    "role": "user",
                    "content": _build_prompt(articles),
                }
            ],
        )
        text = _response_text(response)
        parsed = _parse_json_array(text)
        if len(parsed) != len(articles):
            raise ValueError(f"Expected {len(articles)} classifications, got {len(parsed)}")

        cleaned = [_sanitize_classification(item) for item in parsed]
        for article, classification in zip(articles, cleaned):
            _apply_urgent_rules(article, classification)
        return cleaned
    except Exception as exc:  # Anthropic/network/JSON errors should never stop a run.
        logger.exception("Claude classification failed: %s", exc)
        return [_default_classification(article, apply_urgent_rules=not force_default_on_failure) for article in articles]


def _build_prompt(articles: list[dict[str, Any]]) -> str:
    payload = [
        {
            "title": article.get("title", ""),
            "summary": article.get("summary", ""),
            "source": article.get("source_name") or article.get("source", ""),
        }
        for article in articles
    ]
    return (
        "請把以下香港新聞或公告分類，回傳 JSON array，順序必須與輸入相同。\n"
        "每個分類物件只可包含以下欄位：\n"
        "department_tag: 入境事務處 | 公務員事務局 | 保安局 | 立法會 | 其他\n"
        "priority: urgent | normal\n"
        "category: 招聘 | 考試 | 政策 | 執法 | 統計 | 其他\n"
        "summary_tc: 50字以內繁體中文摘要\n"
        "如涉及招聘、截止申請、考試日期、筆試、面試通知、成績公布、"
        "入境事務助理員、助理文書主任、文書助理，priority 必須為 urgent。\n\n"
        f"輸入 JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def _response_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []):
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _parse_json_array(text: str) -> list[Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise ValueError("Claude response was not a JSON array.")
    return data


def _sanitize_classification(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        item = {}
    return {
        "department_tag": item.get("department_tag") if item.get("department_tag") in VALID_DEPARTMENTS else "其他",
        "priority": item.get("priority") if item.get("priority") in VALID_PRIORITIES else "normal",
        "category": item.get("category") if item.get("category") in VALID_CATEGORIES else "其他",
        "summary_tc": str(item.get("summary_tc") or "")[:50],
    }


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
