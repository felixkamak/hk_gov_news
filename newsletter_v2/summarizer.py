import json
import logging
import re
import sys
from pathlib import Path

import requests

from newsletter_v2.config import LOG_FILE, OUTPUT_DIR

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_TIMEOUT_SECONDS = 180

TRIGGERS_PATH = OUTPUT_DIR / "newsletter_triggers.json"
DIGEST_PATH = OUTPUT_DIR / "daily_digest.json"

logger = logging.getLogger(__name__)


def _setup_logger() -> logging.Logger:
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def _call_ollama(prompt: str) -> str | None:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }

    try:
        response = requests.post(
            OLLAMA_GENERATE_URL,
            json=payload,
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        logger.error(
            "Cannot connect to Ollama at %s. "
            "Please start Ollama and ensure model '%s' is pulled.",
            OLLAMA_BASE_URL,
            OLLAMA_MODEL,
        )
        sys.exit(1)
    except requests.exceptions.RequestException as exc:
        logger.error("Ollama request failed: %s", exc)
        return None

    data = response.json()
    return data.get("response", "")


def _build_prompt(article: dict) -> str:
    headline = article.get("title", "")
    body_text = article.get("body_text", "")
    if len(body_text) > 6000:
        body_text = body_text[:6000] + "\n…（下文已截斷）"

    return f"""你是一位協助香港公務員面試考生準備時事政策題的助手。

請閱讀以下政府新聞稿，完成兩項任務：
1. 判斷此文章對準備公務員面試時事政策題是否有用。
   - 有用：涉及實際政府政策、官員解釋政策理據、立法會事務、重大社會或經濟措施。
   - 無用：招聘廣告、泳灘掛旗警告、暑熱警告、賣旗日、或其他例行操作性通告。
2. 若有用，用繁體中文寫一兩句摘要，說明涉及什麼政策或措施及其重要性；不要逐字引用對話。

標題：{headline}

正文：
{body_text}

只回覆一個 JSON 物件，不要有任何其他文字、前言、markdown 代碼框或解釋。
格式必須嚴格如下：
{{"useful": true, "summary": "一兩句話嘅摘要"}}
或
{{"useful": false, "summary": ""}}"""


def _parse_model_response(raw: str, headline: str) -> dict:
    text = raw.strip()

    think_tag = "think"
    text = re.sub(
        rf"<{think_tag}>.*?</{think_tag}>", "", text, flags=re.DOTALL
    ).strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse JSON for %r; raw response: %s",
                    headline,
                    raw,
                )
                return {"useful": False, "summary": ""}
        else:
            logger.warning(
                "Failed to parse JSON for %r; raw response: %s",
                headline,
                raw,
            )
            return {"useful": False, "summary": ""}

    useful = bool(parsed.get("useful", False))
    summary = parsed.get("summary", "")
    if not isinstance(summary, str):
        summary = str(summary) if summary else ""

    if not useful:
        summary = ""

    return {"useful": useful, "summary": summary.strip()}


def _classify_and_summarize(article: dict) -> dict:
    headline = article.get("title", "")
    logger.info("Summarizing: %s", headline)

    raw = _call_ollama(_build_prompt(article))
    if raw is None:
        logger.warning("No response from Ollama for %r; skipping", headline)
        return {"useful": False, "summary": ""}

    return _parse_model_response(raw, headline)


def run_summarization(
    triggers_path: Path | str | None = None,
    output_path: Path | str | None = None,
) -> list[dict]:
    """
    Read newsletter_triggers.json, classify and summarize each article via local
    Ollama, and save useful items to daily_digest.json.
    """
    _setup_logger()

    triggers_file = Path(triggers_path or TRIGGERS_PATH)
    digest_file = Path(output_path or DIGEST_PATH)

    if not triggers_file.exists():
        logger.error("Triggers file not found: %s", triggers_file)
        return []

    with triggers_file.open(encoding="utf-8") as f:
        articles = json.load(f)

    digest_items = []
    useful_count = 0
    filtered_count = 0

    for article in articles:
        result = _classify_and_summarize(article)
        if result["useful"]:
            useful_count += 1
            digest_items.append(
                {
                    "headline": article.get("title", ""),
                    "url": article.get("url", ""),
                    "published_date": article.get("published_date", ""),
                    "summary": result["summary"],
                }
            )
        else:
            filtered_count += 1

    digest_file.parent.mkdir(parents=True, exist_ok=True)
    with digest_file.open("w", encoding="utf-8") as f:
        json.dump(digest_items, f, ensure_ascii=False, indent=2)

    logger.info("Saved digest with %d item(s) to %s", len(digest_items), digest_file)

    total = len(articles)
    print(
        f"\nSummarization complete: {total} article(s) processed, "
        f"{useful_count} useful, {filtered_count} filtered out."
    )

    return digest_items
