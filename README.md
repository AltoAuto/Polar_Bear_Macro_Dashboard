# Polar Bear Macro Risk Dashboard

A personal macro dashboard — designed to monitor growth, inflation, credit, and stress indicators in near real-time.  

---

 Features

- **Data Ingestion**
  - Automated pulls from **Yahoo Finance** (rates, ETFs, VIX).
  - **FRED API** for official economic series (yields, CPI, unemployment, etc.).
  - Cleaned + standardized into **Parquet files**.

- **Transformations**
  - Yield curve spreads: 3m–10y, 2s–10s.
  - Inflation metrics: CPI YoY, Core CPI, 3m annualized, 10y breakevens.
  - Credit stress: HY vs IG spreads, HY–IG diff, VIX overlays.
  - Signal flags: yield curve inversion, credit stress > 80th percentile.

- **Dashboard UI**
  - Built in **Streamlit** with **Altair charts**.
  - KPI panels for quick readouts (Inflation %, YC spread, VIX, etc.).
  - Panels so far:
    - Yield Curve
    - Inflation
    - Credit & Stress
    - VIX  
  - (Upcoming: Growth & Labor, Global & FX, Strategy Playbook)

- **Pipelines**
  - `daily_run.py` → runs ingestion + transforms + saves derived metrics.
  - Logs results to `logs/daily_run.csv`.

---

## Project Structure

```bash
macro-dashboard/
  collectors/     # data ingestion (yfinance, FRED, etc.)
  transforms/     # computations (yield spreads, inflation, credit stress)
  storage/        # save/load helpers (Parquet)
  pipelines/      # scripts to run jobs (daily_run, Streamlit app)
  config/         # YAML configs (tickers, API keys)
  data/
    raw/          # raw ingested parquet
    derived/      # computed indicators
    signals/      # boolean signals (e.g., inversion flags)
  logs/           # daily_run log CSVs
