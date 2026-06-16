from __future__ import annotations

import logging

import feedparser
import requests

from .enrichers import enrich_vacancies
from .http_utils import retry_session
from .models import Config, Vacancy
from .normalizers import normalize_entry


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

    return enrich_vacancies(vacancies)


def collect_rss_vacancies(config: Config) -> list[Vacancy]:
    dou_vacancies = fetch_rss_vacancies("DOU", config.dou_rss_urls)
    djinni_vacancies = fetch_rss_vacancies("Djinni", config.djinni_rss_urls)
    indeed_vacancies = fetch_rss_vacancies("Indeed", config.indeed_rss_urls)
    return dou_vacancies + djinni_vacancies + indeed_vacancies


def collect_email_alert_vacancies() -> list[Vacancy]:
    """Extension point for future Gmail export / email alert collectors."""
    return []
