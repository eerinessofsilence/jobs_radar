from __future__ import annotations

import re

from .http_utils import retry_session
from .models import AnalysisResult, RunStats, Vacancy
from .text import compact_text, truncate_text


def telegram_chunks(message: str, max_length: int = 3900) -> list[str]:
    chunks: list[str] = []
    remaining = message
    while len(remaining) > max_length:
        split_at = remaining.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def send_telegram_message(bot_token: str, chat_id: str, message: str) -> None:
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    with retry_session(
        total=2,
        backoff_factor=0.5,
        allowed_methods=("POST",),
        read_retries=0,
    ) as session:
        for chunk in telegram_chunks(message):
            response = session.post(
                api_url,
                json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=30,
            )
            response.raise_for_status()


def token_usage_line(stats: RunStats) -> str:
    cost = f", cost=${stats.estimated_cost_usd:.6f}" if stats.estimated_cost_usd is not None else ""
    return (
        f"Token usage: {stats.total_tokens} total "
        f"({stats.prompt_tokens} input, {stats.completion_tokens} output){cost}"
    )


def build_context_lines(stats: RunStats) -> list[str]:
    return [
        f"Total fetched: {stats.total_fetched}",
        f"Missing company: {stats.missing_company}",
        f"Missing salary: {stats.missing_salary}",
        f"Matched by keywords: {stats.matched_by_keywords}",
        f"Skipped by title prefilter: {stats.skipped_by_title_prefilter}",
        f"Skipped by experience prefilter: {stats.skipped_by_experience_prefilter}",
        f"Skipped by negative prefilter: {stats.skipped_by_negative_prefilter}",
        f"Tracked/seen/duplicate: {stats.skipped_existing_vacancies}",
        f"Similar duplicate skipped: {stats.skipped_similar_vacancies}",
        f"New vacancies: {stats.new_vacancies}",
        f"Queued for analysis: {stats.queued_for_analysis}",
        f"Skipped by run limit: {stats.skipped_by_run_limit}",
        f"Local pre-score: {stats.local_prescore_vacancies}",
        f"Cached analysis: {stats.cached_analysis_vacancies}",
        f"Analyzed vacancies: {stats.analyzed_vacancies}",
        f"Appended vacancies: {stats.appended_vacancies}",
        f"Low-score skipped: {stats.skipped_low_score}",
        f"Marked seen: {stats.seen_vacancies}",
        token_usage_line(stats),
    ]


def vacancy_work_format(vacancy: Vacancy) -> str:
    haystack = compact_text(f"{vacancy.location}\n{vacancy.description}").lower()
    if re.search(r"\bpart[- ]time\b|\bpart time\b|\bнеповна\b|\bчасткова\b", haystack):
        return "Part-time"
    if re.search(r"\bfreelance\b|\bcontract\b|\bproject[- ]based\b|\bпроєкт", haystack):
        return "Freelance"
    if re.search(r"\boffice[- ]only\b|\bon[- ]site\b|\boffline\b|\bофіс\b|\bофис\b", haystack):
        return "Office"
    if re.search(r"\bremote\b|\bremotely\b|\bвіддалено\b", haystack):
        return "Remote"
    if re.search(r"\bhybrid\b|\bгібрид\b", haystack):
        return "Hybrid"
    return vacancy.location or "-"


def compact_vacancy_line(vacancy: Vacancy, analysis: AnalysisResult) -> str:
    title = truncate_text(vacancy.title, 72)
    company = vacancy.company or "-"
    salary = vacancy.salary or "-"
    work_format = vacancy_work_format(vacancy)
    return f"{analysis.score} | {title} | {company} | {salary} | {work_format}"


def append_vacancy_group(
    lines: list[str],
    title: str,
    vacancies: list[tuple[Vacancy, AnalysisResult]],
) -> None:
    if not vacancies:
        return

    lines.append("")
    lines.append(title)
    for vacancy, analysis in vacancies:
        lines.append(compact_vacancy_line(vacancy, analysis))
        lines.append(vacancy.url)


def build_no_new_message(stats: RunStats, sheet_url: str = "", warning: str = "") -> str:
    lines = [
        "Job radar: no new matching vacancies found.",
        *build_context_lines(stats),
    ]
    if sheet_url:
        lines.append(f"Sheet: {sheet_url}")
    if warning:
        lines.append("")
        lines.append(f"Warning: {warning}")
    return "\n".join(lines)


def build_summary_message(
    stats: RunStats,
    analyzed: list[tuple[Vacancy, AnalysisResult]],
    min_score: int,
    sheet_url: str = "",
    warning: str = "",
) -> str:
    scored = [(vacancy, analysis) for vacancy, analysis in analyzed if analysis.score > 0]
    sorted_scored = sorted(scored, key=lambda item: item[1].score, reverse=True)
    strong_min_score = max(8, min_score)
    strong_vacancies = [
        (vacancy, analysis)
        for vacancy, analysis in sorted_scored
        if analysis.score >= strong_min_score
    ][:5]
    maybe_vacancies = [
        (vacancy, analysis)
        for vacancy, analysis in sorted_scored
        if min_score <= analysis.score < strong_min_score
    ][:5]
    skipped_notable = [
        (vacancy, analysis)
        for vacancy, analysis in sorted_scored
        if analysis.score < min_score
    ][:5]

    lines = ["Job radar summary", *build_context_lines(stats)]

    if min_score > 0:
        lines.append(f"Minimum score to append/list: {min_score}")
    if sheet_url:
        lines.append(f"Sheet: {sheet_url}")

    if warning:
        lines.append("")
        lines.append(f"Warning: {warning}")

    if strong_vacancies or maybe_vacancies or skipped_notable:
        append_vacancy_group(lines, "Strong", strong_vacancies)
        append_vacancy_group(lines, "Maybe", maybe_vacancies)
        append_vacancy_group(lines, "Skipped notable", skipped_notable)
    else:
        lines.append("")
        lines.append("No scored vacancies to list.")

    return "\n".join(lines)
