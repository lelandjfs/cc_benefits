"""Synthetic checks for benefits_engine (no real transaction data). Run: python -m pytest tests/  or  python tests/test_benefits_engine.py"""
import os, sys
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from benefits_engine import apply_transactions

AMEX, CSR = "Amex Gold", "Chase Sapphire Reserve"


def tx(card, d, amt, name, merchant=None, category=None):
    return {"card": card, "date": d, "amount": amt, "name": name, "merchant_name": merchant, "category": category}


def by_key(txns, today):
    return {s.key: s for s in apply_transactions(txns, today)}


SEED = [tx(AMEX, "2026-01-02", 5, "SEED"), tx(CSR, "2026-01-02", 5, "SEED")]  # full-year coverage


def test_resy_counts_issuer_credit_not_restaurant_name():
    s = by_key(SEED + [tx(AMEX, "2026-09-20", 80, "SOME BISTRO", "Some Bistro", "FOOD_AND_DRINK"),
                       tx(AMEX, "2026-09-28", -50, "AMEX RESY CREDIT", None, "TRANSFER_IN")],
               date(2026, 10, 6))["amex_resy"]
    assert s.used == 50 and s.status == "Fully used" and s.basis == "credit_posting" and s.credit_posted


def test_spend_without_posting_does_not_count_for_credit_rules():
    s = by_key(SEED + [tx(CSR, "2026-09-23", 160, "StubHub Event Tickets", "Stubhub")], date(2026, 10, 6))["csr_stubhub"]
    assert s.used == 0 and s.detected_spend == 160 and s.status == "Unused"


def test_stubhub_and_select_hotels_postings():
    k = by_key(SEED + [tx(CSR, "2026-09-23", -150, "STUBHUB CREDIT $300/YEAR"),
                       tx(CSR, "2026-08-17", -250, "SELECT HOTELS CREDIT $250")], date(2026, 10, 6))
    assert k["csr_stubhub"].used == 150 and k["csr_chase_travel_hotel"].used == 250


def test_refund_at_merchant_is_not_a_credit():
    s = by_key(SEED + [tx(CSR, "2026-09-10", -40, "STUBHUB REFUND", "Stubhub")], date(2026, 10, 6))["csr_stubhub"]
    assert s.used == 0 and not s.credit_posted


def test_doordash_35_from_october_with_slots():
    k = by_key(SEED + [tx(CSR, "2026-10-03", 120, "DD *DOORDASH CORNERPIZ", "Corner Pizza", "FOOD_AND_DRINK"),
                       tx(CSR, "2026-10-04", 30, "DD *DOORDASH DASHMART", "DashMart", "FOOD_AND_DRINK")],
               date(2026, 10, 6))["csr_doordash"]
    assert k.period_value == 35 and k.used == 25 and k.remaining == 10 and k.basis == "spend_estimate"


def test_doordash_restaurant_orders_only_fill_15():
    k = by_key(SEED + [tx(CSR, "2026-10-03", 40, "DD *DOORDASH A", "A", "FOOD_AND_DRINK"),
                       tx(CSR, "2026-10-04", 40, "DD *DOORDASH B", "B", "FOOD_AND_DRINK")],
               date(2026, 10, 6))["csr_doordash"]
    assert k.used == 15 and k.remaining == 20


def test_doordash_before_october_is_25():
    k = by_key(SEED + [tx(CSR, "2026-09-03", 40, "DOORDASH*ORDER", "DoorDash")], date(2026, 9, 20))["csr_doordash"]
    assert k.period_value == 25 and k.used == 25


def test_data_gap_falls_back_to_spend_estimate():
    txns = [tx(CSR, "2026-04-26", 400, "CL *Chase Travel", None, "TRAVEL")]  # data starts after Feb 13 anniversary
    s = by_key(txns, date(2026, 10, 6))["csr_travel"]
    assert s.used == 300 and s.basis == "spend_estimate_data_gap"


def test_cards_never_cross():
    s = by_key(SEED + [tx(CSR, "2026-09-28", -50, "AMEX RESY CREDIT")], date(2026, 10, 6))["amex_resy"]
    assert s.used == 0


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f()
    print(f"{len(fns)} tests passed")
