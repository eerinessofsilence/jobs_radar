from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .settings import (
    DEFAULT_PROFILE_CONFIG_PATH,
    DEFAULT_PROFILE_EXAMPLE_CONFIG_PATH,
    load_json_file,
    project_root,
)


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def join_csv(values: list[str]) -> str:
    return ", ".join(values)


def prompt_value(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def prompt_int(label: str, default: int | None = None) -> int | None:
    while True:
        raw_default = "" if default is None else str(default)
        raw_value = prompt_value(label, raw_default)
        if not raw_value:
            return None
        try:
            value = int(raw_value)
        except ValueError:
            print("Please enter a whole number or leave it empty.")
            continue
        if value < 0:
            print("Please enter 0 or a positive number.")
            continue
        return value


def prompt_csv(label: str, default: list[str]) -> list[str]:
    value = prompt_value(label, join_csv(default))
    return split_csv(value)


def prompt_multiline(label: str, default: str = "") -> str:
    print(label)
    if default:
        print(f"Default: {default}")
    print("Enter one or more lines. Submit an empty line when done.")
    lines: list[str] = []
    while True:
        line = input("> ").strip()
        if not line:
            break
        lines.append(line)
    return " ".join(lines).strip() or default


def build_profile_from_answers(template: dict[str, Any]) -> dict[str, Any]:
    experience = template.get("experience", {})
    negative_prefilter = template.get("negative_prefilter", {})

    profile = dict(template)
    profile["candidate_profile"] = prompt_multiline(
        "Describe your target jobs, strengths, preferred format, and deal-breakers.",
        str(template.get("candidate_profile", "")),
    )
    profile["experience"] = {
        "target_level": prompt_value(
            "Target seniority",
            str(experience.get("target_level", "")),
        ),
        "candidate_years": prompt_value(
            "Your experience",
            str(experience.get("candidate_years", "")),
        ),
        "preferred_required_years": prompt_value(
            "Preferred vacancy requirement",
            str(experience.get("preferred_required_years", "")),
        ),
        "max_required_years": prompt_int(
            "Hard max required years",
            experience.get("max_required_years"),
        ),
        "guidance": prompt_value(
            "Extra seniority guidance",
            str(experience.get("guidance", "")),
        ),
    }
    profile["keywords"] = prompt_csv(
        "Keywords to search for, comma-separated",
        [str(value) for value in template.get("keywords", [])],
    )
    profile["required_title_keywords"] = prompt_csv(
        "Allowed title keywords, comma-separated",
        [str(value) for value in template.get("required_title_keywords", [])],
    )
    profile["negative_prefilter"] = {
        "enabled": True,
        "title_keywords": prompt_csv(
            "Title keywords to skip, comma-separated",
            [str(value) for value in negative_prefilter.get("title_keywords", [])],
        ),
        "description_phrases": prompt_csv(
            "Description phrases to skip, comma-separated",
            [str(value) for value in negative_prefilter.get("description_phrases", [])],
        ),
    }
    return profile


def write_profile(profile: dict[str, Any], output_path: Path, force: bool = False) -> None:
    if output_path.exists() and not force:
        raise RuntimeError(f"{output_path} already exists. Use --force to overwrite it.")
    output_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a local, git-ignored job_radar_profile.json from guided prompts.",
    )
    parser.add_argument(
        "--template",
        default=str(project_root() / DEFAULT_PROFILE_EXAMPLE_CONFIG_PATH),
        help="Profile template JSON path.",
    )
    parser.add_argument(
        "--output",
        default=str(project_root() / DEFAULT_PROFILE_CONFIG_PATH),
        help="Output profile JSON path.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output file.")
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    template_path = Path(args.template).expanduser()
    output_path = Path(args.output).expanduser()
    template = load_json_file(template_path)
    profile = build_profile_from_answers(template)
    write_profile(profile, output_path, force=args.force)
    print(f"Saved local profile to {output_path}")
    print(
        "This file is ignored by git. For GitHub Actions, store its JSON as JOB_RADAR_PROFILE_JSON."
    )


if __name__ == "__main__":
    run()
