"""Builds the Card Benefits Tracker workbook (xlsx -> uploaded to Google Sheets).
Source data: research pass, July 2026 (post Amex Gold refresh, CSR hotel-credit update).
"""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

wb = Workbook()

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)
CSR_FILL = PatternFill("solid", fgColor="DCE6F1")
AMEX_FILL = PatternFill("solid", fgColor="FCE4D6")
WRAP = Alignment(wrap_text=True, vertical="top")
THIN = Border(bottom=Side(style="thin", color="D9D9D9"))


def style_header(ws, ncols, row=1):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def autosize(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ============================================================ README
ws = wb.active
ws.title = "README"
ws["A1"] = "Card Benefits Tracker"
ws["A1"].font = Font(bold=True, size=16)
lines = [
    "",
    "Cards tracked: Chase Sapphire Reserve (personal), American Express Gold Card.",
    "Data current as of: July 2026 (includes Amex Gold 2026 refresh, CSR Edit/hotel credit changes).",
    "",
    "Tabs:",
    "  Benefits Catalog   - every benefit on both cards: credits, point multipliers, memberships, insurance.",
    "  Usage Tracker       - live per-period usage, pulled from Plaid transactions. Checkbox = you've confirmed you're using it.",
    "  Category Spend Guide - which card to use for each purchase category, and why.",
    "  Dining Lists         - curated restaurant benefit lists. NOTE: CSR Exclusive Tables (~400 restaurants) and the",
    "                          Amex Gold Resy credit (~10,000+ restaurants) change weekly/monthly. We link the live",
    "                          source instead of hardcoding names that would go stale.",
    "",
    "Refresh: weekly via GitHub Actions + Plaid (see repo). Evidence column shows the exact transaction",
    "that confirms a benefit was used.",
]
for i, line in enumerate(lines, start=2):
    ws.cell(row=i, column=1, value=line)
autosize(ws, [110])

# ============================================================ Benefits Catalog
ws = wb.create_sheet("Benefits Catalog")
cols = ["Card", "Category", "Benefit", "Value", "Frequency / Reset", "Enrollment Required",
        "How It Works / Notes", "Merchant Match Pattern (statement)", "Source"]
ws.append(cols)
style_header(ws, len(cols))

catalog = [
# ---------------- CSR: Statement Credits ----------------
("Chase Sapphire Reserve", "Statement Credit", "Annual Travel Credit", "$300/yr", "Annual (cardmember year)", "No",
 "Auto-applies to broad travel spend: airlines, hotels, rideshare, parking, tolls, transit.",
 "airline|hotel|amtrak|marriott|hyatt|uber|lyft|parking|toll|transit", "chase.com/sapphire-cards/personal/reserve"),
("Chase Sapphire Reserve", "Statement Credit", "Chase Travel Hotel Credit", "up to $250/stay", "Promo thru 12/31/2026", "No",
 "Prepaid via Chase Travel; IHG, Montage, Pendry, Omni, Virgin Hotels, Minor Hotels, Pan Pacific only.",
 "chase travel", "joinkudos.com/blog/chase-sapphire-reserve-hotel-credits-2026-new-250-credit-flexible-edit-benefits"),
("Chase Sapphire Reserve", "Statement Credit", "The Edit Hotel Credit", "$250 x2 (max $500/yr)", "Per qualifying stay (2 max)", "No",
 "Prepaid The Edit hotels via Chase Travel, 2-night minimum.",
 "chase travel|the edit", "chase.com/sapphire-cards/personal/reserve"),
("Chase Sapphire Reserve", "Statement Credit", "Dining Credit (Exclusive Tables)", "$150 x2 (=$300/yr)", "Semiannual (Jan-Jun, Jul-Dec)", "No",
 "Must dine at a restaurant on the LIVE OpenTable 'Sapphire Reserve Exclusive Tables' list (~400 restaurants, changes weekly). Auto-applies, no reservation required. See Dining Lists tab.",
 "varies by restaurant - cross-ref live list", "thepointsguy.com/credit-cards/chase-sapphire-reserve-exclusive-tables-guide"),
("Chase Sapphire Reserve", "Statement Credit", "StubHub / viagogo Credit", "$150 x2 (=$300/yr)", "Semiannual", "Yes",
 "Enroll via Chase Offers/benefits portal.",
 "stubhub|viagogo", "chase.com/sapphire-cards/personal/reserve"),
("Chase Sapphire Reserve", "Statement Credit", "DoorDash Credit + DashPass", "$300/yr in promos + DashPass ($120/yr value)", "Monthly promos", "Yes",
 "Requires DashPass activation through card benefits.",
 "doordash|door dash", "roamingcactus.com/credit-cards/chase-sapphire-reserve-credits-2026-explained"),
("Chase Sapphire Reserve", "Statement Credit", "Lyft Credit", "$10/mo ($120/yr)", "Monthly", "No",
 "In-app credit. Card must be linked in Lyft app.",
 r"\blyft\b", "chase.com/sapphire-cards/personal/reserve"),
("Chase Sapphire Reserve", "Statement Credit", "Peloton Credit", "$10/mo ($120/yr)", "Monthly, thru 12/31/2027", "No",
 "Requires eligible Peloton App/All-Access membership.",
 "peloton", "joinkudos.com/blog/chase-sapphire-reserve-hotel-credits-2026-new-250-credit-flexible-edit-benefits"),
("Chase Sapphire Reserve", "Statement Credit", "Global Entry / TSA PreCheck", "$120", "Every 4 years", "No",
 "Statement credit for application fee.",
 "global entry|tsa precheck", "chase.com/sapphire-cards/personal/reserve"),

# ---------------- CSR: Earning Multipliers ----------------
("Chase Sapphire Reserve", "Earning Multiplier", "Chase Travel Portal", "8x points", "Ongoing", "No",
 "Flights, hotels, cars, cruises booked through Chase Travel.", "chase travel", "chase.com/sapphire-cards/personal/reserve"),
("Chase Sapphire Reserve", "Earning Multiplier", "Lyft", "5x points", "Thru 9/30/2027", "No", "Direct Lyft rides.", r"\blyft\b", "chase.com/sapphire-cards/personal/reserve"),
("Chase Sapphire Reserve", "Earning Multiplier", "Direct Airfare & Hotel", "4x points", "Ongoing", "No",
 "Booked directly with airline/hotel (not portal, not OTA).", "airline|hotel", "chase.com/sapphire-cards/personal/reserve"),
("Chase Sapphire Reserve", "Earning Multiplier", "Dining", "3x points", "Ongoing", "No",
 "Restaurants, takeout, eligible delivery.", "restaurant|dining", "chase.com/sapphire-cards/personal/reserve"),
("Chase Sapphire Reserve", "Earning Multiplier", "Peloton Equipment >$150", "10x points", "Thru 12/31/2027", "No",
 "Peloton equipment/accessories over $150.", "peloton", "joinkudos.com"),
("Chase Sapphire Reserve", "Earning Multiplier", "Everything Else", "1x points", "Ongoing", "No", "Base rate.", "", ""),

# ---------------- CSR: Memberships ----------------
("Chase Sapphire Reserve", "Membership / Access", "Priority Pass Select", "Included", "Ongoing", "Register once",
 "1,300+ airport lounges worldwide.", "priority pass", "chase.com/sapphire-cards/personal/reserve"),
("Chase Sapphire Reserve", "Membership / Access", "Chase Sapphire Lounge by The Club", "Included", "Ongoing", "No",
 "Unlimited entry, +2 guests, at Chase's own lounge locations.", "", "chase.com/sapphire-cards/personal/reserve"),
("Chase Sapphire Reserve", "Membership / Access", "DashPass", "Complimentary", "Ongoing (with activation)", "Yes", "$0 delivery fees on eligible DoorDash orders.", "", ""),
("Chase Sapphire Reserve", "Membership / Access", "Peloton App Membership Discount", "Discounted rate", "Ongoing", "No", "Reduced Peloton App membership cost.", "", ""),

# ---------------- CSR: Insurance ----------------
("Chase Sapphire Reserve", "Insurance / Protection", "Purchase Protection", "$10,000/item", "120 days from purchase", "No", "Covers theft/damage on eligible purchases.", "", "chase.com Guide to Benefits"),
("Chase Sapphire Reserve", "Insurance / Protection", "Extended Warranty", "+1 yr (up to 4 yrs from purchase)", "On warranties <=3 yrs", "No", "Extends manufacturer warranty.", "", "chase.com Guide to Benefits"),
("Chase Sapphire Reserve", "Insurance / Protection", "Trip Cancellation/Interruption", "$10,000/traveler, $20,000/trip", "Per trip", "No", "13 covered reasons.", "", "chase.com Guide to Benefits"),
("Chase Sapphire Reserve", "Insurance / Protection", "Trip Delay", "$500/traveler", "6+ hr delay or overnight", "No", "Covers meals/lodging during delay.", "", "chase.com Guide to Benefits"),
("Chase Sapphire Reserve", "Insurance / Protection", "Baggage Delay", "$100/day x 5 days", "6+ hr delay", "No", "", "", "chase.com Guide to Benefits"),
("Chase Sapphire Reserve", "Insurance / Protection", "Emergency Evacuation", "$100,000", "Per incident", "Pre-authorization required", "", "", "chase.com Guide to Benefits"),
("Chase Sapphire Reserve", "Insurance / Protection", "Rental Car CDW", "Up to $75,000, primary", "Per rental", "No", "Primary coverage - theft/collision.", "", "chase.com Guide to Benefits"),

# ---------------- Amex Gold: Statement Credits ----------------
("Amex Gold", "Statement Credit", "Uber Cash", "$10/mo ($120/yr)", "Monthly", "Yes",
 "Add Gold Card as payment method in Uber app; credit loads automatically.", r"\buber\b", "americanexpress.com/us/credit-cards/card/gold-card"),
("Amex Gold", "Statement Credit", "Dining Credit", "$10/mo ($120/yr)", "Monthly", "Yes",
 "Grubhub, Cheesecake Factory, Five Guys, Buffalo Wild Wings, Wonder. (Goldbelly/Wine.com dropped 7/1/2026.)",
 "grubhub|cheesecake factory|five guys|buffalo wild wings|wonder", "cardstack.money/articles/credit-card-reviews/amex-gold-dining-credit-guide"),
("Amex Gold", "Statement Credit", "Dunkin' Credit", "$7/mo ($84/yr)", "Monthly", "Yes", "Enroll in Amex app.", "dunkin", "americanexpress.com/us/credit-cards/card/gold-card"),
("Amex Gold", "Statement Credit", "Resy Dining Credit", "$50 x2 (=$100/yr)", "Semiannual", "No (auto)",
 "US restaurants booked/paid via Resy. From 8/1/2026 restaurant must show the 'Resy Credit eligible' badge at time of purchase - not all Resy restaurants qualify. See Dining Lists tab.",
 "resy", "upgradedpoints.com/news/amex-resy-credit-restriction"),
("Amex Gold", "Statement Credit", "Hotel Collection Credit", "$100/stay", "Per stay", "No",
 "Book via Amex Travel, The Hotel Collection properties, 2-night minimum.", "amex travel", "americanexpress.com/us/credit-cards/card/gold-card"),
("Amex Gold", "Statement Credit", "Uber One Membership Credit", "Up to $96 (one-time)", "Thru 10/30/2026", "Yes", "Enroll in Uber One via card benefit.", "uber one", "americanexpress.com/us/credit-cards/card/gold-card"),

# ---------------- Amex Gold: Earning Multipliers ----------------
("Amex Gold", "Earning Multiplier", "US Supermarkets", "4x points", "Cap $25,000/yr, then 1x", "No", "US supermarkets only (not superstores like Walmart/Target).", "supermarket|grocery", "americanexpress.com/us/credit-cards/card/gold-card"),
("Amex Gold", "Earning Multiplier", "Restaurants Worldwide", "4x points", "Cap $50,000/yr, then 1x", "No", "Dine-in and takeout, worldwide.", "restaurant", "americanexpress.com/us/credit-cards/card/gold-card"),
("Amex Gold", "Earning Multiplier", "Prepaid Hotels via Amex Travel", "5x points", "Ongoing (raised from 2x in 2026)", "No", "Book via AmexTravel.com or app, prepaid rate.", "amex travel", "upgradedpoints.com/news/amex-gold-easier-to-use-benefits-refresh"),
("Amex Gold", "Earning Multiplier", "Flights (direct or Amex Travel)", "3x points", "Ongoing", "No", "Booked directly with airline or via AmexTravel.com.", "airline", "americanexpress.com/us/credit-cards/card/gold-card"),
("Amex Gold", "Earning Multiplier", "Everything Else", "1x points", "Ongoing", "No", "Base rate.", "", ""),

# ---------------- Amex Gold: Memberships ----------------
("Amex Gold", "Membership / Access", "Hertz Five Star (Gold+ Rewards)", "Included (new 2026)", "Ongoing", "Enroll in Hertz Gold Plus Rewards", "Vehicle upgrades, free additional driver.", "", "americanexpress.com/us/credit-cards/card/gold-card"),

# ---------------- Amex Gold: Insurance ----------------
("Amex Gold", "Insurance / Protection", "Purchase Protection", "Theft/damage coverage", "90 days from purchase", "No", "", "", "global.americanexpress.com/card-benefits"),
("Amex Gold", "Insurance / Protection", "Extended Warranty", "Up to $10,000/item, $50,000/acct/yr", "Adds 1 yr to warranties <=5 yrs", "No", "", "", "global.americanexpress.com/card-benefits/detail/extended-warranty/amex-gold"),
("Amex Gold", "Insurance / Protection", "Baggage Insurance", "$1,250 carry-on / $500 checked", "Per trip", "No", "Excess coverage over common carrier.", "", "global.americanexpress.com/card-benefits/detail/baggage-insurance-plan-basic/gold"),
]

for row in catalog:
    ws.append(row)

for r in range(2, ws.max_row + 1):
    fill = CSR_FILL if ws.cell(r, 1).value == "Chase Sapphire Reserve" else AMEX_FILL
    for c in range(1, len(cols) + 1):
        cell = ws.cell(r, c)
        cell.fill = fill
        cell.alignment = WRAP
        cell.border = THIN

autosize(ws, [22, 18, 30, 22, 26, 16, 55, 30, 40])
ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{ws.max_row}"

# ============================================================ Usage Tracker
ws = wb.create_sheet("Usage Tracker")
cols = ["Card", "Benefit", "Period", "Value Available", "Period $ Value", "Used ($)", "Remaining ($)", "Status",
        "Reset Date", "Days to Reset", "Evidence (matched transaction)", "Confirmed Using"]
ws.append(cols)
style_header(ws, len(cols))

# numeric per-period dollar value used by the Remaining($) formula (text "Value Available" column is for display only)
PERIOD_VALUE = {
    "Annual Travel Credit": 300, "Chase Travel Hotel Credit": 250, "The Edit Hotel Credit": 500,
    "Dining Credit (Exclusive Tables)": 150, "StubHub / viagogo Credit": 150,
    "DoorDash Credit + DashPass": 25, "Lyft Credit": 10, "Peloton Credit": 10,
    "Global Entry / TSA PreCheck": 120,
    "Uber Cash": 10, "Dining Credit": 10, "Dunkin' Credit": 7, "Resy Dining Credit": 50,
    "Hotel Collection Credit": 100, "Uber One Membership Credit": 96,
}

trackable = [r for r in catalog if r[1] == "Statement Credit"]
for card, _, benefit, value, freq, *_ in trackable:
    r = ws.max_row + 1
    ws.append([card, benefit, "Awaiting first Plaid sync", value, PERIOD_VALUE.get(benefit, 0), 0,
               f"=E{r}-F{r}", "Unused", "", "", "", False])

for r in range(2, ws.max_row + 1):
    fill = CSR_FILL if ws.cell(r, 1).value == "Chase Sapphire Reserve" else AMEX_FILL
    for c in range(1, len(cols) + 1):
        cell = ws.cell(r, c)
        cell.fill = fill
        cell.alignment = WRAP
        cell.border = THIN

dv = DataValidation(type="list", formula1='"TRUE,FALSE"', allow_blank=True)
ws.add_data_validation(dv)
dv.add(f"L2:L{ws.max_row}")

autosize(ws, [22, 30, 22, 20, 12, 12, 14, 14, 14, 12, 40, 14])
ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{ws.max_row}"
note = ws.cell(row=ws.max_row + 2, column=1,
                value="Populated automatically by the weekly Plaid sync (GitHub Actions). 'Confirmed Using' is a manual check "
                      "you can set yourself, or it auto-ticks TRUE once a matching transaction is detected.")
note.font = Font(italic=True, color="666666")

# ============================================================ Category Spend Guide
ws = wb.create_sheet("Category Spend Guide")
cols = ["Purchase Category", "Best Card", "CSR Rate", "Amex Gold Rate", "Why"]
ws.append(cols)
style_header(ws, len(cols))

guide = [
    ("Restaurants / Dining", "Amex Gold", "3x", "4x (cap $50k/yr)", "Amex Gold earns higher on dining up to the cap; after cap, compare to CSR's flat 3x."),
    ("US Supermarkets / Groceries", "Amex Gold", "1x", "4x (cap $25k/yr)", "CSR has no grocery bonus category."),
    ("Flights - direct or issuer portal", "Chase Sapphire Reserve", "8x (Chase Travel) / 4x (direct)", "3x", "Chase Travel portal booking beats Amex's 3x; if booking direct, CSR's 4x still edges Amex's 3x."),
    ("Hotels - prepaid via issuer travel site", "Amex Gold", "8x (Chase Travel)", "5x (Amex Travel)", "Chase Travel portal (8x) beats Amex Travel (5x) - use CSR if booking through a portal."),
    ("Hotels - booked direct with hotel", "Chase Sapphire Reserve", "4x", "1x", "CSR's direct-booking bonus doesn't exist on Amex Gold."),
    ("Rideshare (Lyft)", "Chase Sapphire Reserve", "5x (thru 9/30/2027)", "1x", "Lyft-specific CSR bonus; Amex Gold has no rideshare multiplier (Uber gets Uber Cash instead, not points)."),
    ("Uber", "Amex Gold", "1x (+ no Uber Cash)", "1x + $10/mo Uber Cash", "Amex Gold's Uber Cash is a direct-dollar credit; use it there, use Lyft on CSR."),
    ("Everything else", "Either", "1x", "1x", "No category bonus on either - pick based on which annual credits you still need to hit."),
]
for row in guide:
    ws.append(row)
for r in range(2, ws.max_row + 1):
    for c in range(1, len(cols) + 1):
        cell = ws.cell(r, c)
        cell.alignment = WRAP
        cell.border = THIN
autosize(ws, [30, 22, 22, 22, 55])

# ============================================================ Dining Lists
ws = wb.create_sheet("Dining Lists")
ws["A1"] = "Curated Dining Benefit Lists — Live Sources"
ws["A1"].font = Font(bold=True, size=14)
rows = [
    ("", ""),
    ("These restaurant lists change frequently (CSR's list changed by 91 additions / 64 removals in a single week in July 2026).",
     "Do not rely on a static copy — check the live source before dining if you want the credit guaranteed."),
    ("", ""),
    ("CHASE SAPPHIRE RESERVE — Exclusive Tables (~400 restaurants, Dining Credit)", ""),
    ("Live list (cardmember login):", "https://account.chase.com/sapphire/reserve/sapphireexperiences"),
    ("Also bookable via OpenTable's Exclusive Tables section", ""),
    ("Third-party tracker (unofficial, updated frequently):", "https://nextcard.com/tools/csr-dining-credit-map"),
    ("Third-party tracker (unofficial):", "https://frequentmiler.com/sapphire-reserve-exclusive-tables"),
    ("", ""),
    ("AMEX GOLD — Resy Dining Credit (~10,000+ restaurants, badge-eligible only as of 8/1/2026)", ""),
    ("Live list: check the Resy app/site for the 'Amex Gold' / 'Resy Credit eligible' badge on a restaurant's page before booking.", ""),
    ("Third-party tracker (unofficial):", "https://nextcard.com/tools/resy-map"),
    ("Third-party tracker (unofficial):", "https://crediteats.com/resy"),
    ("", ""),
    ("AMEX GOLD — Dining Credit fixed partners (static, re-verify quarterly)", ""),
    ("Grubhub / Seamless, The Cheesecake Factory, Five Guys, Buffalo Wild Wings, Wonder", "Goldbelly + Wine.com dropped as partners 7/1/2026"),
]
for r in rows:
    ws.append(r)
autosize(ws, [70, 55])
for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
    for cell in row:
        cell.alignment = WRAP

wb.save("card_benefits_tracker.xlsx")
print("saved")
