from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .models import Config, RadarSettings

DEFAULT_CONFIG_PATH = "job_radar_config.json"
DEFAULT_PROFILE_CONFIG_PATH = "job_radar_profile.json"
DEFAULT_PROFILE_EXAMPLE_CONFIG_PATH = "job_radar_profile.example.json"
DEFAULT_SETTINGS_CONFIG_PATH = "job_radar_settings.json"
ROBOTA_SORT_VALUES = {
    "BY_DATE",
    "BY_DISTANCE",
    "BY_SALARY",
    "BY_RELEVANCE",
    "BY_VIEWED",
    "BY_BUSINESS_SCORE",
}
JOBSPY_PROFILE_TERM_VALUES = {"required-title", "keywords", "both"}
JOBSPY_SITE_VALUES = {"indeed", "linkedin"}


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def split_env_urls(value: str | None, defaults: list[str]) -> list[str]:
    if not value:
        return defaults

    urls = [item.strip() for item in re.split(r"[\n,;]+", value) if item.strip()]
    return urls or defaults


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
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


def env_float(
    name: str,
    default: float | None = None,
    minimum: float | None = None,
) -> float | None:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default

    try:
        value = float(raw_value)
    except ValueError:
        logging.warning("Invalid number for %s=%r. Using default %s.", name, raw_value, default)
        return default

    if minimum is not None and value < minimum:
        logging.warning("%s must be at least %s. Using default %s.", name, minimum, default)
        return default

    return value


def env_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, "").strip().upper()
    if not value:
        return default
    if value not in choices:
        logging.warning("Invalid %s=%r. Using default %s.", name, value, default)
        return default
    return value


def env_lower_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    if value not in choices:
        logging.warning("Invalid %s=%r. Using default %s.", name, value, default)
        return default
    return value


def env_choice_list(name: str, default: list[str], choices: set[str]) -> list[str]:
    values = [value.lower() for value in split_env_urls(os.getenv(name), default)]
    valid_values: list[str] = []
    for value in values:
        if value not in choices:
            logging.warning("Ignoring invalid %s value: %r.", name, value)
            continue
        valid_values.append(value)
    return valid_values or default


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    logging.warning("Invalid boolean for %s=%r. Using default %s.", name, value, default)
    return default


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def resolve_config_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return project_root() / path


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Config file is not valid JSON: {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Config file must contain a JSON object: {path}")

    return data


def load_json_value(raw_json: str, source_label: str) -> dict[str, Any]:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{source_label} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"{source_label} must contain a JSON object.")

    return data


def config_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Config key {key!r} must be a non-empty string.")
    return value.strip()


def config_int(data: dict[str, Any], key: str, default: int, minimum: int = 0) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or value < minimum:
        raise RuntimeError(f"Config key {key!r} must be an integer >= {minimum}.")
    return value


def config_string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        raise RuntimeError(f"Config key {key!r} must be a list of strings.")

    values = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if not values:
        raise RuntimeError(f"Config key {key!r} must contain at least one string.")
    return values


def optional_config_string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise RuntimeError(f"Config key {key!r} must be a list of strings.")
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def config_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Config key {key!r} must be a JSON object.")
    return value


def optional_config_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise RuntimeError(f"Config key {key!r} must be a JSON object.")
    return value


def optional_config_string(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key, default)
    if value == "":
        return default
    if not isinstance(value, str):
        raise RuntimeError(f"Config key {key!r} must be a string.")
    return value.strip()


def optional_config_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, int) or value < 0:
        raise RuntimeError(f"Config key {key!r} must be a non-negative integer.")
    return value


def optional_config_bool(data: dict[str, Any], key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"Config key {key!r} must be a boolean.")
    return value


