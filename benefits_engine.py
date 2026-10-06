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
# USAGE COMES FROM THE ISSUER'S OWN CREDIT POSTINGS whenever the issuer posts a
# statement credit (e.g. "AMEX RESY CREDIT", "STUBHUB CREDIT $300/YEAR"). Rules
# with a `credit_regex` count ONLY those postings toward `used` (basis
# "credit_posting"); merchant spend is reported separately as `detected_spend`.
# Benefits that never post a statement credit (Uber Cash, DoorDash checkout
# promos, Lyft in-app credit, Hotel Collection on-property credit) fall back to
# qualifying spend and are labeled basis "spend_estimate".
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
                                       # negative txn matching this counts $|amount| toward `used`.
                                       # When set, ONLY these postings count toward `used`.
    value_schedule: list[tuple[str, float]] | None = None
                                       # [(effective ISO date, period_value), ...] for benefits whose value
                                       # changed; the value in effect at the period start wins
    promo_slots: list[tuple[str, list[tuple[float, str | None]]]] | None = None
                                       # [(effective ISO date, [(slot $, regex or None=any order), ...])] for
                                       # checkout promos that never hit the statement (DoorDash). Each
                                       # qualifying order fills at most one slot.


RULES: list[BenefitRule] = [
    # ---- Amex Gold ---- (2026 refresh)
    BenefitRule("amex_uber", "Amex Gold", "Uber Cash", "monthly", 10.0,
                r"\buber\b", "Uber & Uber Eats. Card must be linked in the Uber app. Uber Cash is "
                "applied in-app and never posts a statement credit, so usage is an estimate from spend."),
    BenefitRule("amex_dining", "Amex Gold", "Dining Credit", "monthly", 10.0,
                r"grubhub|cheesecake factory|five guys|buffalo wild wings|wonder",
                "Grubhub, Cheesecake Factory, Five Guys, BWW, Wonder. Enrollment required. "
                "(Goldbelly/Wine.com dropped as partners 7/1/2026.)",
                credit_regex=r"amex.*dining credit|gold dining credit|dining credit"),
    BenefitRule("amex_dunkin", "Amex Gold", "Dunkin' Credit", "monthly", 7.0,
                r"dunkin", "Enrollment required.",
                credit_regex=r"dunkin.*credit|amex.*dunkin"),
    BenefitRule("amex_resy", "Amex Gold", "Resy Dining Credit", "semiannual", 50.0,
                r"resy", "US Resy-eligible restaurants. From 8/1/2026 restaurant must show "
                "'Resy Credit eligible' badge — not all Resy restaurants qualify. Restaurant charges show "
                "the restaurant's own name, so usage comes from Amex's 'AMEX RESY CREDIT' posting.",
                credit_regex=r"resy credit"),
    BenefitRule("amex_hotel_collection", "Amex Gold", "Hotel Collection Credit", "annual", 100.0,
                r"amex travel", "Book via Amex Travel, Hotel Collection properties, 2-night min. "
                "$100 credit per qualifying stay, no monthly cap or expiry — every stay earns it. "
                "Used on-property, so no statement credit; tracked from Amex Travel spend.",
                per_txn_cap=100.0, uncapped=True),
    # ---- Chase Sapphire Reserve ---- (post 2026 Edit/hotel-credit update)
    BenefitRule("csr_doordash", "Chase Sapphire Reserve", "DoorDash Credit + DashPass", "monthly", 25.0,
                r"doordash|door dash|\bdd \*",
                "Requires DashPass activation. From 10/1/2026: $35/mo = one $15 promo on any order + two "
                "$10 promos on grocery/convenience/retail orders (was $25/mo restaurant promo). Promos apply "
                "at checkout and never post a statement credit, so usage is an estimate from orders.",
                value_schedule=[("2026-01-01", 25.0), ("2026-10-01", 35.0)],
                promo_slots=[
                    ("2026-01-01", [(25.0, None)]),
                    ("2026-10-01", [(15.0, None),
                                    (10.0, r"dashmart|grocery|groceries|safeway|whole foods|trader joe|"
                                           r"sprouts|cvs|walgreens|rite aid|7-eleven|7 eleven|liquor|wine|"
                                           r"petco|petsmart|pet supplies|target|walmart|convenience|flowers|general_merchandise"),
                                    (10.0, r"dashmart|grocery|groceries|safeway|whole foods|trader joe|"
                                           r"sprouts|cvs|walgreens|rite aid|7-eleven|7 eleven|liquor|wine|"
                                           r"petco|petsmart|pet supplies|target|walmart|convenience")]),
                ]),
    BenefitRule("csr_lyft", "Chase Sapphire Reserve", "Lyft Credit", "monthly", 10.0,
                r"\blyft\b", "In-app credit. Card must be linked in Lyft. Applied in-app, never a "
                "statement credit, so usage is an estimate from rides."),
    BenefitRule("csr_peloton", "Chase Sapphire Reserve", "Peloton Credit", "monthly", 10.0,
                r"peloton", "Requires eligible Peloton App/All-Access membership. Thru 12/31/2027.",
                credit_regex=r"peloton.*credit"),
    BenefitRule("csr_chase_travel_hotel", "Chase Sapphire Reserve", "Chase Travel Hotel Credit", "annual", 250.0,
                r"chase travel", "IHG, Montage, Pendry, Omni, Virgin Hotels, Minor Hotels, Pan Pacific only. "
                "Promo thru 12/31/2026. Posts as 'SELECT HOTELS CREDIT $250'.",
                credit_regex=r"select hotels? credit"),
    BenefitRule("csr_edit_hotel", "Chase Sapphire Reserve", "The Edit Hotel Credit", "annual", 500.0,
                r"the edit", "Prepaid The Edit hotels via Chase Travel, 2-night min. Two $250 credits usable "
                "anytime in the calendar year (no half-year split) — capped at $250/stay, $500/yr total.",
                per_txn_cap=250.0, credit_regex=r"\bedit\b.*credit|edit hotel credit"),
    BenefitRule("csr_dining", "Chase Sapphire Reserve", "Dining Credit (Exclusive Tables)", "semiannual", 150.0,
                r"sapphire reserve|exclusive tables", "Restaurant must be on the LIVE OpenTable "
                "'Sapphire Reserve Exclusive Tables' list. Usage comes from Chase's own posting, "
                "'DINING CREDIT $300/YEAR'.",
                credit_regex=r"dining credit"),
    BenefitRule("csr_stubhub", "Chase Sapphire Reserve", "StubHub / viagogo Credit", "semiannual", 150.0,
                r"stubhub|viagogo", "Enrollment required. Posts as 'STUBHUB CREDIT $300/YEAR'.",
                credit_regex=r"(stubhub|viagogo) credit"),
    BenefitRule("csr_travel", "Chase Sapphire Reserve", "Annual Travel Credit", "annual", 300.0,
                r"airline|hotel|airlines|travel|amtrak|marriott|hyatt|united|delta|"
                r"uber|lyft|parking|toll|transit",
                "Auto-applies to broad travel spend. Resets on your CARDMEMBER YEAR (account "
                "anniversary — opened 2/13/2019), not Jan 1. Reset date below is an approximation of "
                "the anniversary itself; the real reset is the close of your first statement after it, "
                "which can land a few days later depending on your statement cycle.",
                credit_regex=r"travel credit"),
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
    credit_posted: bool = False     # an issuer credit posting (credit_regex) was seen this period
    note: str = ""
    basis: str = "spend_estimate"   # credit_posting | spend_estimate | spend_estimate_data_gap
    detected_spend: float = 0.0     # qualifying merchant spend this period (informational)
    credits_posted_total: float = 0.0  # sum of issuer credit postings this period


def _txn_date(t: dict) -> date:
    return date.fromisoformat(t["date"])


def _merchant_text(t: dict) -> str:
    return f"{t.get('merchant_name') or ''} {t.get('name') or ''}".lower()


def _value_on(schedule, default, when: date):
    if not schedule:
        return default
    val = default
    for eff, v in sorted(schedule):
        if date.fromisoformat(eff) <= when:
            val = v
    return val


def _slot_estimate(slots: list[tuple[float, str | None]], orders: list[tuple[date, float, str]]) -> float:
    """Fill each promo slot with at most one order. Specific (regex) slots are filled
    first by matching orders; 'any order' slots take the remaining orders."""
    remaining = sorted(orders)
    used = 0.0
    for value, rx in sorted(slots, key=lambda s: s[1] is None):  # specific slots first
        pat = re.compile(rx, re.I) if rx else None
        for i, (_, amt, text) in enumerate(remaining):
            if pat is None or pat.search(text):
                used += min(value, amt)
                remaining.pop(i)
                break
    return used


def apply_transactions(transactions: list[dict], today: date) -> list[BenefitStatus]:
    """Compute current-period usage for every benefit rule.

    Rules with a credit_regex count ONLY the issuer's credit postings toward `used`.
    Exception: if this card's data starts after the period began and no posting covers
    the full value, we can't see the period's early postings, so we fall back to the
    spend estimate and label it basis="spend_estimate_data_gap".
    """
    first_seen: dict[str, date] = {}
    for t in transactions:
        d = _txn_date(t)
        c = t.get("card")
        if c not in first_seen or d < first_seen[c]:
            first_seen[c] = d

    out: list[BenefitStatus] = []
    for r in RULES:
        start, end, reset = period_bounds(r.period, today, r.key)
        value = _value_on(r.value_schedule, r.period_value, start)
        st = BenefitStatus(
            key=r.key, card=r.card, label=r.label, period=r.period,
            period_value=value, reset_date=reset.isoformat(),
            days_to_reset=(reset - today).days, note=r.note,
        )
        pat = re.compile(r.merchant_regex, re.I)
        credit_pat = re.compile(r.credit_regex, re.I) if r.credit_regex else None
        spend = 0.0
        credits = 0.0
        orders: list[tuple[date, float, str]] = []
        for t in transactions:
            if t.get("card") != r.card:      # never let one card's spend count toward another card's benefit
                continue
            d = _txn_date(t)
            if not (start <= d < end):
                continue
            text = _merchant_text(t)
            amt = float(t["amount"])
            merchant = t.get("merchant_name") or t.get("name")
            if amt > 0:                      # a charge (qualifying spend)
                if not pat.search(text):
                    continue
                contrib = min(amt, r.per_txn_cap) if r.per_txn_cap is not None else amt
                spend += contrib
                orders.append((d, amt, f"{text} {(t.get('category') or '').lower()}"))
                st.matched_txns.append({"date": t["date"], "amount": amt, "merchant": merchant,
                                         "kind": "spend"})
            elif amt < 0 and credit_pat and credit_pat.search(text):   # issuer's own credit posting
                contrib = min(-amt, r.per_txn_cap) if r.per_txn_cap is not None else -amt
                credits += contrib
                st.credit_posted = True
                st.matched_txns.append({"date": t["date"], "amount": amt, "merchant": merchant,
                                         "kind": "credit"})
        st.detected_spend = round(spend, 2)
        st.credits_posted_total = round(credits, 2)

        if r.uncapped:
            st.basis = "credit_posting" if credit_pat else "spend_estimate"
            st.used = round(credits if credit_pat else spend, 2)
            st.remaining = 0.0    # nothing "at risk" — this benefit doesn't expire or run out
            st.status = "Available (uncapped)" if st.used <= 0 else "Ongoing (uncapped)"
            out.append(st)
            continue

        if credit_pat:
            used = min(credits, value)
            st.basis = "credit_posting"
            data_start = first_seen.get(r.card)
            if data_start and data_start > start and used < value and spend > used:
                used = min(max(used, spend), value)
                st.basis = "spend_estimate_data_gap"
        elif r.promo_slots:
            slots = []
            for eff, s in sorted(r.promo_slots):
                if date.fromisoformat(eff) <= start:
                    slots = s
            used = min(_slot_estimate(slots, orders), value)
            st.basis = "spend_estimate"
        else:
            used = min(spend, value)
            st.basis = "spend_estimate"

        st.used = round(used, 2)
        st.remaining = round(value - st.used, 2)
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
