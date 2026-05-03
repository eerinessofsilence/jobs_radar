import tempfile
import unittest
from pathlib import Path

from radar.profile_setup import split_csv, write_profile


class ProfileSetupTest(unittest.TestCase):
    def test_split_csv_strips_empty_items(self) -> None:
        self.assertEqual(["Python", "Django"], split_csv(" Python, , Django "))

    def test_write_profile_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "profile.json"
            path.write_text("{}", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                write_profile({"candidate_profile": "test"}, path, force=False)


if __name__ == "__main__":
    unittest.main()
