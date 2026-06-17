import unittest
from unittest.mock import patch

from radar.jobspy_sources import (
    collect_jobspy_vacancies,
    jobspy_search_terms,
    json_safe,
    vacancy_from_jobspy_row,
)
from radar.models import Config, RadarSettings


def make_radar() -> RadarSettings:
    return RadarSettings(
        candidate_profile="",
        target_experience_level="",
        candidate_years="",
        preferred_required_years="",
        max_required_years=None,
        experience_guidance="",
        required_title_keywords=["Python Developer", "Backend Developer"],
        keywords=["Python", "Django"],
        negative_prefilter_enabled=False,
        negative_title_keywords=[],
        negative_description_phrases=[],
        sheet_headers=["URL"],
        found_date_timezone="UTC",
        found_date_format="%Y-%m-%d",
        default_dou_rss_urls=[],
        default_djinni_rss_urls=[],
        score_min=1,
        score_max=10,
        description_max_chars=3000,
        scoring_guidance="",
        scoring_rubric="",
        generated_reply_instruction="",
        openai_system_prompt="",
        row_defaults={},
    )


def make_config(radar: RadarSettings) -> Config:
    return Config(
        openai_api_key="openai-key",
        google_sheet_id="sheet-id",
        google_service_account_json="{}",
        telegram_bot_token="telegram-token",
        telegram_chat_id="chat-id",
        radar=radar,
        dou_rss_urls=[],
        djinni_rss_urls=[],
    )


class JobSpySourcesTest(unittest.TestCase):
    def test_jobspy_search_terms_uses_required_title_keywords_by_default(self) -> None:
        config = make_config(make_radar())

        self.assertEqual(["Python Developer", "Backend Developer"], jobspy_search_terms(config))

    def test_jobspy_search_terms_can_limit_terms(self) -> None:
        config = make_config(make_radar())
        config.jobspy_max_terms = 1

        self.assertEqual(["Python Developer"], jobspy_search_terms(config))

    def test_vacancy_from_jobspy_row_maps_core_fields(self) -> None:
        vacancy = vacancy_from_jobspy_row(
            {
                "id": "li-123",
                "site": "linkedin",
                "title": "Python Developer",
                "company": "Example",
                "location": "Europe",
                "job_url": "https://www.linkedin.com/jobs/view/123",
                "job_url_direct": None,
                "date_posted": "2026-06-16",
                "description": "Build APIs",
                "min_amount": 2000.0,
                "max_amount": 3000.0,
                "currency": "USD",
                "interval": "monthly",
            },
            "Python Developer",
            "Europe",
        )

        self.assertIsNotNone(vacancy)
        assert vacancy is not None
        self.assertEqual("LinkedIn", vacancy.source)
        self.assertEqual("Python Developer", vacancy.title)
        self.assertEqual("Example", vacancy.company)
        self.assertEqual("2000-3000 USD monthly", vacancy.salary)
        self.assertEqual("Europe", vacancy.metadata["jobspy"]["search_location"])

    def test_json_safe_converts_nan(self) -> None:
        self.assertIsNone(json_safe(float("nan")))

    def test_collect_skips_linkedin_unsupported_location(self) -> None:
        config = make_config(make_radar())
        config.jobspy_enabled = True
        config.jobspy_locations = ["Iceland"]
        config.jobspy_sites = ["linkedin"]

        with self.assertLogs(level="WARNING") as captured:
            vacancies = collect_jobspy_vacancies(config)

        self.assertEqual([], vacancies)
        self.assertIn("LinkedIn does not support this country", "\n".join(captured.output))

    def test_collect_downgrades_linkedin_invalid_country_exception_to_warning(self) -> None:
        config = make_config(make_radar())
        config.jobspy_enabled = True
        config.jobspy_locations = ["Europe"]
        config.jobspy_sites = ["linkedin"]
        error = RuntimeError("Invalid country string: 'iceland'. Valid countries are: ukraine")

        with (
            self.assertLogs(level="WARNING") as captured,
            patch(
                "radar.jobspy_sources.scrape_jobspy_site",
                side_effect=error,
            ),
        ):
            vacancies = collect_jobspy_vacancies(config)

        self.assertEqual([], vacancies)
        self.assertIn("unsupported country in LinkedIn result", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
