"""
plaid_sync.py  —  the weekly job (runs on GitHub Actions).

Pulls new transactions from each connected card via /transactions/sync, upserts them into
Supabase — the durable transaction store (see backfill_supabase.py for the one-time full
history pull) — runs the benefits engine against everything Supabase has for each card,
and writes:
  - benefits_usage.json  (structured, for the Google Sheet updater)
  - summary.md           (human-readable weekly summary)

Env (from GitHub Secrets):
  PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV (default production),
  PLAID_ACCESS_TOKENS = '{"Amex Gold":"access-...","Chase CSR":"access-..."}'
  (dict keys are just internal labels for the tokens; CARD_DISPLAY below maps
  them to the card names used in the Sheet/benefits_engine RULES.)
  SUPABASE_URL, SUPABASE_SECRET_KEY
"""
import os, json, sys
from datetime import date, datetime, timezone
import requests
from benefits_engine import apply_transactions, to_rows

CLIENT_ID  = os.environ["PLAID_CLIENT_ID"]
SECRET     = os.environ["PLAID_SECRET"]
ENV        = os.environ.get("PLAID_ENV", "production")
PLAID_BASE = f"https://{ENV}.plaid.com"
TOKENS     = json.loads(os.environ["PLAID_ACCESS_TOKENS"])
CARD_DISPLAY = {"Amex Gold": "Amex Gold", "Chase CSR": "Chase Sapphire Reserve"}

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}
BATCH_SIZE = 500
PAGE_SIZE = 1000


def plaid_call(path, payload):
    r = requests.post(PLAID_BASE + path, json={"client_id": CLIENT_ID, "secret": SECRET, **payload}, timeout=45)
    if r.status_code >= 300:
        print("Plaid error:", r.status_code, r.text[:600]); sys.exit(1)
    return r.json()


def supabase_get_all(table, params):
    rows, offset = [], 0
    while True:
        headers = {**SB_HEADERS, "Range": f"{offset}-{offset + PAGE_SIZE - 1}"}
        r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers, params=params, timeout=30)
        if r.status_code >= 300:
            print("Supabase error:", r.status_code, r.text[:600]); sys.exit(1)
        batch = r.json()
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def supabase_upsert(table, rows, conflict_col):
    if not rows:
        return
    headers = {**SB_HEADERS, "Prefer": "resolution=merge-duplicates"}
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={conflict_col}",
                           headers=headers, json=chunk, timeout=30)
        if r.status_code >= 300:
            print("Supabase error:", r.status_code, r.text[:600]); sys.exit(1)


def supabase_delete_ids(table, id_col, ids):
    if not ids:
        return
    r = requests.delete(f"{SUPABASE_URL}/rest/v1/{table}?{id_col}=in.({','.join(ids)})",
                         headers=SB_HEADERS, timeout=30)
    if r.status_code >= 300:
        print("Supabase error:", r.status_code, r.text[:600]); sys.exit(1)


def get_cursor(card):
    rows = supabase_get_all("sync_state", {"card": f"eq.{card}", "select": "cursor"})
    return rows[0]["cursor"] if rows else None


def sync_card(label, access_token):
    display = CARD_DISPLAY.get(label, label)
    cursor = get_cursor(display)
    changed, removed_ids = [], []
    while True:
        req = {"access_token": access_token}
        if cursor:
            req["cursor"] = cursor
        resp = plaid_call("/transactions/sync", req)
        changed.extend(resp["added"] + resp["modified"])
        removed_ids.extend(t["transaction_id"] for t in resp["removed"])
        cursor = resp["next_cursor"]
        if not resp["has_more"]:
            break

    rows = [
        {"plaid_transaction_id": t["transaction_id"], "card": display, "date": t["date"],
         "amount": t["amount"], "merchant_name": t.get("merchant_name"), "name": t.get("name"),
         "category": (t.get("personal_finance_category") or {}).get("primary")}
        for t in changed
    ]
    supabase_upsert("transactions", rows, "plaid_transaction_id")
    supabase_delete_ids("transactions", "plaid_transaction_id", removed_ids)
    supabase_upsert("sync_state", [{"card": display, "cursor": cursor}], "card")
    return len(changed), len(removed_ids)


def load_all_transactions():
    return supabase_get_all("transactions", {"select": "date,amount,merchant_name,name,category,card"})


def main():
    today = datetime.now(timezone.utc).date()
    for label, token in TOKENS.items():
        n_changed, n_removed = sync_card(label, token)
        print(f"{CARD_DISPLAY.get(label, label)}: {n_changed} added/modified, {n_removed} removed")

    all_txns = load_all_transactions()
    print(f"Supabase now holds {len(all_txns)} transactions total across both cards")
    statuses = apply_transactions(all_txns, today)
    rows = to_rows(statuses)
    with open("benefits_usage.json", "w") as f:
        json.dump({"generated": today.isoformat(), "benefits": rows}, f, indent=2)

    # human summary — highlight use-it-or-lose-it and unclaimed money
    urgent = [s for s in statuses if s.remaining > 0 and s.days_to_reset <= 12]
    unclaimed = sum(s.remaining for s in statuses)
    lines = [f"# Benefits usage — {today.isoformat()}", ""]
    if urgent:
        lines.append("## ⏰ Resets soon — still unclaimed")
        for s in sorted(urgent, key=lambda x: x.days_to_reset):
            lines.append(f"- **{s.card} {s.label}**: ${s.remaining:.0f} left, resets {s.reset_date} "
                         f"({s.days_to_reset}d). {s.note}")
        lines.append("")
    lines.append(f"## All benefits (${unclaimed:.0f} total still available this period)")
    for s in statuses:
        tick = {"Fully used": "✅", "Partially used": "🟨", "Unused": "⬜",
                "Ongoing (uncapped)": "♾️", "Available (uncapped)": "♾️"}.get(s.status, "•")
        lines.append(f"- {tick} {s.card} {s.label}: used ${s.used:.0f} / ${s.period_value:.0f} "
                     f"→ ${s.remaining:.0f} left (resets {s.reset_date})")
    with open("summary.md", "w") as f:
        f.write("\n".join(lines))
    print(f"\nWrote benefits_usage.json and summary.md. Unclaimed this period: ${unclaimed:.0f}")


if __name__ == "__main__":
    main()
