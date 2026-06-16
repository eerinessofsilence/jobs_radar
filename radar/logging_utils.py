from __future__ import annotations

import logging
import os
import sys

from .models import Config

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"


ANSI_RESET = "\033[0m"


LEVEL_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35;1m",
}


TAG_COLORS = {
    "[start]": "\033[36m",
    "[fetch]": "\033[34m",
    "[filter]": "\033[35m",
    "[analyze]": "\033[36m",
    "[result]": "\033[32m",
    "[sheet]": "\033[33m",
    "[done]": "\033[32;1m",
    "[openai]": "\033[31m",
    "[config]": "\033[36m",
    "[reason]": "\033[37m",
    "[risks]": "\033[33m",
    "[telegram]": "\033[32m",
}


class ColorFormatter(logging.Formatter):
    def __init__(self, fmt: str, datefmt: str, use_color: bool) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        original_levelname = record.levelname
        original_msg = record.msg

        try:
            level_label = f"{original_levelname:<7}"
            if self.use_color:
                color = LEVEL_COLORS.get(original_levelname, "")
                record.levelname = f"{color}{level_label}{ANSI_RESET}" if color else level_label
                if isinstance(record.msg, str):
                    record.msg = color_log_tag(record.msg)
            else:
                record.levelname = level_label

            return super().format(record)
        finally:
            record.levelname = original_levelname
            record.msg = original_msg


def color_log_tag(message: str) -> str:
    for tag, color in TAG_COLORS.items():
        if message.startswith(tag):
            return f"{color}{tag}{ANSI_RESET}{message[len(tag) :]}"
    return message


def should_color_logs() -> bool:
    if "NO_COLOR" in os.environ:
        return False

    mode = os.getenv("LOG_COLOR", "auto").strip().lower() or "auto"
    if mode in {"1", "true", "yes", "on", "always"}:
        return True
    if mode in {"0", "false", "no", "off", "never"}:
        return False

    return sys.stderr.isatty() or os.getenv("GITHUB_ACTIONS") == "true"


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    configured_level = getattr(logging, level_name, None)
    invalid_level_name = level_name if not isinstance(configured_level, int) else ""
    level: int = configured_level if isinstance(configured_level, int) else logging.INFO

    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter(LOG_FORMAT, "%Y-%m-%d %H:%M:%S", should_color_logs()))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    if invalid_level_name:
        logging.warning("[config] Invalid LOG_LEVEL=%r. Using INFO.", invalid_level_name)

    for logger_name in (
        "httpx",
        "httpcore",
        "openai",
        "urllib3",
        "google.auth.transport.requests",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def log_run_start(config: Config) -> None:
    logging.info(
        "[start] model=%s | score=%s-%s | min=%s | max_jobs=%s | feeds=%s | robota=%s | "
        "jobspy=%s | jobspy_sites=%s | jobspy_locations=%s | openai_timeout=%ss | "
        "openai_retries=%s | "
        "max_completion=%s",
        config.openai_model,
        config.radar.score_min,
        config.radar.score_max,
        config.min_score,
        config.max_jobs_per_run,
        len(config.dou_rss_urls) + len(config.djinni_rss_urls) + len(config.indeed_rss_urls),
        len(config.robota_keywords),
        "on" if config.jobspy_enabled else "off",
        len(config.jobspy_sites),
        len(config.jobspy_locations),
        config.openai_timeout_seconds,
        config.openai_max_retries,
        config.openai_max_completion_tokens,
    )
