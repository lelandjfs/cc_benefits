"""
backfill_supabase.py  —  one-time (or re-runnable) full-history pull from Plaid into Supabase.

Calls /transactions/sync from an empty cursor for each linked card, paginating through
`has_more`, and upserts every transaction Plaid will give us into the `transactions` table
via Supabase's REST API (PostgREST) over plain HTTPS — GitHub Actions runners don't have
IPv6 egress, and Supabase's direct Postgres connection (db.<ref>.supabase.co:5432) only
resolves to IPv6, so a raw TCP connection fails there even though it works locally.
Also saves the final cursor into `sync_state` so plaid_sync.py can pick up incremental
syncs from there afterward instead of re-pulling everything each week.

Env (from GitHub Secrets):
  PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV,
  PLAID_ACCESS_TOKENS = '{"Amex Gold":"access-...","Chase CSR":"access-..."}'
  SUPABASE_URL, SUPABASE_SECRET_KEY
"""
import os, json, sys
import requests

PLAID_CLIENT_ID = os.environ["PLAID_CLIENT_ID"]
PLAID_SECRET    = os.environ["PLAID_SECRET"]
PLAID_ENV       = os.environ.get("PLAID_ENV", "production")
PLAID_BASE      = f"https://{PLAID_ENV}.plaid.com"
TOKENS          = json.loads(os.environ["PLAID_ACCESS_TOKENS"])
CARD_DISPLAY    = {"Amex Gold": "Amex Gold", "Chase CSR": "Chase Sapphire Reserve"}

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}
BATCH_SIZE = 500


def plaid_call(path, payload):
    r = requests.post(PLAID_BASE + path, json={"client_id": PLAID_CLIENT_ID, "secret": PLAID_SECRET, **payload}, timeout=45)
    if r.status_code >= 300:
        print("Plaid error:", r.status_code, r.text[:600]); sys.exit(1)
    return r.json()


def supabase_upsert(table, rows, conflict_col):
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={conflict_col}",
                           headers=SB_HEADERS, json=chunk, timeout=30)
        if r.status_code >= 300:
            print("Supabase error:", r.status_code, r.text[:600]); sys.exit(1)


def backfill_card(label, access_token):
    display = CARD_DISPLAY.get(label, label)
    cursor = None
    all_txns = []
    while True:
        req = {"access_token": access_token}
        if cursor:
            req["cursor"] = cursor
        resp = plaid_call("/transactions/sync", req)
        all_txns.extend(resp["added"] + resp["modified"])
        cursor = resp["next_cursor"]
        if not resp["has_more"]:
            break

    rows = [
        {"plaid_transaction_id": t["transaction_id"], "card": display, "date": t["date"],
         "amount": t["amount"], "merchant_name": t.get("merchant_name"), "name": t.get("name"),
         "category": (t.get("personal_finance_category") or {}).get("primary")}
        for t in all_txns
    ]
    supabase_upsert("transactions", rows, "plaid_transaction_id")
    supabase_upsert("sync_state", [{"card": display, "cursor": cursor}], "card")

    dates = sorted(t["date"] for t in all_txns)
    earliest, latest = (dates[0], dates[-1]) if dates else (None, None)
    print(f"{display}: {len(all_txns)} transactions, range {earliest} to {latest}")


def main():
    for label, token in TOKENS.items():
        backfill_card(label, token)


if __name__ == "__main__":
    main()
