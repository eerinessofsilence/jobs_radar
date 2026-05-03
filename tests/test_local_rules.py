import unittest

from radar.local_rules import local_prescore_vacancy
from radar.models import RadarSettings, Vacancy


def make_radar() -> RadarSettings:
    return RadarSettings(
        candidate_profile="",
        target_experience_level="",
        candidate_years="3",
        preferred_required_years="0-3 years",
        max_required_years=3,
        experience_guidance="",
        required_title_keywords=[],
        keywords=["Python"],
        negative_prefilter_enabled=True,
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


def make_vacancy(title: str, description: str = "") -> Vacancy:
    return Vacancy(
        source="Fixture",
        title=title,
        company="",
        location="",
        salary="",
        url="https://example.com/job",
        published_date="",
        description=description,
    )


class LocalRulesTest(unittest.TestCase):
    def test_prescores_node_only_role(self) -> None:
        analysis = local_prescore_vacancy(
            make_vacancy("Node.js / NestJS Backend Developer"),
            make_radar(),
            min_score=5,
        )

        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertIn("node-only", analysis.fit_reason)

    def test_prescores_military_drone_domain(self) -> None:
        analysis = local_prescore_vacancy(
            make_vacancy("Python Developer", "Build software for UAV and drone operations."),
            make_radar(),
            min_score=5,
        )

        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertIn("military/drone", analysis.fit_reason)

    def test_allows_fullstack_node_react_role(self) -> None:
        analysis = local_prescore_vacancy(
            make_vacancy("Full-stack Node.js React Developer"),
            make_radar(),
            min_score=5,
        )

        self.assertIsNone(analysis)


if __name__ == "__main__":
    unittest.main()
