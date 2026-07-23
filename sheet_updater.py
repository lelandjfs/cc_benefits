"""
sheet_updater.py — pushes benefits_usage.json into the "Usage Tracker" tab of the
Google Sheet, via a Google service account (works headlessly in GitHub Actions;
no browser/OAuth needed here).

Env:
  GOOGLE_SERVICE_ACCOUNT_JSON  — full JSON key for the service account (as a string)
  GOOGLE_SHEET_ID              — the spreadsheet ID (from its URL)

The service account must be shared as an Editor on the sheet.
"""
import os, json
from datetime import date
from google.oauth2 import service_account
from googleapiclient.discovery import build

SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TAB = "Usage Tracker"

# Usage Tracker columns (see build_workbook.py):
# A Card | B Benefit | C Period | D Value Available | E Period $ Value |
# F Used ($) | G Remaining($, formula) | H Status | I Reset Date | J Days to Reset |
# K Evidence | L Confirmed Using


def load_usage():
    with open("benefits_usage.json") as f:
        return json.load(f)["benefits"]


def sheets_client():
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def main():
    usage = load_usage()
    by_key = {(u["card"], u["label"]): u for u in usage}

    svc = sheets_client()
    existing = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"'{TAB}'!A2:L200"
    ).execute().get("values", [])

    updates = []
    for i, row in enumerate(existing):
        if len(row) < 2:
            continue
        card, benefit = row[0], row[1]
        u = by_key.get((card, benefit))
        if not u:
            continue
        r = i + 2
        evidence = ""
        if u["matched_txns"]:
            t = u["matched_txns"][-1]
            evidence = f"{t['date']}: {t['merchant']} (${t['amount']:.2f})"
        confirmed = row[11] if len(row) > 11 and row[11] else ""
        if u["used"] > 0:
            confirmed = "TRUE"
        updates.append({
            "range": f"'{TAB}'!C{r}:L{r}",
            "values": [[
                f"resets {u['reset_date']}", row[3] if len(row) > 3 else "",
                row[4] if len(row) > 4 else "", u["used"], f"=E{r}-F{r}",
                u["status"], u["reset_date"], u["days_to_reset"], evidence, confirmed,
            ]],
        })

    if updates:
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"valueInputOption": "USER_ENTERED", "data": updates},
        ).execute()
    print(f"Updated {len(updates)} rows in '{TAB}' — {date.today().isoformat()}")


if __name__ == "__main__":
    main()
