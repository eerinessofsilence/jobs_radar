from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound
from gspread.utils import ValueInputOption

from .models import AnalysisResult, Config, RadarSettings, RunStats, Vacancy
from .tech_stack import (
    TechMentionRecord,
    TechStat,
    build_tech_stats_from_records,
    tech_record_key,
    tech_records_for_vacancies,
)
from .urls import normalize_url

SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SEEN_WORKSHEET_TITLE = "Seen"
RUNS_WORKSHEET_TITLE = "Runs"
ANALYSIS_CACHE_WORKSHEET_TITLE = "AnalysisCache"
TECH_STATS_WORKSHEET_TITLE = "TechStats"
TECH_DB_WORKSHEET_TITLE = "TechDB"
SEEN_SHEET_HEADERS = [
    "Analyzed Date",
    "Source",
    "Title",
    "Company",
    "URL",
    "Score",
    "Decision",
    "Fit Reason",
    "Risks",
]
RUNS_SHEET_HEADERS = [
    "Run Date",
    "Model",
    "Sheet URL",
    "Total Fetched",
    "Missing Company",
    "Missing Salary",
    "Matched Keywords",
    "Title Skipped",
    "Experience Skipped",
    "Negative Skipped",
    "Tracked/Seen/Duplicate",
    "Similar Duplicate Skipped",
    "New Vacancies",
    "Queued For Analysis",
    "Skipped By Run Limit",
    "Local Pre-Score",
    "Cached Analysis",
    "Analyzed",
    "Appended",
    "Low Score Skipped",
    "Marked Seen",
    "Prompt Tokens",
    "Completion Tokens",
    "Total Tokens",
    "Estimated Cost USD",
    "Errors",
]
ANALYSIS_CACHE_HEADERS = [
    "Analyzed Date",
    "Model",
    "URL",
    "Source",
    "Title",
    "Company",
    "Score",
    "Fit Reason",
    "Risks",
    "Generated Reply",
    "Prompt Tokens",
    "Completion Tokens",
    "Total Tokens",
    "Estimated Cost USD",
    "Raw Response",
]
TECH_STATS_HEADERS = [
    "Run Date",
    "Category",
    "Technology",
    "Count",
    "Total Vacancies",
    "Percent",
    "Sources",
    "Top Titles",
]
TECH_DB_HEADERS = [
    "Found Date",
    "Source",
    "URL",
    "Title",
    "Company",
    "Category",
    "Technology",
]


@dataclass(slots=True)
class OpenedSheets:
    worksheet: gspread.Worksheet
    headers: list[str]
    existing_urls: set[str]
    seen_worksheet: gspread.Worksheet
    seen_headers: list[str]
    seen_urls: set[str]
    runs_worksheet: gspread.Worksheet
    runs_headers: list[str]
    analysis_cache_worksheet: gspread.Worksheet
    analysis_cache_headers: list[str]
    analysis_cache: dict[tuple[str, str], AnalysisResult]
    tech_db_worksheet: gspread.Worksheet
    tech_db_headers: list[str]
    tech_db_records: list[TechMentionRecord]
    tech_db_keys: set[tuple[str, str, str]]
    tech_stats_worksheet: gspread.Worksheet
    tech_stats_headers: list[str]


def parse_service_account_info(raw_json: str) -> dict[str, Any]:
    raw_json = raw_json.strip()
    if not raw_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is empty.")

    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        pass

    try:
        decoded = base64.b64decode(raw_json).decode("utf-8")
        return json.loads(decoded)
    except Exception as exc:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON must be a raw service account JSON object "
            "or a base64-encoded JSON object."
        ) from exc


def build_gspread_client(service_account_json: str) -> gspread.Client:
    service_account_info = parse_service_account_info(service_account_json)
    credentials = Credentials.from_service_account_info(service_account_info, scopes=SHEET_SCOPES)
    return gspread.authorize(credentials)


