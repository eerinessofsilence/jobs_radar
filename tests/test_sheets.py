import unittest
from typing import cast

import gspread
from radar.models import AnalysisResult, Config, RadarSettings, RunStats, Vacancy
from radar.sheets import (
    ANALYSIS_CACHE_HEADERS,
    RUNS_SHEET_HEADERS,
    SEEN_SHEET_HEADERS,
    analysis_cache_key,
    analysis_cache_row,
    append_seen_vacancies,
    ensure_sheet_headers,
    load_analysis_cache,
    load_urls_from_headers,
    run_summary_row,
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

    def get_all_values(self) -> list[list[str]]:
        return self.rows


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


def make_run_stats() -> RunStats:
    return RunStats(
        total_fetched=10,
        missing_company=2,
        missing_salary=6,
        matched_by_keywords=8,
        skipped_by_title_prefilter=1,
        skipped_by_experience_prefilter=1,
        skipped_by_negative_prefilter=1,
        skipped_existing_vacancies=2,
        skipped_similar_vacancies=1,
        skipped_by_run_limit=1,
        skipped_low_score=3,
        new_vacancies=5,
        queued_for_analysis=4,
        local_prescore_vacancies=1,
        cached_analysis_vacancies=1,
        analyzed_vacancies=4,
        appended_vacancies=1,
        seen_vacancies=4,
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        estimated_cost_usd=0.0003,
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

    def test_run_summary_row_records_observability_fields(self) -> None:
        radar = make_radar()
        config = make_config(radar)
        stats = make_run_stats()

        row = run_summary_row(
            stats,
            RUNS_SHEET_HEADERS,
            "2026-04-30 12:00",
            config,
            error="OpenAI warning",
        )

        values_by_header = dict(zip(RUNS_SHEET_HEADERS, row, strict=True))
        self.assertEqual("2026-04-30 12:00", values_by_header["Run Date"])
        self.assertEqual("test-model", values_by_header["Model"])
        self.assertEqual(
            "https://docs.google.com/spreadsheets/d/sheet-id/edit",
            values_by_header["Sheet URL"],
        )
        self.assertEqual(10, values_by_header["Total Fetched"])
        self.assertEqual(2, values_by_header["Missing Company"])
        self.assertEqual(6, values_by_header["Missing Salary"])
        self.assertEqual(2, values_by_header["Tracked/Seen/Duplicate"])
        self.assertEqual(1, values_by_header["Similar Duplicate Skipped"])
        self.assertEqual(1, values_by_header["Skipped By Run Limit"])
        self.assertEqual(1, values_by_header["Local Pre-Score"])
        self.assertEqual(1, values_by_header["Cached Analysis"])
        self.assertEqual(3, values_by_header["Low Score Skipped"])
        self.assertEqual(150, values_by_header["Total Tokens"])
        self.assertEqual(0.0003, values_by_header["Estimated Cost USD"])
        self.assertEqual("OpenAI warning", values_by_header["Errors"])

    def test_analysis_cache_roundtrip(self) -> None:
        vacancy = make_vacancy()
        analysis = AnalysisResult(
            score=7,
            fit_reason="Good fit",
            risks="",
            generated_reply="Hi",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            estimated_cost_usd=0.00001,
            raw_response='{"score":7}',
        )

        row = analysis_cache_row(
            vacancy,
            analysis,
            ANALYSIS_CACHE_HEADERS,
            "2026-04-30",
            "test-model",
        )
        worksheet = FakeWorksheet([ANALYSIS_CACHE_HEADERS, row])

        cache = load_analysis_cache(cast(gspread.Worksheet, worksheet), ANALYSIS_CACHE_HEADERS)

        key = analysis_cache_key("test-model", vacancy)
        self.assertIn(key, cache)
        self.assertEqual(7, cache[key].score)
        self.assertEqual("Good fit", cache[key].fit_reason)
        self.assertEqual('{"score":7}', cache[key].raw_response)


if __name__ == "__main__":
    unittest.main()