def merge_config_data(
    profile_data: dict[str, Any],
    settings_data: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(settings_data)
    merged.update(profile_data)
    return merged


def load_config_data() -> dict[str, Any]:
    legacy_config_value = os.getenv("JOB_RADAR_CONFIG", "").strip()
    profile_json_value = os.getenv("JOB_RADAR_PROFILE_JSON", "").strip()
    profile_path = resolve_config_path(
        os.getenv("JOB_RADAR_PROFILE_CONFIG", DEFAULT_PROFILE_CONFIG_PATH).strip()
        or DEFAULT_PROFILE_CONFIG_PATH
    )
    profile_example_path = resolve_config_path(DEFAULT_PROFILE_EXAMPLE_CONFIG_PATH)
    settings_path = resolve_config_path(
        os.getenv("JOB_RADAR_SETTINGS_CONFIG", DEFAULT_SETTINGS_CONFIG_PATH).strip()
        or DEFAULT_SETTINGS_CONFIG_PATH
    )
    split_configs_exist = profile_path.exists() and settings_path.exists()

    if legacy_config_value and not (
        legacy_config_value == DEFAULT_CONFIG_PATH and split_configs_exist
    ):
        return load_json_file(resolve_config_path(legacy_config_value))

    if profile_json_value:
        if not settings_path.exists():
            raise RuntimeError(f"Settings config file not found: {settings_path}")
        return merge_config_data(
            load_json_value(profile_json_value, "JOB_RADAR_PROFILE_JSON"),
            load_json_file(settings_path),
        )

    if split_configs_exist:
        return merge_config_data(load_json_file(profile_path), load_json_file(settings_path))

    if (
        profile_path.name == DEFAULT_PROFILE_CONFIG_PATH
        and profile_example_path.exists()
        and settings_path.exists()
    ):
        return merge_config_data(
            load_json_file(profile_example_path), load_json_file(settings_path)
        )

    if profile_path.exists() != settings_path.exists():
        raise RuntimeError(
            f"Both split config files must exist: {profile_path.name} and {settings_path.name}."
        )

    return load_json_file(resolve_config_path(legacy_config_value or DEFAULT_CONFIG_PATH))


def load_radar_settings_from_data(data: dict[str, Any]) -> RadarSettings:
    experience = optional_config_dict(data, "experience")
    negative_prefilter = optional_config_dict(data, "negative_prefilter")
    rss_urls = config_dict(data, "default_rss_urls")
    analysis = config_dict(data, "analysis")
    row_defaults = config_dict(data, "row_defaults")

    settings = RadarSettings(
        candidate_profile=config_string(data, "candidate_profile"),
        target_experience_level=optional_config_string(experience, "target_level"),
        candidate_years=optional_config_string(experience, "candidate_years"),
        preferred_required_years=optional_config_string(experience, "preferred_required_years"),
        max_required_years=optional_config_int(experience, "max_required_years"),
        experience_guidance=optional_config_string(experience, "guidance"),
        required_title_keywords=optional_config_string_list(data, "required_title_keywords"),
        keywords=config_string_list(data, "keywords"),
        negative_prefilter_enabled=optional_config_bool(negative_prefilter, "enabled"),
        negative_title_keywords=optional_config_string_list(negative_prefilter, "title_keywords"),
        negative_description_phrases=optional_config_string_list(
            negative_prefilter,
            "description_phrases",
        ),
        sheet_headers=config_string_list(data, "sheet_headers"),
        found_date_timezone=optional_config_string(data, "found_date_timezone", "UTC"),
        found_date_format=optional_config_string(data, "found_date_format", "%Y-%m-%d %H:%M"),
        default_dou_rss_urls=config_string_list(rss_urls, "dou"),
        default_djinni_rss_urls=config_string_list(rss_urls, "djinni"),
        score_min=config_int(analysis, "score_min", 1, minimum=0),
        score_max=config_int(analysis, "score_max", 10, minimum=1),
        description_max_chars=config_int(analysis, "description_max_chars", 6000, minimum=500),
        scoring_guidance=config_string(analysis, "scoring_guidance"),
        scoring_rubric=config_string(analysis, "scoring_rubric"),
        generated_reply_instruction=config_string(analysis, "generated_reply_instruction"),
        openai_system_prompt=config_string(analysis, "openai_system_prompt"),
        row_defaults=row_defaults,
    )

    if settings.score_max <= settings.score_min:
        raise RuntimeError("Config analysis.score_max must be greater than analysis.score_min.")

    if "URL" not in settings.sheet_headers:
        raise RuntimeError("Config sheet_headers must include a URL column.")

    return settings


def load_radar_settings(config_path: Path) -> RadarSettings:
    return load_radar_settings_from_data(load_json_file(config_path))


def load_default_radar_settings() -> RadarSettings:
    return load_radar_settings_from_data(load_config_data())


def load_config() -> Config:
    load_dotenv()
    radar = load_default_radar_settings()
    min_score = env_int("MIN_SCORE", 5, minimum=0)

    if min_score > radar.score_max:
        logging.warning(
            "MIN_SCORE=%s is higher than configured score_max=%s. No vacancies will be appended.",
            min_score,
            radar.score_max,
        )

    return Config(
        openai_api_key=require_env("OPENAI_API_KEY"),
        google_sheet_id=require_env("GOOGLE_SHEET_ID"),
        google_service_account_json=require_env("GOOGLE_SERVICE_ACCOUNT_JSON"),
        telegram_bot_token=require_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=require_env("TELEGRAM_CHAT_ID"),
        radar=radar,
        dou_rss_urls=split_env_urls(os.getenv("DOU_RSS_URLS"), radar.default_dou_rss_urls),
        djinni_rss_urls=split_env_urls(os.getenv("DJINNI_RSS_URLS"), radar.default_djinni_rss_urls),
        indeed_rss_urls=split_env_urls(os.getenv("INDEED_RSS_URLS"), []),
        jobspy_enabled=env_bool("JOBSPY_ENABLED", False),
        jobspy_sites=env_choice_list("JOBSPY_SITES", ["indeed", "linkedin"], JOBSPY_SITE_VALUES),
        jobspy_locations=split_env_urls(os.getenv("JOBSPY_LOCATIONS"), ["Ukraine", "Europe"]),
        jobspy_profile_terms=env_lower_choice(
            "JOBSPY_PROFILE_TERMS",
            "required-title",
            JOBSPY_PROFILE_TERM_VALUES,
        ),
        jobspy_max_terms=env_int("JOBSPY_MAX_TERMS", 0, minimum=0),
        jobspy_results_per_term=env_int("JOBSPY_RESULTS_PER_TERM", 5, minimum=1),
        jobspy_country_indeed=os.getenv("JOBSPY_COUNTRY_INDEED", "Ukraine").strip() or "Ukraine",
        jobspy_verbose=env_int("JOBSPY_VERBOSE", 0, minimum=0),
        robota_keywords=split_env_urls(os.getenv("ROBOTA_KEYWORDS"), []),
        robota_cookie=os.getenv("ROBOTA_COOKIE", "").strip(),
        robota_pages_per_keyword=env_int("ROBOTA_PAGES_PER_KEYWORD", 1, minimum=1),
        robota_sort=env_choice("ROBOTA_SORT", "BY_DATE", ROBOTA_SORT_VALUES),
        robota_include_required_title_keywords=env_bool(
            "ROBOTA_INCLUDE_REQUIRED_TITLE_KEYWORDS",
            True,
        ),
        min_score=min_score,
        max_jobs_per_run=env_int("MAX_JOBS_PER_RUN", 20, minimum=1),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        openai_timeout_seconds=env_int("OPENAI_TIMEOUT_SECONDS", 60, minimum=1),
        openai_max_retries=env_int("OPENAI_MAX_RETRIES", 2, minimum=0),
        openai_max_completion_tokens=env_int("OPENAI_MAX_COMPLETION_TOKENS", 700, minimum=1),
        openai_input_cost_per_1m=env_float("OPENAI_INPUT_COST_PER_1M", minimum=0),
        openai_output_cost_per_1m=env_float("OPENAI_OUTPUT_COST_PER_1M", minimum=0),
    )