def ensure_sheet_headers(worksheet: gspread.Worksheet, sheet_headers: list[str]) -> list[str]:
    existing_headers = worksheet.row_values(1)
    if not existing_headers:
        end_column = column_letter(len(sheet_headers))
        worksheet.update(values=[sheet_headers], range_name=f"A1:{end_column}1")
        return sheet_headers

    missing_headers = [header for header in sheet_headers if header not in existing_headers]
    if missing_headers:
        updated_headers = existing_headers + missing_headers
        end_column = column_letter(len(updated_headers))
        worksheet.update(values=[updated_headers], range_name=f"A1:{end_column}1")
        logging.warning("Added missing Google Sheets headers: %s", ", ".join(missing_headers))
        return updated_headers

    return existing_headers


def column_letter(column_number: int) -> str:
    letters = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def load_urls_from_headers(worksheet: gspread.Worksheet, headers: list[str]) -> set[str]:
    if "URL" not in headers:
        raise RuntimeError(f"Google Sheet worksheet {worksheet.title!r} must include a URL column.")

    url_column_index = headers.index("URL") + 1
    values = worksheet.col_values(url_column_index)
    return {normalize_url(str(value)) for value in values[1:] if normalize_url(str(value))}


def load_existing_urls(worksheet: gspread.Worksheet, headers: list[str]) -> set[str]:
    return load_urls_from_headers(worksheet, headers)


