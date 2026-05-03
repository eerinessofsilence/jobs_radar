from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from .text import compact_text


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


TRAILING_TITLE_CONTEXT_PATTERN = re.compile(
    r"^(?:"
    r"(?:віддалено|remote|remotely|office|hybrid|гібрид|офіс|офис|"
    r"київ|kyiv|kiev|львів|lviv|харків|kharkiv|одеса|odesa|дніпро|dnipro|"
    r"україна|ukraine|europe|eu|poland|warsaw|польща|за кордоном)"
    r"|(?:\$|\u20ac|\u00a3|\d).*)$",
    flags=re.IGNORECASE,
)


def strip_title_context(value: str) -> str:
    parts = [part.strip() for part in compact_text(value).split(",") if part.strip()]
    while len(parts) > 1 and TRAILING_TITLE_CONTEXT_PATTERN.search(parts[-1]):
        parts.pop()
    return compact_text(", ".join(parts)).strip(" ,;:")


def extract_company_from_title(title: str) -> str:
    title_match = re.search(r"\s+(at|[ву])\s+(.+)$", title, flags=re.IGNORECASE)
    if not title_match:
        return ""

    marker = title_match.group(1).lower()
    raw_company = title_match.group(2)
    if marker in {"в", "у"}:
        raw_company = raw_company.split(",", 1)[0]

    company = strip_title_context(raw_company)
    if company and len(company) <= 120:
        return company

    return ""


def extract_company_from_description_intro(description: str) -> str:
    first_lines = [compact_text(line) for line in description.splitlines()[:5]]
    intro = next((line for line in first_lines if line), "")
    if not intro:
        return ""

    intro_match = re.match(
        r"^([A-ZА-ЯІЇЄҐ][\wА-Яа-яІіЇїЄєҐґ&.'’ -]{1,80}?)\s+"
        r"(?:[-\u2013\u2014]|is|are|це)\s+",
        intro,
        flags=re.IGNORECASE,
    )
    if intro_match:
        return compact_text(intro_match.group(1)).strip(" ,.;:")

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


class VacancyExtractor:
    source = "Generic"

    def extract_company(self, entry: Any, title: str, description: str) -> str:
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

        company = extract_company_from_title(title)
        if company:
            return company

        description_match = re.search(
            r"(?im)^\s*(?:company|\u043a\u043e\u043c\u043f\u0430\u043d\u0456\u044f|"
            r"\u043a\u043e\u043c\u043f\u0430\u043d\u0438\u044f)\s*:\s*(.+)$",
            description,
        )
        if description_match:
            return compact_text(description_match.group(1))[:120]

        return extract_company_from_description_intro(description)[:120]

    def extract_location(self, entry: Any, description: str) -> str:
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

    def extract_salary(self, entry: Any, title: str, description: str) -> str:
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


class DouExtractor(VacancyExtractor):
    source = "DOU"

    def extract_company(self, entry: Any, title: str, description: str) -> str:
        company = first_entry_value(entry, ["dou_company", "company", "company_name"])
        if company:
            return compact_text(company)

        company = extract_company_from_title(title)
        if company:
            return company

        return super().extract_company(entry, title, description)


class DjinniExtractor(VacancyExtractor):
    source = "Djinni"

    def extract_company(self, entry: Any, title: str, description: str) -> str:
        company = first_entry_value(entry, ["djinni_company", "company", "company_name"])
        if company:
            return compact_text(company)

        return super().extract_company(entry, title, description)


EXTRACTORS_BY_SOURCE: dict[str, VacancyExtractor] = {
    DouExtractor.source: DouExtractor(),
    DjinniExtractor.source: DjinniExtractor(),
}


def extractor_for_source(source: str) -> VacancyExtractor:
    return EXTRACTORS_BY_SOURCE.get(source, VacancyExtractor())


def extract_company(entry: Any, title: str, description: str, source: str = "Generic") -> str:
    return extractor_for_source(source).extract_company(entry, title, description)


def extract_location(entry: Any, description: str, source: str = "Generic") -> str:
    return extractor_for_source(source).extract_location(entry, description)


def extract_salary(
    entry: Any,
    title: str,
    description: str,
    source: str = "Generic",
) -> str:
    return extractor_for_source(source).extract_salary(entry, title, description)
