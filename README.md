# AI Finance Controller
### Razorpay Buildathon — Track 04: "Run the books and the cash position"

A fully functional finance-ops agent that closes one finance-ops loop on a
90+ record synthetic batch: **reconciliation**, **cash-flow forecasting**,
and **conversational Q&A** — reporting its match rate and unresolved
exceptions honestly.

---

## What's built

| Module | File | What it does |
|--------|------|----------------|
| **Core Engine — Data Reconciliation** | `generate_data.py`, `reconcile.py` | Generates 90+ synthetic invoice/bank records (deliberately messy: tax deductions, partial payments, duplicates, typos, unmatched entries) and reconciles them with a 4-pass matching strategy — exact → tax-adjusted → partial → fuzzy. Every match states its **reason**. |
| **Predictor — Cash-Flow Forecaster** | `forecast.py` | Runs a transparent linear-trend + day-of-week model over the *reconciled* (verified) cash-in data to project the cash position for the next N days. |
| **Conversational UI** | `chat_agent.py`, `app.py` | A Streamlit chat where a merchant can ask in plain English or Hinglish — "have all invoices cleared?", "how's next month's budget?" — and the answer is always read from real reconciliation data, never invented. |

**Bonus add-ons** (beyond the brief):
- **Duplicate detection** — both duplicate invoices (double-billing) *and* duplicate bank credits (bank feed glitches).
- **Fuzzy reference matching** — catches typo/OCR-style errors too (`difflib` similarity).
- **Party-name matching** — when the bank reference is no help at all (e.g. a narration reading "Sharma Ji Ent" for an invoice billed to "Sharma Ji Enterprises"), the engine falls back to comparing the distinctive words in the party name against the narration — no naive exact-string matching required.
- **Match rate by ₹ value**, not just row-count — the number a real finance controller actually needs.
- **Optional real-LLM mode** — supply your own Anthropic API key and chat is answered by Claude (falls back to a rule-based agent, works fully offline otherwise).
- **Downloadable CSVs** for matched pairs, exceptions, and the forecast — auditable, not a black box.

---

## How to run

```bash
cd ai_finance_controller
pip install -r requirements.txt
streamlit run app.py
```

This opens `http://localhost:8501` in your browser. The app auto-generates
data and runs reconciliation + forecast on first load, so every tab shows
real results immediately:

1. **Reconciliation** tab — match rate, matched pairs, exception list
2. **Cash-Flow Forecast** tab — projected balance chart
3. **Chat with your books** tab — ask questions in plain language

Want real LLM mode? Open the **Chat** panel in the sidebar, toggle
**"Use real LLM (Claude)"**, and paste your Anthropic API key (kept only
for the session, never saved to disk).

---

## Testing without Streamlit (CLI)

```bash
python generate_data.py   # writes data/invoices.csv, data/bank_statement.csv
python reconcile.py       # writes data/matched.csv, exceptions.csv, summary.json — prints the match rate
python forecast.py        # writes data/forecast.csv, forecast_summary.json
```

Sample output (from a real run):

```
match_rate_by_value_pct: 89.7%
matched_count: 36 / 47 invoices
exception_count: 27
  - unmatched_invoice: 7
  - unmatched_bank_credit: 6
  - partial_payment_balance_due: 6
  - duplicate_invoice: 4
  - duplicate_bank_credit: 4
```

---

## Why this design

- **Explainable, not a black box**: every match carries a `match_type` +
  `detail` field explaining why it matched — a judge or merchant can verify it.
- **Honest exceptions**: the brief asks for "throughput plus measured
  accuracy plus an honest exception list" — so unmatched items are never
  hidden, only categorized (duplicate vs unmatched vs partial).
- **Chained pipeline**: the forecast runs only on reconciled (verified)
  money, not the raw bank statement — so the projection isn't skewed by
  unverified inflows.
- **Offline-first**: every module works fully without internet or an API
  key (rule-based chat + numpy/pandas forecast) — the LLM is an upgrade,
  not a dependency.

---

## Project structure

```
ai_finance_controller/
├── app.py              # Streamlit UI — 3 tabs
├── generate_data.py    # Synthetic invoice + bank data generator
├── reconcile.py         # Matching engine
├── forecast.py           # Cash-flow projector
├── chat_agent.py          # Rule-based + optional LLM chat brain
├── requirements.txt
├── README.md
└── data/                   # generated at runtime (csv/json)
```