def get_or_create_seen_worksheet(spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
    return get_or_create_worksheet(
        spreadsheet,
        SEEN_WORKSHEET_TITLE,
        len(SEEN_SHEET_HEADERS),
        "analyzed URL tracking",
    )


def get_or_create_runs_worksheet(spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
    return get_or_create_worksheet(
        spreadsheet,
        RUNS_WORKSHEET_TITLE,
        len(RUNS_SHEET_HEADERS),
        "run history",
    )


def get_or_create_analysis_cache_worksheet(spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
    return get_or_create_worksheet(
        spreadsheet,
        ANALYSIS_CACHE_WORKSHEET_TITLE,
        len(ANALYSIS_CACHE_HEADERS),
        "OpenAI analysis cache",
    )


def get_or_create_tech_stats_worksheet(spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
    return get_or_create_worksheet(
        spreadsheet,
        TECH_STATS_WORKSHEET_TITLE,
        len(TECH_STATS_HEADERS),
        "technology stack statistics",
    )


def get_or_create_tech_db_worksheet(spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
    return get_or_create_worksheet(
        spreadsheet,
        TECH_DB_WORKSHEET_TITLE,
        len(TECH_DB_HEADERS),
        "per-vacancy technology mentions",
    )


def get_or_create_worksheet(
    spreadsheet: gspread.Spreadsheet,
    title: str,
    columns: int,
    purpose: str,
) -> gspread.Worksheet:
    try:
        return spreadsheet.worksheet(title)
    except WorksheetNotFound:
        logging.info(
            "[sheet] Creating worksheet %r for %s.",
            title,
            purpose,
        )
        return spreadsheet.add_worksheet(
            title=title,
            rows=1000,
            cols=columns,
        )


def google_sheet_access_help(config: Config) -> str:
    try:
        service_account_info = parse_service_account_info(config.google_service_account_json)
    except RuntimeError:
        service_account_info = {}

    project_id = service_account_info.get("project_id", "<google-cloud-project-id>")
    client_email = service_account_info.get("client_email", "<service-account-email>")

    return (
        "Could not open the Google Sheet. Check Google Sheets setup:\n"
        f"1. Enable Google Sheets API for project {project_id}: "
        f"https://console.cloud.google.com/apis/library/sheets.googleapis.com?project={project_id}\n"
        "2. Wait a few minutes after enabling the API.\n"
        f"3. Share the Google Sheet with {client_email} as Editor.\n"
        "4. Verify GOOGLE_SHEET_ID is the spreadsheet ID, not the full Google Sheet URL."
    )


def open_sheet(config: Config) -> OpenedSheets:
    client = build_gspread_client(config.google_service_account_json)
    try:
        spreadsheet = client.open_by_key(config.google_sheet_id)
    except PermissionError as exc:
        raise RuntimeError(google_sheet_access_help(config)) from exc

    worksheet = spreadsheet.sheet1
    headers = ensure_sheet_headers(worksheet, config.radar.sheet_headers)
    existing_urls = load_existing_urls(worksheet, headers)
    seen_worksheet = get_or_create_seen_worksheet(spreadsheet)
    seen_headers = ensure_sheet_headers(seen_worksheet, SEEN_SHEET_HEADERS)
    seen_urls = load_urls_from_headers(seen_worksheet, seen_headers)
    runs_worksheet = get_or_create_runs_worksheet(spreadsheet)
    runs_headers = ensure_sheet_headers(runs_worksheet, RUNS_SHEET_HEADERS)
    analysis_cache_worksheet = get_or_create_analysis_cache_worksheet(spreadsheet)
    analysis_cache_headers = ensure_sheet_headers(
        analysis_cache_worksheet,
        ANALYSIS_CACHE_HEADERS,
    )
    analysis_cache = load_analysis_cache(analysis_cache_worksheet, analysis_cache_headers)
    tech_db_worksheet = get_or_create_tech_db_worksheet(spreadsheet)
    tech_db_headers = ensure_sheet_headers(tech_db_worksheet, TECH_DB_HEADERS)
    tech_db_records = load_tech_db_records(tech_db_worksheet, tech_db_headers)
    tech_db_keys = {tech_record_key(record) for record in tech_db_records}
    tech_stats_worksheet = get_or_create_tech_stats_worksheet(spreadsheet)
    tech_stats_headers = ensure_sheet_headers(tech_stats_worksheet, TECH_STATS_HEADERS)
    return OpenedSheets(
        worksheet=worksheet,
        headers=headers,
        existing_urls=existing_urls,
        seen_worksheet=seen_worksheet,
        seen_headers=seen_headers,
        seen_urls=seen_urls,
        runs_worksheet=runs_worksheet,
        runs_headers=runs_headers,
        analysis_cache_worksheet=analysis_cache_worksheet,
        analysis_cache_headers=analysis_cache_headers,
        analysis_cache=analysis_cache,
        tech_db_worksheet=tech_db_worksheet,
        tech_db_headers=tech_db_headers,
        tech_db_records=tech_db_records,
        tech_db_keys=tech_db_keys,
        tech_stats_worksheet=tech_stats_worksheet,
        tech_stats_headers=tech_stats_headers,
    )


def row_for_vacancy(
    vacancy: Vacancy,
    analysis: AnalysisResult,
    headers: list[str],
    found_date: str,
    radar: RadarSettings,
    row_defaults: dict[str, Any],
) -> list[Any]:
    values_by_header: dict[str, Any] = dict(row_defaults)
    values_by_header.update(
        {
            "Found Date": found_date,
            "Source": vacancy.source,
            "Title": vacancy.title,
            "Company": vacancy.company,
            "Location": vacancy.location,
            "Salary": vacancy.salary,
            "URL": vacancy.url,
            "Published Date": format_published_date(vacancy.published_date, radar),
            "Matched Keywords": ", ".join(vacancy.matched_keywords),
            "Score": analysis.score,
            "Fit Reason": analysis.fit_reason,
            "Risks": analysis.risks,
            "Generated Reply": analysis.generated_reply,
        }
    )
    return [values_by_header.get(header, "") for header in headers]


def sheet_timezone(radar: RadarSettings) -> ZoneInfo:
    try:
        return ZoneInfo(radar.found_date_timezone)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(
            f"Config found_date_timezone={radar.found_date_timezone!r} is not a valid timezone."
        ) from exc


def format_sheet_datetime(value: datetime, radar: RadarSettings) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(sheet_timezone(radar)).strftime(radar.found_date_format)


def format_found_date(radar: RadarSettings) -> str:
    return format_sheet_datetime(datetime.now(UTC), radar)


def format_published_date(published_date: str, radar: RadarSettings) -> str:
    if not published_date:
        return ""

    try:
        parsed = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
    except ValueError:
        return published_date

    return format_sheet_datetime(parsed, radar)


def append_analyzed_vacancies(
    worksheet: gspread.Worksheet,
    headers: list[str],
    analyzed: list[tuple[Vacancy, AnalysisResult]],
    radar: RadarSettings,
    row_defaults: dict[str, Any],
) -> int:
    if not analyzed:
        return 0

    found_date = format_found_date(radar)
    rows = [
        row_for_vacancy(vacancy, analysis, headers, found_date, radar, row_defaults)
        for vacancy, analysis in analyzed
    ]
    worksheet.append_rows(rows, value_input_option=ValueInputOption.raw)
    return len(rows)


def seen_decision(analysis: AnalysisResult, min_score: int) -> str:
    if analysis.score <= 0:
        return "Analysis failed"
    if min_score > 0 and analysis.score < min_score:
        return f"Below min score ({min_score})"
    return "Appended"


def seen_row_for_vacancy(
    vacancy: Vacancy,
    analysis: AnalysisResult,
    headers: list[str],
    analyzed_date: str,
    min_score: int,
) -> list[Any]:
    values_by_header: dict[str, Any] = {
        "Analyzed Date": analyzed_date,
        "Source": vacancy.source,
        "Title": vacancy.title,
        "Company": vacancy.company,
        "URL": vacancy.url,
        "Score": analysis.score,
        "Decision": seen_decision(analysis, min_score),
        "Fit Reason": analysis.fit_reason,
        "Risks": analysis.risks,
    }
    return [values_by_header.get(header, "") for header in headers]


def append_seen_vacancies(
    worksheet: gspread.Worksheet,
    headers: list[str],
    analyzed: list[tuple[Vacancy, AnalysisResult]],
    radar: RadarSettings,
    min_score: int,
) -> int:
    successful_analysis = [
        (vacancy, analysis) for vacancy, analysis in analyzed if analysis.score > 0
    ]
    if not successful_analysis:
        return 0

    analyzed_date = format_found_date(radar)
    rows = [
        seen_row_for_vacancy(vacancy, analysis, headers, analyzed_date, min_score)
        for vacancy, analysis in successful_analysis
    ]
    worksheet.append_rows(rows, value_input_option=ValueInputOption.raw)
    return len(rows)


def parse_int_cell(value: Any) -> int:
    try:
        return int(float(str(value).strip() or "0"))
    except (TypeError, ValueError):
        return 0


def parse_float_cell(value: Any) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_analysis_cache(
    worksheet: gspread.Worksheet,
    headers: list[str],
) -> dict[tuple[str, str], AnalysisResult]:
    if "URL" not in headers or "Model" not in headers:
        return {}

    rows = worksheet.get_all_values()
    cache: dict[tuple[str, str], AnalysisResult] = {}
    for row in rows[1:]:
        values = {
            header: row[index] if index < len(row) else "" for index, header in enumerate(headers)
        }
        url = normalize_url(str(values.get("URL", "")))
        model = str(values.get("Model", "")).strip()
        score = parse_int_cell(values.get("Score", ""))
        if not url or not model or score <= 0:
            continue

        cache[(model, url)] = AnalysisResult(
            score=score,
            fit_reason=str(values.get("Fit Reason", "")),
            risks=str(values.get("Risks", "")),
            generated_reply=str(values.get("Generated Reply", "")),
            prompt_tokens=parse_int_cell(values.get("Prompt Tokens", "")),
            completion_tokens=parse_int_cell(values.get("Completion Tokens", "")),
            total_tokens=parse_int_cell(values.get("Total Tokens", "")),
            estimated_cost_usd=parse_float_cell(values.get("Estimated Cost USD", "")),
            raw_response=str(values.get("Raw Response", "")),
            source="cache",
        )
    return cache


def analysis_cache_key(model: str, vacancy: Vacancy) -> tuple[str, str]:
    return (model, normalize_url(vacancy.url))


def analysis_cache_row(
    vacancy: Vacancy,
    analysis: AnalysisResult,
    headers: list[str],
    analyzed_date: str,
    model: str,
) -> list[Any]:
    values_by_header: dict[str, Any] = {
        "Analyzed Date": analyzed_date,
        "Model": model,
        "URL": vacancy.url,
        "Source": vacancy.source,
        "Title": vacancy.title,
        "Company": vacancy.company,
        "Score": analysis.score,
        "Fit Reason": analysis.fit_reason,
        "Risks": analysis.risks,
        "Generated Reply": analysis.generated_reply,
        "Prompt Tokens": analysis.prompt_tokens,
        "Completion Tokens": analysis.completion_tokens,
        "Total Tokens": analysis.total_tokens,
        "Estimated Cost USD": (
            round(analysis.estimated_cost_usd, 6) if analysis.estimated_cost_usd is not None else ""
        ),
        "Raw Response": analysis.raw_response,
    }
    return [values_by_header.get(header, "") for header in headers]


def append_analysis_cache_rows(
    worksheet: gspread.Worksheet,
    headers: list[str],
    analyzed: list[tuple[Vacancy, AnalysisResult]],
    radar: RadarSettings,
    model: str,
) -> int:
    cacheable = [
        (vacancy, analysis)
        for vacancy, analysis in analyzed
        if analysis.score > 0 and analysis.source == "openai"
    ]
    if not cacheable:
        return 0

    analyzed_date = format_found_date(radar)
    rows = [
        analysis_cache_row(vacancy, analysis, headers, analyzed_date, model)
        for vacancy, analysis in cacheable
    ]
    worksheet.append_rows(rows, value_input_option=ValueInputOption.raw)
    return len(rows)


def tech_db_record_from_values(values: dict[str, Any]) -> TechMentionRecord | None:
    url = str(values.get("URL", "")).strip()
    category = str(values.get("Category", "")).strip()
    technology = str(values.get("Technology", "")).strip()
    if not url or not category or not technology:
        return None
    return TechMentionRecord(
        found_date=str(values.get("Found Date", "")),
        source=str(values.get("Source", "")),
        url=url,
        title=str(values.get("Title", "")),
        company=str(values.get("Company", "")),
        category=category,
        technology=technology,
    )


def load_tech_db_records(
    worksheet: gspread.Worksheet,
    headers: list[str],
) -> list[TechMentionRecord]:
    if "URL" not in headers or "Category" not in headers or "Technology" not in headers:
        return []

    records: list[TechMentionRecord] = []
    rows = worksheet.get_all_values()
    for row in rows[1:]:
        values = {
            header: row[index] if index < len(row) else "" for index, header in enumerate(headers)
        }
        record = tech_db_record_from_values(values)
        if record:
            records.append(record)
    return records


def tech_db_row(record: TechMentionRecord, headers: list[str]) -> list[Any]:
    values_by_header: dict[str, Any] = {
        "Found Date": record.found_date,
        "Source": record.source,
        "URL": record.url,
        "Title": record.title,
        "Company": record.company,
        "Category": record.category,
        "Technology": record.technology,
    }
    return [values_by_header.get(header, "") for header in headers]


def append_tech_db_records(
    worksheet: gspread.Worksheet,
    headers: list[str],
    existing_keys: set[tuple[str, str, str]],
    vacancies: list[Vacancy],
    radar: RadarSettings,
) -> tuple[int, list[TechMentionRecord]]:
    if not vacancies:
        return 0, []

    found_date = format_found_date(radar)
    records = tech_records_for_vacancies(vacancies, found_date)
    new_records: list[TechMentionRecord] = []
    for record in records:
        key = tech_record_key(record)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        new_records.append(record)

    if not new_records:
        return 0, []

    rows = [tech_db_row(record, headers) for record in new_records]
    worksheet.append_rows(rows, value_input_option=ValueInputOption.raw)
    return len(rows), new_records


def tech_stats_row(stat: TechStat, headers: list[str], run_date: str) -> list[Any]:
    values_by_header: dict[str, Any] = {
        "Run Date": run_date,
        "Category": stat.category,
        "Technology": stat.technology,
        "Count": stat.count,
        "Total Vacancies": stat.total_vacancies,
        "Percent": round(stat.percent, 1),
        "Sources": ", ".join(sorted(stat.sources)),
        "Top Titles": " | ".join(stat.top_titles),
    }
    return [values_by_header.get(header, "") for header in headers]


def append_tech_stats(
    worksheet: gspread.Worksheet,
    headers: list[str],
    records: list[TechMentionRecord],
    radar: RadarSettings,
) -> int:
    worksheet.clear()
    if not records:
        end_column = column_letter(len(headers))
        worksheet.update(values=[headers], range_name=f"A1:{end_column}1")
        return 0

    stats = build_tech_stats_from_records(records)
    if not stats:
        end_column = column_letter(len(headers))
        worksheet.update(values=[headers], range_name=f"A1:{end_column}1")
        return 0

    run_date = format_found_date(radar)
    rows = [tech_stats_row(stat, headers, run_date) for stat in stats]
    end_column = column_letter(len(headers))
    end_row = len(rows) + 1
    worksheet.update(
        values=[headers, *rows],
        range_name=f"A1:{end_column}{end_row}",
        value_input_option=ValueInputOption.raw,
    )
    return len(rows)


def google_sheet_url(config: Config) -> str:
    return f"https://docs.google.com/spreadsheets/d/{config.google_sheet_id}/edit"


def run_summary_row(
    stats: RunStats,
    headers: list[str],
    run_date: str,
    config: Config,
    error: str = "",
) -> list[Any]:
    values_by_header: dict[str, Any] = {
        "Run Date": run_date,
        "Model": config.openai_model,
        "Sheet URL": google_sheet_url(config),
        "Total Fetched": stats.total_fetched,
        "Missing Company": stats.missing_company,
        "Missing Salary": stats.missing_salary,
        "Matched Keywords": stats.matched_by_keywords,
        "Title Skipped": stats.skipped_by_title_prefilter,
        "Experience Skipped": stats.skipped_by_experience_prefilter,
        "Negative Skipped": stats.skipped_by_negative_prefilter,
        "Tracked/Seen/Duplicate": stats.skipped_existing_vacancies,
        "Similar Duplicate Skipped": stats.skipped_similar_vacancies,
        "New Vacancies": stats.new_vacancies,
        "Queued For Analysis": stats.queued_for_analysis,
        "Skipped By Run Limit": stats.skipped_by_run_limit,
        "Local Pre-Score": stats.local_prescore_vacancies,
        "Cached Analysis": stats.cached_analysis_vacancies,
        "Analyzed": stats.analyzed_vacancies,
        "Appended": stats.appended_vacancies,
        "Low Score Skipped": stats.skipped_low_score,
        "Marked Seen": stats.seen_vacancies,
        "Prompt Tokens": stats.prompt_tokens,
        "Completion Tokens": stats.completion_tokens,
        "Total Tokens": stats.total_tokens,
        "Estimated Cost USD": (
            round(stats.estimated_cost_usd, 6) if stats.estimated_cost_usd is not None else ""
        ),
        "Errors": error,
    }
    return [values_by_header.get(header, "") for header in headers]


def append_run_summary(
    worksheet: gspread.Worksheet,
    headers: list[str],
    stats: RunStats,
    config: Config,
    error: str = "",
) -> int:
    row = run_summary_row(
        stats,
        headers,
        format_found_date(config.radar),
        config,
        error=error,
    )
    worksheet.append_rows([row], value_input_option=ValueInputOption.raw)
    return 1
