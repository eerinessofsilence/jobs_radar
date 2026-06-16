import unittest

from radar.models import Config, RadarSettings
from radar.robota import robota_payload, robota_search_keywords, vacancy_from_robota_item


def make_config(
    robota_keywords: list[str],
    required_title_keywords: list[str],
    include_required: bool = True,
) -> Config:
    radar = RadarSettings(
        candidate_profile="",
        target_experience_level="",
        candidate_years="",
        preferred_required_years="",
        max_required_years=None,
        experience_guidance="",
        required_title_keywords=required_title_keywords,
        keywords=[],
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
    return Config(
        openai_api_key="openai-key",
        google_sheet_id="sheet-id",
        google_service_account_json="{}",
        telegram_bot_token="telegram-token",
        telegram_chat_id="chat-id",
        radar=radar,
        dou_rss_urls=[],
        djinni_rss_urls=[],
        robota_keywords=robota_keywords,
        robota_include_required_title_keywords=include_required,
    )


class RobotaTest(unittest.TestCase):
    def test_vacancy_from_robota_item_maps_core_fields(self) -> None:
        vacancy = vacancy_from_robota_item(
            {
                "id": "10526732",
                "title": "Python Developer",
                "description": "<p>Backend work with Python</p>",
                "sortDate": "2026-06-15T15:36:05.047",
                "sortDateText": "20 годин тому",
                "salary": {"amount": 25000, "amountFrom": 25000, "amountTo": 30000},
                "company": {"id": "15447580", "name": "Bravilo"},
                "city": {"id": "1", "name": "Київ"},
                "formApplyCustomUrl": "",
            },
            "python developer",
        )

        self.assertIsNotNone(vacancy)
        assert vacancy is not None
        self.assertEqual("Robota.ua", vacancy.source)
        self.assertEqual("Python Developer", vacancy.title)
        self.assertEqual("Bravilo", vacancy.company)
        self.assertEqual("Київ", vacancy.location)
        self.assertEqual("25000-30000 UAH", vacancy.salary)
        self.assertEqual("https://robota.ua/company15447580/vacancy10526732", vacancy.url)
        self.assertEqual("2026-06-15T15:36:05.047", vacancy.published_date)
        self.assertEqual("Backend work with Python", vacancy.description)
        self.assertEqual("python developer", vacancy.metadata["robota"]["keywords"])

    def test_robota_payload_uses_keyword_filter_and_page(self) -> None:
        payload = robota_payload("junior python developer", 2)

        self.assertEqual("getPublishedVacanciesList", payload["operationName"])
        self.assertEqual(2, payload["variables"]["pagination"]["page"])
        self.assertEqual(20, payload["variables"]["pagination"]["count"])
        self.assertEqual("BY_DATE", payload["variables"]["sort"])
        self.assertEqual(
            "junior python developer",
            payload["variables"]["filter"]["keywords"],
        )

    def test_robota_payload_allows_sort_override(self) -> None:
        payload = robota_payload("python developer", 0, "BY_BUSINESS_SCORE")

        self.assertEqual("BY_BUSINESS_SCORE", payload["variables"]["sort"])

    def test_robota_search_keywords_include_required_title_keywords(self) -> None:
        config = make_config(
            ["python developer", "Python Developer"],
            ["Backend Developer", "Python Developer"],
        )

        self.assertEqual(
            ["python developer", "Backend Developer"],
            robota_search_keywords(config),
        )

    def test_robota_search_keywords_stays_disabled_without_manual_keywords(self) -> None:
        config = make_config([], ["Backend Developer"])

        self.assertEqual([], robota_search_keywords(config))

    def test_robota_search_keywords_can_skip_required_title_keywords(self) -> None:
        config = make_config(["python developer"], ["Backend Developer"], include_required=False)

        self.assertEqual(["python developer"], robota_search_keywords(config))


if __name__ == "__main__":
    unittest.main()
