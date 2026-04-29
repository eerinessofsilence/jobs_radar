# Job Radar

Automated job radar for GitHub Actions. It reads DOU and Djinni RSS feeds, filters vacancies by configured keywords, analyzes new vacancies with OpenAI, appends results to Google Sheets, and sends a Telegram summary.

The script does not auto-apply to jobs. It only generates draft replies.

## Files

- `job_radar.py` - main runner
- `job_radar_config.json` - editable radar profile, keywords, headers, RSS defaults, and prompt settings
- `requirements.txt` - Python dependencies
- `.github/workflows/job-radar.yml` - GitHub Actions workflow
- `.env.example` - local environment template

## Google Sheet Setup

Create a Google Sheet and add this exact header row in row 1:

```text
Found Date | Source | Title | Company | Location | Salary | URL | Published Date | Matched Keywords | Score | Fit Reason | Risks | Generated Reply | Status | Notes
```

The script will create the header row if the first worksheet is empty. If your sheet already has headers, keep the names above so appends land in the expected columns.

The canonical header list lives in `job_radar_config.json` under `sheet_headers`.

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

## Radar Config

Edit `job_radar_config.json` to change non-secret radar behavior without touching Python code:

- `candidate_profile` - profile OpenAI uses to judge each vacancy.
- `experience` - target seniority and years-of-experience limits.
- `keywords` - title + description keyword filter before OpenAI analysis.
- `negative_prefilter` - conservative title/text filters that skip obvious non-fits before OpenAI.
- `default_rss_urls` - default DOU and Djinni RSS URLs.
- `sheet_headers` - Google Sheet columns and append order.
- `analysis` - prompt guidance, max description length, and OpenAI system prompt.
- `row_defaults` - default values such as `Status` and `Notes`.

You can add extra `sheet_headers`; they will be appended as blank/default columns. Keep the existing core header names unless you also update the Python field mapping.

Use `candidate_profile` for skills, preferred work type, domains, and deal-breakers. Use `experience` for seniority filtering:

- `target_level` - broad level, for example `Junior to Middle, not higher than Middle`.
- `candidate_years` - your actual experience, for example `2 years commercial experience plus pet/freelance projects`.
- `preferred_required_years` - vacancy requirements you prefer, for example `0-4 years`.
- `max_required_years` - hard numeric threshold used in the prompt to penalize vacancies above that requirement.
- `guidance` - extra seniority rules in plain English.

Use `negative_prefilter` to save OpenAI calls on obvious non-fits. `title_keywords` are checked against the vacancy title. `description_phrases` are checked against title + description, so keep them conservative to avoid false skips.

By default, the script reads `job_radar_config.json` from the project directory. To use another file, set:

```env
JOB_RADAR_CONFIG=path/to/another_config.json
```

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

- `JOB_RADAR_CONFIG` - defaults to `job_radar_config.json`.
- `DOU_RSS_URLS` - defaults to `https://jobs.dou.ua/vacancies/feeds/`
- `DJINNI_RSS_URLS` - defaults to `https://djinni.co/jobs/rss/`
- `MIN_SCORE` - defaults to `5`; only vacancies with this score or higher are appended and shown in the Telegram top list.
- `MAX_JOBS_PER_RUN` - defaults to `20`; limits OpenAI analysis per run.
- `OPENAI_MODEL` - defaults to `gpt-4o-mini`.
- `LOG_LEVEL` - defaults to `INFO`; use `DEBUG` for lower-level diagnostics.
- `LOG_COLOR` - defaults to `auto`; use `always` to force ANSI colors or `never` to disable them.

Multiple RSS URLs can be separated with commas, semicolons, or new lines.

## Running Manually

Open the Actions tab in GitHub, select `Job Radar`, and click `Run workflow`.

## Logs

Default `INFO` logs are compact:

- `[start]` - model, score range, minimum score, run limit, and feed count.
- `[fetch]` - DOU / Djinni / total fetched vacancies.
- `[filter]` - fetched, keyword-matched, negative-skipped, new, and tracked/duplicate counts.
- `[analyze]` - how many new vacancies are queued for OpenAI.
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
4. Applies `negative_prefilter` before OpenAI.
5. Loads existing URLs from Google Sheets.
6. Skips URLs already present in the sheet.
7. Limits OpenAI analysis to `MAX_JOBS_PER_RUN`.
8. Requests strict JSON from OpenAI with a configured 1-10 scoring rubric.
9. Recovers from invalid JSON by stripping markdown fences and extracting the first JSON object.
10. Appends analyzed vacancies whose score is at least `MIN_SCORE`.
11. Sends a Telegram summary with counts and the top 5 vacancies by score.

## Scoring

The score is configured in `job_radar_config.json` under `analysis`:

- `score_min` - default `1`
- `score_max` - default `10`
- `scoring_guidance` - general scoring rules
- `scoring_rubric` - concrete meaning of scores

Keywords are only the first filter: a vacancy must match at least one keyword before OpenAI analyzes it. Then `negative_prefilter` skips obvious non-fits. The final score is not a keyword count. OpenAI evaluates the whole remaining vacancy using the rubric: title, responsibilities, tech stack, experience requirements, remote/freelance/part-time/project fit, company/context clarity, salary if present, and risks.

Normal analyzed vacancies should receive `1-10`. Score `0` is reserved by the script for technical failures such as invalid OpenAI JSON or API errors.

Default appended row values are configured in `job_radar_config.json`:

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
