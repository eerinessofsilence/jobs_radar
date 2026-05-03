# Job Radar

Automated job radar for GitHub Actions. It reads DOU and Djinni RSS feeds, filters vacancies by configured keywords, analyzes new vacancies with OpenAI, appends results to Google Sheets, and sends a Telegram summary.

The script does not auto-apply to jobs. It only generates draft replies.

## Files

- `job_radar.py` - thin entry point for the scheduled radar run
- `reset_sheet.py` - clears previous vacancy rows from Google Sheets without changing formatting
- `radar/` - application package with RSS feed loading, normalization, extraction, enrichment hooks, filters, OpenAI analysis, Sheets, Telegram, config loading, and orchestration
- `tests/` - unit tests
- `job_radar_profile.json` - personal search profile, keywords, experience limits, negative filters, and RSS defaults
- `job_radar_settings.json` - software settings such as headers, date formatting, scoring prompt, and row defaults
- `pyproject.toml` - Ruff, mypy, project scripts, and local quality-check tasks
- `requirements.in` - direct runtime dependencies
- `requirements.txt` - pinned runtime dependency lock
- `requirements-dev.in` / `requirements-dev.txt` - direct and pinned development dependencies
- `.github/workflows/job-radar.yml` - GitHub Actions workflow
- `.env.example` - local environment template

## Google Sheet Setup

Create a Google Sheet and add this exact header row in row 1:

```text
Found Date | Source | Title | Company | Location | Salary | URL | Published Date | Matched Keywords | Score | Fit Reason | Risks | Generated Reply | Status | Notes
```

The script will create the header row if the first worksheet is empty. If your sheet already has headers, keep the names above so appends land in the expected columns.

The canonical header list lives in `job_radar_settings.json` under `sheet_headers`.

The script also creates/uses a `Seen` worksheet tab automatically. It stores every URL that was successfully analyzed or locally pre-scored, including vacancies skipped because their score is below `MIN_SCORE`. This prevents the same low-score vacancy from being analyzed and paid for again on the next run. Technical failures with score `0` are not marked seen, so they can be retried later.

The script also creates/uses an `AnalysisCache` worksheet tab automatically. It stores successful OpenAI JSON responses by model and normalized URL so future runs can reuse the analysis without another OpenAI call.

The script also creates/uses a `Runs` worksheet tab automatically. Each radar run appends one row with model, fetched/matched/analyzed/appended counts, filter skips, tracked/seen/similar duplicates, run-limit skips, local pre-score/cache counts, low-score skips, token usage, estimated cost if configured, sheet URL, and any warnings/errors.

Recommended `Status` values:

```text
New | Interesting | Applied | Rejected | Later | No fit
```

If your existing sheet already has old `Applied` or `Applied Date` columns, delete them manually in Google Sheets after confirming you no longer need them. The script will not delete existing columns automatically.

Find `GOOGLE_SHEET_ID` in the sheet URL:

```text
https://docs.google.com/spreadsheets/d/<GOOGLE_SHEET_ID>/edit
```

## Google Service Account Credentials

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable the Google Sheets API.
4. Go to IAM & Admin -> Service Accounts.
5. Create a service account.
6. Open the service account, go to Keys, and create a JSON key.
7. Copy the full JSON file contents into `GOOGLE_SERVICE_ACCOUNT_JSON`.
8. In your Google Sheet, click Share and share the sheet with the service account email from the JSON field `client_email`.

`GOOGLE_SERVICE_ACCOUNT_JSON` may be stored as raw JSON or base64-encoded JSON. GitHub repository secrets can store the raw JSON directly.

## Telegram Setup

1. Open Telegram and message `@BotFather`.
2. Run `/newbot` and follow the prompts.
3. Copy the bot token into `TELEGRAM_BOT_TOKEN`.
4. Send any message to your new bot.
5. Open this URL in a browser, replacing `<TOKEN>`:

```text
https://api.telegram.org/bot<TOKEN>/getUpdates
```

