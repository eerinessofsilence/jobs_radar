from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import gspread
from google.oauth2.service_account import Credentials

from .models import AnalysisResult, Config, RadarSettings, Vacancy
from .urls import normalize_url


SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


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


def load_existing_urls(worksheet: gspread.Worksheet, headers: list[str]) -> set[str]:
    if "URL" not in headers:
        raise RuntimeError("Google Sheet must include a URL column.")

    url_column_index = headers.index("URL") + 1
    values = worksheet.col_values(url_column_index)
    return {normalize_url(value) for value in values[1:] if normalize_url(value)}


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


def open_sheet(config: Config) -> tuple[gspread.Worksheet, list[str], set[str]]:
    client = build_gspread_client(config.google_service_account_json)
    try:
        worksheet = client.open_by_key(config.google_sheet_id).sheet1
    except PermissionError as exc:
        raise RuntimeError(google_sheet_access_help(config)) from exc
    headers = ensure_sheet_headers(worksheet, config.radar.sheet_headers)
    existing_urls = load_existing_urls(worksheet, headers)
    return worksheet, headers, existing_urls


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
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(sheet_timezone(radar)).strftime(radar.found_date_format)


def format_found_date(radar: RadarSettings) -> str:
    return format_sheet_datetime(datetime.now(timezone.utc), radar)


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
    worksheet.append_rows(rows, value_input_option="RAW")
    return len(rows)
