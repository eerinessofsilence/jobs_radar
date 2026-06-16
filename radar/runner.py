from __future__ import annotations

import logging
from datetime import UTC, datetime

from openai import OpenAI

from .feeds import collect_email_alert_vacancies, collect_rss_vacancies
from .filters import (
    experience_prefilter_reason,
    filter_by_min_score,
    keyword_summary_is_relevant,
    match_keyword_summary,
    negative_prefilter_reason,
    title_prefilter_reason,
)
from .local_rules import dedupe_similar_vacancies, local_prescore_vacancy
from .logging_utils import log_run_start, setup_logging
from .models import AnalysisResult, Config, OpenAIQuotaError, RunStats, Vacancy
from .openai_analysis import analyze_vacancy
from .robota import collect_robota_vacancies
from .settings import load_config
from .sheets import (
    OpenedSheets,
    analysis_cache_key,
    append_analysis_cache_rows,
    append_analyzed_vacancies,
    append_run_summary,
    append_seen_vacancies,
    google_sheet_url,
    open_sheet,
)
from .telegram import build_no_new_message, build_summary_message, send_telegram_message
from .text import keywords_label, truncate_text, vacancy_label


def unique_new_vacancies(vacancies: list[Vacancy], existing_urls: set[str]) -> list[Vacancy]:
    new_vacancies: list[Vacancy] = []
    seen_urls = set(existing_urls)

    for vacancy in vacancies:
        if not vacancy.url or vacancy.url in seen_urls:
            continue

        seen_urls.add(vacancy.url)
        new_vacancies.append(vacancy)

    return new_vacancies


def unique_new_and_similar_vacancies(
    vacancies: list[Vacancy],
    existing_urls: set[str],
) -> tuple[list[Vacancy], int, int]:
    url_unique = unique_new_vacancies(vacancies, existing_urls)
    similar_unique, skipped_similar = dedupe_similar_vacancies(url_unique)
    skipped_existing = len(vacancies) - len(url_unique)
    return similar_unique, skipped_existing, skipped_similar


def vacancy_published_timestamp(vacancy: Vacancy) -> float:
    try:
        published_at = datetime.fromisoformat(vacancy.published_date)
    except ValueError:
        return 0.0

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    return published_at.timestamp()


def interleave_vacancies_by_source(vacancies: list[Vacancy]) -> list[Vacancy]:
    grouped_vacancies: dict[str, list[Vacancy]] = {}
    source_order: list[str] = []

    for vacancy in sorted(vacancies, key=vacancy_published_timestamp, reverse=True):
        if vacancy.source not in grouped_vacancies:
            grouped_vacancies[vacancy.source] = []
            source_order.append(vacancy.source)
        grouped_vacancies[vacancy.source].append(vacancy)

    interleaved: list[Vacancy] = []
    while any(grouped_vacancies.values()):
        for source in source_order:
            source_vacancies = grouped_vacancies[source]
            if source_vacancies:
                interleaved.append(source_vacancies.pop(0))

    return interleaved


def combine_warning(existing_warning: str, new_warning: str) -> str:
    if not existing_warning:
        return new_warning
    return f"{existing_warning} {new_warning}"


def log_openai_usage(vacancy: Vacancy, analysis: AnalysisResult) -> None:
    if not analysis.total_tokens:
        return

    cost = (
        f"${analysis.estimated_cost_usd:.6f}"
        if analysis.estimated_cost_usd is not None
        else "unconfigured"
    )
    logging.info(
        "[openai] tokens=%s | input=%s | output=%s | cost=%s | %s",
        analysis.total_tokens,
        analysis.prompt_tokens,
        analysis.completion_tokens,
        cost,
        vacancy_label(vacancy),
    )


