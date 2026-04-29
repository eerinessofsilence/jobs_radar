from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import gspread
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from openai import OpenAI, RateLimitError


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DEFAULT_CONFIG_PATH = "job_radar_config.json"
ANSI_RESET = "\033[0m"
LEVEL_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35;1m",
}
TAG_COLORS = {
    "[start]": "\033[36m",
    "[fetch]": "\033[34m",
    "[filter]": "\033[35m",
    "[analyze]": "\033[36m",
    "[result]": "\033[32m",
    "[sheet]": "\033[33m",
    "[done]": "\033[32;1m",
    "[openai]": "\033[31m",
    "[config]": "\033[36m",
    "[reason]": "\033[37m",
    "[risks]": "\033[33m",
    "[telegram]": "\033[32m",
}


@dataclass(slots=True)
class RadarSettings:
    candidate_profile: str
    target_experience_level: str
    candidate_years: str
    preferred_required_years: str
    max_required_years: int | None
    experience_guidance: str
    keywords: list[str]
    negative_prefilter_enabled: bool
    negative_title_keywords: list[str]
    negative_description_phrases: list[str]
    sheet_headers: list[str]
    default_dou_rss_urls: list[str]
    default_djinni_rss_urls: list[str]
    score_min: int
    score_max: int
    description_max_chars: int
    scoring_guidance: str
    scoring_rubric: str
    generated_reply_instruction: str
    openai_system_prompt: str
    row_defaults: dict[str, Any]


@dataclass(slots=True)
class Config:
    openai_api_key: str
    google_sheet_id: str
    google_service_account_json: str
    telegram_bot_token: str
    telegram_chat_id: str
    radar: RadarSettings
    dou_rss_urls: list[str]
    djinni_rss_urls: list[str]
    min_score: int = 0
    max_jobs_per_run: int = 20
    openai_model: str = "gpt-4o-mini"


@dataclass(slots=True)
class Vacancy:
    source: str
    title: str
    company: str
    location: str
    salary: str
    url: str
    published_date: str
    description: str
    matched_keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AnalysisResult:
    score: int
    fit_reason: str
    risks: str
    generated_reply: str


@dataclass(slots=True)
class RunStats:
    total_fetched: int = 0
    matched_by_keywords: int = 0
    skipped_by_negative_prefilter: int = 0
    new_vacancies: int = 0
    analyzed_vacancies: int = 0
    appended_vacancies: int = 0


class OpenAIQuotaError(RuntimeError):
    """Raised when OpenAI reports exhausted account quota."""


class ColorFormatter(logging.Formatter):
    def __init__(self, fmt: str, datefmt: str, use_color: bool) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        original_levelname = record.levelname
        original_msg = record.msg

        try:
            level_label = f"{original_levelname:<7}"
            if self.use_color:
                color = LEVEL_COLORS.get(original_levelname, "")
                record.levelname = f"{color}{level_label}{ANSI_RESET}" if color else level_label
                if isinstance(record.msg, str):
                    record.msg = color_log_tag(record.msg)
            else:
                record.levelname = level_label

            return super().format(record)
        finally:
            record.levelname = original_levelname
            record.msg = original_msg


def color_log_tag(message: str) -> str:
    for tag, color in TAG_COLORS.items():
        if message.startswith(tag):
            return f"{color}{tag}{ANSI_RESET}{message[len(tag):]}"
    return message


def should_color_logs() -> bool:
    if "NO_COLOR" in os.environ:
        return False

    mode = (os.getenv("LOG_COLOR", "auto").strip().lower() or "auto")
    if mode in {"1", "true", "yes", "on", "always"}:
        return True
    if mode in {"0", "false", "no", "off", "never"}:
        return False

    return sys.stderr.isatty() or os.getenv("GITHUB_ACTIONS") == "true"


