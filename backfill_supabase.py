"""
backfill_supabase.py  —  one-time (or re-runnable) full-history pull from Plaid into Supabase.

Calls /transactions/sync from an empty cursor for each linked card, paginating through
`has_more`, and upserts every transaction Plaid will give us into the `transactions` table.
Also saves the final cursor into `sync_state` so plaid_sync.py can pick up incremental
syncs from there afterward instead of re-pulling everything each week.

Env (from GitHub Secrets):
  PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV,
  PLAID_ACCESS_TOKENS = '{"Amex Gold":"access-...","Chase CSR":"access-..."}'
  SUPABASE_DB_URL
"""
import os, json, sys
import requests
import psycopg2
from psycopg2.extras import execute_values

CLIENT_ID = os.environ["PLAID_CLIENT_ID"]
SECRET    = os.environ["PLAID_SECRET"]
ENV       = os.environ.get("PLAID_ENV", "production")
BASE      = f"https://{ENV}.plaid.com"
TOKENS    = json.loads(os.environ["PLAID_ACCESS_TOKENS"])
DB_URL    = os.environ["SUPABASE_DB_URL"]
CARD_DISPLAY = {"Amex Gold": "Amex Gold", "Chase CSR": "Chase Sapphire Reserve"}


def call(path, payload):
    r = requests.post(BASE + path, json={"client_id": CLIENT_ID, "secret": SECRET, **payload}, timeout=45)
    if r.status_code >= 300:
        print("Plaid error:", r.status_code, r.text[:600]); sys.exit(1)
    return r.json()


def backfill_card(label, access_token, conn):
    display = CARD_DISPLAY.get(label, label)
    cursor = None
    all_txns = []
    while True:
        req = {"access_token": access_token}
        if cursor:
            req["cursor"] = cursor
        resp = call("/transactions/sync", req)
        all_txns.extend(resp["added"] + resp["modified"])
        cursor = resp["next_cursor"]
        if not resp["has_more"]:
            break

    rows = [
        (t["transaction_id"], display, t["date"], t["amount"],
         t.get("merchant_name"), t.get("name"),
         (t.get("personal_finance_category") or {}).get("primary"))
        for t in all_txns
    ]
    if rows:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO transactions
                    (plaid_transaction_id, card, date, amount, merchant_name, name, category)
                VALUES %s
                ON CONFLICT (plaid_transaction_id) DO UPDATE SET
                    amount = EXCLUDED.amount, merchant_name = EXCLUDED.merchant_name,
                    name = EXCLUDED.name, category = EXCLUDED.category
            """, rows)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sync_state (card, cursor) VALUES (%s, %s)
            ON CONFLICT (card) DO UPDATE SET cursor = EXCLUDED.cursor
        """, (display, cursor))
    conn.commit()

    dates = sorted(t["date"] for t in all_txns)
    earliest, latest = (dates[0], dates[-1]) if dates else (None, None)
    print(f"{display}: {len(all_txns)} transactions, range {earliest} to {latest}")


def main():
    conn = psycopg2.connect(DB_URL)
    for label, token in TOKENS.items():
        backfill_card(label, token, conn)
    conn.close()


if __name__ == "__main__":
    main()
