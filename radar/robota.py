from __future__ import annotations

import logging
from typing import Any

import requests

from .extractors import clean_html
from .http_utils import retry_session
from .models import Config, Vacancy
from .text import compact_text

ROBOTA_ENDPOINT = "https://dracula.robota.ua/?q=getPublishedVacanciesList"
ROBOTA_SOURCE = "Robota.ua"
ROBOTA_PAGE_SIZE = 20

PUBLISHED_VACANCIES_QUERY = """
query getPublishedVacanciesList(
  $filter: PublishedVacanciesFilterInput!,
  $pagination: PublishedVacanciesPaginationInput!,
  $sort: PublishedVacanciesSortType!
) {
  publishedVacancies(filter: $filter, pagination: $pagination, sort: $sort) {
    totalCount
    items {
      id
      title
      description
      sortDate
      sortDateText
      salary {
        amount
        comment
        amountFrom
        amountTo
      }
      company {
        id
        name
      }
      city {
        id
        name
      }
      formApplyCustomUrl
      anonymous
      isActive
    }
  }
}
""".strip()


def robota_headers(config: Config) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) job-radar/1.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "uk",
        "Content-Type": "application/json",
        "Origin": "https://robota.ua",
        "Referer": "https://robota.ua/",
        "apollographql-client-name": "seeker-web",
    }
    if config.robota_cookie:
        try:
            config.robota_cookie.encode("latin-1")
        except UnicodeEncodeError as exc:
            raise RuntimeError(
                "ROBOTA_COOKIE contains a character that cannot be sent in an HTTP header. "
                "Copy the full Cookie request header from DevTools; do not use shortened "
                "values containing an ellipsis like '…'."
            ) from exc
        headers["Cookie"] = config.robota_cookie
    return headers


def robota_filter(keywords: str) -> dict[str, Any]:
    return {
        "keywords": keywords,
        "militaryVacancyDisplayMode": "APPENDED",
        "metroBranches": [],
        "additionalKeywords": "",
        "clusterKeywords": [],
        "location": {"longitude": 0, "latitude": 0},
        "salary": 0,
        "districtIds": [],
        "microDistrictIds": [],
        "scheduleIds": [],
        "rubrics": [],
        "showAgencies": True,
        "showOnlyNoCvApplyVacancies": False,
        "showOnlySpecialNeeds": False,
        "showOnlyWithoutExperience": False,
        "showOnlyNotViewed": False,
        "showWithoutSalary": True,
        "isReservation": False,
        "isForVeterans": False,
        "isOfficeWithGenerator": False,
        "isOfficeWithShelter": False,
        "gender": None,
        "branchIds": [],
    }


def robota_payload(keywords: str, page: int, sort: str = "BY_DATE") -> dict[str, Any]:
    return {
        "operationName": "getPublishedVacanciesList",
        "variables": {
            "pagination": {"count": ROBOTA_PAGE_SIZE, "page": page},
            "filter": robota_filter(keywords),
            "sort": sort,
        },
        "query": PUBLISHED_VACANCIES_QUERY,
    }


def unique_search_keywords(values: list[str]) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for value in values:
        keyword = compact_text(value)
        key = keyword.lower()
        if not keyword or key in seen:
            continue
        seen.add(key)
        keywords.append(keyword)
    return keywords


def robota_search_keywords(config: Config) -> list[str]:
    if not config.robota_keywords:
        return []

    keywords = list(config.robota_keywords)
    if config.robota_include_required_title_keywords:
        keywords.extend(config.radar.required_title_keywords)
    return unique_search_keywords(keywords)


def robota_salary(value: dict[str, Any] | None) -> str:
    if not isinstance(value, dict):
        return ""

    amount_from = value.get("amountFrom")
    amount_to = value.get("amountTo")
    amount = value.get("amount")
    comment = compact_text(str(value.get("comment") or ""))

    if amount_from and amount_to and amount_from != amount_to:
        salary = f"{amount_from}-{amount_to} UAH"
    elif amount_from or amount_to or amount:
        salary = f"{amount_from or amount_to or amount} UAH"
    else:
        salary = ""

    if salary and comment:
        return f"{salary} {comment}"
    return salary


def robota_url(item: dict[str, Any]) -> str:
    custom_url = item.get("formApplyCustomUrl")
    if isinstance(custom_url, str) and custom_url.strip().startswith("http"):
        return custom_url.strip()

    company = item.get("company") if isinstance(item.get("company"), dict) else {}
    company_id = company.get("id")
    vacancy_id = item.get("id")
    if company_id and vacancy_id:
        return f"https://robota.ua/company{company_id}/vacancy{vacancy_id}"
    if vacancy_id:
        return f"https://robota.ua/vacancy{vacancy_id}"
    return ""


def vacancy_from_robota_item(item: dict[str, Any], keywords: str) -> Vacancy | None:
    title = compact_text(str(item.get("title") or ""))
    url = robota_url(item)
    if not title or not url:
        return None

    company = item.get("company") if isinstance(item.get("company"), dict) else {}
    city = item.get("city") if isinstance(item.get("city"), dict) else {}
    description = clean_html(str(item.get("description") or ""))

    return Vacancy(
        source=ROBOTA_SOURCE,
        title=title,
        company=compact_text(str(company.get("name") or "")),
        location=compact_text(str(city.get("name") or "")),
        salary=robota_salary(item.get("salary")),
        url=url,
        published_date=str(item.get("sortDate") or item.get("sortDateText") or ""),
        description=description,
        metadata={
            "source": ROBOTA_SOURCE,
            "robota": {
                "id": item.get("id"),
                "company_id": company.get("id"),
                "city_id": city.get("id"),
                "keywords": keywords,
                "sort_date_text": item.get("sortDateText"),
            },
        },
    )


def collect_robota_vacancies(config: Config) -> list[Vacancy]:
    search_keywords = robota_search_keywords(config)
    if not search_keywords:
        return []

    vacancies: list[Vacancy] = []
    headers = robota_headers(config)

    with retry_session(total=2, backoff_factor=0.5, allowed_methods=("POST",)) as session:
        for keywords in search_keywords:
            for page in range(config.robota_pages_per_keyword):
                try:
                    response = session.post(
                        ROBOTA_ENDPOINT,
                        headers=headers,
                        json=robota_payload(keywords, page, config.robota_sort),
                        timeout=30,
                    )
                    if response.status_code >= 400:
                        logging.error(
                            "[fetch] Robota.ua status=%s body=%s",
                            response.status_code,
                            response.text[:1000],
                        )
                    response.raise_for_status()
                    payload = response.json()
                except requests.RequestException as exc:
                    logging.exception(
                        "[fetch] Robota.ua failed for %r page=%s: %s",
                        keywords,
                        page,
                        exc,
                    )
                    break
                except ValueError as exc:
                    logging.exception("[fetch] Robota.ua returned non-JSON response: %s", exc)
                    break

                errors = payload.get("errors")
                if errors:
                    logging.warning("[fetch] Robota.ua GraphQL errors: %s", errors)
                    break

                published = payload.get("data", {}).get("publishedVacancies", {})
                items = published.get("items") or []
                parsed_count = 0
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    vacancy = vacancy_from_robota_item(item, keywords)
                    if vacancy:
                        vacancies.append(vacancy)
                        parsed_count += 1

                logging.debug(
                    "[fetch] Robota.ua %r page=%s parsed %s vacancies",
                    keywords,
                    page,
                    parsed_count,
                )
                if len(items) < ROBOTA_PAGE_SIZE:
                    break

    return vacancies