def setup_logging() -> None:
    level_name = (os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO")
    level = getattr(logging, level_name, None)
    invalid_level_name = level_name if not isinstance(level, int) else ""
    if invalid_level_name:
        level = logging.INFO

    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter(LOG_FORMAT, "%Y-%m-%d %H:%M:%S", should_color_logs()))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    if invalid_level_name:
        logging.warning("[config] Invalid LOG_LEVEL=%r. Using INFO.", invalid_level_name)

    for logger_name in (
        "httpx",
        "httpcore",
        "openai",
        "urllib3",
        "google.auth.transport.requests",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


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


def log_run_start(config: Config) -> None:
    logging.info(
        "[start] model=%s | score=%s-%s | min=%s | max_jobs=%s | feeds=%s",
        config.openai_model,
        config.radar.score_min,
        config.radar.score_max,
        config.min_score,
        config.max_jobs_per_run,
        len(config.dou_rss_urls) + len(config.djinni_rss_urls),
    )


def split_env_urls(value: str | None, defaults: list[str]) -> list[str]:
    if not value:
        return defaults

    urls = [item.strip() for item in re.split(r"[\n,;]+", value) if item.strip()]
    return urls or defaults


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default

    try:
        value = int(raw_value)
    except ValueError:
        logging.warning("Invalid integer for %s=%r. Using default %s.", name, raw_value, default)
        return default

    if minimum is not None and value < minimum:
        logging.warning("%s must be at least %s. Using default %s.", name, minimum, default)
        return default

    return value


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def resolve_config_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Config file is not valid JSON: {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Config file must contain a JSON object: {path}")

    return data


def config_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Config key {key!r} must be a non-empty string.")
    return value.strip()


def config_int(data: dict[str, Any], key: str, default: int, minimum: int = 0) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or value < minimum:
        raise RuntimeError(f"Config key {key!r} must be an integer >= {minimum}.")
    return value


def config_string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        raise RuntimeError(f"Config key {key!r} must be a list of strings.")

    values = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if not values:
        raise RuntimeError(f"Config key {key!r} must contain at least one string.")
    return values


def optional_config_string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise RuntimeError(f"Config key {key!r} must be a list of strings.")
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def config_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Config key {key!r} must be a JSON object.")
    return value


def optional_config_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise RuntimeError(f"Config key {key!r} must be a JSON object.")
    return value


def optional_config_string(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key, default)
    if value == "":
        return default
    if not isinstance(value, str):
        raise RuntimeError(f"Config key {key!r} must be a string.")
    return value.strip()


def optional_config_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, int) or value < 0:
        raise RuntimeError(f"Config key {key!r} must be a non-negative integer.")
    return value


def optional_config_bool(data: dict[str, Any], key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"Config key {key!r} must be a boolean.")
    return value


def load_radar_settings(config_path: Path) -> RadarSettings:
    data = load_json_file(config_path)
    experience = optional_config_dict(data, "experience")
    negative_prefilter = optional_config_dict(data, "negative_prefilter")
    rss_urls = config_dict(data, "default_rss_urls")
    analysis = config_dict(data, "analysis")
    row_defaults = config_dict(data, "row_defaults")

    settings = RadarSettings(
        candidate_profile=config_string(data, "candidate_profile"),
        target_experience_level=optional_config_string(experience, "target_level"),
        candidate_years=optional_config_string(experience, "candidate_years"),
        preferred_required_years=optional_config_string(experience, "preferred_required_years"),
        max_required_years=optional_config_int(experience, "max_required_years"),
        experience_guidance=optional_config_string(experience, "guidance"),
        keywords=config_string_list(data, "keywords"),
        negative_prefilter_enabled=optional_config_bool(negative_prefilter, "enabled"),
        negative_title_keywords=optional_config_string_list(negative_prefilter, "title_keywords"),
        negative_description_phrases=optional_config_string_list(
            negative_prefilter,
            "description_phrases",
        ),
        sheet_headers=config_string_list(data, "sheet_headers"),
        default_dou_rss_urls=config_string_list(rss_urls, "dou"),
        default_djinni_rss_urls=config_string_list(rss_urls, "djinni"),
        score_min=config_int(analysis, "score_min", 1, minimum=0),
        score_max=config_int(analysis, "score_max", 10, minimum=1),
        description_max_chars=config_int(analysis, "description_max_chars", 6000, minimum=500),
        scoring_guidance=config_string(analysis, "scoring_guidance"),
        scoring_rubric=config_string(analysis, "scoring_rubric"),
        generated_reply_instruction=config_string(analysis, "generated_reply_instruction"),
        openai_system_prompt=config_string(analysis, "openai_system_prompt"),
        row_defaults=row_defaults,
    )

    if settings.score_max <= settings.score_min:
        raise RuntimeError("Config analysis.score_max must be greater than analysis.score_min.")

    if "URL" not in settings.sheet_headers:
        raise RuntimeError("Config sheet_headers must include a URL column.")

    return settings


def load_config() -> Config:
    load_dotenv()
    config_path = resolve_config_path(os.getenv("JOB_RADAR_CONFIG", DEFAULT_CONFIG_PATH).strip() or DEFAULT_CONFIG_PATH)
    radar = load_radar_settings(config_path)
    min_score = env_int("MIN_SCORE", 5, minimum=0)

    if min_score > radar.score_max:
        logging.warning(
            "MIN_SCORE=%s is higher than configured score_max=%s. No vacancies will be appended.",
            min_score,
            radar.score_max,
        )

    return Config(
        openai_api_key=require_env("OPENAI_API_KEY"),
        google_sheet_id=require_env("GOOGLE_SHEET_ID"),
        google_service_account_json=require_env("GOOGLE_SERVICE_ACCOUNT_JSON"),
        telegram_bot_token=require_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=require_env("TELEGRAM_CHAT_ID"),
        radar=radar,
        dou_rss_urls=split_env_urls(os.getenv("DOU_RSS_URLS"), radar.default_dou_rss_urls),
        djinni_rss_urls=split_env_urls(os.getenv("DJINNI_RSS_URLS"), radar.default_djinni_rss_urls),
        min_score=min_score,
        max_jobs_per_run=env_int("MAX_JOBS_PER_RUN", 20, minimum=1),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
    )


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


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    path = parts.path.rstrip("/") if parts.path != "/" else parts.path
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, urlencode(query), ""))


