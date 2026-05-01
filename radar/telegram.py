from __future__ import annotations

from .http_utils import retry_session
from .models import AnalysisResult, RunStats, Vacancy


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
        f"Matched by keywords: {stats.matched_by_keywords}",
        f"Skipped by title prefilter: {stats.skipped_by_title_prefilter}",
        f"Skipped by experience prefilter: {stats.skipped_by_experience_prefilter}",
        f"Skipped by negative prefilter: {stats.skipped_by_negative_prefilter}",
        f"Tracked/seen/duplicate: {stats.skipped_existing_vacancies}",
        f"New vacancies: {stats.new_vacancies}",
        f"Queued for analysis: {stats.queued_for_analysis}",
        f"Skipped by run limit: {stats.skipped_by_run_limit}",
        f"Analyzed vacancies: {stats.analyzed_vacancies}",
        f"Appended vacancies: {stats.appended_vacancies}",
        f"Low-score skipped: {stats.skipped_low_score}",
        f"Marked seen: {stats.seen_vacancies}",
        token_usage_line(stats),
    ]


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
    eligible_top = [
        (vacancy, analysis) for vacancy, analysis in analyzed if analysis.score >= min_score
    ]
    top_vacancies = sorted(eligible_top, key=lambda item: item[1].score, reverse=True)[:5]

    lines = ["Job radar summary", *build_context_lines(stats)]

    if min_score > 0:
        lines.append(f"Minimum score to append/list: {min_score}")
    if sheet_url:
        lines.append(f"Sheet: {sheet_url}")

    if warning:
        lines.append("")
        lines.append(f"Warning: {warning}")

    if top_vacancies:
        lines.append("")
        lines.append("Top vacancies:")
        for index, (vacancy, analysis) in enumerate(top_vacancies, start=1):
            company = f" at {vacancy.company}" if vacancy.company else ""
            lines.append(f"{index}. {vacancy.title}{company}")
            lines.append(f"Score: {analysis.score}")
            lines.append(vacancy.url)
    else:
        lines.append("")
        lines.append("No analyzed vacancies met the minimum score for the top list.")

    return "\n".join(lines)
