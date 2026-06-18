import unittest

from radar.models import Vacancy
from radar.tech_stack import build_tech_stats, extract_tech_mentions, tech_stat_to_dict


def make_vacancy(
    title: str,
    description: str,
    source: str = "Fixture",
) -> Vacancy:
    return Vacancy(
        source=source,
        title=title,
        company="Example",
        location="Remote",
        salary="",
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        published_date="",
        description=description,
    )


class TechStackTest(unittest.TestCase):
    def test_extracts_categories_with_aliases(self) -> None:
        mentions = extract_tech_mentions(
            "Python backend with DRF, Postgres, Docker Compose and GitHub Actions."
        )
        pairs = {(mention.category, mention.technology) for mention in mentions}

        self.assertIn(("Languages", "Python"), pairs)
        self.assertIn(("Backend Frameworks", "Django REST Framework"), pairs)
        self.assertIn(("Databases", "PostgreSQL"), pairs)
        self.assertIn(("DevOps", "Docker Compose"), pairs)
        self.assertIn(("DevOps", "GitHub Actions"), pairs)

    def test_does_not_match_short_alias_inside_word(self) -> None:
        mentions = extract_tech_mentions("Django developer")
        pairs = {(mention.category, mention.technology) for mention in mentions}

        self.assertIn(("Backend Frameworks", "Django"), pairs)
        self.assertNotIn(("Languages", "Go"), pairs)

    def test_build_stats_counts_vacancies_not_mentions(self) -> None:
        vacancies = [
            make_vacancy("Python Developer", "Python, Python, FastAPI and Redis.", "Djinni"),
            make_vacancy("Backend Developer", "Fast API, PostgreSQL, Docker.", "Robota.ua"),
        ]

        stats = {stat.technology: tech_stat_to_dict(stat) for stat in build_tech_stats(vacancies)}

        self.assertEqual(1, stats["Python"]["count"])
        self.assertEqual(2, stats["FastAPI"]["count"])
        self.assertEqual(100.0, stats["FastAPI"]["percent"])
        self.assertEqual(["Djinni", "Robota.ua"], stats["FastAPI"]["sources"])

    def test_build_stats_dedupes_by_normalized_url(self) -> None:
        vacancy = make_vacancy("Python Developer", "Python and Django.", "Robota.ua")
        duplicate = make_vacancy("Python Developer", "Python and Django.", "Robota.ua")
        duplicate.url = vacancy.url + "?utm_source=x"

        stats = {
            stat.technology: tech_stat_to_dict(stat)
            for stat in build_tech_stats([vacancy, duplicate])
        }

        self.assertEqual(1, stats["Python"]["count"])
        self.assertEqual(1, stats["Python"]["total_vacancies"])


if __name__ == "__main__":
    unittest.main()