def clean_html(value: str) -> str:
    if not value:
        return ""

    soup = BeautifulSoup(value, "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def first_entry_value(entry: Any, keys: list[str]) -> str:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return clean_html(value)
    return ""


def entry_description(entry: Any) -> str:
    if entry.get("content"):
        content_values = [item.get("value", "") for item in entry.get("content", []) if item.get("value")]
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
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, IndexError, OverflowError):
        return str(raw_date)


def extract_company(entry: Any, title: str, description: str) -> str:
    company = first_entry_value(
        entry,
        [
            "company",
            "company_name",
            "djinni_company",
            "dou_company",
            "author",
            "creator",
            "dc_creator",
        ],
    )
    if company:
        return compact_text(company)

    title_match = re.search(r"\s+at\s+(.+)$", title, flags=re.IGNORECASE)
    if title_match and len(title_match.group(1)) <= 80:
        return compact_text(title_match.group(1))

    description_match = re.search(
        r"(?im)^\s*(?:company|\u043a\u043e\u043c\u043f\u0430\u043d\u0456\u044f|"
        r"\u043a\u043e\u043c\u043f\u0430\u043d\u0438\u044f)\s*:\s*(.+)$",
        description,
    )
    if description_match:
        return compact_text(description_match.group(1))[:120]

    return ""


def extract_location(entry: Any, description: str) -> str:
    location = first_entry_value(
        entry,
        [
            "location",
            "job_location",
            "djinni_location",
            "dou_location",
            "region",
        ],
    )
    if location:
        return compact_text(location)

    location_match = re.search(
        r"(?im)^\s*(?:location|\u043b\u043e\u043a\u0430\u0446\u0456\u044f|"
        r"\u043b\u043e\u043a\u0430\u0446\u0438\u044f|\u043c\u0456\u0441\u0442\u043e|"
        r"\u0433\u043e\u0440\u043e\u0434)\s*:\s*(.+)$",
        description,
    )
    if location_match:
        return compact_text(location_match.group(1))[:120]

    if re.search(
        r"\bremote\b|\b\u0432\u0456\u0434\u0434\u0430\u043b\u0435\u043d\u043e\b|\bremotely\b",
        description,
        flags=re.IGNORECASE,
    ):
        return "Remote"

    return ""


