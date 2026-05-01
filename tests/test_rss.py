import unittest

import feedparser
from radar.rss import extract_salary, normalize_entry

RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Jobs</title>
    <item>
      <title>Python Developer $2,000-3,000 at Acme</title>
      <link>https://example.com/jobs/python/?utm_source=rss&amp;id=42</link>
      <pubDate>Wed, 29 Apr 2026 12:30:00 +0300</pubDate>
      <description><![CDATA[
        <p>Location: Remote</p>
        <p>Requirements: Python, Django, REST API.</p>
      ]]></description>
    </item>
  </channel>
</rss>
"""


class RssTest(unittest.TestCase):
    def test_normalize_entry_parses_feed_fixture(self) -> None:
        parsed = feedparser.parse(RSS_FIXTURE)

        vacancy = normalize_entry(parsed.entries[0], "Fixture")

        self.assertIsNotNone(vacancy)
        assert vacancy is not None
        self.assertEqual("Python Developer $2,000-3,000 at Acme", vacancy.title)
        self.assertEqual("Fixture", vacancy.source)
        self.assertEqual("Acme", vacancy.company)
        self.assertEqual("Remote", vacancy.location)
        self.assertEqual("$2,000-3,000", vacancy.salary)
        self.assertEqual("https://example.com/jobs/python?id=42", vacancy.url)
        self.assertEqual("2026-04-29T09:30:00+00:00", vacancy.published_date)
        self.assertIn("Python, Django, REST API.", vacancy.description)

    def test_extract_salary_uses_explicit_description_line(self) -> None:
        salary = extract_salary(
            {},
            "Backend Developer",
            "Compensation: 2500-3500 USD based on experience",
        )

        self.assertEqual("2500-3500 USD", salary)

    def test_extract_salary_rejects_implausible_plain_small_numbers(self) -> None:
        salary = extract_salary({}, "Backend Developer", "Salary: 20 days vacation")

        self.assertEqual("", salary)


if __name__ == "__main__":
    unittest.main()
