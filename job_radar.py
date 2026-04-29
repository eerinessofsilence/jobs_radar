from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import gspread
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from openai import OpenAI


LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

DEFAULT_DOU_RSS_URLS = ["https://jobs.dou.ua/vacancies/feeds/"]
DEFAULT_DJINNI_RSS_URLS = ["https://djinni.co/jobs/rss/"]

KEYWORDS = [
    "n8n",
    "Make",
    "Zapier",
    "automation",
    "AI automation",
    "OpenAI",
    "ChatGPT",
    "Telegram bot",
    "Google Sheets",
    "CRM automation",
    "API integration",
    "no-code",
    "low-code",
    "workflow automation",
    "business process automation",
]

CANDIDATE_PROFILE = """
I am looking for freelance, part-time, remote, or project-based work related to
n8n, Make, Zapier, AI automation, Telegram bots, Google Sheets, CRM integrations,
API integrations, and business process automation.

I prefer practical automation tasks and small or medium business workflows.
I do not want office-only jobs, unrelated sales jobs, or jobs that require many
years of enterprise software development unless automation is the main focus.
""".strip()

SHEET_HEADERS = [
    "Found Date",
    "Source",
    "Title",
    "Company",
    "Location",
    "Salary",
    "URL",
    "Published Date",
    "Matched Keywords",
    "Score",
    "Fit Reason",
    "Risks",
    "Generated Reply",
    "Status",
    "Applied",
    "Applied Date",
    "Notes",
]


@dataclass(slots=True)
class Config:
    openai_api_key: str
    google_sheet_id: str
    google_service_account_json: str
    telegram_bot_token: str
    telegram_chat_id: str
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
    new_vacancies: int = 0
    analyzed_vacancies: int = 0
    appended_vacancies: int = 0


def setup_logging() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format=LOG_FORMAT)


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


def load_config() -> Config:
    load_dotenv()

    return Config(
        openai_api_key=require_env("OPENAI_API_KEY"),
        google_sheet_id=require_env("GOOGLE_SHEET_ID"),
        google_service_account_json=require_env("GOOGLE_SERVICE_ACCOUNT_JSON"),
        telegram_bot_token=require_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=require_env("TELEGRAM_CHAT_ID"),
        dou_rss_urls=split_env_urls(os.getenv("DOU_RSS_URLS"), DEFAULT_DOU_RSS_URLS),
        djinni_rss_urls=split_env_urls(os.getenv("DJINNI_RSS_URLS"), DEFAULT_DJINNI_RSS_URLS),
        min_score=env_int("MIN_SCORE", 0, minimum=0),
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
            logging.info("Fetching %s RSS feed: %s", source, url)
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            logging.exception("Failed to fetch %s RSS feed %s: %s", source, url, exc)
            continue

        parsed_feed = feedparser.parse(response.content)
        if parsed_feed.bozo:
            logging.warning("Feedparser reported an issue for %s: %s", url, parsed_feed.bozo_exception)

        for entry in parsed_feed.entries:
            vacancy = normalize_entry(entry, source)
            if vacancy:
                vacancies.append(vacancy)

    return vacancies


def collect_rss_vacancies(config: Config) -> list[Vacancy]:
    vacancies = []
    vacancies.extend(fetch_rss_vacancies("DOU", config.dou_rss_urls))
    vacancies.extend(fetch_rss_vacancies("Djinni", config.djinni_rss_urls))
    return vacancies


def collect_email_alert_vacancies() -> list[Vacancy]:
    """Extension point for future Gmail export / email alert collectors."""
    return []


def match_keywords(vacancy: Vacancy, keywords: list[str]) -> list[str]:
    haystack = f"{vacancy.title}\n{vacancy.description}".lower()
    matches: list[str] = []

    for keyword in keywords:
        pattern = re.escape(keyword.lower())
        if keyword[0].isalnum():
            pattern = r"\b" + pattern
        if keyword[-1].isalnum():
            pattern = pattern + r"\b"

        if re.search(pattern, haystack, flags=re.IGNORECASE):
            matches.append(keyword)

    return matches


def ensure_sheet_headers(worksheet: gspread.Worksheet) -> list[str]:
    existing_headers = worksheet.row_values(1)
    if not existing_headers:
        end_column = column_letter(len(SHEET_HEADERS))
        worksheet.update(values=[SHEET_HEADERS], range_name=f"A1:{end_column}1")
        return SHEET_HEADERS

    missing_headers = [header for header in SHEET_HEADERS if header not in existing_headers]
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


def open_sheet(config: Config) -> tuple[gspread.Worksheet, list[str], set[str]]:
    client = build_gspread_client(config.google_service_account_json)
    worksheet = client.open_by_key(config.google_sheet_id).sheet1
    headers = ensure_sheet_headers(worksheet)
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


def parse_openai_json(content: str) -> AnalysisResult:
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
            score = max(0, min(100, score))
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


def vacancy_prompt(vacancy: Vacancy) -> str:
    description = vacancy.description[:6000]
    matched_keywords = ", ".join(vacancy.matched_keywords)

    return f"""
Candidate profile:
{CANDIDATE_PROFILE}

Keywords:
{", ".join(KEYWORDS)}

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

Analyze the vacancy for this candidate. Score from 0 to 100.
Prefer freelance, part-time, remote, project-based, practical automation work.
Penalize office-only roles, unrelated sales roles, and heavy enterprise software
development roles unless automation is clearly central.

Return only strict JSON with exactly these keys:
{{
  "score": 0,
  "fit_reason": "",
  "risks": "",
  "generated_reply": ""
}}

The generated_reply must be a short draft message only. Do not claim that an
application was sent.
""".strip()


def analyze_vacancy(client: OpenAI, model: str, vacancy: Vacancy) -> AnalysisResult:
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful job-fit analyst. Return valid JSON only. "
                        "Do not wrap JSON in markdown."
                    ),
                },
                {"role": "user", "content": vacancy_prompt(vacancy)},
            ],
        )
        content = response.choices[0].message.content or ""
        return parse_openai_json(content)
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
) -> list[Any]:
    values_by_header: dict[str, Any] = {
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
        "Status": "New",
        "Applied": False,
        "Applied Date": "",
        "Notes": "",
    }
    return [values_by_header.get(header, "") for header in headers]


