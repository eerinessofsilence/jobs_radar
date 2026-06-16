import unittest

from radar.robota import robota_payload, vacancy_from_robota_item


class RobotaTest(unittest.TestCase):
    def test_vacancy_from_robota_item_maps_core_fields(self) -> None:
        vacancy = vacancy_from_robota_item(
            {
                "id": "10526732",
                "title": "Python Developer",
                "description": "<p>Backend work with Python</p>",
                "sortDate": "2026-06-15T15:36:05.047",
                "sortDateText": "20 годин тому",
                "salary": {"amount": 25000, "amountFrom": 25000, "amountTo": 30000},
                "company": {"id": "15447580", "name": "Bravilo"},
                "city": {"id": "1", "name": "Київ"},
                "formApplyCustomUrl": "",
            },
            "python developer",
        )

        self.assertIsNotNone(vacancy)
        assert vacancy is not None
        self.assertEqual("Robota.ua", vacancy.source)
        self.assertEqual("Python Developer", vacancy.title)
        self.assertEqual("Bravilo", vacancy.company)
        self.assertEqual("Київ", vacancy.location)
        self.assertEqual("25000-30000 UAH", vacancy.salary)
        self.assertEqual("https://robota.ua/company15447580/vacancy10526732", vacancy.url)
        self.assertEqual("2026-06-15T15:36:05.047", vacancy.published_date)
        self.assertEqual("Backend work with Python", vacancy.description)
        self.assertEqual("python developer", vacancy.metadata["robota"]["keywords"])

    def test_robota_payload_uses_keyword_filter_and_page(self) -> None:
        payload = robota_payload("junior python developer", 2)

        self.assertEqual("getPublishedVacanciesList", payload["operationName"])
        self.assertEqual(2, payload["variables"]["pagination"]["page"])
        self.assertEqual(20, payload["variables"]["pagination"]["count"])
        self.assertEqual(
            "junior python developer",
            payload["variables"]["filter"]["keywords"],
        )


if __name__ == "__main__":
    unittest.main()
