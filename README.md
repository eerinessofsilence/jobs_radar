# Job Radar

Automated job radar for GitHub Actions. It reads DOU and Djinni RSS feeds, filters vacancies by automation-related keywords, analyzes new vacancies with OpenAI, appends results to Google Sheets, and sends a Telegram summary.

The script does not auto-apply to jobs. It only generates draft replies.

## Files

- `job_radar.py` - main runner
- `requirements.txt` - Python dependencies
- `.github/workflows/job-radar.yml` - GitHub Actions workflow
- `.env.example` - local environment template

## Google Sheet Setup

Create a Google Sheet and add this exact header row in row 1:

```text
Found Date | Source | Title | Company | Location | Salary | URL | Published Date | Matched Keywords | Score | Fit Reason | Risks | Generated Reply | Status | Applied | Applied Date | Notes
```

The script will create the header row if the first worksheet is empty. If your sheet already has headers, keep the names above so appends land in the expected columns.

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

- `DOU_RSS_URLS` - defaults to `https://jobs.dou.ua/vacancies/feeds/`
- `DJINNI_RSS_URLS` - defaults to `https://djinni.co/jobs/rss/`
- `MIN_SCORE` - defaults to `0`; controls which analyzed jobs appear in the Telegram top list.
- `MAX_JOBS_PER_RUN` - defaults to `20`; limits OpenAI analysis per run.
- `OPENAI_MODEL` - defaults to `gpt-4o-mini`.

Multiple RSS URLs can be separated with commas, semicolons, or new lines.

## Running Manually

Open the Actions tab in GitHub, select `Job Radar`, and click `Run workflow`.

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
3. Matches keywords against title and description.
4. Loads existing URLs from Google Sheets.
5. Skips URLs already present in the sheet.
6. Limits OpenAI analysis to `MAX_JOBS_PER_RUN`.
7. Requests strict JSON from OpenAI.
8. Recovers from invalid JSON by stripping markdown fences and extracting the first JSON object.
9. Appends analyzed vacancies to Google Sheets.
10. Sends a Telegram summary with counts and the top 5 vacancies by score.

Rows are appended with:

- `Status` = `New`
- `Applied` = `false`
- `Applied Date` = empty
- `Notes` = empty
