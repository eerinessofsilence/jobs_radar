import unittest

from radar.reset import data_rows_clear_range


class ResetSheetTest(unittest.TestCase):
    def test_no_range_for_empty_sheet(self) -> None:
        self.assertIsNone(data_rows_clear_range([], ["URL"]))

    def test_no_range_for_header_only(self) -> None:
        self.assertIsNone(data_rows_clear_range([["URL"]], ["URL"]))

    def test_clears_data_rows_but_keeps_header(self) -> None:
        values = [
            ["Found Date", "Source", "URL"],
            ["29.04.2026", "Djinni", "https://example.com/1"],
            ["29.04.2026", "DOU", "https://example.com/2"],
        ]

        self.assertEqual("A2:C3", data_rows_clear_range(values, ["Found Date", "Source", "URL"]))

    def test_uses_configured_header_width_when_sheet_rows_are_shorter(self) -> None:
        values = [
            ["Found Date", "Source"],
            ["29.04.2026", "Djinni"],
        ]

        self.assertEqual(
            "A2:D2",
            data_rows_clear_range(values, ["Found Date", "Source", "URL", "Status"]),
        )


if __name__ == "__main__":
    unittest.main()
