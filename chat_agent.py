"""
chat_agent.py
-------------
Section 3's brain: answers merchant questions in plain language by reading
the outputs of reconcile.py and forecast.py.

Two modes:
  1. RULE-BASED (default, always available, zero API key needed): a small
     intent classifier over the question, backed by real numbers pulled
     live from summary.json / forecast_summary.json / exceptions.csv.
     This is what makes the "agent" trustworthy — every number it states
     is read straight from the reconciliation engine's output, never
     invented.
  2. LLM MODE (optional): if the user supplies an Anthropic API key in the
     sidebar, questions are instead answered by Claude, given the same
     structured summary as context — so answers read more naturally and
     can handle follow-ups/phrasing the rule-based layer would miss, while
     still being grounded only in the real reconciliation data (no browsing,
     no invented figures).
"""

import json
import re

import pandas as pd

DATA_DIR = "data"


def _safe_read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _safe_read_csv(path):
    try:
        return pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame()


def build_context():
    """Assemble the grounding context both the rule-based layer and the
    optional LLM layer answer from."""
    summary = _safe_read_json(f"{DATA_DIR}/summary.json")
    fcast_summary = _safe_read_json(f"{DATA_DIR}/forecast_summary.json")
    exceptions = _safe_read_csv(f"{DATA_DIR}/exceptions.csv")
    matched = _safe_read_csv(f"{DATA_DIR}/matched.csv")
    return {
        "reconciliation_summary": summary,
        "forecast_summary": fcast_summary,
        "exceptions": exceptions,
        "matched": matched,
    }


def _find_party_or_invoice(question, matched, exceptions):
    """Look for an invoice ID (INV-xxxx) or a party name mentioned in the
    question, and pull whatever we know about it."""
    inv_match = re.search(r"INV-\d+", question, re.IGNORECASE)
    if inv_match:
        inv_id = inv_match.group(0).upper()
        hit = matched[matched["invoice_id"] == inv_id] if not matched.empty else pd.DataFrame()
        if not hit.empty:
            row = hit.iloc[0]
            return (f"{inv_id} is reconciled — matched to bank transaction {row['txn_id']} "
                    f"via a {row['match_type'].replace('_',' ')} match. "
                    f"Invoice amount ₹{row['invoice_amount']:,.2f}, bank amount ₹{row['bank_amount']:,.2f}. "
                    f"{row['detail']}")
        exc_hit = exceptions[exceptions["reference"] == inv_id] if not exceptions.empty else pd.DataFrame()
        if not exc_hit.empty:
            row = exc_hit.iloc[0]
            return f"{inv_id} is an open exception ({row['type'].replace('_',' ')}): {row['detail']}"
        return f"I don't have any record of {inv_id} in this batch."
    return None


def answer_rule_based(question, ctx):
    q = question.lower().strip()
    summary = ctx["reconciliation_summary"]
    fcast = ctx["forecast_summary"]
    exceptions = ctx["exceptions"]
    matched = ctx["matched"]

    if not summary:
        return "Run reconciliation first so I have data to answer from."

    specific = _find_party_or_invoice(question, matched, exceptions)
    if specific:
        return specific

    # match rate / cleared invoices
    if any(k in q for k in ["match rate", "cleared", "clear ho", "settled", "reconcil"]):
        return (f"Match rate is **{summary.get('match_rate_by_value_pct')}%** by invoice value — "
                f"₹{summary.get('reconciled_value'):,.2f} reconciled out of ₹{summary.get('total_invoice_value'):,.2f} total. "
                f"{summary.get('matched_count')} of {summary.get('total_invoices')} invoices have a matching bank transaction. "
                f"{summary.get('exception_count')} items still need attention.")

    # exceptions
    if any(k in q for k in ["exception", "problem", "issue", "pending", "duplicate", "galti"]):
        if exceptions.empty:
            return "No open exceptions — everything is reconciled."
        breakdown = summary.get("exception_type_breakdown", {})
        lines = [f"- {k.replace('_',' ').title()}: {v}" for k, v in breakdown.items()]
        top = exceptions.head(5)
        detail_lines = [f"  • {r['type'].replace('_',' ')} — {r['party']} — ₹{r['amount']:,.2f}" for _, r in top.iterrows()]
        return ("There are **" + str(summary.get('exception_count')) + " open exceptions**:\n"
                + "\n".join(lines) + "\n\nA few examples:\n" + "\n".join(detail_lines))

    # forecast / budget / next month cash
    if any(k in q for k in ["forecast", "budget", "next month", "cash", "agla mahina", "kitna paisa", "balance"]):
        if not fcast:
            return "Run the forecast first so I have a cash-flow projection to share."
        return (f"Over the next {fcast.get('forecast_days')} days, projected net inflow is "
                f"₹{fcast.get('total_projected_inflow'):,.2f}, taking the cash balance from "
                f"₹{fcast.get('opening_balance'):,.2f} to roughly ₹{fcast.get('projected_balance_end'):,.2f} "
                f"by the end of the period. This is built from a linear trend over "
                f"{fcast.get('history_days_used')} days of reconciled inflows, adjusted for "
                f"day-of-week patterns.")

    # partial payments
    if "partial" in q:
        pp = exceptions[exceptions["type"] == "partial_payment_balance_due"] if not exceptions.empty else pd.DataFrame()
        if pp.empty:
            return "No partial payments outstanding right now."
        total = pp["amount"].sum()
        return (f"There are {len(pp)} invoices with a balance still due, totalling ₹{total:,.2f}. "
                "These are payments where the bank credit came in lower than the invoice amount.")

    return ("I can tell you about the match rate, open exceptions, duplicates, partial payments, "
            "the cash-flow forecast, or a specific invoice (e.g. 'INV-1005'). What would you like to know?")


def answer_with_llm(question, ctx, api_key, model="claude-sonnet-4-6"):
    """Optional: route the question to Claude via the Anthropic API,
    grounded strictly in the reconciliation/forecast summary so it can't
    invent numbers. Requires `anthropic` package and network access in
    the user's own environment."""
    try:
        import anthropic
    except ImportError:
        return answer_rule_based(question, ctx) + "\n\n_(Install the `anthropic` package to enable LLM-mode answers.)_"

    client = anthropic.Anthropic(api_key=api_key)

    context_payload = {
        "reconciliation_summary": ctx["reconciliation_summary"],
        "forecast_summary": ctx["forecast_summary"],
        "exceptions_sample": ctx["exceptions"].head(15).to_dict(orient="records") if not ctx["exceptions"].empty else [],
        "matched_sample": ctx["matched"].head(15).to_dict(orient="records") if not ctx["matched"].empty else [],
    }

    system_prompt = (
        "You are the AI Finance Controller chat agent for a merchant dashboard. "
        "Answer ONLY using the JSON data provided below — never invent figures. "
        "If the data doesn't contain the answer, say so plainly. Be concise, "
        "use ₹ for amounts, and use bold for key numbers.\n\n"
        f"DATA:\n{json.dumps(context_payload, indent=2, default=str)}"
    )

    resp = client.messages.create(
        model=model,
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": question}],
    )
    return "".join(block.text for block in resp.content if hasattr(block, "text"))
