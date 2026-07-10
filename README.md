# Marathon Tracker — Setup Guide (GitHub-backed)

Streamlit app with no external database: your plan and run log are two CSVs in this repo, read and written through the GitHub API. Every logged run is a commit.

## 1. Create the repo

New GitHub repo (private is fine) containing:

```
app.py
requirements.txt
plan.csv       <- your training plan
runs.csv       <- headers only; the app appends to it
```

**plan.csv** — replace the sample rows with your real plan (dates can be `2026-08-03` or `8/3/2026`):

```csv
Week,Start Date,Planned Miles
1,2026-08-03,22
2,2026-08-10,25
```

Easiest way to get this from your existing Google Sheet: File → Download → CSV, then trim to these three columns.

**runs.csv** — just the header line:

```csv
Date,Miles,Note
```

## 2. Create a fine-grained personal access token

1. GitHub → Settings → Developer settings → **Personal access tokens → Fine-grained tokens** → Generate new token.
2. Repository access: **Only select repositories** → pick this repo.
3. Permissions → Repository permissions → **Contents: Read and write**. Nothing else.
4. Expiration: up to you — set it past January 2027 so it doesn't die mid-training block.
5. Generate and copy the token (starts with `github_pat_`). You won't see it again.

## 3. Deploy on Streamlit Community Cloud

1. https://share.streamlit.io → **New app** → this repo, branch `main`, file `app.py`.
2. **App settings → Secrets** — paste:

```toml
[github]
token = "github_pat_XXXXXXXXXXXX"
repo = "yourusername/your-repo-name"

[app]
race_date = "2027-01-17"
```

3. Deploy. Add the app URL to your phone's home screen (browser Share → Add to Home Screen).

## Day-to-day

- Log runs from the app; each one commits to `runs.csv`.
- To fix or delete a run: use the **Delete a run** expander in the app, or edit `runs.csv` directly on GitHub (mobile web works fine).
- To revise your plan: edit `plan.csv` in the repo — the app picks it up on next refresh.
- Reads cache for 2 minutes; the **Refresh** button forces a re-read.
- Your entire training history is in the repo's commit log.

## Sharing

Anyone with the app URL can view and log runs (Community Cloud apps are public by default — you can restrict viewers to specific emails in app settings if you'd rather keep it to yourself).

## Local testing (optional)

Put the same TOML in `.streamlit/secrets.toml` (gitignore it), then:

```
pip install -r requirements.txt
streamlit run app.py
```
