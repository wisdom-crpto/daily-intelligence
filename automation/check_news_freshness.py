"""Local, read-only guard against stale or recycled Daily Intelligence issues.

Publication dates in data.json are editorial claims, not independently verified
timestamps. This catches calendar-day staleness and repetition; the editor must
still verify source publication times and distinguish disclosure from event date.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
import unicodedata
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _issue_path(root: Path, day: dt.date) -> Path:
    return root / f"{day:%Y}" / f"{day:%m}" / day.isoformat() / "data.json"


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def _normalized(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", value).casefold()
                   if char.isalnum())


def check(root: Path, day: dt.date, now: dt.datetime | None = None) -> list[str]:
    """Return hard failures. This deliberately does not claim hour-level proof."""
    errors: list[str] = []
    path = _issue_path(root, day)
    data = _load(path)
    if data.get("date") != day.isoformat():
        errors.append("data.json date does not match issue directory")
    try:
        generated = dt.datetime.fromisoformat(data["generated_at"])
        if generated.tzinfo is None or generated.utcoffset() is None:
            raise ValueError("timezone missing")
        if generated.astimezone(SHANGHAI).date() < day:
            errors.append("generated_at precedes the report date in Shanghai")
        if now is not None and generated > now + dt.timedelta(minutes=5):
            errors.append("generated_at is in the future")
    except (KeyError, TypeError, ValueError):
        errors.append("generated_at must be a timezone-aware ISO 8601 timestamp")

    sources = data.get("sources")
    if not isinstance(sources, dict):
        return errors + ["sources must contain ai and business_macro categories"]
    fresh_urls: set[str] = set()
    current_titles: set[str] = set()
    for category in ("ai", "business_macro"):
        entries = sources.get(category)
        if not isinstance(entries, list) or len(entries) < 2:
            errors.append(f"{category} needs at least two primary, recent sources")
            continue
        for item in entries:
            if not isinstance(item, dict):
                errors.append(f"{category}: invalid source entry")
                continue
            url = item.get("url")
            title = item.get("title")
            published = item.get("published")
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                errors.append(f"{category}: source URL missing")
                continue
            if not isinstance(title, str) or not title.strip():
                errors.append(f"{category}: source title missing")
                continue
            if item.get("primary") is not True:
                errors.append(f"{category}: source must be primary")
            try:
                source_day = dt.date.fromisoformat(published)
            except (TypeError, ValueError):
                errors.append(f"{category}: source publication date unknown")
                continue
            if source_day not in {day, day - dt.timedelta(days=1)}:
                errors.append(f"{category}: source is outside current/previous calendar day: {url}")
            if url in fresh_urls:
                errors.append(f"duplicate source URL within issue: {url}")
            fresh_urls.add(url)
            current_titles.add(_normalized(title))
    if len(fresh_urls) < 4:
        errors.append("at least four distinct recent source URLs required")

    thesis = data.get("thesis")
    current_thesis = _normalized(thesis) if isinstance(thesis, str) else ""
    if not current_thesis:
        errors.append("thesis missing")
    for days_back in (1, 2):
        prior_day = day - dt.timedelta(days=days_back)
        prior_path = _issue_path(root, prior_day)
        if not prior_path.exists():
            continue
        prior = _load(prior_path)
        prior_thesis = prior.get("thesis")
        if isinstance(prior_thesis, str) and current_thesis == _normalized(prior_thesis):
            errors.append(f"thesis repeats {prior_day}")
        prior_sources = prior.get("sources")
        if isinstance(prior_sources, dict):
            for group in prior_sources.values():
                if not isinstance(group, list):
                    continue
                for source in group:
                    if not isinstance(source, dict):
                        continue
                    if source.get("url") in fresh_urls:
                        errors.append(f"source URL repeats {prior_day}: {source['url']}")
                    title = source.get("title")
                    if isinstance(title, str) and _normalized(title) in current_titles:
                        errors.append(f"source event repeats {prior_day}: {title}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="report date YYYY-MM-DD; defaults to latest issue")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.date:
            day = dt.date.fromisoformat(args.date)
        else:
            dated = [dt.date.fromisoformat(p.name) for p in args.root.glob("????/??/????-??-??")
                     if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)]
            if not dated:
                raise ValueError("no dated issues found")
            day = max(dated)
        errors = check(args.root, day, dt.datetime.now(dt.timezone.utc))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Freshness check failed: {exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(f"Freshness check failed: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"Freshness structure passed for {day}; source hours and factual novelty require editorial verification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
