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
# K Evidence | L Confirmed Using | M Urgency
URGENCY_DAYS = 14
USAGE_TRACKER_GID = 974407183


def load_usage():
    with open("benefits_usage.json") as f:
        return json.load(f)["benefits"]


def sheets_client():
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def urgency_text(remaining, days_to_reset):
    if remaining <= 0 or days_to_reset is None or days_to_reset == "":
        return ""
    if days_to_reset <= URGENCY_DAYS:
        return f"⚠️ Use within {days_to_reset}d or lose ${remaining:.0f}"
    return ""


RED = {"red": 0.96, "green": 0.80, "blue": 0.80}
WHITE = {"red": 1, "green": 1, "blue": 1}


def main():
    usage = load_usage()
    by_key = {(u["card"], u["label"]): u for u in usage}

    svc = sheets_client()
    existing = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"'{TAB}'!A2:M200"
    ).execute().get("values", [])

    updates = []
    color_requests = []
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
        remaining = u["remaining"]
        urgent = remaining > 0 and u["days_to_reset"] not in (None, "") and u["days_to_reset"] <= URGENCY_DAYS
        updates.append({
            "range": f"'{TAB}'!C{r}:M{r}",
            "values": [[
                f"resets {u['reset_date']}", row[3] if len(row) > 3 else "",
                row[4] if len(row) > 4 else "", u["used"], f"=E{r}-F{r}",
                u["status"], u["reset_date"], u["days_to_reset"], evidence, confirmed,
                urgency_text(remaining, u["days_to_reset"]),
            ]],
        })
        color_requests.append({
            "repeatCell": {
                "range": {"sheetId": USAGE_TRACKER_GID, "startRowIndex": r - 1, "endRowIndex": r,
                          "startColumnIndex": 12, "endColumnIndex": 13},
                "cell": {"userEnteredFormat": {"backgroundColor": RED if urgent else WHITE}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

    if updates:
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"valueInputOption": "USER_ENTERED", "data": updates},
        ).execute()
    if color_requests:
        svc.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": color_requests}).execute()
    print(f"Updated {len(updates)} rows in '{TAB}' — {date.today().isoformat()}")


if __name__ == "__main__":
    main()