def append_analyzed_vacancies(
    worksheet: gspread.Worksheet,
    headers: list[str],
    analyzed: list[tuple[Vacancy, AnalysisResult]],
) -> int:
    if not analyzed:
        return 0

    found_date = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [row_for_vacancy(vacancy, analysis, headers, found_date) for vacancy, analysis in analyzed]
    worksheet.append_rows(rows, value_input_option="RAW")
    return len(rows)


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
        f"New vacancies: {stats.new_vacancies}"
    )


def build_summary_message(
    stats: RunStats,
    analyzed: list[tuple[Vacancy, AnalysisResult]],
    min_score: int,
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
        f"New vacancies: {stats.new_vacancies}",
        f"Analyzed vacancies: {stats.analyzed_vacancies}",
        f"Appended vacancies: {stats.appended_vacancies}",
    ]

    if min_score > 0:
        lines.append(f"Top list minimum score: {min_score}")

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
    openai_client = OpenAI(api_key=config.openai_api_key)

    worksheet, headers, existing_urls = open_sheet(config)

    rss_vacancies = collect_rss_vacancies(config)
    email_vacancies = collect_email_alert_vacancies()
    fetched_vacancies = rss_vacancies + email_vacancies

    stats = RunStats(total_fetched=len(fetched_vacancies))

    matched_vacancies: list[Vacancy] = []
    for vacancy in fetched_vacancies:
        vacancy.matched_keywords = match_keywords(vacancy, KEYWORDS)
        if vacancy.matched_keywords:
            matched_vacancies.append(vacancy)

    stats.matched_by_keywords = len(matched_vacancies)
    new_vacancies = unique_new_vacancies(matched_vacancies, existing_urls)
    stats.new_vacancies = len(new_vacancies)

    if not new_vacancies:
        message = build_no_new_message(stats)
        send_telegram_message(config.telegram_bot_token, config.telegram_chat_id, message)
        logging.info("No new matching vacancies found.")
        return

    vacancies_to_analyze = new_vacancies[: config.max_jobs_per_run]
    if len(new_vacancies) > len(vacancies_to_analyze):
        logging.info(
            "Limiting analysis from %s to MAX_JOBS_PER_RUN=%s vacancies.",
            len(new_vacancies),
            config.max_jobs_per_run,
        )

    analyzed: list[tuple[Vacancy, AnalysisResult]] = []
    for vacancy in vacancies_to_analyze:
        logging.info("Analyzing vacancy: %s", vacancy.url)
        analysis = analyze_vacancy(openai_client, config.openai_model, vacancy)
        analyzed.append((vacancy, analysis))

    stats.analyzed_vacancies = len(analyzed)
    stats.appended_vacancies = append_analyzed_vacancies(worksheet, headers, analyzed)

    message = build_summary_message(stats, analyzed, config.min_score)
    send_telegram_message(config.telegram_bot_token, config.telegram_chat_id, message)
    logging.info("Job radar run completed. Appended %s vacancies.", stats.appended_vacancies)


if __name__ == "__main__":
    run()
