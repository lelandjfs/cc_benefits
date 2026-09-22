# Card Benefits Tracker

Tracks every benefit on Chase Sapphire Reserve (personal) + Amex Gold, pulls real
transactions via Plaid, and writes usage into a private Google Sheet weekly via GitHub Actions.

```
Plaid (your cards) ──► GitHub Action (weekly) ──► Supabase (durable transaction store)
                                                        │
                                                        ▼
                                benefits_usage.json + summary.md ──► Google Sheet
```

Raw transactions live in Supabase (`transactions` + `sync_state` tables), not just an ephemeral
GitHub Actions cache — so history survives indefinitely and is directly queryable (e.g. via the
Supabase SQL editor) instead of only visible through the aggregated Sheet.

## Files
| File | What it does |
|---|---|
| `benefits_engine.py` | Logic: transactions → per-benefit usage. Edit `RULES` here to tune matching. |
| `plaid_sync.py` | Fetches new transactions, upserts them into Supabase, runs the engine, writes local outputs. |
| `backfill_supabase.py` | One-time (or re-runnable) full-history pull from Plaid into Supabase. Run via the "Backfill transactions to Supabase" GitHub Action. |
| `sheet_updater.py` | Pushes computed usage into the Sheet's "Usage Tracker" tab. |
| `link_setup.py` | One-time: connects a card, prints its Plaid access token. |
| `build_workbook.py` | Regenerates the whole Sheet from scratch (catalog + tabs) if needed. |
| `.github/workflows/weekly.yml` | Runs the sync every Monday, and on demand. |
| `.github/workflows/backfill.yml` | On-demand full-history backfill into Supabase. |

## Status
- [x] Comprehensive benefits catalog built (credits, multipliers, memberships, insurance)
- [x] Google Sheet created (5 tabs)
- [x] Production Plaid keys + both cards linked
- [x] Google service account wired to GitHub Secrets
- [x] Weekly GitHub Action live (Mondays, 6am PT)
- [x] Supabase transaction store (`transactions`, `sync_state`) backing the pipeline
- [ ] Full YTD history — current backfill only reaches ~105 days back (Plaid's default lookback
      at initial Link time). Getting further back means re-linking both cards with
      `transactions.days_requested` set, which requires logging into Amex/Chase again.

## Setup (already done — kept here for reference / re-linking)

### 1. Link your cards
```bash
cd cc_benefits
pip install -r requirements.txt
PLAID_CLIENT_ID=... PLAID_SECRET=<production secret> PLAID_ENV=production \
  python3 link_setup.py "Amex Gold"
# repeat for "Chase CSR", combine both into one JSON:
# {"Amex Gold": "access-production-xxxx", "Chase CSR": "access-production-yyyy"}
```
To get more than ~105 days of history (Plaid's default lookback), this needs
`transactions.days_requested` set in `link_setup.py`'s `/link/token/create` call before
re-linking — history depth is fixed at the moment a Plaid Item is created and can't be
extended retroactively on an existing Item.

### 2. Create a Google service account (so GitHub Actions can write to the Sheet headlessly)
1. console.cloud.google.com → new/existing project → **APIs & Services → Library** → enable **Google Sheets API**.
2. **APIs & Services → Credentials → Create Credentials → Service Account**. Name it anything.
3. Open the service account → **Keys → Add Key → Create new key → JSON**. Downloads a JSON file.
4. Open the Sheet → **Share** → paste the service account's email (looks like `...@...iam.gserviceaccount.com`) → give **Editor**.

### 3. Create the Supabase tables
In the Supabase SQL editor:
```sql
CREATE TABLE transactions (
    plaid_transaction_id TEXT PRIMARY KEY,
    card TEXT NOT NULL,
    date DATE NOT NULL,
    amount NUMERIC NOT NULL,
    merchant_name TEXT,
    name TEXT,
    category TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_transactions_card_date ON transactions (card, date);
CREATE TABLE sync_state (card TEXT PRIMARY KEY, cursor TEXT);
```

### 4. Add GitHub repo secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:
- `PLAID_CLIENT_ID`, `PLAID_SECRET` (production), `PLAID_ENV=production`, `PLAID_ACCESS_TOKENS` (JSON from step 1)
- `GOOGLE_SERVICE_ACCOUNT_JSON` — paste the full contents of the JSON key file from step 2
- `GOOGLE_SHEET_ID` — the ID from your target Sheet's URL (the segment after `/d/`)
- `SUPABASE_URL` — the project URL (e.g. `https://<ref>.supabase.co`)
- `SUPABASE_SECRET_KEY` — the project's secret API key (Project Settings → API Keys). Uses
  PostgREST over HTTPS rather than a raw Postgres connection string, since GitHub Actions
  runners don't have IPv6 egress and Supabase's direct `db.<ref>.supabase.co:5432` connection
  only resolves to IPv6.

### 5. Backfill + validate
Repo → **Actions → Backfill transactions to Supabase → Run workflow** to pull available history in.
Then **Actions → Weekly benefits sync → Run workflow** and check the Sheet's Usage Tracker tab updated.

## Notes
- CSR Exclusive Tables and the Amex Resy credit depend on curated restaurant lists that change
  weekly/monthly — the engine flags qualifying merchant activity, but the Sheet's Dining Lists tab
  links the live source since a hardcoded restaurant list would go stale fast.
- Global Entry/TSA PreCheck ($120/4yr) isn't auto-tracked (one-time, irregular period) — check it
  off manually in the Sheet when used.
- Rotate the Plaid secret anytime in the dashboard; re-run `link_setup.py` to refresh tokens.