def extract_salary(entry: Any, description: str) -> str:
    salary = first_entry_value(entry, ["salary", "djinni_salary", "dou_salary"])
    if salary:
        return compact_text(salary)

    salary_line_match = re.search(
        r"(?im)^\s*(?:salary|compensation|\u0437\u0430\u0440\u043f\u043b\u0430\u0442\u0430|"
        r"\u0432\u0438\u043b\u043a\u0430)\s*:\s*(.+)$",
        description,
    )
    if salary_line_match:
        return compact_text(salary_line_match.group(1))[:120]

    salary_match = re.search(
        r"(?:\$|\u20ac|\u00a3)\s?\d[\d\s,]*(?:\s?[-\u2013]\s?"
        r"(?:\$|\u20ac|\u00a3)?\s?\d[\d\s,]*)?"
        r"(?:\s*(?:/|per)\s*(?:month|mo|hour|hr|year|yr))?",
        description,
        flags=re.IGNORECASE,
    )
    return compact_text(salary_match.group(0)) if salary_match else ""


def normalize_entry(entry: Any, source: str) -> Vacancy | None:
    title = compact_text(clean_html(entry.get("title", "")))
    url = normalize_url(entry.get("link", "") or entry.get("id", ""))
    description = entry_description(entry)

    if not title or not url:
        logging.debug("Skipping %s entry without title or URL.", source)
        return None

    return Vacancy(
        source=source,
        title=title,
        company=extract_company(entry, title, description),
        location=extract_location(entry, description),
        salary=extract_salary(entry, description),
        url=url,
        published_date=parse_published_date(entry),
        description=description,
    )


def fetch_rss_vacancies(source: str, urls: list[str]) -> list[Vacancy]:
    vacancies: list[Vacancy] = []
    headers = {"User-Agent": "job-radar/1.0 (+https://github.com/actions)"}

    for url in urls:
        try:
            logging.debug("[fetch] %s RSS: %s", source, url)
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            logging.exception("[fetch] %s RSS failed: %s", source, exc)
            continue

        parsed_feed = feedparser.parse(response.content)
        if parsed_feed.bozo:
            logging.warning("[fetch] %s RSS parse warning: %s", source, parsed_feed.bozo_exception)

        parsed_count = 0
        for entry in parsed_feed.entries:
            vacancy = normalize_entry(entry, source)
            if vacancy:
                vacancies.append(vacancy)
                parsed_count += 1
        logging.debug("[fetch] %s RSS parsed %s vacancies", source, parsed_count)

    return vacancies


def collect_rss_vacancies(config: Config) -> list[Vacancy]:
    dou_vacancies = fetch_rss_vacancies("DOU", config.dou_rss_urls)
    djinni_vacancies = fetch_rss_vacancies("Djinni", config.djinni_rss_urls)
    logging.info(
        "[fetch] DOU=%s | Djinni=%s | total=%s",
        len(dou_vacancies),
        len(djinni_vacancies),
        len(dou_vacancies) + len(djinni_vacancies),
    )
    return dou_vacancies + djinni_vacancies


def collect_email_alert_vacancies() -> list[Vacancy]:
    """Extension point for future Gmail export / email alert collectors."""
    return []


def keyword_matches_text(keyword: str, text: str) -> bool:
    if not keyword:
        return False

    pattern = re.escape(keyword.lower())
    if keyword[0].isalnum():
        pattern = r"\b" + pattern
    if keyword[-1].isalnum():
        pattern = pattern + r"\b"

    return re.search(pattern, text.lower(), flags=re.IGNORECASE) is not None


def match_keywords(vacancy: Vacancy, keywords: list[str]) -> list[str]:
    haystack = f"{vacancy.title}\n{vacancy.description}"
    return [keyword for keyword in keywords if keyword_matches_text(keyword, haystack)]


def negative_prefilter_reason(vacancy: Vacancy, radar: RadarSettings) -> str:
    if not radar.negative_prefilter_enabled:
        return ""

    for keyword in radar.negative_title_keywords:
        if keyword_matches_text(keyword, vacancy.title):
            return f"title:{keyword}"

    haystack = f"{vacancy.title}\n{vacancy.description}"
    for phrase in radar.negative_description_phrases:
        if keyword_matches_text(phrase, haystack):
            return f"text:{phrase}"

    return ""


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


def strip_markdown_fences(content: str) -> str:
    content = content.strip()
    fence_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL | re.IGNORECASE)
    return fence_match.group(1).strip() if fence_match else content


def extract_first_json_object(content: str) -> str | None:
    start = content.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(content)):
        char = content[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]

    return None


