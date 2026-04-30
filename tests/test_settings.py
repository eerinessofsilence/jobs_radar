import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from radar.settings import load_config_data, load_radar_settings_from_data, resolve_config_path


def minimal_profile() -> dict:
    return {
        "candidate_profile": "Backend developer",
        "experience": {"candidate_years": "3", "max_required_years": 3},
        "required_title_keywords": ["Developer"],
        "keywords": ["Python"],
        "negative_prefilter": {"enabled": True, "title_keywords": [], "description_phrases": []},
        "default_rss_urls": {"dou": ["https://example.com/dou"], "djinni": ["https://example.com/djinni"]},
    }


def minimal_settings() -> dict:
    return {
        "sheet_headers": ["URL"],
        "found_date_timezone": "UTC",
        "found_date_format": "%Y-%m-%d",
        "analysis": {
            "score_min": 1,
            "score_max": 10,
            "description_max_chars": 3000,
            "openai_system_prompt": "Return JSON.",
            "scoring_guidance": "Score fit.",
            "scoring_rubric": "1-10",
            "generated_reply_instruction": "Reply briefly.",
        },
        "row_defaults": {"Status": "New"},
    }


class SettingsTest(unittest.TestCase):
    def test_resolve_config_path_uses_project_root(self) -> None:
        self.assertEqual(Path.cwd() / "job_radar_profile.json", resolve_config_path("job_radar_profile.json"))

    def test_loads_split_config_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_path = Path(temp_dir) / "profile.json"
            settings_path = Path(temp_dir) / "settings.json"
            profile_path.write_text(json.dumps(minimal_profile()), encoding="utf-8")
            settings_path.write_text(json.dumps(minimal_settings()), encoding="utf-8")

            env = {
                "JOB_RADAR_PROFILE_CONFIG": str(profile_path),
                "JOB_RADAR_SETTINGS_CONFIG": str(settings_path),
                "JOB_RADAR_CONFIG": "",
            }
            with patch.dict(os.environ, env, clear=False):
                data = load_config_data()
                radar = load_radar_settings_from_data(data)

        self.assertEqual("Backend developer", radar.candidate_profile)
        self.assertEqual(3, radar.max_required_years)
        self.assertEqual("UTC", radar.found_date_timezone)
        self.assertEqual(["URL"], radar.sheet_headers)


if __name__ == "__main__":
    unittest.main()
