import unittest

from radar.models import AnalysisResult, RunStats, Vacancy
from radar.telegram import build_summary_message, telegram_chunks


def make_vacancy(
    title: str,
    company: str = "Acme",
    salary: str = "$1000",
    description: str = "Remote Python work",
) -> Vacancy:
    return Vacancy(
        source="Fixture",
        title=title,
        company=company,
        location="Remote",
        salary=salary,
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        published_date="",
        description=description,
    )


class TelegramTest(unittest.TestCase):
    def test_telegram_chunks_split_at_newline_when_possible(self) -> None:
        chunks = telegram_chunks("first line\nsecond line\nthird line", max_length=23)

        self.assertEqual(["first line\nsecond line", "third line"], chunks)

    def test_telegram_chunks_split_long_line_without_newline(self) -> None:
        chunks = telegram_chunks("abcdefghij", max_length=4)

        self.assertEqual(["abcd", "efgh", "ij"], chunks)

    def test_summary_includes_operational_context_and_sheet_link(self) -> None:
        stats = RunStats(
            total_fetched=10,
            missing_company=2,
            missing_salary=6,
            matched_by_keywords=8,
            skipped_existing_vacancies=2,
            skipped_by_run_limit=1,
            skipped_low_score=3,
            new_vacancies=5,
            queued_for_analysis=4,
            analyzed_vacancies=4,
            appended_vacancies=1,
            seen_vacancies=4,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            estimated_cost_usd=0.0003,
        )

        message = build_summary_message(
            stats,
            analyzed=[],
            min_score=5,
            sheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit",
        )

        self.assertIn("Tracked/seen/duplicate: 2", message)
        self.assertIn("Missing company: 2", message)
        self.assertIn("Missing salary: 6", message)
        self.assertIn("Skipped by run limit: 1", message)
        self.assertIn("Low-score skipped: 3", message)
        self.assertIn("Token usage: 150 total (100 input, 50 output), cost=$0.000300", message)
        self.assertIn("Sheet: https://docs.google.com/spreadsheets/d/sheet-id/edit", message)

    def test_summary_groups_scored_vacancies(self) -> None:
        stats = RunStats(total_fetched=3, analyzed_vacancies=3)
        analyzed = [
            (
                make_vacancy("Strong Python Developer", company="Alpha", salary="$4000"),
                AnalysisResult(score=9, fit_reason="", risks="", generated_reply=""),
            ),
            (
                make_vacancy("Maybe Backend Developer", company="", salary=""),
                AnalysisResult(score=6, fit_reason="", risks="", generated_reply=""),
            ),
            (
                make_vacancy("Office Python Developer", description="Office-only work"),
                AnalysisResult(score=3, fit_reason="", risks="", generated_reply=""),
            ),
        ]

        message = build_summary_message(stats, analyzed, min_score=5)

        self.assertIn("Strong\n9 | Strong Python Developer | Alpha | $4000 | Remote", message)
        self.assertIn("Maybe\n6 | Maybe Backend Developer | - | - | Remote", message)
        self.assertIn(
            "Skipped notable\n3 | Office Python Developer | Acme | $1000 | Office",
            message,
        )


if __name__ == "__main__":
    unittest.main()
