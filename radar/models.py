from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RadarSettings:
    candidate_profile: str
    target_experience_level: str
    candidate_years: str
    preferred_required_years: str
    max_required_years: int | None
    experience_guidance: str
    required_title_keywords: list[str]
    keywords: list[str]
    negative_prefilter_enabled: bool
    negative_title_keywords: list[str]
    negative_description_phrases: list[str]
    sheet_headers: list[str]
    found_date_timezone: str
    found_date_format: str
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
    openai_timeout_seconds: int = 60
    openai_max_retries: int = 2
    openai_max_completion_tokens: int = 700
    openai_input_cost_per_1m: float | None = None
    openai_output_cost_per_1m: float | None = None


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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnalysisResult:
    score: int
    fit_reason: str
    risks: str
    generated_reply: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    raw_response: str = ""
    source: str = "openai"


@dataclass(slots=True)
class RunStats:
    total_fetched: int = 0
    matched_by_keywords: int = 0
    skipped_by_title_prefilter: int = 0
    skipped_by_experience_prefilter: int = 0
    skipped_by_negative_prefilter: int = 0
    skipped_existing_vacancies: int = 0
    skipped_similar_vacancies: int = 0
    skipped_by_run_limit: int = 0
    skipped_low_score: int = 0
    new_vacancies: int = 0
    queued_for_analysis: int = 0
    local_prescore_vacancies: int = 0
    cached_analysis_vacancies: int = 0
    analyzed_vacancies: int = 0
    appended_vacancies: int = 0
    seen_vacancies: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None


class OpenAIQuotaError(RuntimeError):
    """Raised when OpenAI reports exhausted account quota."""