6. Find `message.chat.id` in the response and use it as `TELEGRAM_CHAT_ID`.

For a group chat, add the bot to the group, send a message in the group, then use the group `chat.id`. Group IDs are often negative numbers.

## OpenAI Setup

Create an OpenAI API key and set it as `OPENAI_API_KEY`.

The default model is:

```text
gpt-4o-mini
```

Override it with `OPENAI_MODEL` if needed.

## Local Run

Use Python 3.11.

```bash
cp .env.example .env
pip install -r requirements.txt
python job_radar.py
```

Fill `.env` before running. For local use, put `GOOGLE_SERVICE_ACCOUNT_JSON` on one line or wrap it in quotes if your shell requires it.

For development checks, install dev dependencies:

```bash
pip install -r requirements-dev.txt
python -m poethepoet check
```

## Reset Google Sheet

Use `reset_sheet.py` to clear old vacancy rows while keeping the header row and existing Google Sheets formatting:

```bash
python reset_sheet.py --dry-run
python reset_sheet.py --yes
```

The reset script uses only `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`, and the radar config files. It clears values from row 2 down via the Google Sheets API, so formatting, column widths, colors, filters, and validation rules are not changed.

By default it resets the first worksheet. To target a specific worksheet tab, set `RESET_SHEET_WORKSHEET` or pass `--worksheet`:

```bash
python reset_sheet.py --yes --worksheet Sheet1
```

The reset command does not clear auxiliary worksheets unless you explicitly target them:

```bash
python reset_sheet.py --yes --worksheet Seen
python reset_sheet.py --yes --worksheet Runs
```

## Radar Config

Edit `job_radar_profile.json` for personal search criteria:

- `candidate_profile` - profile OpenAI uses to judge each vacancy.
- `experience` - target seniority and years-of-experience limits.
- `required_title_keywords` - developer-role title gate before OpenAI analysis.
- `keywords` - title + description keyword filter before OpenAI analysis.
- `negative_prefilter` - conservative title/text filters that skip obvious non-fits before OpenAI.
- `default_rss_urls` - default DOU and Djinni RSS URLs.

Edit `job_radar_settings.json` for software behavior:

- `sheet_headers` - Google Sheet columns and append order.
- `found_date_timezone` / `found_date_format` - display format for `Found Date` and `Published Date`; the default config writes compact local timestamps like `29.04.2026 16:12`.
- `analysis` - prompt guidance, max description length, and OpenAI system prompt.
- `row_defaults` - default values such as `Status` and `Notes`.

You can add extra `sheet_headers`; they will be appended as blank/default columns. Keep the existing core header names unless you also update the Python field mapping.

`Salary` is best-effort because DOU and Djinni RSS entries do not always expose a dedicated salary field. The parser checks explicit salary fields first, then salary-like values in the title, then explicit salary/compensation lines in the description.

Use `candidate_profile` for skills, preferred work type, domains, and deal-breakers. Use `experience` for seniority filtering:

- `target_level` - broad level, for example `Junior to Middle, not higher than Middle`.
- `candidate_years` - your actual experience, for example `2 years commercial experience plus pet/freelance projects`.
- `preferred_required_years` - vacancy requirements you prefer, for example `0-4 years`.
- `max_required_years` - hard numeric threshold used to skip vacancies that require more years before OpenAI analysis.
- `guidance` - extra seniority rules in plain English.

The experience prefilter rejects clear requirements above `max_required_years`, including forms like `4+ years`, `at least 4 years`, `more than 3 years`, `3-5 years`, and `Experience: 4 years`.

Use `negative_prefilter` to save OpenAI calls on obvious non-fits. `title_keywords` are checked against the vacancy title. `description_phrases` are checked against title + description, so keep them conservative to avoid false skips.

Use `required_title_keywords` to keep the radar focused on developer roles. A vacancy still needs to match the general `keywords`, but its title must also look like a backend, full-stack, frontend, Python, React, Node.js, API, or integration developer/engineer role.

