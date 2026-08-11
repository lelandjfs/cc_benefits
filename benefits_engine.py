"""
benefits_engine.py
Turns a list of Plaid transactions into per-benefit usage for the current period.

Pure logic, no network — this is the part we can test locally with mock data.
The Plaid fetch lives in plaid_sync.py and feeds transactions into apply_transactions().
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from datetime import date


# ----------------------------------------------------------------------------
# Benefit rules. Each credit says: which card, how to recognize a qualifying
# transaction, the reset period, and the dollar value available per period.
#
# Detection uses two signals from Plaid:
#   - merchant_name / name  (regex, case-insensitive)
#   - amount sign: on a credit card, a positive amount = a charge (spend),
#                  a negative amount = a credit/refund/payment.
# For most credits we count QUALIFYING SPEND at the merchant, capped at the
# period value. We also surface detected credit POSTINGS (negative amounts at
# that merchant) as strong confirmation the credit actually hit.
# ----------------------------------------------------------------------------
@dataclass
class BenefitRule:
    key: str
    card: str
    label: str
    period: str            # "monthly" | "semiannual" | "annual"
    period_value: float    # dollars available per period (or per-stay cap, if uncapped=True)
    merchant_regex: str    # matches merchant_name or name
    note: str = ""
    per_txn_cap: float | None = None  # cap credit from any single matching transaction (e.g. $250/stay)
    uncapped: bool = False            # True = every qualifying txn earns credit, no period-total ceiling
    credit_regex: str | None = None   # matches the ISSUER'S OWN credit-posting line item (e.g. "DINING
                                       # CREDIT $300/YEAR"), for benefits where qualifying spend can't be
                                       # matched directly (e.g. a dynamic curated restaurant list) — a
                                       # negative txn matching this counts $|amount| toward `used`


RULES: list[BenefitRule] = [
    # ---- Amex Gold ---- (2026 refresh)
    BenefitRule("amex_uber", "Amex Gold", "Uber Cash", "monthly", 10.0,
                r"\buber\b", "Uber & Uber Eats. Card must be linked in the Uber app."),
    BenefitRule("amex_dining", "Amex Gold", "Dining Credit", "monthly", 10.0,
                r"grubhub|cheesecake factory|five guys|buffalo wild wings|wonder",
                "Grubhub, Cheesecake Factory, Five Guys, BWW, Wonder. Enrollment required. "
                "(Goldbelly/Wine.com dropped as partners 7/1/2026.)"),
    BenefitRule("amex_dunkin", "Amex Gold", "Dunkin' Credit", "monthly", 7.0,
                r"dunkin", "Enrollment required."),
    BenefitRule("amex_resy", "Amex Gold", "Resy Dining Credit", "semiannual", 50.0,
                r"resy", "US Resy-eligible restaurants. From 8/1/2026 restaurant must show "
                "'Resy Credit eligible' badge — not all Resy restaurants qualify."),
    BenefitRule("amex_hotel_collection", "Amex Gold", "Hotel Collection Credit", "annual", 100.0,
                r"amex travel", "Book via Amex Travel, Hotel Collection properties, 2-night min. "
                "$100 credit per qualifying stay, no monthly cap or expiry — every stay earns it.",
                per_txn_cap=100.0, uncapped=True),
    # ---- Chase Sapphire Reserve ---- (post 2026 Edit/hotel-credit update)
    BenefitRule("csr_doordash", "Chase Sapphire Reserve", "DoorDash Credit + DashPass", "monthly", 25.0,
                r"doordash|door dash", "Requires DashPass activation."),
    BenefitRule("csr_lyft", "Chase Sapphire Reserve", "Lyft Credit", "monthly", 10.0,
                r"\blyft\b", "In-app credit. Card must be linked in Lyft."),
    BenefitRule("csr_peloton", "Chase Sapphire Reserve", "Peloton Credit", "monthly", 10.0,
                r"peloton", "Requires eligible Peloton App/All-Access membership. Thru 12/31/2027."),
    BenefitRule("csr_chase_travel_hotel", "Chase Sapphire Reserve", "Chase Travel Hotel Credit", "annual", 250.0,
                r"chase travel", "IHG, Montage, Pendry, Omni, Virgin Hotels, Minor Hotels, Pan Pacific only. "
                "Promo thru 12/31/2026."),
    BenefitRule("csr_edit_hotel", "Chase Sapphire Reserve", "The Edit Hotel Credit", "annual", 500.0,
                r"the edit", "Prepaid The Edit hotels via Chase Travel, 2-night min. Two $250 credits usable "
                "anytime in the calendar year (no half-year split) — capped at $250/stay, $500/yr total.",
                per_txn_cap=250.0),
    BenefitRule("csr_dining", "Chase Sapphire Reserve", "Dining Credit (Exclusive Tables)", "semiannual", 150.0,
                r"sapphire reserve|exclusive tables", "Restaurant must be on the LIVE OpenTable "
                "'Sapphire Reserve Exclusive Tables' list. The underlying restaurant charge can't be "
                "matched directly — Plaid shows the restaurant's own name, not 'exclusive tables' — so "
                "detection watches for Chase's own credit-posting line item instead, "
                "e.g. 'DINING CREDIT $300/YEAR'.",
                credit_regex=r"dining credit"),
    BenefitRule("csr_stubhub", "Chase Sapphire Reserve", "StubHub / viagogo Credit", "semiannual", 150.0,
                r"stubhub|viagogo", "Enrollment required."),
    BenefitRule("csr_travel", "Chase Sapphire Reserve", "Annual Travel Credit", "annual", 300.0,
                r"airline|hotel|airlines|travel|amtrak|marriott|hyatt|united|delta|"
                r"uber|lyft|parking|toll|transit",
                "Auto-applies to broad travel spend. Resets on your CARDMEMBER YEAR (account "
                "anniversary — opened 2/13/2019), not Jan 1. Reset date below is an approximation of "
                "the anniversary itself; the real reset is the close of your first statement after it, "
                "which can land a few days later depending on your statement cycle."),
]


# ----------------------------------------------------------------------------
# Reset-anchor overrides, by rule key, for "annual" benefits that reset on the
# cardmember year (account anniversary) rather than the calendar year. Fill in
# (month, day) once you know the account-open date; until then those rules
# fall back to a Jan 1 calendar-year approximation.
# ----------------------------------------------------------------------------
ANNIVERSARY_OVERRIDES: dict[str, tuple[int, int]] = {
    "csr_travel": (2, 13),              # CSR opened 2/13/2019
    "amex_hotel_collection": (7, 2),    # Amex Gold opened 7/2/2024 (cosmetic only — this rule is uncapped)
}


# ----------------------------------------------------------------------------
# Period math
# ----------------------------------------------------------------------------
def period_bounds(period: str, today: date, rule_key: str | None = None) -> tuple[date, date, date]:
    """Return (period_start, period_end_exclusive, reset_date) for the period
    that contains `today`."""
    y = today.year
    if period == "monthly":
        start = today.replace(day=1)
        nxt = (start.replace(year=y + 1, month=1) if start.month == 12
               else start.replace(month=start.month + 1))
        return start, nxt, nxt
    if period == "semiannual":
        if today.month <= 6:
            return date(y, 1, 1), date(y, 7, 1), date(y, 7, 1)
        return date(y, 7, 1), date(y + 1, 1, 1), date(y + 1, 1, 1)
    # annual
    override = ANNIVERSARY_OVERRIDES.get(rule_key) if rule_key else None
    if override:
        month, day = override
        anniversary = date(y, month, day)
        if today >= anniversary:
            return anniversary, date(y + 1, month, day), date(y + 1, month, day)
        return date(y - 1, month, day), anniversary, anniversary
    # calendar-year approximation (fine for calendar-year benefits; see
    # ANNIVERSARY_OVERRIDES for cardmember-year ones)
    return date(y, 1, 1), date(y + 1, 1, 1), date(y + 1, 1, 1)


@dataclass
class BenefitStatus:
    key: str
    card: str
    label: str
    period: str
    period_value: float
    used: float = 0.0
    remaining: float = 0.0
    status: str = "Unused"          # Unused | Partially used | Fully used | Expired | Available (uncapped)
    reset_date: str = ""
    days_to_reset: int = 0
    matched_txns: list = field(default_factory=list)
    credit_posted: bool = False     # a negative (credit) posting was seen
    note: str = ""


def _txn_date(t: dict) -> date:
    return date.fromisoformat(t["date"])


def _merchant_text(t: dict) -> str:
    return f"{t.get('merchant_name') or ''} {t.get('name') or ''}".lower()


def apply_transactions(transactions: list[dict], today: date) -> list[BenefitStatus]:
    """Compute current-period usage for every benefit rule."""
    out: list[BenefitStatus] = []
    for r in RULES:
        start, end, reset = period_bounds(r.period, today, r.key)
        st = BenefitStatus(
            key=r.key, card=r.card, label=r.label, period=r.period,
            period_value=r.period_value, reset_date=reset.isoformat(),
            days_to_reset=(reset - today).days, note=r.note,
        )
        pat = re.compile(r.merchant_regex, re.I)
        credit_pat = re.compile(r.credit_regex, re.I) if r.credit_regex else None
        spend = 0.0
        for t in transactions:
            if t.get("card") != r.card:      # never let one card's spend count toward another card's benefit
                continue
            d = _txn_date(t)
            if not (start <= d < end):
                continue
            text = _merchant_text(t)
            amt = float(t["amount"])
            if amt > 0:                      # a charge (qualifying spend)
                if not pat.search(text):
                    continue
                contrib = min(amt, r.per_txn_cap) if r.per_txn_cap is not None else amt
                spend += contrib
                st.matched_txns.append({"date": t["date"], "amount": amt,
                                         "merchant": t.get("merchant_name") or t.get("name")})
            elif amt < 0:                    # a credit/refund posted
                is_credit_posting = bool(credit_pat and credit_pat.search(text))
                if not (pat.search(text) or is_credit_posting):
                    continue
                st.credit_posted = True
                st.matched_txns.append({"date": t["date"], "amount": amt,
                                         "merchant": t.get("merchant_name") or t.get("name")})
                if is_credit_posting:        # issuer's own credit posting is definitive proof of usage
                    contrib = min(-amt, r.per_txn_cap) if r.per_txn_cap is not None else -amt
                    spend += contrib
        if r.uncapped:
            st.used = round(spend, 2)
            st.remaining = 0.0    # nothing "at risk" — this benefit doesn't expire or run out
            st.status = "Available (uncapped)" if st.used <= 0 else "Ongoing (uncapped)"
        else:
            st.used = round(min(spend, r.period_value), 2)
            st.remaining = round(r.period_value - st.used, 2)
            if st.used <= 0:
                st.status = "Unused"
            elif st.remaining <= 0.001:
                st.status = "Fully used"
            else:
                st.status = "Partially used"
        out.append(st)
    return out


def to_rows(statuses: list[BenefitStatus]) -> list[dict]:
    return [asdict(s) for s in statuses]
