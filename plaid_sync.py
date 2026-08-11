"""
plaid_sync.py  —  the weekly job (runs on GitHub Actions).

Pulls new transactions from each connected card via /transactions/sync,
keeps a rolling local cache, runs the benefits engine, and writes:
  - benefits_usage.json  (structured, for the Google Sheet updater)
  - summary.md           (human-readable weekly summary)

Env (from GitHub Secrets):
  PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV (default production),
  PLAID_ACCESS_TOKENS = '{"Amex Gold":"access-...","Chase CSR":"access-..."}'
  (dict keys are just internal labels for the tokens; CARD_DISPLAY below maps
  them to the card names used in the Sheet/benefits_engine RULES.)
"""
import os, json, sys
from datetime import date, datetime, timezone
import requests
from benefits_engine import apply_transactions, to_rows

CLIENT_ID = os.environ["PLAID_CLIENT_ID"]
SECRET    = os.environ["PLAID_SECRET"]
ENV       = os.environ.get("PLAID_ENV", "production")
BASE      = f"https://{ENV}.plaid.com"
TOKENS    = json.loads(os.environ["PLAID_ACCESS_TOKENS"])
CACHE     = "transactions_cache.json"
CARD_DISPLAY = {"Amex Gold": "Amex Gold", "Chase CSR": "Chase Sapphire Reserve"}


def call(path, payload):
    r = requests.post(BASE + path, json={"client_id": CLIENT_ID, "secret": SECRET, **payload}, timeout=45)
    if r.status_code >= 300:
        print("Plaid error:", r.status_code, r.text[:600]); sys.exit(1)
    return r.json()


def load_cache():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}   # { label: { "cursor": str, "txns": { txn_id: txn } } }


def sync_card(label, access_token, state):
    st = state.setdefault(label, {"cursor": None, "txns": {}})
    cursor = st["cursor"]
    while True:
        req = {"access_token": access_token}
        if cursor:
            req["cursor"] = cursor
        resp = call("/transactions/sync", req)
        for t in resp["added"] + resp["modified"]:
            st["txns"][t["transaction_id"]] = {
                "date": t["date"],
                "amount": t["amount"],
                "merchant_name": t.get("merchant_name"),
                "name": t.get("name"),
                "category": (t.get("personal_finance_category") or {}).get("primary"),
                "card": CARD_DISPLAY.get(label, label),
            }
        for t in resp["removed"]:
            st["txns"].pop(t["transaction_id"], None)
        cursor = resp["next_cursor"]
        if not resp["has_more"]:
            break
    st["cursor"] = cursor
    return len(st["txns"])


def main():
    today = datetime.now(timezone.utc).date()
    state = load_cache()
    all_txns = []
    for label, token in TOKENS.items():
        n = sync_card(label, token, state)
        all_txns.extend(state[label]["txns"].values())
        print(f"{label}: {n} transactions cached")

    with open(CACHE, "w") as f:
        json.dump(state, f, indent=2)

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
