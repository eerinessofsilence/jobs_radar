from __future__ import annotations

import logging
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any

from .extractors import clean_html, extractor_for_source
from .models import Vacancy
from .text import compact_text
from .urls import normalize_url


def entry_description(entry: Any) -> str:
    if entry.get("content"):
        content_values = [
            item.get("value", "") for item in entry.get("content", []) if item.get("value")
        ]
        if content_values:
            return clean_html("\n".join(content_values))

    return clean_html(entry.get("summary", "") or entry.get("description", ""))


def parse_published_date(entry: Any) -> str:
    raw_date = entry.get("published") or entry.get("updated") or entry.get("created") or ""
    if not raw_date:
        return ""

    try:
        parsed = parsedate_to_datetime(raw_date)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError, IndexError, OverflowError):
        return str(raw_date)


def entry_metadata(entry: Any, source: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": source,
        "rss": {
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "id": entry.get("id", ""),
            "published": entry.get("published", ""),
            "updated": entry.get("updated", ""),
            "author": entry.get("author", ""),
            "keys": sorted(str(key) for key in entry.keys()),
        },
    }
    tags = entry.get("tags") or []
    if tags:
        metadata["rss"]["tags"] = [
            tag.get("term", "") for tag in tags if isinstance(tag, dict) and tag.get("term")
        ]
    return metadata


def normalize_entry(entry: Any, source: str) -> Vacancy | None:
    title = compact_text(clean_html(entry.get("title", "")))
    url = normalize_url(entry.get("link", "") or entry.get("id", ""))
    description = entry_description(entry)

    if not title or not url:
        logging.debug("Skipping %s entry without title or URL.", source)
        return None

    extractor = extractor_for_source(source)
    return Vacancy(
        source=source,
        title=title,
        company=extractor.extract_company(entry, title, description),
        location=extractor.extract_location(entry, description),
        salary=extractor.extract_salary(entry, title, description),
        url=url,
        published_date=parse_published_date(entry),
        description=description,
        metadata=entry_metadata(entry, source),
    )
