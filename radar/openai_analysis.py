from __future__ import annotations

import json
import logging
import re

from openai import OpenAI, RateLimitError

from .models import AnalysisResult, OpenAIQuotaError, RadarSettings, Vacancy

DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 60
DEFAULT_MAX_COMPLETION_TOKENS = 700


def strip_markdown_fences(content: str) -> str:
    content = content.strip()
    fence_match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
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


def estimate_openai_cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    input_cost_per_1m: float | None,
    output_cost_per_1m: float | None,
) -> float | None:
    if input_cost_per_1m is None or output_cost_per_1m is None:
        return None
    return (prompt_tokens / 1_000_000 * input_cost_per_1m) + (
        completion_tokens / 1_000_000 * output_cost_per_1m
    )


def openai_usage_value(usage: object, name: str) -> int:
    if isinstance(usage, dict):
        value = usage.get(name, 0)
    else:
        value = getattr(usage, name, 0)

    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def attach_openai_usage(
    analysis: AnalysisResult,
    usage: object | None,
    input_cost_per_1m: float | None,
    output_cost_per_1m: float | None,
) -> AnalysisResult:
    if usage is None:
        return analysis

    analysis.prompt_tokens = openai_usage_value(usage, "prompt_tokens")
    analysis.completion_tokens = openai_usage_value(usage, "completion_tokens")
    analysis.total_tokens = (
        openai_usage_value(usage, "total_tokens")
        or analysis.prompt_tokens + analysis.completion_tokens
    )
    analysis.estimated_cost_usd = estimate_openai_cost_usd(
        analysis.prompt_tokens,
        analysis.completion_tokens,
        input_cost_per_1m,
        output_cost_per_1m,
    )
    return analysis


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
            "Hard limit: vacancies that require more than "
            f"{radar.max_required_years} years of experience are not suitable and must receive "
            f"the minimum score {radar.score_min}."
        )
    if radar.experience_guidance:
        lines.append(radar.experience_guidance)
    return "\n".join(lines)


DESCRIPTION_SECTION_PATTERN = re.compile(
    r"\b(?:requirements?|responsibilit(?:y|ies)|what you'?ll do|tasks?|"
    r"tech(?:nology)? stack|stack|format|work format|location|salary|compensation|"
    r"вимоги|обов.?язки|задач[іи]|технології|стек|формат|локація|"
    r"зарплата|компенсація|оплата)\b",
    flags=re.IGNORECASE,
)


def smart_description_excerpt(description: str, max_chars: int) -> str:
    if len(description) <= max_chars:
        return description

    paragraphs = [
        paragraph.strip() for paragraph in re.split(r"\n{2,}", description) if paragraph.strip()
    ]
    if not paragraphs:
        return description[:max_chars]

    selected: list[str] = []
    used_indexes: set[int] = set()
    for index, paragraph in enumerate(paragraphs[:2]):
        selected.append(paragraph)
        used_indexes.add(index)

    for index, paragraph in enumerate(paragraphs):
        if index in used_indexes:
            continue
        if DESCRIPTION_SECTION_PATTERN.search(paragraph):
            selected.append(paragraph)
            used_indexes.add(index)

    excerpt = "\n\n".join(selected)
    if len(excerpt) <= max_chars:
        return excerpt

    lines = [line.strip() for line in excerpt.splitlines() if line.strip()]
    compact_lines: list[str] = []
    current_size = 0
    for line in lines:
        line_size = len(line) + 1
        if compact_lines and current_size + line_size > max_chars:
            break
        compact_lines.append(line)
        current_size += line_size

    if compact_lines:
        return "\n".join(compact_lines)[:max_chars].rstrip()

    return excerpt[:max_chars].rstrip()


def vacancy_prompt(vacancy: Vacancy, radar: RadarSettings) -> str:
    description = smart_description_excerpt(vacancy.description, radar.description_max_chars)
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


def analyze_vacancy(
    client: OpenAI,
    model: str,
    vacancy: Vacancy,
    radar: RadarSettings,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    timeout_seconds: int = DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    input_cost_per_1m: float | None = None,
    output_cost_per_1m: float | None = None,
) -> AnalysisResult:
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_completion_tokens=max_completion_tokens,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": radar.openai_system_prompt,
                },
                {"role": "user", "content": vacancy_prompt(vacancy, radar)},
            ],
            timeout=timeout_seconds,
        )
        content = response.choices[0].message.content or ""
        analysis = parse_openai_json(content, radar.score_min, radar.score_max)
        analysis.raw_response = content
        analysis.source = "openai"
        return attach_openai_usage(
            analysis,
            response.usage,
            input_cost_per_1m,
            output_cost_per_1m,
        )
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
