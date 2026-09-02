"""
app.py
------
AI Finance Controller — Streamlit front-end (Section 3 of the brief).

Three tabs:
  1. Reconciliation  — match rate, matched pairs, exception list, downloads
  2. Cash-Flow Forecast — next-30-day projection chart + table
  3. Chat with your books — ask in plain language (Hindi/English), grounded
     in the reconciled data. Optional Anthropic API key for LLM-mode.

Run:
    pip install -r requirements.txt
    streamlit run app.py
"""

import os

import pandas as pd
import streamlit as st

from generate_data import generate
from reconcile import reconcile
from forecast import forecast
from chat_agent import build_context, answer_rule_based, answer_with_llm

st.set_page_config(page_title="AI Finance Controller", page_icon="◆", layout="wide")

DATA_DIR = "data"

# ---------------------------------------------------------------- Theme --
LEDGER_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
    --bg: #0F1115;
    --panel: #1A1D26;
    --panel-2: #20232F;
    --ink: #E5E7EB;
    --ink-soft: #9CA3AF;
    --rule: #2B2E3A;
    --indigo: #818CF8;
    --indigo-deep: #6366F1;
    --violet: #A78BFA;
    --teal: #2DD4BF;
    --gold: #FBBF24;
    --green: #34D399;
    --green-soft: rgba(52,211,153,0.14);
    --red: #F87171;
    --red-soft: rgba(248,113,113,0.14);
    --amber-soft: rgba(251,191,36,0.14);
    --indigo-soft: rgba(129,140,248,0.14);
    --violet-soft: rgba(167,139,250,0.14);
}

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; color: var(--ink); }
.stApp { background: var(--bg); }

h1, h2, h3 { font-family: 'Fraunces', serif; font-weight: 600; color: var(--ink); letter-spacing: -0.01em; }
h1 { font-size: 2rem !important; }
h2 { font-size: 1.4rem !important; }

