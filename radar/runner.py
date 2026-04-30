from __future__ import annotations

import logging
from datetime import datetime, timezone

from openai import OpenAI

from .filters import (
    experience_prefilter_reason,
    filter_by_min_score,
    match_keywords,
    negative_prefilter_reason,
    title_prefilter_reason,
)
from .logging_utils import log_run_start, setup_logging
from .models import AnalysisResult, OpenAIQuotaError, RunStats, Vacancy
from .openai_analysis import analyze_vacancy
from .rss import collect_email_alert_vacancies, collect_rss_vacancies
from .sheets import append_analyzed_vacancies, open_sheet
from .settings import load_config
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


def vacancy_published_timestamp(vacancy: Vacancy) -> float:
    try:
        published_at = datetime.fromisoformat(vacancy.published_date)
    except ValueError:
        return 0.0

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
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


def run() -> None:
    setup_logging()
    config = load_config()
    log_run_start(config)
    openai_client = OpenAI(api_key=config.openai_api_key, max_retries=0)

    worksheet, headers, existing_urls = open_sheet(config)
    logging.debug("[sheet] Connected. Existing tracked URLs: %s", len(existing_urls))

    rss_vacancies = collect_rss_vacancies(config)
    email_vacancies = collect_email_alert_vacancies()
    fetched_vacancies = rss_vacancies + email_vacancies

    stats = RunStats(total_fetched=len(fetched_vacancies))

    matched_vacancies: list[Vacancy] = []
    for vacancy in fetched_vacancies:
        vacancy.matched_keywords = match_keywords(vacancy, config.radar.keywords)
        if vacancy.matched_keywords:
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
            logging.debug("[filter] experience skip=%s | %s", experience_reason, vacancy_label(vacancy))
            continue

        reason = negative_prefilter_reason(vacancy, config.radar)
        if reason:
            stats.skipped_by_negative_prefilter += 1
            logging.debug("[filter] negative skip=%s | %s", reason, vacancy_label(vacancy))
            continue
        prefiltered_vacancies.append(vacancy)

    new_vacancies = interleave_vacancies_by_source(
        unique_new_vacancies(prefiltered_vacancies, existing_urls)
    )
    stats.new_vacancies = len(new_vacancies)
    skipped_existing = len(prefiltered_vacancies) - stats.new_vacancies

    logging.info(
        "[filter] fetched=%s | matched=%s | title_skip=%s | exp_skip=%s | neg_skip=%s | new=%s | tracked/dup=%s",
        stats.total_fetched,
        stats.matched_by_keywords,
        stats.skipped_by_title_prefilter,
        stats.skipped_by_experience_prefilter,
        stats.skipped_by_negative_prefilter,
        stats.new_vacancies,
        skipped_existing,
    )

    if not new_vacancies:
        message = build_no_new_message(stats)
        send_telegram_message(config.telegram_bot_token, config.telegram_chat_id, message)
        logging.info("[done] no new matching vacancies | telegram=sent")
        return

    vacancies_to_analyze = new_vacancies[: config.max_jobs_per_run]
    if len(new_vacancies) > len(vacancies_to_analyze):
        logging.info(
            "[analyze] %s/%s new vacancies queued",
            len(vacancies_to_analyze),
            len(new_vacancies),
        )
    else:
        logging.info("[analyze] %s new vacancies queued", len(vacancies_to_analyze))

    analyzed: list[tuple[Vacancy, AnalysisResult]] = []
    warning = ""
    for index, vacancy in enumerate(vacancies_to_analyze, start=1):
        logging.debug(
            "[analyze] %s/%s | url=%s | keywords=%s",
            index,
            len(vacancies_to_analyze),
            vacancy.url,
            keywords_label(vacancy.matched_keywords),
        )
        try:
            analysis = analyze_vacancy(openai_client, config.openai_model, vacancy, config.radar)
        except OpenAIQuotaError as exc:
            warning = str(exc)
            logging.error("[openai] %s", warning)
            break

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
    analyzed_to_append = filter_by_min_score(analyzed, config.min_score)
    skipped_low_score = len(analyzed) - len(analyzed_to_append)
    logging.info(
        "[sheet] append=%s | skip_low_score=%s | min=%s",
        len(analyzed_to_append),
        skipped_low_score,
        config.min_score,
    )
    stats.appended_vacancies = append_analyzed_vacancies(
        worksheet,
        headers,
        analyzed_to_append,
        config.radar,
        config.radar.row_defaults,
    )

    message = build_summary_message(stats, analyzed, config.min_score, warning=warning)
    send_telegram_message(config.telegram_bot_token, config.telegram_chat_id, message)
    logging.info(
        "[done] fetched=%s | matched=%s | title_skip=%s | exp_skip=%s | neg_skip=%s | new=%s | analyzed=%s | appended=%s | telegram=sent",
        stats.total_fetched,
        stats.matched_by_keywords,
        stats.skipped_by_title_prefilter,
        stats.skipped_by_experience_prefilter,
        stats.skipped_by_negative_prefilter,
        stats.new_vacancies,
        stats.analyzed_vacancies,
        stats.appended_vacancies,
    )


if __name__ == "__main__":
    run()
