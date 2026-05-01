import unittest
from types import SimpleNamespace
from unittest.mock import patch

from radar import runner
from radar.models import AnalysisResult, Config, RadarSettings, Vacancy


def make_radar() -> RadarSettings:
    return RadarSettings(
        candidate_profile="Python backend developer",
        target_experience_level="",
        candidate_years="",
        preferred_required_years="",
        max_required_years=None,
        experience_guidance="",
        required_title_keywords=[],
        keywords=["Python"],
        negative_prefilter_enabled=False,
        negative_title_keywords=[],
        negative_description_phrases=[],
        sheet_headers=["URL", "Score"],
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
        row_defaults={"Status": "New"},
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
        min_score=5,
        max_jobs_per_run=10,
        openai_model="test-model",
    )


def make_vacancy(url: str, title: str = "Python Developer") -> Vacancy:
    return Vacancy(
        source="Fixture",
        title=title,
        company="Acme",
        location="Remote",
        salary="",
        url=url,
        published_date="2026-04-29T09:30:00+00:00",
        description="Python backend work",
    )


class RunnerOrchestrationTest(unittest.TestCase):
    def test_run_skips_seen_urls_and_tracks_low_score_analysis(self) -> None:
        radar_settings = make_radar()
        config = make_config(radar_settings)
        seen_vacancy = make_vacancy("https://example.com/seen")
        new_vacancy = make_vacancy("https://example.com/new")
        low_score_analysis = AnalysisResult(
            score=4,
            fit_reason="Weak fit",
            risks="Too little backend work",
            generated_reply="",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        sheets = SimpleNamespace(
            worksheet=object(),
            headers=["URL", "Score"],
            existing_urls=set(),
            seen_worksheet=object(),
            seen_headers=["URL", "Score"],
            seen_urls={"https://example.com/seen"},
        )

        with (
            patch.object(runner, "setup_logging"),
            patch.object(runner, "load_config", return_value=config),
            patch.object(runner, "OpenAI", return_value=object()),
            patch.object(runner, "open_sheet", return_value=sheets),
            patch.object(
                runner,
                "collect_rss_vacancies",
                return_value=[seen_vacancy, new_vacancy],
            ),
            patch.object(runner, "collect_email_alert_vacancies", return_value=[]),
            patch.object(runner, "analyze_vacancy", return_value=low_score_analysis) as analyze,
            patch.object(runner, "append_analyzed_vacancies", return_value=0) as append_main,
            patch.object(runner, "append_seen_vacancies", return_value=1) as append_seen,
            patch.object(runner, "send_telegram_message") as send_message,
        ):
            runner.run()

        analyze.assert_called_once()
        analyzed_vacancy = analyze.call_args.args[2]
        self.assertEqual(new_vacancy.url, analyzed_vacancy.url)

        appended_rows = append_main.call_args.args[2]
        self.assertEqual([], appended_rows)

        seen_rows = append_seen.call_args.args[2]
        self.assertEqual([(new_vacancy, low_score_analysis)], seen_rows)
        send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
