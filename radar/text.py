from __future__ import annotations

import re

from .models import Vacancy


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def truncate_text(value: str, max_length: int = 160) -> str:
    compacted = compact_text(value)
    if len(compacted) <= max_length:
        return compacted
    return compacted[: max_length - 3].rstrip() + "..."


def vacancy_label(vacancy: Vacancy) -> str:
    parts = [vacancy.title]
    if vacancy.company:
        parts.append(vacancy.company)
    if vacancy.location:
        parts.append(vacancy.location)
    parts.append(vacancy.source)
    return " | ".join(parts)


def keywords_label(keywords: list[str], max_items: int = 5) -> str:
    if not keywords:
        return "-"

    visible_keywords = keywords[:max_items]
    suffix = "" if len(keywords) <= max_items else f" +{len(keywords) - max_items}"
    return ", ".join(visible_keywords) + suffix
