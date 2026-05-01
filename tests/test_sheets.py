import unittest
from typing import cast

import gspread
from radar.models import AnalysisResult, RadarSettings, Vacancy
from radar.sheets import (
    SEEN_SHEET_HEADERS,
    append_seen_vacancies,
    ensure_sheet_headers,
    load_urls_from_headers,
    seen_row_for_vacancy,
)


class FakeWorksheet:
    title = "Fake"

    def __init__(self, rows: list[list[str]]) -> None:
        self.rows = rows
        self.updated_values: list[list[str]] = []
        self.updated_range = ""
        self.appended_rows: list[list[str]] = []

    def row_values(self, row: int) -> list[str]:
        return self.rows[row - 1] if len(self.rows) >= row else []

    def col_values(self, column: int) -> list[str]:
        index = column - 1
        return [row[index] for row in self.rows if len(row) > index]

    def update(self, values: list[list[str]], range_name: str) -> None:
        self.updated_values = values
        self.updated_range = range_name

    def append_rows(self, rows: list[list[str]], value_input_option: object) -> None:
        self.appended_rows = rows


def make_radar() -> RadarSettings:
    return RadarSettings(
        candidate_profile="",
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


def make_vacancy() -> Vacancy:
    return Vacancy(
        source="Djinni",
        title="Python Developer",
        company="Example Co",
        location="Remote",
        salary="",
        url="https://example.com/job?utm_source=x&id=1",
        published_date="",
        description="",
    )


class SheetsTest(unittest.TestCase):
    def test_ensure_sheet_headers_adds_missing_headers(self) -> None:
        worksheet = FakeWorksheet([["URL"]])

        with self.assertLogs(level="WARNING"):
            headers = ensure_sheet_headers(cast(gspread.Worksheet, worksheet), ["URL", "Score"])

        self.assertEqual(["URL", "Score"], headers)
        self.assertEqual([["URL", "Score"]], worksheet.updated_values)
        self.assertEqual("A1:B1", worksheet.updated_range)

    def test_load_urls_from_headers_normalizes_urls(self) -> None:
        worksheet = FakeWorksheet(
            [
                ["URL"],
                ["https://example.com/job/?utm_source=newsletter&id=1"],
            ]
        )

        self.assertEqual(
            {"https://example.com/job?id=1"},
            load_urls_from_headers(cast(gspread.Worksheet, worksheet), ["URL"]),
        )

    def test_seen_row_marks_below_min_score(self) -> None:
        row = seen_row_for_vacancy(
            make_vacancy(),
            AnalysisResult(score=4, fit_reason="Weak fit", risks="", generated_reply=""),
            SEEN_SHEET_HEADERS,
            "30.04.2026 12:00",
            min_score=5,
        )

        self.assertEqual("30.04.2026 12:00", row[0])
        self.assertEqual("https://example.com/job?utm_source=x&id=1", row[4])
        self.assertEqual(4, row[5])
        self.assertEqual("Below min score (5)", row[6])

    def test_append_seen_vacancies_skips_technical_failures(self) -> None:
        worksheet = FakeWorksheet([SEEN_SHEET_HEADERS])

        count = append_seen_vacancies(
            cast(gspread.Worksheet, worksheet),
            SEEN_SHEET_HEADERS,
            [
                (
                    make_vacancy(),
                    AnalysisResult(
                        score=0,
                        fit_reason="",
                        risks="OpenAI failed",
                        generated_reply="",
                    ),
                ),
                (
                    make_vacancy(),
                    AnalysisResult(score=4, fit_reason="Weak fit", risks="", generated_reply=""),
                ),
            ],
            make_radar(),
            min_score=5,
        )

        self.assertEqual(1, count)
        self.assertEqual(1, len(worksheet.appended_rows))
        self.assertEqual("Below min score (5)", worksheet.appended_rows[0][6])


if __name__ == "__main__":
    unittest.main()
