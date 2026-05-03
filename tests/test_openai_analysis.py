import unittest

from radar.models import AnalysisResult
from radar.openai_analysis import (
    attach_openai_usage,
    estimate_openai_cost_usd,
    parse_openai_json,
    smart_description_excerpt,
    strip_markdown_fences,
)


class FakeUsage:
    prompt_tokens = 1000
    completion_tokens = 250
    total_tokens = 1250


class OpenAIAnalysisTest(unittest.TestCase):
    def test_strip_markdown_fences_handles_json_fence(self) -> None:
        content = '```json\n{"score": 7}\n```'

        self.assertEqual('{"score": 7}', strip_markdown_fences(content))

    def test_parse_openai_json_handles_markdown_fenced_json(self) -> None:
        content = (
            '```json\n{"score": 7, "fit_reason": "Good fit", '
            '"risks": "", "generated_reply": "Hi"}\n```'
        )
        result = parse_openai_json(
            content,
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

    def test_estimate_openai_cost_uses_per_million_prices(self) -> None:
        cost = estimate_openai_cost_usd(
            prompt_tokens=1000,
            completion_tokens=250,
            input_cost_per_1m=0.1,
            output_cost_per_1m=0.8,
        )

        assert cost is not None
        self.assertAlmostEqual(
            0.0003,
            cost,
        )

    def test_attach_openai_usage_adds_tokens_and_cost(self) -> None:
        result = attach_openai_usage(
            AnalysisResult(score=7, fit_reason="", risks="", generated_reply=""),
            FakeUsage(),
            input_cost_per_1m=0.1,
            output_cost_per_1m=0.8,
        )

        self.assertEqual(1000, result.prompt_tokens)
        self.assertEqual(250, result.completion_tokens)
        self.assertEqual(1250, result.total_tokens)
        self.assertAlmostEqual(0.0003, result.estimated_cost_usd or 0)

    def test_smart_description_excerpt_keeps_relevant_sections(self) -> None:
        description = "\n\n".join(
            [
                "Intro paragraph about the company.",
                "Another intro line.",
                "Perks and culture text that can be dropped.",
                "Requirements: Python, Django, PostgreSQL.",
                "Responsibilities: build APIs and integrations.",
                "Format: remote, part-time.",
            ]
        )

        excerpt = smart_description_excerpt(description, max_chars=140)

        self.assertIn("Intro paragraph", excerpt)
        self.assertIn("Requirements", excerpt)
        self.assertNotIn("Perks and culture", excerpt)


if __name__ == "__main__":
    unittest.main()
