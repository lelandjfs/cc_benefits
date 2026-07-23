# Card Benefits Tracker

Tracks every benefit on Chase Sapphire Reserve (personal) + Amex Gold, pulls real
transactions via Plaid, and writes usage into a Google Sheet weekly via GitHub Actions.

Sheet: https://docs.google.com/spreadsheets/d/1lRKGMfQ9QiVRm_hOEZv2-OTBHiZ-jCGSfINPEG3VZvY

```
Plaid (your cards) ──► GitHub Action (weekly) ──► benefits_usage.json + summary.md ──► Google Sheet
```

## Files
| File | What it does |
|---|---|
| `benefits_engine.py` | Logic: transactions → per-benefit usage. Edit `RULES` here to tune matching. |
| `plaid_sync.py` | Fetches new transactions, runs the engine, writes local outputs. |
| `sheet_updater.py` | Pushes computed usage into the Sheet's "Usage Tracker" tab. |
| `link_setup.py` | One-time: connects a card, prints its Plaid access token. |
| `build_workbook.py` | Regenerates the whole Sheet from scratch (catalog + tabs) if needed. |
| `.github/workflows/weekly.yml` | Runs the sync every Monday, and on demand. |

## Status
- [x] Comprehensive benefits catalog built (credits, multipliers, memberships, insurance)
- [x] Google Sheet created (5 tabs)
- [x] Plaid pipeline validated against Sandbox
- [ ] Production Plaid keys (pending Plaid approval)
- [ ] Cards linked (`link_setup.py`) with production tokens
- [ ] Google service account created + wired to GitHub Secrets
- [ ] First live GitHub Actions run

## Setup — once production Plaid access lands

### 1. Link your cards
```bash
cd cc_benefits
pip install -r requirements.txt
PLAID_CLIENT_ID=... PLAID_SECRET=<production secret> PLAID_ENV=production \
  python3 link_setup.py "Amex Gold"
# repeat for "Chase CSR", combine both into one JSON:
# {"Amex Gold": "access-production-xxxx", "Chase CSR": "access-production-yyyy"}
```

### 2. Create a Google service account (so GitHub Actions can write to the Sheet headlessly)
1. console.cloud.google.com → new/existing project → **APIs & Services → Library** → enable **Google Sheets API**.
2. **APIs & Services → Credentials → Create Credentials → Service Account**. Name it anything.
3. Open the service account → **Keys → Add Key → Create new key → JSON**. Downloads a JSON file.
4. Open the Sheet → **Share** → paste the service account's email (looks like `...@...iam.gserviceaccount.com`) → give **Editor**.

### 3. Add GitHub repo secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:
- `PLAID_CLIENT_ID`, `PLAID_SECRET` (production), `PLAID_ENV=production`, `PLAID_ACCESS_TOKENS` (JSON from step 1)
- `GOOGLE_SERVICE_ACCOUNT_JSON` — paste the full contents of the JSON key file from step 2
- `GOOGLE_SHEET_ID` — `1lRKGMfQ9QiVRm_hOEZv2-OTBHiZ-jCGSfINPEG3VZvY`

### 4. Run it once to validate
Repo → **Actions → Weekly benefits sync → Run workflow**. Check the Sheet's Usage Tracker tab updated.

## Notes
- CSR Exclusive Tables and the Amex Resy credit depend on curated restaurant lists that change
  weekly/monthly — the engine flags qualifying merchant activity, but the Sheet's Dining Lists tab
  links the live source since a hardcoded restaurant list would go stale fast.
- Global Entry/TSA PreCheck ($120/4yr) isn't auto-tracked (one-time, irregular period) — check it
  off manually in the Sheet when used.
- Rotate the Plaid secret anytime in the dashboard; re-run `link_setup.py` to refresh tokens.
