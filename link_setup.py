"""
link_setup.py  —  ONE-TIME bank connection (no frontend needed).

Run this once per card. It uses Plaid Hosted Link: Plaid hosts the connect UI,
you open a URL, log into your bank, and this script retrieves and prints a
durable access_token. Paste that token into your GitHub Secret PLAID_ACCESS_TOKENS.

Usage:
    PLAID_CLIENT_ID=xxx PLAID_SECRET=xxx PLAID_ENV=production python3 link_setup.py "Amex Gold"

Requires: pip install requests
"""
import os, sys, time, json, requests

CLIENT_ID = os.environ["PLAID_CLIENT_ID"]
SECRET    = os.environ["PLAID_SECRET"]
ENV       = os.environ.get("PLAID_ENV", "production")   # sandbox | production
BASE      = f"https://{ENV}.plaid.com"
LABEL     = sys.argv[1] if len(sys.argv) > 1 else "card"


def call(path, payload):
    r = requests.post(BASE + path, json={"client_id": CLIENT_ID, "secret": SECRET, **payload}, timeout=30)
    if r.status_code >= 300:
        print("Plaid error:", r.status_code, r.text[:600]); sys.exit(1)
    return r.json()


def main():
    # 1) create a hosted link token
    lt = call("/link/token/create", {
        "user": {"client_user_id": "leland-benefits"},
        "client_name": "Card Benefits Tracker",
        "products": ["transactions"],
        "country_codes": ["US"],
        "language": "en",
        "hosted_link": {"url_lifetime_seconds": 1800},
    })
    link_token = lt["link_token"]
    print("\n" + "=" * 70)
    print(f"Connect your {LABEL} — open this URL in your browser and log in:\n")
    print("   " + lt["hosted_link_url"])
    print("\n" + "=" * 70)
    input("\nPress ENTER here after you've finished connecting in the browser...")

    # 2) retrieve the public_token from the finished session
    public_token = None
    for _ in range(20):
        got = call("/link/token/get", {"link_token": link_token})
        results = (got.get("results") or {}).get("item_add_results") or []
        if results and results[0].get("public_token"):
            public_token = results[0]["public_token"]; break
        if (got.get("on_success") or {}).get("public_token"):
            public_token = got["on_success"]["public_token"]; break
        time.sleep(3)
    if not public_token:
        print("Could not find a completed session yet. Re-run after finishing the browser step.")
        sys.exit(1)

    # 3) exchange for a durable access_token
    ex = call("/item/public_token/exchange", {"public_token": public_token})
    access_token = ex["access_token"]
    print("\n✅ Connected! Save this in your GitHub Secret PLAID_ACCESS_TOKENS as:")
    print(json.dumps({LABEL: access_token}, indent=2))
    print("\n(If you have both cards, run this again for the other and combine both keys "
          "into one JSON object, e.g. {\"Amex Gold\": \"...\", \"Chase CSR\": \"...\"})")


if __name__ == "__main__":
    main()
