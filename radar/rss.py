from __future__ import annotations

import logging
import re
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup

from .http_utils import retry_session
from .models import Config, Vacancy
from .text import compact_text
from .urls import normalize_url


def clean_html(value: str) -> str:
    if not value:
        return ""

    soup = BeautifulSoup(value, "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def first_entry_value(entry: Any, keys: list[str]) -> str:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return clean_html(value)
    return ""


def entry_description(entry: Any) -> str:
    if entry.get("content"):
        content_values = [
            item.get("value", "") for item in entry.get("content", []) if item.get("value")
        ]
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
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat(timespec="seconds")
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


SALARY_AMOUNT_PATTERN = re.compile(
    r"(?:(?:up to|to|\u0434\u043e)\s*)?"
    r"(?:\$|\u20ac|\u00a3)\s?\d[\d\s,.]*"
    r"(?:\s?[-\u2013\u2014]\s?(?:\$|\u20ac|\u00a3)?\s?\d[\d\s,.]*)?"
    r"(?:\s*(?:/|per)\s*(?:month|mo|hour|hr|year|yr))?",
    flags=re.IGNORECASE,
)


EXPLICIT_SALARY_AMOUNT_PATTERN = re.compile(
    r"(?:(?:up to|to|\u0434\u043e)\s*)?"
    r"(?:(?:\$|\u20ac|\u00a3)\s?)?\d[\d\s,.]*"
    r"(?:\s?[-\u2013\u2014]\s?(?:(?:\$|\u20ac|\u00a3)\s?)?\d[\d\s,.]*)?"
    r"(?:\s*(?:USD|EUR|GBP))?"
    r"(?:\s*(?:/|per)\s*(?:month|mo|hour|hr|year|yr))?",
    flags=re.IGNORECASE,
)


SALARY_CONTEXT_PATTERN = re.compile(
    r"\b(?:salary|compensation|rate|budget|pay|paid|monthly|hourly|"
    r"\u0437\u0430\u0440\u043f\u043b\u0430\u0442\u0430|\u0432\u0438\u043b\u043a\u0430)\b",
    flags=re.IGNORECASE,
)


def salary_amounts(value: str) -> list[float]:
    normalized = re.sub(r"(?<=\d)[\s,](?=\d)", "", value)
    return [float(number) for number in re.findall(r"\d+(?:\.\d+)?", normalized)]


def strip_salary_notes(value: str) -> str:
    value = re.sub(r"\s*\([^)]*\)", " ", value)
    value = re.sub(
        r"\b(?:depending on experience|based on experience|depending on skills|"
        r"gross|net|before taxes|after taxes)\b.*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return compact_text(value).strip(" ,.;:")


def salary_looks_plausible(value: str) -> bool:
    amounts = salary_amounts(value)
    if not amounts:
        return False

    highest_amount = max(amounts)
    if highest_amount > 300_000:
        return False

    lowered = value.lower()
    if highest_amount < 100 and not re.search(
        r"(?:\$|\u20ac|\u00a3|\busd\b|\beur\b|\bgbp\b|(?:/|per)\s*(?:hour|hr))",
        lowered,
    ):
        return False

    if re.search(r"(?:/|per)\s*(?:year|yr)", lowered) and highest_amount < 5_000:
        return False

    return True


def first_salary_amount(value: str, pattern: re.Pattern[str] = SALARY_AMOUNT_PATTERN) -> str:
    salary_match = pattern.search(strip_salary_notes(value))
    if not salary_match:
        return ""

    salary = compact_text(salary_match.group(0)).strip(" ,.;:")
    return salary if salary_looks_plausible(salary) else ""


def normalize_explicit_salary(value: str) -> str:
    salary = first_salary_amount(value, EXPLICIT_SALARY_AMOUNT_PATTERN)
    if salary:
        return salary

    return ""


def extract_salary(entry: Any, title: str, description: str) -> str:
    salary = first_entry_value(entry, ["salary", "djinni_salary", "dou_salary"])
    if salary:
        return normalize_explicit_salary(salary)

    salary = first_salary_amount(title)
    if salary:
        return salary

    salary_line_match = re.search(
        r"(?im)^\s*(?:salary|compensation|\u0437\u0430\u0440\u043f\u043b\u0430\u0442\u0430|"
        r"\u0432\u0438\u043b\u043a\u0430)\s*:\s*(.+)$",
        description,
    )
    if salary_line_match:
        salary = normalize_explicit_salary(salary_line_match.group(1))
        if salary:
            return salary

    for line in description.splitlines():
        if not SALARY_CONTEXT_PATTERN.search(line):
            continue

        salary = first_salary_amount(line)
        if salary:
            return salary

    return ""


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
        salary=extract_salary(entry, title, description),
        url=url,
        published_date=parse_published_date(entry),
        description=description,
    )


def fetch_rss_vacancies(source: str, urls: list[str]) -> list[Vacancy]:
    vacancies: list[Vacancy] = []
    headers = {"User-Agent": "job-radar/1.0 (+https://github.com/actions)"}

    with retry_session(total=3, backoff_factor=0.5, allowed_methods=("GET",)) as session:
        for url in urls:
            try:
                logging.debug("[fetch] %s RSS: %s", source, url)
                response = session.get(url, headers=headers, timeout=30)
                response.raise_for_status()
            except requests.RequestException as exc:
                logging.exception("[fetch] %s RSS failed: %s", source, exc)
                continue

            parsed_feed = feedparser.parse(response.content)
            if parsed_feed.bozo:
                logging.warning(
                    "[fetch] %s RSS parse warning: %s",
                    source,
                    parsed_feed.bozo_exception,
                )

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
