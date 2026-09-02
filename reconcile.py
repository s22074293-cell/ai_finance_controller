"""
reconcile.py
------------
The core reconciliation engine (Section 1 of the brief).

Takes invoices.csv + bank_statement.csv and produces:
  - matched pairs (with a match_type explaining WHY they matched)
  - an honest exception list: unmatched invoices, unmatched bank credits,
    duplicate invoices, duplicate bank credits, partial payments
  - a match rate: % of invoice value that has been reconciled to a bank
    transaction (matched + partial), not just % of row count — this is
    the number that actually matters to a finance controller.

Matching strategy (deterministic, explainable — this is what an "AI
Finance Controller" should actually do, not a black box):

  1. Exact reference match, exact amount  -> "exact"
  2. Exact reference match, amount within TDS-style tolerance
     (bank amount = invoice amount * (1 - tax%) for tax% in {2,5,10,...})
     -> "tax_adjusted"
  3. Exact reference match, bank amount significantly less than invoice
     amount -> "partial_payment"
  4. Fuzzy reference match (typo-tolerant, via difflib) + amount within
     1% and date within a window -> "fuzzy"
  5. Party-name fuzzy match against the bank narration (when the
     reference is no help at all — e.g. "Sharma Ji Ent" in the bank feed
     for an invoice billed to "Sharma Ji Enterprises") + amount/date
     tolerance -> "name_matched"
  6. Duplicate invoice detection: two+ invoice rows with identical
     party + amount + invoice_date -> flagged as duplicate_invoice,
     only one is expected to be paid.
  7. Duplicate bank credit detection: two+ bank rows with identical
     reference + amount -> flagged as duplicate_bank_credit.
  8. Anything left over on either side is a genuine exception.

Run: python reconcile.py
Reads: data/invoices.csv, data/bank_statement.csv
Writes: data/matched.csv, data/exceptions.csv, data/summary.json
"""

import json
import os
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import pandas as pd

DATA_DIR = "data"
DATE_WINDOW_DAYS = 25
TAX_RATE_OPTIONS = [0.02, 0.05, 0.10, 0.18]
AMOUNT_TOLERANCE_PCT = 0.005  # 0.5% wiggle room for rounding


def _load():
    inv = pd.read_csv(f"{DATA_DIR}/invoices.csv", parse_dates=["invoice_date"])
    bank = pd.read_csv(f"{DATA_DIR}/bank_statement.csv", parse_dates=["txn_date"])
    inv["amount"] = inv["amount"].astype(float)
    bank["amount"] = bank["amount"].astype(float)
    return inv, bank


def _ref_similarity(a, b):
    return SequenceMatcher(None, str(a), str(b)).ratio()


NARRATION_PREFIXES = ["NEFT/", "NEFT-", "UPI/", "UPI-", "FT-", "FT/", "RTGS/", "RTGS-", "IMPS/", "IMPS-"]
NAME_STOPWORDS = {"pvt", "ltd", "llc", "co", "corp", "corporation", "enterprises", "ent",
                   "works", "traders", "trading", "industries", "distributors", "retail",
                   "chain", "estates", "solutions", "mart", "exports", "handicrafts"}


def _significant_words(name):
    """Strip generic business-suffix words so 'Sharma Ji Enterprises' and
    'Sharma Ji Ent' compare on their distinctive part: {'sharma','ji'}."""
    cleaned = str(name).lower()
    for p in NARRATION_PREFIXES:
        cleaned = cleaned.replace(p.lower(), " ")
    words = [w.strip(".,/-") for w in cleaned.split()]
    return {w for w in words if w and w not in NAME_STOPWORDS and len(w) > 1}


def _name_overlap_score(party_name, narration):
    """Fraction of the party's distinctive words that also appear in the
    bank narration — catches 'Sharma Ji Ent' inside a narration that also
    contains 'Sharma Ji Enterprises', despite the differing suffix."""
    party_words = _significant_words(party_name)
    narration_words = _significant_words(narration)
    if not party_words:
        return 0.0
    overlap = party_words & narration_words
    return len(overlap) / len(party_words)


def flag_duplicates(inv, bank):
    """Return (dup_invoice_ids, dup_bank_txn_ids) — the SECOND+ occurrence
    of each duplicate group is flagged, keeping the first as the
    legitimate record."""
    dup_invoice_ids = set()
    grp = inv.groupby(["party", "amount", "invoice_date"])
    for _, g in grp:
        if len(g) > 1:
            dup_invoice_ids.update(g["invoice_id"].tolist()[1:])

    dup_bank_ids = set()
    grp2 = bank.groupby(["reference", "amount"])
    for _, g in grp2:
        if len(g) > 1:
            dup_bank_ids.update(g["txn_id"].tolist()[1:])

    return dup_invoice_ids, dup_bank_ids


