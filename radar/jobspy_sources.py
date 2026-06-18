from __future__ import annotations

import logging
import math
from typing import Any

from .models import Config, RadarSettings, Vacancy
from .text import compact_text

JOBSPY_SITE_SOURCES = {
    "indeed": "Indeed",
    "linkedin": "LinkedIn",
}
LINKEDIN_UNSUPPORTED_LOCATION_COUNTRIES = {"iceland"}


def unique_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = compact_text(value)
        key = term.lower()
        if not term or key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return terms


def profile_search_terms(radar: RadarSettings, mode: str) -> list[str]:
    terms: list[str] = []
    if mode in {"required-title", "both"}:
        terms.extend(radar.required_title_keywords)
    if mode in {"keywords", "both"}:
        terms.extend(radar.keywords)
    return unique_terms(terms)


def jobspy_search_terms(config: Config) -> list[str]:
    terms = profile_search_terms(config.radar, config.jobspy_profile_terms)
    if config.jobspy_max_terms > 0:
        terms = terms[: config.jobspy_max_terms]
    return terms


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def salary_from_row(row: dict[str, Any]) -> str:
    min_amount = row.get("min_amount")
    max_amount = row.get("max_amount")
    currency = compact_text(str(row.get("currency") or ""))
    interval = compact_text(str(row.get("interval") or ""))

    if min_amount and max_amount and min_amount != max_amount:
        salary = f"{min_amount:g}-{max_amount:g}"
    elif min_amount or max_amount:
        salary = f"{min_amount or max_amount:g}"
    else:
        return ""

    parts = [salary]
    if currency:
        parts.append(currency)
    if interval:
        parts.append(interval)
    return " ".join(parts)


def vacancy_from_jobspy_row(
    row: dict[str, Any],
    search_term: str,
    search_location: str,
) -> Vacancy | None:
    title = compact_text(str(row.get("title") or ""))
    url = compact_text(str(row.get("job_url") or row.get("job_url_direct") or ""))
    if not title or not url:
        return None

    site = compact_text(str(row.get("site") or "JobSpy"))
    source = JOBSPY_SITE_SOURCES.get(site.lower(), site)

    return Vacancy(
        source=source,
        title=title,
        company=compact_text(str(row.get("company") or "")),
        location=compact_text(str(row.get("location") or "")),
        salary=salary_from_row(row),
        url=url,
        published_date=str(row.get("date_posted") or ""),
        description=compact_text(str(row.get("description") or "")),
        metadata={
            "source": source,
            "jobspy": {
                "id": json_safe(row.get("id")),
                "site": site,
                "search_term": search_term,
                "search_location": search_location,
                "job_url_direct": json_safe(row.get("job_url_direct")),
                "is_remote": json_safe(row.get("is_remote")),
                "job_type": json_safe(row.get("job_type")),
            },
        },
    )


def scrape_jobspy_site(
    site: str,
    term: str,
    location: str,
    config: Config,
) -> list[Vacancy]:
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError(
            "python-jobspy is not installed. Install it with: "
            "venv/bin/python -m pip install -r requirements-jobspy.txt"
        ) from exc

    kwargs: dict[str, Any] = {}
    if site == "indeed":
        kwargs["country_indeed"] = config.jobspy_country_indeed

    jobs = scrape_jobs(
        site_name=[site],
        search_term=term,
        location=location,
        results_wanted=config.jobspy_results_per_term,
        verbose=config.jobspy_verbose,
        **kwargs,
    )

    vacancies: list[Vacancy] = []
    for row in jobs.to_dict("records"):
        vacancy = vacancy_from_jobspy_row(row, term, location)
        if vacancy:
            vacancies.append(vacancy)
    return vacancies


def is_linkedin_unsupported_country_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "invalid country string" in message


def should_skip_jobspy_site_location(site: str, location: str) -> bool:
    if site != "linkedin":
        return False
    return location.strip().lower() in LINKEDIN_UNSUPPORTED_LOCATION_COUNTRIES


def collect_jobspy_vacancies(config: Config) -> list[Vacancy]:
    if not config.jobspy_enabled:
        return []

    terms = jobspy_search_terms(config)
    if not terms:
        logging.warning("[fetch] JobSpy enabled but no search terms are configured.")
        return []

    vacancies: list[Vacancy] = []
    for term in terms:
        for location in config.jobspy_locations:
            for site in config.jobspy_sites:
                if should_skip_jobspy_site_location(site, location):
                    logging.warning(
                        "[fetch] JobSpy skipped %s | %r | %s: "
                        "LinkedIn does not support this country.",
                        site,
                        term,
                        location,
                    )
                    continue
                logging.info("[fetch] JobSpy %s | %r | %s", site, term, location)
                try:
                    site_vacancies = scrape_jobspy_site(site, term, location, config)
                except Exception as exc:
                    if site == "linkedin" and is_linkedin_unsupported_country_error(exc):
                        logging.warning(
                            "[fetch] JobSpy skipped linkedin | %r | %s: "
                            "unsupported country in LinkedIn result (%s).",
                            term,
                            location,
                            exc,
                        )
                        continue
                    logging.exception(
                        "[fetch] JobSpy failed for %s | %r | %s: %s",
                        site,
                        term,
                        location,
                        exc,
                    )
                    continue
                vacancies.extend(site_vacancies)

    return vacancies


def vacancy_to_dict(vacancy: Vacancy) -> dict[str, Any]:
    return {
        "source": vacancy.source,
        "title": vacancy.title,
        "company": vacancy.company,
        "location": vacancy.location,
        "salary": vacancy.salary,
        "url": vacancy.url,
        "published_date": vacancy.published_date,
        "description": vacancy.description,
        "metadata": vacancy.metadata,
    }
