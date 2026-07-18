"""Entry point for 小紅書-focused social media trigger scraping."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_PKG_ROOT = Path(__file__).resolve().parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from collectors.announcements_collector import AnnouncementsCollector  # noqa: E402
from collectors.base_collector import setup_logging  # noqa: E402
from collectors.jobs_collector import JobsCollector, TARGET_TITLES  # noqa: E402
from config import ANNOUNCEMENT_SOURCES, JOB_SOURCES, OUTPUT_DIR  # noqa: E402


logger = logging.getLogger(__name__)

JOB_KEYWORDS = ("招聘", "空缺", "職位")
EXAM_KEYWORDS = ("基本法", "國安法", "BLNST", "CRE", "考試")


def main() -> None:
    """Run collectors, categorise items, and write social_media_triggers.json."""
    setup_logging()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / "social_media_triggers.json"
    previous = load_previous_output(output_path)

    raw_items = run_collectors()
    items = dedupe_by_url(raw_items)
    buckets = categorise_items(items)
    payload = build_output(buckets)
    payload = apply_job_carry_forward(payload, previous)

    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(
        f"jobs={payload['summary']['job_openings']} "
        f"exams={payload['summary']['exam_updates']} "
        f"announcements={payload['summary']['announcements']} "
        f"urgent={payload['summary']['urgent_count']} "
        f"-> {output_path}"
    )
    logger.info("Wrote %s", output_path)


def load_previous_output(path: Path) -> dict[str, Any]:
    """Load existing triggers JSON; empty dict if missing or unparseable."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.info("No usable previous output at %s", path)
    return {}


def apply_job_carry_forward(
    payload: dict[str, Any], previous: dict[str, Any]
) -> dict[str, Any]:
    """Keep last good job_openings when this run scraped zero jobs."""
    today = datetime.now().strftime("%Y-%m-%d")
    triggers = payload.setdefault("triggers", {})
    new_jobs = triggers.get("job_openings") or []
    prev_jobs = (previous.get("triggers") or {}).get("job_openings") or []
    jobs_ok = bool(new_jobs)

    if jobs_ok:
        payload["jobs_fresh"] = True
        payload["jobs_last_updated"] = today
    elif prev_jobs:
        triggers["job_openings"] = list(prev_jobs)
        payload["jobs_fresh"] = False
        payload["jobs_last_updated"] = (
            previous.get("jobs_last_updated")
            or previous.get("generated_date")
            or today
        )
        logger.warning(
            "Empty job scrape; carried forward %s previous job_openings (last updated %s)",
            len(prev_jobs),
            payload["jobs_last_updated"],
        )
    else:
        payload["jobs_fresh"] = False
        payload["jobs_last_updated"] = (
            previous.get("jobs_last_updated")
            or previous.get("generated_date")
            or today
        )

    buckets = triggers
    payload["summary"] = build_summary(buckets)
    payload["has_content"] = any(
        payload["summary"][key] for key in ("job_openings", "exam_updates", "announcements")
    )
    payload["content_suggestion"] = pick_content_suggestion(buckets)
    return payload


def build_summary(buckets: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    urgent_count = sum(
        1
        for items in buckets.values()
        for item in items
        if item.get("is_urgent")
    )
    return {
        "job_openings": len(buckets.get("job_openings") or []),
        "exam_updates": len(buckets.get("exam_updates") or []),
        "announcements": len(buckets.get("announcements") or []),
        "urgent_count": urgent_count,
    }


def run_collectors() -> list[dict[str, Any]]:
    """Run all configured collectors; one failure never blocks the rest."""
    collected: list[dict[str, Any]] = []

    for source in JOB_SOURCES:
        try:
            logger.info("Starting jobs collector: %s", source["name"])
            items = JobsCollector(source).parse()
            logger.info("Jobs collector %s returned %s items", source["name"], len(items))
            collected.extend(items)
        except Exception as exc:
            logger.exception("Jobs collector failed for %s: %s", source.get("name"), exc)

    for source in ANNOUNCEMENT_SOURCES:
        try:
            logger.info("Starting announcements collector: %s", source["name"])
            items = AnnouncementsCollector(source).parse()
            logger.info("Announcements collector %s returned %s items", source["name"], len(items))
            collected.extend(items)
        except Exception as exc:
            logger.exception("Announcements collector failed for %s: %s", source.get("name"), exc)

    return collected


def matches_target_job(title: str) -> bool:
    """AceGovHK-relevant titles only (job_openings bucket)."""
    return any(keyword in title for keyword in TARGET_TITLES)


def dedupe_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(item)
    return unique


def categorise_items(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split items into job_openings, exam_updates, and announcements."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "job_openings": [],
        "exam_updates": [],
        "announcements": [],
    }

    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        trigger = to_trigger(item)

        is_job = any(keyword in text for keyword in JOB_KEYWORDS) or item.get("content_type") == "job"
        if is_job and matches_target_job(item.get("title", "")):
            buckets["job_openings"].append(trigger)
        elif any(keyword in text for keyword in EXAM_KEYWORDS) or item.get("content_type") == "exam":
            buckets["exam_updates"].append(trigger)
        else:
            buckets["announcements"].append(trigger)

    return buckets


def to_trigger(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "published_date": item.get("published_date", ""),
        "summary": item.get("summary", ""),
        "source_name": item.get("source_name", ""),
        "source_url": item.get("source_url", ""),
        "content_type": item.get("content_type", ""),
        "closing_date": item.get("closing_date", ""),
        "salary": item.get("salary", ""),
        "department": item.get("department", ""),
        "is_urgent": bool(item.get("is_urgent") or item.get("preclassified_priority") == "urgent"),
    }


def build_output(buckets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    summary = build_summary(buckets)
    has_content = any(
        summary[key] for key in ("job_openings", "exam_updates", "announcements")
    )
    content_suggestion = pick_content_suggestion(buckets)

    return {
        "generated_date": datetime.now().strftime("%Y-%m-%d"),
        "has_content": has_content,
        "content_suggestion": content_suggestion,
        "summary": summary,
        "triggers": buckets,
    }


def pick_content_suggestion(buckets: dict[str, list[dict[str, Any]]]) -> str:
    any_urgent = any(
        item.get("is_urgent") for items in buckets.values() for item in items
    )
    if buckets["job_openings"] or any_urgent:
        return "A類：時效資訊帖"
    if buckets["exam_updates"]:
        return "A類：考試資訊帖"
    return "C類：互動類帖"


if __name__ == "__main__":
    main()