/* Masthead — gradient banner, the one bold visual statement */
.ledger-masthead {
    background: linear-gradient(120deg, #4F46E5 0%, #7C3AED 100%);
    border-radius: 12px; padding: 1.6rem 2rem; margin-bottom: 1.8rem;
    box-shadow: 0 8px 28px -6px rgba(79,70,229,0.45);
}
.ledger-masthead .mark { font-family: 'Fraunces', serif; font-weight: 700; font-size: 2.1rem; color: #FFFFFF; margin: 0; display: flex; align-items: center; gap: 0.7rem; }
.logo-badge {
    display: inline-flex; align-items: center; justify-content: center;
    width: 42px; height: 42px; border-radius: 8px; background: rgba(255,255,255,0.14);
    border: 1px solid rgba(255,255,255,0.3); font-family: 'IBM Plex Mono', monospace;
    font-weight: 600; font-size: 1rem; color: #FFFFFF; letter-spacing: -0.02em;
}
.ledger-masthead .tagline { font-family: 'IBM Plex Sans', sans-serif; font-size: 0.98rem; color: #E9E7FC; margin-top: 0.3rem; }

/* Sidebar */
section[data-testid="stSidebar"] { background: var(--panel); border-right: 1px solid var(--rule); }
section[data-testid="stSidebar"] h3 { font-family: 'Fraunces', serif; color: var(--indigo); }

/* Buttons */
.stButton>button {
    border-radius: 8px; border: 1px solid var(--indigo-deep); font-family: 'IBM Plex Sans', sans-serif; font-weight: 500;
}
.stButton>button[kind="primary"] { background: var(--indigo-deep); border-color: var(--indigo-deep); color: #fff; }
.stButton>button[kind="primary"]:hover { background: #4338CA; border-color: #4338CA; }
.stButton>button[kind="secondary"] { background: var(--panel-2); color: var(--ink); border-color: var(--rule); }
.stButton>button[kind="secondary"]:hover { border-color: var(--indigo); color: var(--indigo); }

/* Tabs */
div[data-baseweb="tab-list"] { border-bottom: 1px solid var(--rule); gap: 0.5rem; }
div[data-baseweb="tab-list"] button { font-family: 'IBM Plex Sans', sans-serif; font-weight: 600; font-size: 1rem; color: var(--ink-soft); }
div[data-baseweb="tab-list"] button[aria-selected="true"] { color: var(--indigo); }
div[data-baseweb="tab-highlight"] { background-color: var(--indigo) !important; height: 3px !important; }

/* Metrics -- colored card feel */
div[data-testid="stMetric"] {
    background: var(--panel-2); border-radius: 10px; padding: 0.9rem 1rem 0.7rem;
    border: 1px solid var(--rule); border-top: 3px solid var(--indigo);
}
div[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace; color: var(--ink); font-size: 1.5rem !important; }
div[data-testid="stMetricLabel"] { color: var(--ink-soft); font-size: 0.85rem; }

/* Info / success / warning boxes */
.stAlert { border-radius: 8px; }

/* Chat */
div[data-testid="stChatMessage"] { background: var(--panel-2); border-radius: 10px; border: 1px solid var(--rule); }

/* DataFrames */
div[data-testid="stDataFrame"] { border: 1px solid var(--rule); border-radius: 8px; font-family: 'IBM Plex Mono', monospace; }

/* Divider color */
hr { border-color: var(--rule) !important; }

/* Progress bar */
div[data-testid="stProgress"] > div > div { background: linear-gradient(90deg, var(--indigo), var(--violet)); }

/* Sidebar expanders (Reconcile / Forecast / Chat panels) */
section[data-testid="stSidebar"] details {
    border: 1px solid var(--rule); border-radius: 10px; background: var(--panel-2);
    margin-bottom: 0.8rem; overflow: hidden;
}
section[data-testid="stSidebar"] details summary {
    font-family: 'Fraunces', serif; font-weight: 600; font-size: 1.02rem;
    padding: 0.65rem 0.9rem; color: var(--ink);
}
section[data-testid="stSidebar"] details summary:hover { color: var(--indigo); }
section[data-testid="stSidebar"] details[open] summary { border-bottom: 1px solid var(--rule); color: var(--indigo); }
section[data-testid="stSidebar"] details > div { padding: 0.8rem 0.9rem 0.9rem; }

/* Colored left-accent per panel, so each step is visually distinct */
section[data-testid="stSidebar"] div[data-testid="stExpander"]:nth-of-type(1) details { border-left: 4px solid #6B7280; }
section[data-testid="stSidebar"] div[data-testid="stExpander"]:nth-of-type(2) details { border-left: 4px solid var(--indigo); }
section[data-testid="stSidebar"] div[data-testid="stExpander"]:nth-of-type(3) details { border-left: 4px solid var(--violet); }
section[data-testid="stSidebar"] div[data-testid="stExpander"]:nth-of-type(4) details { border-left: 4px solid var(--teal); }
/* Colored status pills used inside tables */
.pill { display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.78rem; font-weight: 600; }

/* Circular gauge for match rate */
.gauge-wrap { display: flex; align-items: center; gap: 1.4rem; margin-bottom: 0.6rem; }
.gauge {
    width: 108px; height: 108px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: conic-gradient(var(--indigo) calc(var(--pct) * 1%), var(--rule) 0);
}
.gauge-inner {
    width: 82px; height: 82px; border-radius: 50%; background: var(--panel);
    display: flex; align-items: center; justify-content: center; flex-direction: column;
}
.gauge-inner .pct { font-family: 'IBM Plex Mono', monospace; font-size: 1.35rem; font-weight: 600; color: var(--indigo); }
.gauge-inner .lbl { font-size: 0.65rem; color: var(--ink-soft); }

/* Always-on KPI strip below masthead */
.kpi-strip { display: flex; gap: 1rem; margin-bottom: 1.6rem; flex-wrap: wrap; }
.kpi-card {
    flex: 1; min-width: 160px; background: var(--panel-2); border: 1px solid var(--rule);
    border-radius: 10px; padding: 0.7rem 1rem;
}
.kpi-card .kpi-label { font-size: 0.78rem; color: var(--ink-soft); }
.kpi-card .kpi-value { font-family: 'IBM Plex Mono', monospace; font-size: 1.3rem; font-weight: 600; color: var(--ink); }
</style>
"""
st.markdown(LEDGER_CSS, unsafe_allow_html=True)


def ensure_data():
    if not os.path.exists(f"{DATA_DIR}/invoices.csv"):
        generate()


def ensure_pipeline_ran():
    """Auto-run reconciliation and forecast once on first load, so every
    tab shows real results immediately instead of an empty state."""
    if not os.path.exists(f"{DATA_DIR}/summary.json"):
        reconcile()
    if not os.path.exists(f"{DATA_DIR}/forecast_summary.json"):
        forecast()


ensure_data()
ensure_pipeline_ran()

st.markdown(
    """
    <div class="ledger-masthead">
        <p class="mark"><span class="logo-badge">AF</span>AI Finance Controller</p>
        <p class="tagline">Reconciliation, forecasting, and answers — read from the same set of books.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---- Always-visible KPI strip (reads live from disk, works on every tab) --
import json as _json


def _kpi_strip():
    summary_path, fcast_path = f"{DATA_DIR}/summary.json", f"{DATA_DIR}/forecast_summary.json"
    if not (os.path.exists(summary_path) and os.path.exists(fcast_path)):
        return
    with open(summary_path) as f:
        s = _json.load(f)
    with open(fcast_path) as f:
        fc = _json.load(f)
    st.markdown(
        f"""
        <div class="kpi-strip">
            <div class="kpi-card"><div class="kpi-label">Match rate</div><div class="kpi-value">{s['match_rate_by_value_pct']}%</div></div>
            <div class="kpi-card"><div class="kpi-label">Open exceptions</div><div class="kpi-value">{s['exception_count']}</div></div>
            <div class="kpi-card"><div class="kpi-label">Reconciled value</div><div class="kpi-value">₹{s['reconciled_value']:,.0f}</div></div>
            <div class="kpi-card"><div class="kpi-label">Projected balance ({fc['forecast_days']}d)</div><div class="kpi-value">₹{fc['projected_balance_end']:,.0f}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _gauge(pct, label="Match rate"):
    st.markdown(
        f"""
        <div class="gauge-wrap">
            <div class="gauge" style="--pct:{pct};">
                <div class="gauge-inner"><span class="pct">{pct}%</span><span class="lbl">{label}</span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


PILL_COLORS = {
    "exact": ("rgba(52,211,153,0.16)", "#34D399"),
    "tax_adjusted": ("rgba(129,140,248,0.16)", "#818CF8"),
    "fuzzy": ("rgba(167,139,250,0.16)", "#A78BFA"),
    "name_matched": ("rgba(45,212,191,0.16)", "#2DD4BF"),
    "partial_payment": ("rgba(251,191,36,0.16)", "#FBBF24"),
    "unmatched_invoice": ("rgba(248,113,113,0.16)", "#F87171"),
    "unmatched_bank_credit": ("rgba(248,113,113,0.16)", "#F87171"),
    "duplicate_invoice": ("rgba(251,191,36,0.16)", "#FBBF24"),
    "duplicate_bank_credit": ("rgba(251,191,36,0.16)", "#FBBF24"),
    "partial_payment_balance_due": ("rgba(129,140,248,0.16)", "#818CF8"),
}


def _style_status_col(df, col):
    def _color(val):
        bg, fg = PILL_COLORS.get(val, ("rgba(156,163,175,0.16)", "#9CA3AF"))
        return f"background-color: {bg}; color: {fg}; font-weight: 600;"
    styler = df.style
    if hasattr(styler, "map"):
        return styler.map(_color, subset=[col])
    return styler.applymap(_color, subset=[col])


_kpi_strip()

# ---------------------------------------------------------------- Sidebar --
with st.sidebar:
    st.markdown("### AI Finance Controller")

    st.divider()

    with st.expander("Data", expanded=False):
        if st.button("Regenerate synthetic batch", use_container_width=True):
            generate()
            reconcile()
            forecast(opening_balance=500000.0, forecast_days=30)
            st.success("New batch generated and reconciled.")

    with st.expander("Reconcile", expanded=True):
        if st.button("Run reconciliation", type="primary", use_container_width=True):
            with st.spinner("Matching invoices to bank transactions..."):
                matched_df, exceptions_df, summary = reconcile()
            st.session_state["summary"] = summary
            st.success(f"Match rate: {summary['match_rate_by_value_pct']}%")

    with st.expander("Forecast", expanded=False):
        opening_balance = st.number_input("Opening cash balance (₹)", min_value=0.0, value=500000.0, step=10000.0)
        forecast_days = st.slider("Forecast horizon (days)", 7, 60, 30)
        if st.button("Run forecast", type="primary", use_container_width=True):
            if not os.path.exists(f"{DATA_DIR}/matched.csv"):
                st.warning("Run reconciliation first.")
            else:
                with st.spinner("Projecting cash position..."):
                    fcast_df, fcast_summary = forecast(opening_balance=opening_balance, forecast_days=forecast_days)
                st.success(f"Projected balance in {forecast_days}d: ₹{fcast_summary['projected_balance_end']:,.0f}")

    with st.expander("Chat", expanded=False):
        use_llm = st.toggle("Use real LLM (Claude)", value=False)
        api_key = None
        if use_llm:
            api_key = st.text_input("Anthropic API key", type="password")


# ------------------------------------------------------------------ Tabs --
tab1, tab2, tab3 = st.tabs(["Reconciliation", "Cash-Flow Forecast", "Chat with your books"])

# ---- Tab 1: Reconciliation --------------------------------------------------
with tab1:
    st.header("Multi-source reconciliation")

    summary_path = f"{DATA_DIR}/summary.json"
    if not os.path.exists(summary_path):
        st.info("Click **Run reconciliation** in the sidebar to process the synthetic batch.")
    else:
        with open(summary_path) as f:
            summary = _json.load(f)

        gcol, mcol = st.columns([1, 3])
        with gcol:
            _gauge(summary['match_rate_by_value_pct'])
        with mcol:
            c1, c2, c3 = st.columns(3)
            c1.metric("Invoices matched", f"{summary['matched_count']} / {summary['total_invoices']}")
            c2.metric("Reconciled value", f"₹{summary['reconciled_value']:,.0f}")
            c3.metric("Open exceptions", summary['exception_count'])

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Matched")
            matched_df = pd.read_csv(f"{DATA_DIR}/matched.csv")
            if not matched_df.empty:
                mt_counts = matched_df["match_type"].value_counts()
                st.bar_chart(mt_counts)
                st.dataframe(_style_status_col(matched_df, "match_type"), use_container_width=True, height=280)
                st.download_button("Download matched.csv", matched_df.to_csv(index=False), "matched.csv", "text/csv")
            else:
                st.write("No matches yet.")

        with col_b:
            st.subheader("Exceptions — needs a human")
            exceptions_df = pd.read_csv(f"{DATA_DIR}/exceptions.csv")
            if not exceptions_df.empty:
                exc_counts = exceptions_df["type"].value_counts()
                st.bar_chart(exc_counts)
                st.dataframe(_style_status_col(exceptions_df, "type"), use_container_width=True, height=280)
                st.download_button("Download exceptions.csv", exceptions_df.to_csv(index=False), "exceptions.csv", "text/csv")
            else:
                st.write("No open exceptions — fully reconciled!")

# ---- Tab 2: Forecast --------------------------------------------------------
with tab2:
    st.header("Forward cash-flow forecast")

    fcast_summary_path = f"{DATA_DIR}/forecast_summary.json"
    if not os.path.exists(fcast_summary_path):
        st.info("Click **Run forecast** in the sidebar (after reconciliation) to generate a projection.")
    else:
        with open(fcast_summary_path) as f:
            fs = _json.load(f)

        c1, c2, c3 = st.columns(3)
        c1.metric("Opening balance", f"₹{fs['opening_balance']:,.0f}")
        c2.metric(f"Projected balance ({fs['forecast_days']}d)", f"₹{fs['projected_balance_end']:,.0f}")
        c3.metric("Total projected inflow", f"₹{fs['total_projected_inflow']:,.0f}")

        fcast_df = pd.read_csv(f"{DATA_DIR}/forecast.csv", parse_dates=["date"])
        st.line_chart(fcast_df.set_index("date")["projected_cash_balance"])
        st.bar_chart(fcast_df.set_index("date")["predicted_net_inflow"])
        st.dataframe(fcast_df, use_container_width=True, height=280)
        st.download_button("Download forecast.csv", fcast_df.to_csv(index=False), "forecast.csv", "text/csv")

# ---- Tab 3: Chat -------------------------------------------------------------
with tab3:
    st.header("Ask your books a question")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    if not st.session_state.chat_history:
        with st.chat_message("assistant"):
            st.markdown("Hi! I can answer questions about your reconciliation and cash-flow forecast — try one of the examples below, or type your own.")

    for role, msg in st.session_state.chat_history:
        with st.chat_message(role):
            st.markdown(msg)

    example_cols = st.columns(4)
    examples = [
        "What's the match rate?",
        "Show exceptions",
        "How's next month's forecast?",
        "Which payments are partial?",
    ]
    clicked = None
    for col, ex in zip(example_cols, examples):
        if col.button(ex, use_container_width=True):
            clicked = ex

    user_q = st.chat_input("Type your question...") or clicked

    if user_q:
        st.session_state.chat_history.append(("user", user_q))
        with st.chat_message("user"):
            st.markdown(user_q)

        ctx = build_context()
        if use_llm and api_key:
            with st.spinner("Asking Claude..."):
                answer = answer_with_llm(user_q, ctx, api_key)
        else:
            answer = answer_rule_based(user_q, ctx)

        st.session_state.chat_history.append(("assistant", answer))
        with st.chat_message("assistant"):
            st.markdown(answer)
