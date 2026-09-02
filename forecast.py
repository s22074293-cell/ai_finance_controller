"""
forecast.py
-----------
Section 2 of the brief: the forward cash-flow forecaster.

Deliberately does NOT depend on Prophet (heavy dependency, often unavailable
offline). Instead uses a transparent, explainable model built on pandas/numpy:

  1. Build a daily net cash-flow series from the RECONCILED bank credits
     (only money actually confirmed via reconciliation is treated as real
     cash-in — this is the point of chaining Section 2 after Section 1).
  2. Fit a linear trend (numpy polyfit) over the historical daily series.
  3. Layer a day-of-week seasonality factor (some weekdays run higher
     inflow than others) estimated from the historical data.
  4. Project the next FORECAST_DAYS days as trend * seasonality, and
     accumulate into a running cash position starting from a given
     opening balance.

This is intentionally simple and auditable — a finance controller should
be able to see exactly why the forecast says what it says, not just trust
a black box.

Run: python forecast.py
Reads: data/matched.csv (falls back to data/bank_statement.csv if absent)
Writes: data/forecast.csv, data/forecast_summary.json
"""

import json
import os
from datetime import timedelta

import numpy as np
import pandas as pd

DATA_DIR = "data"
FORECAST_DAYS = 30
OPENING_BALANCE_DEFAULT = 500000.0


def _load_cashflow_history():
    """Prefer reconciled inflows (matched.csv); fall back to raw bank
    statement if reconciliation hasn't been run yet."""
    matched_path = f"{DATA_DIR}/matched.csv"
    bank_path = f"{DATA_DIR}/bank_statement.csv"

    if os.path.exists(matched_path) and os.path.getsize(matched_path) > 0:
        try:
            m = pd.read_csv(matched_path)
            if not m.empty:
                bank = pd.read_csv(bank_path, parse_dates=["txn_date"])
                bank = bank[bank["txn_id"].isin(m["txn_id"])]
                return bank[["txn_date", "amount"]].rename(columns={"txn_date": "date"})
        except Exception:
            pass

    bank = pd.read_csv(bank_path, parse_dates=["txn_date"])
    return bank[["txn_date", "amount"]].rename(columns={"txn_date": "date"})


def forecast(opening_balance=OPENING_BALANCE_DEFAULT, forecast_days=FORECAST_DAYS):
    hist = _load_cashflow_history()
    hist["date"] = pd.to_datetime(hist["date"])
    daily = hist.groupby("date")["amount"].sum().sort_index()

    full_range = pd.date_range(daily.index.min(), daily.index.max())
    daily = daily.reindex(full_range, fill_value=0.0)
    daily.index.name = "date"

    x = np.arange(len(daily))
    y = daily.values

    if len(x) >= 2 and np.ptp(x) > 0:
        slope, intercept = np.polyfit(x, y, 1)
    else:
        slope, intercept = 0.0, float(y.mean()) if len(y) else 0.0

    dow_factor = {}
    df_hist = pd.DataFrame({"date": daily.index, "amount": daily.values})
    df_hist["dow"] = df_hist["date"].dt.dayofweek
    overall_mean = df_hist["amount"].mean() or 1.0
    for d in range(7):
        vals = df_hist.loc[df_hist["dow"] == d, "amount"]
        dow_factor[d] = (vals.mean() / overall_mean) if len(vals) and overall_mean else 1.0

    last_date = daily.index.max()
    last_x = len(daily) - 1

    rows = []
    running_balance = opening_balance
    for i in range(1, forecast_days + 1):
        future_date = last_date + timedelta(days=i)
        trend_value = slope * (last_x + i) + intercept
        factor = dow_factor.get(future_date.dayofweek, 1.0)
        predicted_inflow = max(0.0, trend_value * factor)
        running_balance += predicted_inflow
        rows.append({
            "date": future_date.date().isoformat(),
            "predicted_net_inflow": round(predicted_inflow, 2),
            "projected_cash_balance": round(running_balance, 2),
        })

    forecast_df = pd.DataFrame(rows)

    summary = {
        "opening_balance": opening_balance,
        "history_days_used": int(len(daily)),
        "history_start": daily.index.min().date().isoformat(),
        "history_end": daily.index.max().date().isoformat(),
        "daily_trend_slope": round(float(slope), 2),
        "avg_historical_daily_inflow": round(float(y.mean()) if len(y) else 0.0, 2),
        "forecast_days": forecast_days,
        "projected_balance_end": round(float(forecast_df["projected_cash_balance"].iloc[-1]), 2) if not forecast_df.empty else opening_balance,
        "total_projected_inflow": round(float(forecast_df["predicted_net_inflow"].sum()), 2) if not forecast_df.empty else 0.0,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    forecast_df.to_csv(f"{DATA_DIR}/forecast.csv", index=False)
    with open(f"{DATA_DIR}/forecast_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    return forecast_df, summary


if __name__ == "__main__":
    forecast_df, summary = forecast()
    print(json.dumps(summary, indent=2))
    print(forecast_df.head())
