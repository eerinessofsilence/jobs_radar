from __future__ import annotations

import re
from dataclasses import dataclass

from .models import AnalysisResult, RadarSettings, Vacancy
from .text import compact_text, truncate_text


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


STACK_CONTEXT_PATTERN = re.compile(
    r"\b(?:tech(?:nology)? stack|stack|requirements?|must have|skills?|"
    r"вимоги|навички|стек|технології)\b",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class KeywordMatchSummary:
    title_matches: list[str]
    description_matches: list[str]
    stack_matches: list[str]
    score: int

    @property
    def labels(self) -> list[str]:
        labels: list[str] = []
        labels.extend(f"title:{keyword}" for keyword in self.title_matches)
        labels.extend(f"stack:{keyword}" for keyword in self.stack_matches)
        labels.extend(f"description:{keyword}" for keyword in self.description_matches)
        return labels


def stack_context_text(description: str) -> str:
    paragraphs = [
        paragraph.strip() for paragraph in re.split(r"\n{2,}", description) if paragraph.strip()
    ]
    return "\n".join(
        paragraph for paragraph in paragraphs if STACK_CONTEXT_PATTERN.search(paragraph)
    )


def match_keyword_summary(vacancy: Vacancy, keywords: list[str]) -> KeywordMatchSummary:
    title_matches: list[str] = []
    description_matches: list[str] = []
    stack_matches: list[str] = []
    stack_text = stack_context_text(vacancy.description)

    for keyword in keywords:
        in_title = keyword_matches_text(keyword, vacancy.title)
        in_stack = bool(stack_text and keyword_matches_text(keyword, stack_text))
        in_description = keyword_matches_text(keyword, vacancy.description)

        if in_title:
            title_matches.append(keyword)
        elif in_stack:
            stack_matches.append(keyword)
        elif in_description:
            description_matches.append(keyword)

    score = len(title_matches) * 3 + len(stack_matches) * 2 + len(description_matches)
    return KeywordMatchSummary(
        title_matches=title_matches,
        description_matches=description_matches,
        stack_matches=stack_matches,
        score=score,
    )


def keyword_summary_is_relevant(summary: KeywordMatchSummary) -> bool:
    return bool(summary.title_matches or summary.stack_matches or summary.score >= 2)


EXPERIENCE_NUMBER_PATTERN = r"\d+(?:[.,]\d+)?"


EXPERIENCE_UNIT_PATTERN = (
    r"(?:years?|yrs?|y\.?o\.?e\.?|\u0440\u0456\u043a|\u0440\u043e\u043a(?:\u0438|\u0456\u0432|\u0443)?|"
    r"\u0433\u043e\u0434\u0430|\u043b\u0435\u0442)"
)


EXPERIENCE_NOUN_PATTERN = (
    r"(?:experience|\u0434\u043e\u0441\u0432\u0456\u0434|\u0434\u043e\u0441\u0432\u0456\u0434\u0443|"
    r"\u043e\u043f\u044b\u0442|\u043e\u043f\u044b\u0442\u0430)"
)


EXPERIENCE_REQUIREMENT_CONTEXT_PATTERN = re.compile(
    r"\b(?:experience|commercial|professional|hands-on|relevant|requirements?|"
    r"qualifications?|must|should|required|candidate|you\s+have|developer|engineer|"
    r"role|position|\u0434\u043e\u0441\u0432\u0456\u0434|\u0434\u043e\u0441\u0432\u0456\u0434\u0443|"
    r"\u043e\u043f\u044b\u0442|\u043e\u043f\u044b\u0442\u0430|\u0432\u0438\u043c\u043e\u0433\u0438|"
    r"\u0442\u0440\u0435\u0431\u043e\u0432\u0430\u043d\u0438\u044f|\u043f\u043e\u0442\u0440\u0456\u0431\u043d\u043e|"
    r"\u043d\u0435\u043e\u0431\u0445\u0456\u0434\u043d\u043e|\u0434\u043e\u043b\u0436\u0435\u043d)\b",
    flags=re.IGNORECASE,
)


EXPERIENCE_MORE_THAN_PATTERN = re.compile(
    rf"\b(?:more\s+than|over|above|greater\s+than|\u0431\u0456\u043b\u044c\u0448\u0435|"
    rf"\u043f\u043e\u043d\u0430\u0434|\u0431\u043e\u043b\u0435\u0435|\u0431\u043e\u043b\u044c\u0448\u0435|"
    rf"\u0441\u0432\u044b\u0448\u0435)\s+(?P<years>{EXPERIENCE_NUMBER_PATTERN})\s*\+?\s*"
    rf"{EXPERIENCE_UNIT_PATTERN}\b",
    flags=re.IGNORECASE,
)


EXPERIENCE_RANGE_PATTERN = re.compile(
    rf"\b(?P<lower>{EXPERIENCE_NUMBER_PATTERN})\s*(?:[-\u2013\u2014]|\bto\b|\b\u0434\u043e\b)\s*"
    rf"(?P<upper>{EXPERIENCE_NUMBER_PATTERN})\s*\+?\s*{EXPERIENCE_UNIT_PATTERN}\b",
    flags=re.IGNORECASE,
)


EXPERIENCE_REQUIREMENT_BEFORE_PATTERN = re.compile(
    rf"\b(?:requirements?|qualifications?|must(?:\s+have)?|should(?:\s+have)?|"
    rf"required|candidate|you\s+have|\u0432\u0438\u043c\u043e\u0433\u0438|"
    rf"\u0442\u0440\u0435\u0431\u043e\u0432\u0430\u043d\u0438\u044f)\b.{{0,120}}?"
    rf"\b(?P<years>{EXPERIENCE_NUMBER_PATTERN})\s*\+?\s*{EXPERIENCE_UNIT_PATTERN}\b",
    flags=re.IGNORECASE,
)


EXPERIENCE_MINIMUM_PATTERN = re.compile(
    rf"\b(?:at\s+least|minimum|min\.?|from|starting\s+from|not\s+less\s+than|"
    rf"no\s+less\s+than|\u0432\u0456\u0434|\u043e\u0442|\u043c\u0456\u043d\u0456\u043c\u0443\u043c|"
    rf"\u043c\u0438\u043d\u0438\u043c\u0443\u043c|\u043d\u0435\s+\u043c\u0435\u043d\u0448\u0435|"
    rf"\u043d\u0435\s+\u043c\u0435\u043d\u0435\u0435)\s+(?P<years>{EXPERIENCE_NUMBER_PATTERN})"
    rf"\s*\+?\s*{EXPERIENCE_UNIT_PATTERN}\b",
    flags=re.IGNORECASE,
)


EXPERIENCE_PLUS_PATTERN = re.compile(
    rf"\b(?P<years>{EXPERIENCE_NUMBER_PATTERN})\s*\+\s*{EXPERIENCE_UNIT_PATTERN}\b",
    flags=re.IGNORECASE,
)


EXPERIENCE_YEARS_OF_PATTERN = re.compile(
    rf"\b(?P<years>{EXPERIENCE_NUMBER_PATTERN})\s*{EXPERIENCE_UNIT_PATTERN}\b"
    rf"(?:\s+(?:of|with|in))?(?:\s+\w+){{0,5}}\s+{EXPERIENCE_NOUN_PATTERN}\b",
    flags=re.IGNORECASE,
)


EXPERIENCE_NOUN_BEFORE_PATTERN = re.compile(
    rf"\b{EXPERIENCE_NOUN_PATTERN}\b(?:\s+\w+){{0,6}}[\s:;\-]+"
    rf"(?P<years>{EXPERIENCE_NUMBER_PATTERN})\s*\+?\s*{EXPERIENCE_UNIT_PATTERN}\b",
    flags=re.IGNORECASE,
)


EXPERIENCE_STANDALONE_YEARS_PATTERN = re.compile(
    rf"\b(?P<years>{EXPERIENCE_NUMBER_PATTERN})\s*{EXPERIENCE_UNIT_PATTERN}\b",
    flags=re.IGNORECASE,
)


def parse_experience_years(value: str) -> float:
    return float(value.replace(",", "."))


def experience_years_exceed_limit(
    value: str,
    max_required_years: int,
    include_exact_limit: bool = False,
) -> bool:
    years = parse_experience_years(value)
    if years <= 0 or years > 40:
        return False
    if include_exact_limit:
        return years >= max_required_years
    return years > max_required_years


def has_experience_requirement_context(text: str, match: re.Match[str]) -> bool:
    window_start = max(0, match.start() - 160)
    window_end = min(len(text), match.end() + 160)
    window = text[window_start:window_end]
    return EXPERIENCE_REQUIREMENT_CONTEXT_PATTERN.search(window) is not None


def experience_prefilter_match_reason(
    match: re.Match[str],
    max_required_years: int,
) -> str:
    snippet = truncate_text(match.group(0), 80)
    return f"required_experience>{max_required_years}: {snippet}"


def experience_prefilter_reason(vacancy: Vacancy, radar: RadarSettings) -> str:
    if radar.max_required_years is None:
        return ""

    title = compact_text(vacancy.title)
    haystack = compact_text(f"{vacancy.title}\n{vacancy.description}")
    max_required_years = radar.max_required_years

    for match in EXPERIENCE_STANDALONE_YEARS_PATTERN.finditer(title):
        if experience_years_exceed_limit(match.group("years"), max_required_years):
            return experience_prefilter_match_reason(match, max_required_years)

    for match in EXPERIENCE_MORE_THAN_PATTERN.finditer(haystack):
        if not has_experience_requirement_context(haystack, match):
            continue
        if experience_years_exceed_limit(
            match.group("years"),
            max_required_years,
            include_exact_limit=True,
        ):
            return experience_prefilter_match_reason(match, max_required_years)

    for match in EXPERIENCE_RANGE_PATTERN.finditer(haystack):
        if not has_experience_requirement_context(haystack, match):
            continue
        if experience_years_exceed_limit(match.group("upper"), max_required_years):
            return experience_prefilter_match_reason(match, max_required_years)

    for pattern in (
        EXPERIENCE_REQUIREMENT_BEFORE_PATTERN,
        EXPERIENCE_MINIMUM_PATTERN,
        EXPERIENCE_PLUS_PATTERN,
        EXPERIENCE_YEARS_OF_PATTERN,
        EXPERIENCE_NOUN_BEFORE_PATTERN,
    ):
        for match in pattern.finditer(haystack):
            if not has_experience_requirement_context(haystack, match):
                continue
            if experience_years_exceed_limit(match.group("years"), max_required_years):
                return experience_prefilter_match_reason(match, max_required_years)

    return ""


def title_prefilter_reason(vacancy: Vacancy, radar: RadarSettings) -> str:
    if not radar.required_title_keywords:
        return ""

    for keyword in radar.required_title_keywords:
        if keyword_matches_text(keyword, vacancy.title):
            return ""

    return "missing_developer_title"


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


def filter_by_min_score(
    analyzed: list[tuple[Vacancy, AnalysisResult]],
    min_score: int,
) -> list[tuple[Vacancy, AnalysisResult]]:
    if min_score <= 0:
        return analyzed
    return [(vacancy, analysis) for vacancy, analysis in analyzed if analysis.score >= min_score]
