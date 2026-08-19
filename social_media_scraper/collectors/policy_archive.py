"""Per-ISO-week archive for info.gov.hk policy news.

Each run backfills the last N days and merges the results into week files named
`policy_news_YYYY-Www.json` (e.g. policy_news_2026-W34.json). Merging is
idempotent: re-running the same day never duplicates items (dedupe by URL) and
never loses previously stored items for that week.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


def iso_week_key(iso_date: str) -> str | None:
    """'2026-08-19' -> '2026-W34'. Returns None for unparseable/empty dates."""
    parsed = _parse_iso(iso_date)
    if parsed is None:
        return None
    iso_year, iso_week, _ = parsed.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def _parse_iso(iso_date: str) -> date | None:
    if not iso_date:
        return None
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _week_bounds(week_key: str) -> tuple[str, str]:
    """'2026-W34' -> ('2026-08-17', '2026-08-23') (Mon..Sun)."""
    iso_year = int(week_key[:4])
    iso_week = int(week_key.split("W")[1])
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def _sort_key(item: dict[str, Any]) -> tuple[str, str]:
    # Newest first; stable tie-break on title.
    return (item.get("published_date", ""), item.get("title", ""))


def write_weekly_archive(
    items: list[dict[str, Any]],
    output_dir: Path,
    today: date | None = None,
) -> dict[str, Path]:
    """Merge `items` into their ISO-week files. Returns {week_key: path} touched.

    Items whose published_date cannot be parsed are filed under the current
    ISO week so nothing is silently dropped.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    anchor = today or date.today()
    fallback_week = iso_week_key(anchor.isoformat())

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        week_key = iso_week_key(item.get("published_date", "")) or fallback_week
        grouped.setdefault(week_key, []).append(item)

    touched: dict[str, Path] = {}
    for week_key, new_items in grouped.items():
        path = output_dir / f"policy_news_{week_key}.json"
        existing = _load_week(path)

        merged: dict[str, dict[str, Any]] = {}
        for item in existing + new_items:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            # Keep the first occurrence; later duplicates are ignored.
            merged.setdefault(url, item)

        ordered = sorted(merged.values(), key=_sort_key, reverse=True)
        week_start, week_end = _week_bounds(week_key)
        payload = {
            "iso_week": week_key,
            "week_start": week_start,
            "week_end": week_end,
            "last_updated": anchor.isoformat(),
            "count": len(ordered),
            "items": ordered,
        }
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        touched[week_key] = path

    return touched


def _load_week(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("items") if isinstance(data, dict) else None
        return items if isinstance(items, list) else []
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []


def recent_items(
    items: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Deduped, newest-first, capped list for the main triggers JSON."""
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        url = str(item.get("url") or "").strip()
        if url:
            merged.setdefault(url, item)
    ordered = sorted(merged.values(), key=_sort_key, reverse=True)
    return ordered[:limit]
