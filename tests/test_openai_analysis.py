import unittest

from radar.openai_analysis import parse_openai_json, strip_markdown_fences


class OpenAIAnalysisTest(unittest.TestCase):
    def test_strip_markdown_fences_handles_json_fence(self) -> None:
        content = '```json\n{"score": 7}\n```'

        self.assertEqual('{"score": 7}', strip_markdown_fences(content))

    def test_parse_openai_json_handles_markdown_fenced_json(self) -> None:
        result = parse_openai_json(
            '```json\n{"score": 7, "fit_reason": "Good fit", "risks": "", "generated_reply": "Hi"}\n```',
            score_min=1,
            score_max=10,
        )

        self.assertEqual(7, result.score)
        self.assertEqual("Good fit", result.fit_reason)
        self.assertEqual("Hi", result.generated_reply)

    def test_parse_openai_json_extracts_json_from_surrounding_text(self) -> None:
        result = parse_openai_json(
            'Result: {"score": 11, "fit_reason": "Strong", "risks": "", "generated_reply": ""}',
            score_min=1,
            score_max=10,
        )

        self.assertEqual(10, result.score)
        self.assertEqual("Strong", result.fit_reason)


if __name__ == "__main__":
    unittest.main()