By default, the script reads `job_radar_profile.json` and `job_radar_settings.json` from the project directory. To use different split config files, set:

```env
JOB_RADAR_PROFILE_CONFIG=path/to/profile.json
JOB_RADAR_SETTINGS_CONFIG=path/to/settings.json
```

Legacy single-file config is still supported through `JOB_RADAR_CONFIG`.

## GitHub Actions Setup

Push this project to a GitHub repository. Then open:

```text
Repository -> Settings -> Secrets and variables -> Actions
```

Add these repository secrets:

- `OPENAI_API_KEY` - from your OpenAI account.
- `GOOGLE_SHEET_ID` - from the Google Sheet URL between `/d/` and `/edit`.
- `GOOGLE_SERVICE_ACCOUNT_JSON` - the full Google service account JSON key contents.
- `TELEGRAM_BOT_TOKEN` - from Telegram `@BotFather`.
- `TELEGRAM_CHAT_ID` - from Telegram Bot API `getUpdates`.

Optional repository variables:

- `JOB_RADAR_PROFILE_CONFIG` - defaults to `job_radar_profile.json`.
- `JOB_RADAR_SETTINGS_CONFIG` - defaults to `job_radar_settings.json`.
- `JOB_RADAR_CONFIG` - optional legacy single-file config override.
- `DOU_RSS_URLS` - defaults to developer-focused DOU category feeds: Python, Front End, Node.js, and React Native.
- `DJINNI_RSS_URLS` - defaults to developer-focused Djinni category feeds: Python, Fullstack, React.js, Node.js, and React Native.
- `MIN_SCORE` - defaults to `5`; only vacancies with this score or higher are appended and shown in the Telegram top list.
- `MAX_JOBS_PER_RUN` - defaults to `20`; limits OpenAI analysis per run.
- `OPENAI_MODEL` - defaults to `gpt-4o-mini`.
- `OPENAI_TIMEOUT_SECONDS` - defaults to `60`; timeout for OpenAI analysis calls.
- `OPENAI_MAX_RETRIES` - defaults to `2`; retry count handled by the OpenAI client.
- `OPENAI_MAX_COMPLETION_TOKENS` - defaults to `700`; response token cap for each analysis.
- `OPENAI_INPUT_COST_PER_1M` / `OPENAI_OUTPUT_COST_PER_1M` - optional current model prices per 1M tokens. When set, logs include estimated OpenAI cost per analyzed vacancy.
- `LOG_LEVEL` - defaults to `INFO`; use `DEBUG` for lower-level diagnostics.
- `LOG_COLOR` - defaults to `auto`; use `always` to force ANSI colors or `never` to disable them.

Multiple RSS URLs can be separated with commas, semicolons, or new lines.

## Tests

Run the full local quality gate with:

```bash
python -m poethepoet check
```

Or run only unit tests with:

```bash
python -m unittest discover -s tests
```

## Running Manually

Open the Actions tab in GitHub, select `Job Radar`, and click `Run workflow`.

## Logs

Default `INFO` logs are compact:

- `[start]` - model, score range, minimum score, run limit, and feed count.
- `[fetch]` - DOU / Djinni / total fetched vacancies.
- `[filter]` - fetched, keyword-matched, title-skipped, experience-skipped, negative-skipped, new, and tracked/duplicate counts.
- `[analyze]` - how many new vacancies are queued for OpenAI.
- `[openai]` - token usage per analyzed vacancy and estimated cost if token prices are configured.
- `[result]` - one line per analyzed vacancy with score and `append` or `skip<N`.
- `[sheet]` - rows eligible for append and rows skipped below `MIN_SCORE`.
- `[done]` - final counters and Telegram status.

Detailed URL, matched keywords, fit reason, and risks are logged only in `DEBUG`.

Set `LOG_LEVEL=DEBUG` in `.env` or GitHub variables if you need lower-level diagnostics.
Set `LOG_COLOR=always` if your terminal supports ANSI colors but auto-detection does not enable them. Set `LOG_COLOR=never` or `NO_COLOR=1` to disable colors.