def parse_openai_json(content: str, score_min: int, score_max: int) -> AnalysisResult:
    cleaned = strip_markdown_fences(content)
    candidates = [cleaned]

    extracted = extract_first_json_object(cleaned)
    if extracted and extracted != cleaned:
        candidates.append(extracted)

    last_error = ""
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            score = int(parsed.get("score", 0))
            score = max(score_min, min(score_max, score))
            return AnalysisResult(
                score=score,
                fit_reason=str(parsed.get("fit_reason", "")).strip(),
                risks=str(parsed.get("risks", "")).strip(),
                generated_reply=str(parsed.get("generated_reply", "")).strip(),
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            last_error = str(exc)

    return AnalysisResult(
        score=0,
        fit_reason="",
        risks=f"OpenAI returned invalid JSON: {last_error}. Raw response: {content[:500]}",
        generated_reply="",
    )


def is_openai_insufficient_quota(exc: RateLimitError) -> bool:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("code") == "insufficient_quota":
            return True

    message = str(exc).lower()
    return "insufficient_quota" in message or "exceeded your current quota" in message


def experience_prompt_section(radar: RadarSettings) -> str:
    if not any(
        [
            radar.target_experience_level,
            radar.candidate_years,
            radar.preferred_required_years,
            radar.max_required_years is not None,
            radar.experience_guidance,
        ]
    ):
        return ""

    lines = ["Experience preference:"]
    if radar.target_experience_level:
        lines.append(f"Target level: {radar.target_experience_level}")
    if radar.candidate_years:
        lines.append(f"Candidate experience: {radar.candidate_years}")
    if radar.preferred_required_years:
        lines.append(f"Preferred vacancy requirement: {radar.preferred_required_years}")
    if radar.max_required_years is not None:
        lines.append(
            f"Penalize vacancies that require more than {radar.max_required_years} years of experience."
        )
    if radar.experience_guidance:
        lines.append(radar.experience_guidance)
    return "\n".join(lines)


def vacancy_prompt(vacancy: Vacancy, radar: RadarSettings) -> str:
    description = vacancy.description[: radar.description_max_chars]
    matched_keywords = ", ".join(vacancy.matched_keywords)
    experience_section = experience_prompt_section(radar)

    return f"""
Candidate profile:
{radar.candidate_profile}

{experience_section}

Keywords:
{", ".join(radar.keywords)}

Vacancy:
Source: {vacancy.source}
Title: {vacancy.title}
Company: {vacancy.company}
Location: {vacancy.location}
Salary: {vacancy.salary}
URL: {vacancy.url}
Published date: {vacancy.published_date}
Matched keywords: {matched_keywords}
Description:
{description}

Analyze the vacancy for this candidate. Score from {radar.score_min} to {radar.score_max}.
{radar.scoring_guidance}

Scoring rubric:
{radar.scoring_rubric}

Return only strict JSON with exactly these keys:
{{
  "score": {radar.score_min},
  "fit_reason": "",
  "risks": "",
  "generated_reply": ""
}}

{radar.generated_reply_instruction}
""".strip()


def analyze_vacancy(client: OpenAI, model: str, vacancy: Vacancy, radar: RadarSettings) -> AnalysisResult:
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": radar.openai_system_prompt,
                },
                {"role": "user", "content": vacancy_prompt(vacancy, radar)},
            ],
        )
        content = response.choices[0].message.content or ""
        return parse_openai_json(content, radar.score_min, radar.score_max)
    except RateLimitError as exc:
        if is_openai_insufficient_quota(exc):
            raise OpenAIQuotaError(
                "OpenAI quota is exhausted or billing is not active. "
                "Check OpenAI billing, usage limits, and the API key project."
            ) from exc

        logging.exception("OpenAI rate limit failed for %s", vacancy.url)
        return AnalysisResult(
            score=0,
            fit_reason="",
            risks=f"OpenAI rate limit failed: {exc}",
            generated_reply="",
        )
    except Exception as exc:
        logging.exception("OpenAI analysis failed for %s", vacancy.url)
        return AnalysisResult(
            score=0,
            fit_reason="",
            risks=f"OpenAI analysis failed: {exc}",
            generated_reply="",
        )


def row_for_vacancy(
    vacancy: Vacancy,
    analysis: AnalysisResult,
    headers: list[str],
    found_date: str,
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
            "Published Date": vacancy.published_date,
            "Matched Keywords": ", ".join(vacancy.matched_keywords),
            "Score": analysis.score,
            "Fit Reason": analysis.fit_reason,
            "Risks": analysis.risks,
            "Generated Reply": analysis.generated_reply,
        }
    )
    return [values_by_header.get(header, "") for header in headers]