def reconcile():
    inv, bank = _load()
    dup_invoice_ids, dup_bank_ids = flag_duplicates(inv, bank)

    matched_rows = []
    matched_invoice_ids = set()
    matched_bank_ids = set()

    invoices_to_try = inv[~inv["invoice_id"].isin(dup_invoice_ids)].copy()
    bank_to_try = bank[~bank["txn_id"].isin(dup_bank_ids)].copy()

    # Pass 1: exact reference + exact amount
    for _, irow in invoices_to_try.iterrows():
        candidates = bank_to_try[
            (bank_to_try["reference"] == irow["reference"]) &
            (~bank_to_try["txn_id"].isin(matched_bank_ids))
        ]
        for _, brow in candidates.iterrows():
            if abs(brow["amount"] - irow["amount"]) <= irow["amount"] * AMOUNT_TOLERANCE_PCT:
                matched_rows.append({
                    "invoice_id": irow["invoice_id"], "txn_id": brow["txn_id"],
                    "party": irow["party"], "invoice_amount": irow["amount"],
                    "bank_amount": brow["amount"], "match_type": "exact",
                    "detail": "Reference and amount matched exactly.",
                })
                matched_invoice_ids.add(irow["invoice_id"])
                matched_bank_ids.add(brow["txn_id"])
                break

    # Pass 2: exact reference + tax-adjusted amount
    for _, irow in invoices_to_try.iterrows():
        if irow["invoice_id"] in matched_invoice_ids:
            continue
        candidates = bank_to_try[
            (bank_to_try["reference"] == irow["reference"]) &
            (~bank_to_try["txn_id"].isin(matched_bank_ids))
        ]
        for _, brow in candidates.iterrows():
            for rate in TAX_RATE_OPTIONS:
                expected = irow["amount"] * (1 - rate)
                if abs(brow["amount"] - expected) <= expected * AMOUNT_TOLERANCE_PCT:
                    matched_rows.append({
                        "invoice_id": irow["invoice_id"], "txn_id": brow["txn_id"],
                        "party": irow["party"], "invoice_amount": irow["amount"],
                        "bank_amount": brow["amount"], "match_type": "tax_adjusted",
                        "detail": f"Matched after accounting for ~{int(rate*100)}% tax/TDS deduction.",
                    })
                    matched_invoice_ids.add(irow["invoice_id"])
                    matched_bank_ids.add(brow["txn_id"])
                    break
            if irow["invoice_id"] in matched_invoice_ids:
                break

    # Pass 3: exact reference, amount clearly lower -> partial payment
    for _, irow in invoices_to_try.iterrows():
        if irow["invoice_id"] in matched_invoice_ids:
            continue
        candidates = bank_to_try[
            (bank_to_try["reference"] == irow["reference"]) &
            (~bank_to_try["txn_id"].isin(matched_bank_ids))
        ]
        for _, brow in candidates.iterrows():
            if brow["amount"] < irow["amount"] * 0.97:
                pct = round(brow["amount"] / irow["amount"] * 100, 1)
                matched_rows.append({
                    "invoice_id": irow["invoice_id"], "txn_id": brow["txn_id"],
                    "party": irow["party"], "invoice_amount": irow["amount"],
                    "bank_amount": brow["amount"], "match_type": "partial_payment",
                    "detail": f"Only {pct}% of invoice value received. Balance still due.",
                })
                matched_invoice_ids.add(irow["invoice_id"])
                matched_bank_ids.add(brow["txn_id"])
                break

    # Pass 4: fuzzy reference match (typo-tolerant) within a date window
    for _, irow in invoices_to_try.iterrows():
        if irow["invoice_id"] in matched_invoice_ids:
            continue
        best_score, best_txn = 0, None
        for _, brow in bank_to_try.iterrows():
            if brow["txn_id"] in matched_bank_ids:
                continue
            if abs((brow["txn_date"] - irow["invoice_date"]).days) > DATE_WINDOW_DAYS:
                continue
            if abs(brow["amount"] - irow["amount"]) > irow["amount"] * AMOUNT_TOLERANCE_PCT:
                continue
            score = _ref_similarity(irow["reference"], brow["reference"])
            if score > best_score:
                best_score, best_txn = score, brow
        if best_txn is not None and best_score >= 0.75:
            matched_rows.append({
                "invoice_id": irow["invoice_id"], "txn_id": best_txn["txn_id"],
                "party": irow["party"], "invoice_amount": irow["amount"],
                "bank_amount": best_txn["amount"], "match_type": "fuzzy",
                "detail": f"Reference similarity {best_score:.0%}; amount and date aligned within tolerance.",
            })
            matched_invoice_ids.add(irow["invoice_id"])
            matched_bank_ids.add(best_txn["txn_id"])

    # Pass 5: party-name fuzzy match against the bank narration, for cases
    # where the reference number doesn't help at all (e.g. bank narration
    # only carries a shortened/abbreviated version of the party name, like
    # "Sharma Ji Ent" for "Sharma Ji Enterprises") — amount + date must
    # still line up within tolerance, but the reference is ignored.
    for _, irow in invoices_to_try.iterrows():
        if irow["invoice_id"] in matched_invoice_ids:
            continue
        best_score, best_txn = 0.0, None
        for _, brow in bank_to_try.iterrows():
            if brow["txn_id"] in matched_bank_ids:
                continue
            if abs((brow["txn_date"] - irow["invoice_date"]).days) > DATE_WINDOW_DAYS:
                continue
            if abs(brow["amount"] - irow["amount"]) > irow["amount"] * AMOUNT_TOLERANCE_PCT:
                continue
            score = _name_overlap_score(irow["party"], brow["narration"])
            if score > best_score:
                best_score, best_txn = score, brow
        if best_txn is not None and best_score >= 0.5:
            matched_rows.append({
                "invoice_id": irow["invoice_id"], "txn_id": best_txn["txn_id"],
                "party": irow["party"], "invoice_amount": irow["amount"],
                "bank_amount": best_txn["amount"], "match_type": "name_matched",
                "detail": f"No reference match, but bank narration '{best_txn['narration']}' shares "
                          f"{best_score:.0%} of the party name's distinctive words with '{irow['party']}'.",
            })
            matched_invoice_ids.add(irow["invoice_id"])
            matched_bank_ids.add(best_txn["txn_id"])

    matched_df = pd.DataFrame(matched_rows)

    # ---- Exceptions -------------------------------------------------------
    exceptions = []

    for _, irow in inv.iterrows():
        if irow["invoice_id"] in dup_invoice_ids:
            exceptions.append({
                "type": "duplicate_invoice", "reference": irow["invoice_id"],
                "party": irow["party"], "amount": irow["amount"],
                "detail": "Likely double-billing: same party, amount and date as another invoice.",
            })
        elif irow["invoice_id"] not in matched_invoice_ids:
            exceptions.append({
                "type": "unmatched_invoice", "reference": irow["invoice_id"],
                "party": irow["party"], "amount": irow["amount"],
                "detail": "No corresponding bank credit found. Payment likely pending.",
            })

    for _, brow in bank.iterrows():
        if brow["txn_id"] in dup_bank_ids:
            exceptions.append({
                "type": "duplicate_bank_credit", "reference": brow["txn_id"],
                "party": brow["narration"], "amount": brow["amount"],
                "detail": "Bank feed shows this credit more than once — verify with the bank before booking.",
            })
        elif brow["txn_id"] not in matched_bank_ids:
            exceptions.append({
                "type": "unmatched_bank_credit", "reference": brow["txn_id"],
                "party": brow["narration"], "amount": brow["amount"],
                "detail": "Money received with no matching invoice on file — could be an advance or misdirected transfer.",
            })

    # partial payments are technically "matched" but still owe a balance —
    # surface them as exceptions too, since they need follow-up
    for row in matched_rows:
        if row["match_type"] == "partial_payment":
            balance = round(row["invoice_amount"] - row["bank_amount"], 2)
            exceptions.append({
                "type": "partial_payment_balance_due", "reference": row["invoice_id"],
                "party": row["party"], "amount": balance,
                "detail": f"Balance of {balance:,.2f} still outstanding on this invoice.",
            })

    exceptions_df = pd.DataFrame(exceptions)

    # ---- Match rate (by invoice VALUE, the number that matters) ----------
    total_invoice_value = inv[~inv["invoice_id"].isin(dup_invoice_ids)]["amount"].sum()
    reconciled_value = matched_df["invoice_amount"].sum() if not matched_df.empty else 0
    match_rate = round(reconciled_value / total_invoice_value * 100, 1) if total_invoice_value else 0

    summary = {
        "total_invoices": int(len(inv)),
        "total_bank_txns": int(len(bank)),
        "matched_count": int(len(matched_df)),
        "match_rate_by_value_pct": match_rate,
        "match_type_breakdown": matched_df["match_type"].value_counts().to_dict() if not matched_df.empty else {},
        "exception_count": int(len(exceptions_df)),
        "exception_type_breakdown": exceptions_df["type"].value_counts().to_dict() if not exceptions_df.empty else {},
        "total_invoice_value": round(float(total_invoice_value), 2),
        "reconciled_value": round(float(reconciled_value), 2),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    matched_df.to_csv(f"{DATA_DIR}/matched.csv", index=False)
    exceptions_df.to_csv(f"{DATA_DIR}/exceptions.csv", index=False)
    with open(f"{DATA_DIR}/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    return matched_df, exceptions_df, summary


if __name__ == "__main__":
    matched_df, exceptions_df, summary = reconcile()
    print(json.dumps(summary, indent=2))
