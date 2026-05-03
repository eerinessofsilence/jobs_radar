import unittest

from radar.filters import (
    experience_prefilter_reason,
    keyword_summary_is_relevant,
    match_keyword_summary,
)
from radar.models import RadarSettings, Vacancy


def make_radar(max_required_years: int | None = 3) -> RadarSettings:
    return RadarSettings(
        candidate_profile="",
        target_experience_level="",
        candidate_years="3",
        preferred_required_years="0-3 years",
        max_required_years=max_required_years,
        experience_guidance="",
        required_title_keywords=[],
        keywords=[],
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


def make_vacancy(title: str, description: str) -> Vacancy:
    return Vacancy(
        source="Djinni",
        title=title,
        company="",
        location="",
        salary="",
        url="https://example.com/job",
        published_date="",
        description=description,
    )


class ExperiencePrefilterTest(unittest.TestCase):
    def test_keyword_summary_weights_title_stack_and_description_matches(self) -> None:
        vacancy = make_vacancy(
            "Python Developer",
            "Nice company intro.\n\nTech stack: Django, PostgreSQL.\n\nWe mention Docker once.",
        )

        summary = match_keyword_summary(vacancy, ["Python", "Django", "PostgreSQL", "Docker"])

        self.assertEqual(["Python"], summary.title_matches)
        self.assertEqual(["Django", "PostgreSQL"], summary.stack_matches)
        self.assertEqual(["Docker"], summary.description_matches)
        self.assertEqual(8, summary.score)
        self.assertTrue(keyword_summary_is_relevant(summary))

    def test_keyword_summary_rejects_single_description_only_match(self) -> None:
        vacancy = make_vacancy("Customer Success Manager", "Integrates with APIs.")

        summary = match_keyword_summary(vacancy, ["APIs"])

        self.assertEqual(["APIs"], summary.description_matches)
        self.assertFalse(keyword_summary_is_relevant(summary))

    def test_rejects_plus_requirement_above_limit(self) -> None:
        vacancy = make_vacancy(
            "Python Developer",
            "Requirements: 4+ years of commercial experience with Python.",
        )

        self.assertIn("required_experience>3", experience_prefilter_reason(vacancy, make_radar()))

    def test_rejects_more_than_limit_requirement(self) -> None:
        vacancy = make_vacancy(
            "Backend Developer",
            "You have more than 3 years of experience building APIs.",
        )

        self.assertIn("required_experience>3", experience_prefilter_reason(vacancy, make_radar()))

    def test_rejects_range_above_limit(self) -> None:
        vacancy = make_vacancy(
            "Full Stack Developer",
            "Requirements: 2-4 years of relevant experience.",
        )

        self.assertIn("required_experience>3", experience_prefilter_reason(vacancy, make_radar()))

    def test_rejects_experience_field_above_limit(self) -> None:
        vacancy = make_vacancy("React Developer", "Experience: 4 years")

        self.assertIn("required_experience>3", experience_prefilter_reason(vacancy, make_radar()))

    def test_rejects_title_year_requirement_above_limit(self) -> None:
        vacancy = make_vacancy("Python Developer 4 years", "")

        self.assertIn("required_experience>3", experience_prefilter_reason(vacancy, make_radar()))

    def test_allows_requirement_at_limit(self) -> None:
        vacancy = make_vacancy(
            "Python Developer",
            "Requirements: 3+ years of commercial experience with Python.",
        )

        self.assertEqual("", experience_prefilter_reason(vacancy, make_radar()))

    def test_allows_range_with_upper_bound_at_limit(self) -> None:
        vacancy = make_vacancy(
            "Backend Developer",
            "Requirements: 1-3 years of relevant experience.",
        )

        self.assertEqual("", experience_prefilter_reason(vacancy, make_radar()))

    def test_allows_when_limit_is_disabled(self) -> None:
        vacancy = make_vacancy(
            "Python Developer",
            "Requirements: 5+ years of commercial experience with Python.",
        )

        self.assertEqual("", experience_prefilter_reason(vacancy, make_radar(None)))


if __name__ == "__main__":
    unittest.main()
