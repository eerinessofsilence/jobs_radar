from __future__ import annotations

import re

from .models import AnalysisResult, RadarSettings, Vacancy
from .text import compact_text


def normalize_similarity_text(value: str) -> str:
    normalized = compact_text(value).lower()
    normalized = re.sub(r"\([^)]*\)", " ", normalized)
    normalized = re.sub(
        r"\b(?:middle|senior|junior|lead|strong|developer|engineer)\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"[^a-zа-яіїєґ0-9+#.]+", " ", normalized, flags=re.IGNORECASE)
    return compact_text(normalized)


def similar_vacancy_key(vacancy: Vacancy) -> str:
    title = normalize_similarity_text(vacancy.title)
    company = normalize_similarity_text(vacancy.company)
    source = normalize_similarity_text(vacancy.source)
    if company:
        return f"{source}|{company}|{title}"
    return f"{source}|{title}"


def dedupe_similar_vacancies(vacancies: list[Vacancy]) -> tuple[list[Vacancy], int]:
    unique: list[Vacancy] = []
    seen_keys: set[str] = set()

    for vacancy in vacancies:
        key = similar_vacancy_key(vacancy)
        if key in seen_keys:
            continue

        seen_keys.add(key)
        unique.append(vacancy)

    return unique, len(vacancies) - len(unique)


def local_prescore_vacancy(
    vacancy: Vacancy,
    radar: RadarSettings,
    min_score: int,
) -> AnalysisResult | None:
    haystack = compact_text(f"{vacancy.title}\n{vacancy.location}\n{vacancy.description}").lower()

    obvious_reasons: list[str] = []
    if re.search(r"\boffice[- ]only\b|\bon[- ]site\b|\boffline\b", haystack):
        obvious_reasons.append("office-only format")
    if re.search(r"\brelocation\s+required\b|\bmust relocate\b", haystack):
        obvious_reasons.append("relocation required")
    if re.search(r"\b(?:7|8|9|10)\+?\s+years\b", haystack):
        obvious_reasons.append("requires far more experience")
    if radar.max_required_years is not None and re.search(
        rf"\b(?:{radar.max_required_years + 3}|{radar.max_required_years + 4}|"
        rf"{radar.max_required_years + 5})\+?\s+years\b",
        haystack,
    ):
        obvious_reasons.append("above configured experience limit")

    if not obvious_reasons:
        return None

    score = min(radar.score_min, max(1, min_score - 1 if min_score > 1 else 1))
    reason = "Local pre-score skipped OpenAI: " + ", ".join(obvious_reasons) + "."
    return AnalysisResult(
        score=score,
        fit_reason=reason,
        risks="Skipped before OpenAI by deterministic rules.",
        generated_reply="",
        source="local_prescore",
    )
