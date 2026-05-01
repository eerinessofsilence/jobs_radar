import unittest

from radar.urls import normalize_url


class UrlsTest(unittest.TestCase):
    def test_normalize_url_removes_tracking_params_and_trailing_slash(self) -> None:
        self.assertEqual(
            "https://example.com/jobs?id=42&source=rss",
            normalize_url(
                "https://EXAMPLE.com/jobs/?utm_source=newsletter&id=42&fbclid=abc&source=rss"
            ),
        )

    def test_normalize_url_keeps_root_path(self) -> None:
        self.assertEqual("https://example.com/", normalize_url("https://example.com/"))


if __name__ == "__main__":
    unittest.main()
