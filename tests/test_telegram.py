import unittest

from radar.telegram import telegram_chunks


class TelegramTest(unittest.TestCase):
    def test_telegram_chunks_split_at_newline_when_possible(self) -> None:
        chunks = telegram_chunks("first line\nsecond line\nthird line", max_length=23)

        self.assertEqual(["first line\nsecond line", "third line"], chunks)

    def test_telegram_chunks_split_long_line_without_newline(self) -> None:
        chunks = telegram_chunks("abcdefghij", max_length=4)

        self.assertEqual(["abcd", "efgh", "ij"], chunks)


if __name__ == "__main__":
    unittest.main()