def update_openai_usage_stats(
    stats: RunStats,
    analyzed: list[tuple[Vacancy, AnalysisResult]],
) -> None:
    estimated_costs = [
        analysis.estimated_cost_usd
        for _, analysis in analyzed
        if analysis.estimated_cost_usd is not None
    ]
    stats.prompt_tokens = sum(analysis.prompt_tokens for _, analysis in analyzed)
    stats.completion_tokens = sum(analysis.completion_tokens for _, analysis in analyzed)
    stats.total_tokens = sum(analysis.total_tokens for _, analysis in analyzed)
    stats.estimated_cost_usd = sum(estimated_costs) if estimated_costs else None


def source_zero_warning(config: Config, vacancies: list[Vacancy]) -> str:
    source_counts: dict[str, int] = {}
    for vacancy in vacancies:
        source_counts[vacancy.source] = source_counts.get(vacancy.source, 0) + 1

    missing_sources: list[str] = []
    if config.dou_rss_urls and source_counts.get("DOU", 0) == 0:
        missing_sources.append("DOU")
    if config.djinni_rss_urls and source_counts.get("Djinni", 0) == 0:
        missing_sources.append("Djinni")
    if config.indeed_rss_urls and source_counts.get("Indeed", 0) == 0:
        missing_sources.append("Indeed")
    if config.robota_keywords and source_counts.get("Robota.ua", 0) == 0:
        missing_sources.append("Robota.ua")

    if not missing_sources:
        return ""

    return "No vacancies parsed from configured source(s): " + ", ".join(missing_sources) + "."


def cached_analysis_for_vacancy(
    sheets: OpenedSheets,
    config: Config,
    vacancy: Vacancy,
) -> AnalysisResult | None:
    cached = sheets.analysis_cache.get(analysis_cache_key(config.openai_model, vacancy))
    if not cached:
        return None

    return AnalysisResult(
        score=cached.score,
        fit_reason=cached.fit_reason,
        risks=cached.risks,
        generated_reply=cached.generated_reply,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        estimated_cost_usd=None,
        raw_response=cached.raw_response,
        source="cache",
    )


def record_run_summary(
    sheets: OpenedSheets,
    stats: RunStats,
    config: Config,
    warning: str,
) -> str:
    try:
        append_run_summary(
            sheets.runs_worksheet,
            sheets.runs_headers,
            stats,
            config,
            error=warning,
        )
    except Exception as exc:
        logging.exception("[sheet] Failed to append run summary.")
        warning = combine_warning(warning, f"Runs tracking failed: {exc}")
    return warning