def append_analyzed_vacancies(
    worksheet: gspread.Worksheet,
    headers: list[str],
    analyzed: list[tuple[Vacancy, AnalysisResult]],
    row_defaults: dict[str, Any],
) -> int:
    if not analyzed:
        return 0

    found_date = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [
        row_for_vacancy(vacancy, analysis, headers, found_date, row_defaults)
        for vacancy, analysis in analyzed
    ]
    worksheet.append_rows(rows, value_input_option="RAW")
    return len(rows)


def filter_by_min_score(
    analyzed: list[tuple[Vacancy, AnalysisResult]],
    min_score: int,
) -> list[tuple[Vacancy, AnalysisResult]]:
    if min_score <= 0:
        return analyzed
    return [(vacancy, analysis) for vacancy, analysis in analyzed if analysis.score >= min_score]


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
    for chunk in telegram_chunks(message):
        response = requests.post(
            api_url,
            json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
            timeout=30,
        )
        response.raise_for_status()


def build_no_new_message(stats: RunStats) -> str:
    return (
        "Job radar: no new matching vacancies found.\n"
        f"Total fetched: {stats.total_fetched}\n"
        f"Matched by keywords: {stats.matched_by_keywords}\n"
        f"Skipped by negative prefilter: {stats.skipped_by_negative_prefilter}\n"
        f"New vacancies: {stats.new_vacancies}"
    )


def build_summary_message(
    stats: RunStats,
    analyzed: list[tuple[Vacancy, AnalysisResult]],
    min_score: int,
    warning: str = "",
) -> str:
    eligible_top = [
        (vacancy, analysis)
        for vacancy, analysis in analyzed
        if analysis.score >= min_score
    ]
    top_vacancies = sorted(eligible_top, key=lambda item: item[1].score, reverse=True)[:5]

    lines = [
        "Job radar summary",
        f"Total fetched: {stats.total_fetched}",
        f"Matched by keywords: {stats.matched_by_keywords}",
        f"Skipped by negative prefilter: {stats.skipped_by_negative_prefilter}",
        f"New vacancies: {stats.new_vacancies}",
        f"Analyzed vacancies: {stats.analyzed_vacancies}",
        f"Appended vacancies: {stats.appended_vacancies}",
    ]

    if min_score > 0:
        lines.append(f"Minimum score to append/list: {min_score}")

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


def unique_new_vacancies(vacancies: list[Vacancy], existing_urls: set[str]) -> list[Vacancy]:
    new_vacancies: list[Vacancy] = []
    seen_urls = set(existing_urls)

    for vacancy in vacancies:
        if not vacancy.url or vacancy.url in seen_urls:
            continue

        seen_urls.add(vacancy.url)
        new_vacancies.append(vacancy)

    return new_vacancies


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
        reason = negative_prefilter_reason(vacancy, config.radar)
        if reason:
            stats.skipped_by_negative_prefilter += 1
            logging.debug("[filter] negative skip=%s | %s", reason, vacancy_label(vacancy))
            continue
        prefiltered_vacancies.append(vacancy)

    new_vacancies = unique_new_vacancies(prefiltered_vacancies, existing_urls)
    stats.new_vacancies = len(new_vacancies)
    skipped_existing = len(prefiltered_vacancies) - stats.new_vacancies

    logging.info(
        "[filter] fetched=%s | matched=%s | neg_skip=%s | new=%s | tracked/dup=%s",
        stats.total_fetched,
        stats.matched_by_keywords,
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
        config.radar.row_defaults,
    )

    message = build_summary_message(stats, analyzed, config.min_score, warning=warning)
    send_telegram_message(config.telegram_bot_token, config.telegram_chat_id, message)
    logging.info(
        "[done] fetched=%s | matched=%s | neg_skip=%s | new=%s | analyzed=%s | appended=%s | telegram=sent",
        stats.total_fetched,
        stats.matched_by_keywords,
        stats.skipped_by_negative_prefilter,
        stats.new_vacancies,
        stats.analyzed_vacancies,
        stats.appended_vacancies,
    )


if __name__ == "__main__":
    run()
