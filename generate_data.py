"""
generate_data.py
-----------------
Generates a synthetic 50+ record financial dataset for the AI Finance
Controller: an invoices ledger and a bank statement, deliberately seeded
with the kinds of messiness a real finance-ops team deals with:

  - Clean 1:1 matches (invoice paid in full, on time)
  - TDS / tax-deducted payments (bank amount != invoice amount by a tax %)
  - Partial payments (bank amount < invoice amount)
  - Duplicate invoice entries (double-billing / double-entry errors)
  - Unmatched invoices (payment not yet received)
  - Unmatched bank credits (payment received with no matching invoice —
    e.g. advance payment, misdirected transfer)
  - Reference numbers that are slightly garbled (typos), to force fuzzy
    matching instead of naive exact-string matching
  - Duplicate bank credits (same payment captured twice by the bank feed)
  - Party-name variations where the bank narration only carries an
    abbreviated form of the party name (e.g. "Sharma Ji Ent" for an
    invoice billed to "Sharma Ji Enterprises") with an unrelated
    reference number — forces name-based matching, not just reference
    matching

Run: python generate_data.py
Outputs: data/invoices.csv, data/bank_statement.csv
"""

import csv
import random
from datetime import datetime, timedelta

random.seed(42)

OUT_DIR = "data"

PARTIES = [
    "Aarav Textiles Pvt Ltd", "Blue Ocean Traders", "Chandra Electronics",
    "Deccan Logistics", "Everest Furnishings", "Falcon Hardware Co",
    "Ganga Foods Ltd", "Himalaya Exports", "Indus Packaging Works",
    "Jaipur Handicrafts", "Kaveri Textiles", "Lotus Pharma Distributors",
    "Marigold Retail Chain", "Nilgiri Tea Estates", "Orion Steel Traders",
    "Prakash Auto Parts", "Quantum Tech Solutions", "Ravi Stationery Mart",
    "Sundar Spices Co", "Trident Chemicals", "Sharma Ji Enterprises",
]

TAX_RATE_OPTIONS = [0.02, 0.05, 0.10]  # common TDS-style deduction rates
START_DATE = datetime(2026, 7, 1)


def rand_date(base, spread_days=45):
    return base + timedelta(days=random.randint(0, spread_days))


def money(x):
    return round(x, 2)


def garble_ref(ref):
    """Introduce a light typo so exact string matching fails but a human
    (or fuzzy matcher) can still tell it's the same reference."""
    if len(ref) < 4:
        return ref
    i = random.randint(1, len(ref) - 2)
    return ref[:i] + ref[i + 1] + ref[i] + ref[i + 2:]  # swap two chars


def abbreviate_name(name):
    """'Sharma Ji Enterprises' -> 'Sharma Ji Ent' — the kind of shortened
    name a bank narration field actually carries, forcing the reconciler
    to match on partial name overlap rather than an exact string."""
    words = name.split()
    if len(words) <= 1:
        return name[:6]
    return " ".join(words[:-1] + [words[-1][:3]])