## Schedule

The workflow runs every day at 06:00 and 15:00 UTC:

```yaml
- cron: "0 6 * * *"
- cron: "0 15 * * *"
```

Edit `.github/workflows/job-radar.yml` to change the schedule.

## Adding Work.ua and robota.ua Later via Gmail Alerts

Keep DOU and Djinni collection RSS-only. For Work.ua and robota.ua, a practical later path is:

1. Create saved job searches or email alerts on Work.ua and robota.ua.
2. Send those alerts to Gmail.
3. Export matching emails or connect the Gmail API.
4. Add a collector that parses those messages into the same `Vacancy` structure used by `job_radar.py`.
5. Return those vacancies from `collect_email_alert_vacancies()`.

This avoids browser automation and avoids scraping protected/private pages.

## What the Script Does

1. Fetches DOU and Djinni RSS feeds.
2. Parses RSS items into normalized vacancy records.
3. Matches configured keywords against title and description.
4. Applies `required_title_keywords` to keep the queue focused on developer roles.
5. Applies the hard experience prefilter before OpenAI.
6. Applies `negative_prefilter` before OpenAI.
7. Loads existing URLs from Google Sheets.
8. Skips URLs already present in the sheet.
9. Deduplicates similar vacancies by normalized source, company, and title.
10. Interleaves new vacancies by source before applying `MAX_JOBS_PER_RUN`, so one source does not crowd out the other.
11. Limits OpenAI analysis to `MAX_JOBS_PER_RUN`.
12. Reuses cached OpenAI analysis from `AnalysisCache` when the model and URL match.
13. Locally pre-scores obvious non-fits before OpenAI.
14. Sends a compacted vacancy description to OpenAI, prioritizing intro, requirements, responsibilities, stack, format, and salary sections.
15. Requests strict JSON from OpenAI with a configured 1-10 scoring rubric, timeout, retry count, and completion-token cap.
16. Recovers from invalid JSON by stripping markdown fences and extracting the first JSON object.
17. Appends analyzed vacancies whose score is at least `MIN_SCORE`.
18. Marks successfully analyzed vacancies in the `Seen` worksheet to avoid re-analyzing low-score repeats.
19. Appends successful OpenAI responses to `AnalysisCache`.
20. Appends one run-history row to the `Runs` worksheet with counts, skips, token usage, and warnings.
21. Sends a Telegram summary with the same operational context, a Google Sheet link, and the top 5 vacancies by score.

## Scoring

The score is configured in `job_radar_settings.json` under `analysis`:

- `score_min` - default `1`
- `score_max` - default `10`
- `scoring_guidance` - general scoring rules
- `scoring_rubric` - concrete meaning of scores

Keywords are only the first filter: a vacancy must match at least one keyword before OpenAI analyzes it. Then the experience prefilter and `negative_prefilter` skip obvious non-fits. The final score is not a keyword count. OpenAI evaluates the whole remaining vacancy using the rubric: title, responsibilities, tech stack, experience requirements, remote/freelance/part-time/project fit, company/context clarity, salary if present, and risks.

Normal analyzed vacancies should receive `1-10`. Score `0` is reserved by the script for technical failures such as invalid OpenAI JSON or API errors.

Default appended row values are configured in `job_radar_settings.json`:

- `Status` = `New`
- `Notes` = empty

## Troubleshooting

### OpenAI 429 insufficient_quota

If the log says `OpenAI quota is exhausted` or `insufficient_quota`, the RSS and Google Sheets parts are working, but the OpenAI API key cannot make paid API calls.

Check:

1. Billing is active in your OpenAI account.
2. The API key belongs to the correct OpenAI project.
3. The project has available usage budget / limits.
4. `OPENAI_API_KEY` in `.env` or GitHub Secrets is the current key.

After fixing billing or limits, run `python job_radar.py` again. The script does not append vacancies that were not analyzed because of exhausted quota.
