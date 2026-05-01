from __future__ import annotations

import argparse
import logging
import os
import sys

import gspread
from dotenv import load_dotenv

from .settings import load_default_radar_settings, require_env
from .sheets import build_gspread_client, column_letter


def data_rows_clear_range(values: list[list[str]], configured_headers: list[str]) -> str | None:
    if len(values) <= 1:
        return None

    max_columns = max([len(row) for row in values] + [len(configured_headers), 1])
    return f"A2:{column_letter(max_columns)}{len(values)}"


def open_reset_worksheet(
    client: gspread.Client,
    sheet_id: str,
    worksheet_title: str,
) -> gspread.Worksheet:
    spreadsheet = client.open_by_key(sheet_id)
    if worksheet_title:
        return spreadsheet.worksheet(worksheet_title)
    return spreadsheet.sheet1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clear all vacancy data rows from the Google Sheet without changing formatting. "
            "The header row is kept."
        )
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually clear the sheet data rows. Required unless --dry-run is used.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the range that would be cleared without changing the sheet.",
    )
    parser.add_argument(
        "--worksheet",
        default=os.getenv("RESET_SHEET_WORKSHEET", ""),
        help="Worksheet title to reset. Defaults to the first worksheet.",
    )
    return parser.parse_args()


def run() -> int:
    load_dotenv()
    args = parse_args()
    from .logging_utils import setup_logging

    setup_logging()

    if not args.yes and not args.dry_run:
        logging.error("[sheet] Refusing to clear data without --yes. Use --dry-run to preview.")
        return 2

    radar = load_default_radar_settings()
    sheet_id = require_env("GOOGLE_SHEET_ID")
    service_account_json = require_env("GOOGLE_SERVICE_ACCOUNT_JSON")

    client = build_gspread_client(service_account_json)
    worksheet = open_reset_worksheet(client, sheet_id, args.worksheet.strip())
    values = worksheet.get_all_values()
    clear_range = data_rows_clear_range(values, radar.sheet_headers)

    if not clear_range:
        logging.info("[sheet] No data rows to clear in worksheet %r.", worksheet.title)
        return 0

    data_rows = len(values) - 1
    logging.info(
        "[sheet] worksheet=%r | rows=%s | range=%s",
        worksheet.title,
        data_rows,
        clear_range,
    )

    if args.dry_run:
        logging.info("[sheet] dry-run only; no values were cleared.")
        return 0

    worksheet.batch_clear([clear_range])
    logging.info("[sheet] cleared %s data rows without changing formatting.", data_rows)
    return 0


if __name__ == "__main__":
    sys.exit(run())