def generate():
    invoices = []
    bank_txns = []

    inv_counter = 1001
    txn_counter = 500001

    n_clean = 20
    n_tax_diff = 8
    n_partial = 5
    n_duplicate_invoice = 4
    n_unmatched_invoice = 6
    n_unmatched_bank = 5
    n_duplicate_bank = 4
    n_name_variation = 5
    n_garbled_ref = 6  # subset drawn from the clean matches, handled inline

    # ---- 1. Clean 1:1 matches -------------------------------------------------
    for _ in range(n_clean):
        party = random.choice(PARTIES)
        amount = money(random.uniform(8000, 250000))
        inv_date = rand_date(START_DATE)
        pay_date = inv_date + timedelta(days=random.randint(1, 12))
        inv_id = f"INV-{inv_counter}"
        inv_counter += 1
        ref = inv_id
        use_garbled = random.random() < (n_garbled_ref / n_clean)
        bank_ref = garble_ref(ref) if use_garbled else ref

        invoices.append({
            "invoice_id": inv_id, "party": party, "invoice_date": inv_date.date(),
            "amount": amount, "tax_pct": 0, "reference": ref, "status": "issued",
        })
        bank_txns.append({
            "txn_id": f"TXN{txn_counter}", "txn_date": pay_date.date(),
            "amount": amount, "reference": bank_ref, "narration": f"NEFT/{party.split()[0].upper()}/PAYMENT",
        })
        txn_counter += 1

    # ---- 2. TDS / tax-difference payments -------------------------------------
    for _ in range(n_tax_diff):
        party = random.choice(PARTIES)
        amount = money(random.uniform(15000, 300000))
        tax_pct = random.choice(TAX_RATE_OPTIONS)
        inv_date = rand_date(START_DATE)
        pay_date = inv_date + timedelta(days=random.randint(2, 15))
        inv_id = f"INV-{inv_counter}"
        inv_counter += 1
        net_amount = money(amount * (1 - tax_pct))

        invoices.append({
            "invoice_id": inv_id, "party": party, "invoice_date": inv_date.date(),
            "amount": amount, "tax_pct": tax_pct, "reference": inv_id, "status": "issued",
        })
        bank_txns.append({
            "txn_id": f"TXN{txn_counter}", "txn_date": pay_date.date(),
            "amount": net_amount, "reference": inv_id,
            "narration": f"NEFT/{party.split()[0].upper()}/TDS DEDUCTED",
        })
        txn_counter += 1

    # ---- 3. Partial payments ---------------------------------------------------
    for _ in range(n_partial):
        party = random.choice(PARTIES)
        amount = money(random.uniform(20000, 200000))
        pct_paid = random.choice([0.4, 0.5, 0.6, 0.75])
        inv_date = rand_date(START_DATE)
        pay_date = inv_date + timedelta(days=random.randint(3, 20))
        inv_id = f"INV-{inv_counter}"
        inv_counter += 1
        paid_amount = money(amount * pct_paid)

        invoices.append({
            "invoice_id": inv_id, "party": party, "invoice_date": inv_date.date(),
            "amount": amount, "tax_pct": 0, "reference": inv_id, "status": "issued",
        })
        bank_txns.append({
            "txn_id": f"TXN{txn_counter}", "txn_date": pay_date.date(),
            "amount": paid_amount, "reference": inv_id,
            "narration": f"NEFT/{party.split()[0].upper()}/PART PAYMENT",
        })
        txn_counter += 1

    # ---- 3b. Party-name variation payments (reference is no help at all) -------
    for _ in range(n_name_variation):
        party = random.choice(PARTIES)
        amount = money(random.uniform(10000, 150000))
        inv_date = rand_date(START_DATE)
        pay_date = inv_date + timedelta(days=random.randint(2, 10))
        inv_id = f"INV-{inv_counter}"
        inv_counter += 1

        invoices.append({
            "invoice_id": inv_id, "party": party, "invoice_date": inv_date.date(),
            "amount": amount, "tax_pct": 0, "reference": inv_id, "status": "issued",
        })
        # bank reference is deliberately unrelated to the invoice ID —
        # only the abbreviated name in the narration ties this back
        bank_txns.append({
            "txn_id": f"TXN{txn_counter}", "txn_date": pay_date.date(),
            "amount": amount, "reference": f"REF{random.randint(10000, 99999)}",
            "narration": f"NEFT/{abbreviate_name(party)}/PAYMENT",
        })
        txn_counter += 1

    # ---- 4. Duplicate invoice entries (billing error) --------------------------
    for _ in range(n_duplicate_invoice):
        party = random.choice(PARTIES)
        amount = money(random.uniform(10000, 100000))
        inv_date = rand_date(START_DATE)
        pay_date = inv_date + timedelta(days=random.randint(2, 10))
        inv_id = f"INV-{inv_counter}"
        inv_counter += 1
        dup_id = f"INV-{inv_counter}"
        inv_counter += 1

        # same underlying bill, entered twice with different invoice numbers
        invoices.append({
            "invoice_id": inv_id, "party": party, "invoice_date": inv_date.date(),
            "amount": amount, "tax_pct": 0, "reference": inv_id, "status": "issued",
        })
        invoices.append({
            "invoice_id": dup_id, "party": party, "invoice_date": inv_date.date(),
            "amount": amount, "tax_pct": 0, "reference": dup_id, "status": "issued",
        })
        # only one payment actually happened
        bank_txns.append({
            "txn_id": f"TXN{txn_counter}", "txn_date": pay_date.date(),
            "amount": amount, "reference": inv_id,
            "narration": f"NEFT/{party.split()[0].upper()}/PAYMENT",
        })
        txn_counter += 1

    # ---- 5. Unmatched invoices (payment pending) --------------------------------
    for _ in range(n_unmatched_invoice):
        party = random.choice(PARTIES)
        amount = money(random.uniform(5000, 180000))
        inv_date = rand_date(START_DATE, spread_days=40)
        inv_id = f"INV-{inv_counter}"
        inv_counter += 1
        invoices.append({
            "invoice_id": inv_id, "party": party, "invoice_date": inv_date.date(),
            "amount": amount, "tax_pct": 0, "reference": inv_id, "status": "issued",
        })

    # ---- 6. Unmatched bank credits (no invoice on file) --------------------------
    for _ in range(n_unmatched_bank):
        party = random.choice(PARTIES)
        amount = money(random.uniform(5000, 90000))
        pay_date = rand_date(START_DATE, spread_days=45)
        bank_txns.append({
            "txn_id": f"TXN{txn_counter}", "txn_date": pay_date.date(),
            "amount": amount, "reference": f"ADVREF{random.randint(1000,9999)}",
            "narration": f"NEFT/{party.split()[0].upper()}/ADVANCE",
        })
        txn_counter += 1

    # ---- 7. Duplicate bank credits (bank feed glitch) -----------------------------
    picked = random.sample(bank_txns[:n_clean], n_duplicate_bank)
    for original in picked:
        bank_txns.append({
            "txn_id": f"TXN{txn_counter}", "txn_date": original["txn_date"],
            "amount": original["amount"], "reference": original["reference"],
            "narration": original["narration"] + " (DUP)",
        })
        txn_counter += 1

    random.shuffle(invoices)
    random.shuffle(bank_txns)

    import os
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(f"{OUT_DIR}/invoices.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["invoice_id", "party", "invoice_date", "amount", "tax_pct", "reference", "status"])
        w.writeheader()
        w.writerows(invoices)

    with open(f"{OUT_DIR}/bank_statement.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["txn_id", "txn_date", "amount", "reference", "narration"])
        w.writeheader()
        w.writerows(bank_txns)

    print(f"Generated {len(invoices)} invoices and {len(bank_txns)} bank transactions.")
    print(f"Written to {OUT_DIR}/invoices.csv and {OUT_DIR}/bank_statement.csv")


if __name__ == "__main__":
    generate()
