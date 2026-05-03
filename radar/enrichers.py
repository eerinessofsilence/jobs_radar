from __future__ import annotations

from .models import Vacancy


def enrich_vacancy(vacancy: Vacancy) -> Vacancy:
    """Extension point for source page enrichment after RSS normalization."""
    return vacancy


def enrich_vacancies(vacancies: list[Vacancy]) -> list[Vacancy]:
    return [enrich_vacancy(vacancy) for vacancy in vacancies]