def run() -> None:
    setup_logging()
    config = load_config()
    log_run_start(config)
    openai_client = OpenAI(
        api_key=config.openai_api_key,
        timeout=config.openai_timeout_seconds,
        max_retries=config.openai_max_retries,
    )

    sheets = open_sheet(config)
    tracked_urls = sheets.existing_urls | sheets.seen_urls
    logging.debug(
        "[sheet] Connected. Existing rows=%s | seen rows=%s | tracked URLs=%s",
        len(sheets.existing_urls),
        len(sheets.seen_urls),
        len(tracked_urls),
    )

    rss_vacancies = collect_rss_vacancies(config)
    robota_vacancies = collect_robota_vacancies(config)
    email_vacancies = collect_email_alert_vacancies()
    fetched_vacancies = rss_vacancies + robota_vacancies + email_vacancies
    source_counts: dict[str, int] = {}
    for vacancy in fetched_vacancies:
        source_counts[vacancy.source] = source_counts.get(vacancy.source, 0) + 1
    logging.info(
        "[fetch] DOU=%s | Djinni=%s | Indeed=%s | Robota.ua=%s | total=%s",
        source_counts.get("DOU", 0),
        source_counts.get("Djinni", 0),
        source_counts.get("Indeed", 0),
        source_counts.get("Robota.ua", 0),
        len(fetched_vacancies),
    )

    stats = RunStats(total_fetched=len(fetched_vacancies))
    stats.missing_company = sum(1 for vacancy in fetched_vacancies if not vacancy.company)
    stats.missing_salary = sum(1 for vacancy in fetched_vacancies if not vacancy.salary)
    warning = source_zero_warning(config, fetched_vacancies)

    matched_vacancies: list[Vacancy] = []
    for vacancy in fetched_vacancies:
        keyword_summary = match_keyword_summary(vacancy, config.radar.keywords)
        vacancy.matched_keywords = keyword_summary.labels
        if keyword_summary_is_relevant(keyword_summary):
            matched_vacancies.append(vacancy)

    stats.matched_by_keywords = len(matched_vacancies)

    prefiltered_vacancies: list[Vacancy] = []
    for vacancy in matched_vacancies:
        title_reason = title_prefilter_reason(vacancy, config.radar)
        if title_reason:
            stats.skipped_by_title_prefilter += 1
            logging.debug("[filter] title skip=%s | %s", title_reason, vacancy_label(vacancy))
            continue

        experience_reason = experience_prefilter_reason(vacancy, config.radar)
        if experience_reason:
            stats.skipped_by_experience_prefilter += 1
            logging.debug(
                "[filter] experience skip=%s | %s",
                experience_reason,
                vacancy_label(vacancy),
            )
            continue

        reason = negative_prefilter_reason(vacancy, config.radar)
        if reason:
            stats.skipped_by_negative_prefilter += 1
            logging.debug("[filter] negative skip=%s | %s", reason, vacancy_label(vacancy))
            continue
        prefiltered_vacancies.append(vacancy)

    unique_vacancies, skipped_existing, skipped_similar = unique_new_and_similar_vacancies(
        prefiltered_vacancies,
        tracked_urls,
    )
    new_vacancies = interleave_vacancies_by_source(unique_vacancies)
    stats.new_vacancies = len(new_vacancies)
    stats.skipped_existing_vacancies = skipped_existing
    stats.skipped_similar_vacancies = skipped_similar

    logging.info(
        "[filter] fetched=%s | missing_company=%s | missing_salary=%s | matched=%s | "
        "title_skip=%s | exp_skip=%s | "
        "neg_skip=%s | new=%s | tracked/seen/dup=%s | similar_dup=%s",
        stats.total_fetched,
        stats.missing_company,
        stats.missing_salary,
        stats.matched_by_keywords,
        stats.skipped_by_title_prefilter,
        stats.skipped_by_experience_prefilter,
        stats.skipped_by_negative_prefilter,
        stats.new_vacancies,
        stats.skipped_existing_vacancies,
        stats.skipped_similar_vacancies,
    )

    if not new_vacancies:
        warning = record_run_summary(sheets, stats, config, warning)
        message = build_no_new_message(stats, google_sheet_url(config), warning=warning)
        send_telegram_message(config.telegram_bot_token, config.telegram_chat_id, message)
        logging.info("[done] no new matching vacancies | telegram=sent")
        return

    vacancies_to_analyze = new_vacancies[: config.max_jobs_per_run]
    stats.queued_for_analysis = len(vacancies_to_analyze)
    stats.skipped_by_run_limit = len(new_vacancies) - len(vacancies_to_analyze)
    if len(new_vacancies) > len(vacancies_to_analyze):
        logging.info(
            "[analyze] %s/%s new vacancies queued",
            len(vacancies_to_analyze),
            len(new_vacancies),
        )
    else:
        logging.info("[analyze] %s new vacancies queued", len(vacancies_to_analyze))

    analyzed: list[tuple[Vacancy, AnalysisResult]] = []
    for index, vacancy in enumerate(vacancies_to_analyze, start=1):
        logging.debug(
            "[analyze] %s/%s | url=%s | keywords=%s",
            index,
            len(vacancies_to_analyze),
            vacancy.url,
            keywords_label(vacancy.matched_keywords),
        )
        analysis = cached_analysis_for_vacancy(sheets, config, vacancy)
        if analysis:
            stats.cached_analysis_vacancies += 1
            logging.info("[cache] reused analysis | %s", vacancy_label(vacancy))
        else:
            analysis = local_prescore_vacancy(vacancy, config.radar, config.min_score)
            if analysis:
                stats.local_prescore_vacancies += 1
                logging.info("[prescore] score=%s | %s", analysis.score, vacancy_label(vacancy))
            else:
                try:
                    analysis = analyze_vacancy(
                        openai_client,
                        config.openai_model,
                        vacancy,
                        config.radar,
                        max_completion_tokens=config.openai_max_completion_tokens,
                        timeout_seconds=config.openai_timeout_seconds,
                        input_cost_per_1m=config.openai_input_cost_per_1m,
                        output_cost_per_1m=config.openai_output_cost_per_1m,
                    )
                except OpenAIQuotaError as exc:
                    warning = str(exc)
                    logging.error("[openai] %s", warning)
                    break

        log_openai_usage(vacancy, analysis)
        action = "append" if analysis.score >= config.min_score else f"skip<{config.min_score}"
        logging.info(
            "[result] %s/%s | score=%s/%s | %s | %s",
            index,
            len(vacancies_to_analyze),
            analysis.score,
            config.radar.score_max,
            action,
            vacancy_label(vacancy),
        )
        if analysis.fit_reason:
            logging.debug("[reason] %s", truncate_text(analysis.fit_reason))
        if analysis.risks:
            logging.debug("[risks] %s", truncate_text(analysis.risks))
        analyzed.append((vacancy, analysis))

    stats.analyzed_vacancies = len(analyzed)
    update_openai_usage_stats(stats, analyzed)
    analyzed_to_append = filter_by_min_score(analyzed, config.min_score)
    stats.skipped_low_score = len(analyzed) - len(analyzed_to_append)
    logging.info(
        "[sheet] append=%s | skip_low_score=%s | min=%s",
        len(analyzed_to_append),
        stats.skipped_low_score,
        config.min_score,
    )
    stats.appended_vacancies = append_analyzed_vacancies(
        sheets.worksheet,
        sheets.headers,
        analyzed_to_append,
        config.radar,
        config.radar.row_defaults,
    )
    try:
        stats.seen_vacancies = append_seen_vacancies(
            sheets.seen_worksheet,
            sheets.seen_headers,
            analyzed,
            config.radar,
            config.min_score,
        )
    except Exception as exc:
        logging.exception("[sheet] Failed to mark analyzed vacancies in Seen worksheet.")
        warning = combine_warning(warning, f"Seen tracking failed: {exc}")

    try:
        appended_cache_rows = append_analysis_cache_rows(
            sheets.analysis_cache_worksheet,
            sheets.analysis_cache_headers,
            analyzed,
            config.radar,
            config.openai_model,
        )
        logging.info("[cache] appended=%s", appended_cache_rows)
    except Exception as exc:
        logging.exception("[sheet] Failed to append analysis cache rows.")
        warning = combine_warning(warning, f"Analysis cache failed: {exc}")

    warning = record_run_summary(sheets, stats, config, warning)

    message = build_summary_message(
        stats,
        analyzed,
        config.min_score,
        google_sheet_url(config),
        warning=warning,
    )
    send_telegram_message(config.telegram_bot_token, config.telegram_chat_id, message)
    logging.info(
        "[done] fetched=%s | matched=%s | title_skip=%s | exp_skip=%s | "
        "neg_skip=%s | new=%s | analyzed=%s | cached=%s | prescore=%s | appended=%s | "
        "telegram=sent",
        stats.total_fetched,
        stats.matched_by_keywords,
        stats.skipped_by_title_prefilter,
        stats.skipped_by_experience_prefilter,
        stats.skipped_by_negative_prefilter,
        stats.new_vacancies,
        stats.analyzed_vacancies,
        stats.cached_analysis_vacancies,
        stats.local_prescore_vacancies,
        stats.appended_vacancies,
    )


if __name__ == "__main__":
    run()
