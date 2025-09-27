# pipelines/daily_run.py
"""
PURPOSE
-------
Chain the daily workflow in one command:
1) Pull market data from config (yfinance)
2) Compute derived 3m–10y spread (bp)
3) Compute signals: inversion_today, inversion_30d
4) Append a one-line CSV log with latest values to logs/daily_run.csv
"""

from pathlib import Path
from datetime import datetime, timezone
import csv

from collectors.market import fetch_market_from_config
from transforms.yield_curve import compute_yield_spread_3m10y
from transforms.signals import compute_yc_inversion_today, compute_yc_inversion_30d
from storage.io_parquet import load_parquet
from transforms.yield_curve_2s10s import compute_yield_spread_2s10s
from transforms.signals import compute_yc2s10s_inversion_today, compute_yc2s10s_inversion_30d
from collectors.fred import fetch_fred_series
from storage.io_parquet import save_parquet
from transforms.inflation import compute_inflation_metrics
from transforms.credit import compute_credit_levels, compute_credit_stress_flag

def _latest_value(parquet_rel_path: str, col: str | None = None):
    """
    Load a parquet and return the latest (last row) value.
    If 'col' is None, assumes single-column frame.
    Returns (timestamp_iso, value) or (None, None) if empty.
    """
    df = load_parquet(parquet_rel_path)
    if df is None or df.empty:
        return None, None
    if col is None:
        col = df.columns[0]
    ts = df.index.max()
    val = df.loc[ts, col]
    # if row is a Series, convert to scalar
    try:
        val = float(val)
    except Exception:
        pass
    return ts.isoformat(), val


def _pull_fred(series_ids: list[str], start: str = "2000-01-01") -> int:
    """
    Pull a list of FRED series (e.g., ["DGS2"]) and save to data/raw/fred/.
    Returns how many series were successfully written.
    """
    written = 0
    for sid in series_ids:
        try:
            df = fetch_fred_series(sid, start=start)
            if df is None or df.empty:
                print(f"[daily_run] WARNING: FRED {sid} returned empty.")
                continue
            save_parquet(df, f"raw/fred/{sid}.parquet")
            print(f"[daily_run] FRED {sid} rows: {len(df):,}")
            written += 1
        except Exception as e:
            print(f"[daily_run] ERROR pulling FRED {sid}:", e)
    return written


def _append_log(row: dict, log_path: Path):
    """
    Append a dict row to CSV at logs/daily_run.csv.
    Creates file with header if it doesn't exist.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            w.writeheader()
        w.writerow(row)


if __name__ == "__main__":
    # 1) Pull market data
    pulled = fetch_market_from_config(lookback_days=20000)

    # Pull needed FRED series
    fred_count = _pull_fred(
        [
            "DGS2",  # 2-Year Treasury Constant Maturity Rate (yield on 2y U.S. Treasury)
            "DGS3MO",  # 3-Month Treasury Constant Maturity Rate (yield on 3m U.S. Treasury)
            "CPIAUCSL",  # Consumer Price Index for All Urban Consumers (Headline CPI, index, SA)
            "CPILFESL", # Consumer Price Index for All Urban Consumers: All Items Less Food & Energy (Core CPI, index, SA)
            "T10YIE",  # 10-Year Breakeven Inflation Rate (market-implied inflation from TIPS vs Treasuries)
            "BAMLH0A0HYM2",  # ICE BofA US High Yield Option-Adjusted Spread (HY OAS) – risk premium on junk bonds
            "BAMLC0A0CM" # ICE BofA US Corporate Option-Adjusted Spread (IG OAS) – risk premium on investment grade bonds
        ],
        start="1999-01-01"
    )

    # 2) Compute spread
    compute_yield_spread_3m10y()
    compute_yield_spread_2s10s()


    # 3) Compute signals
    compute_yc_inversion_today()
    compute_yc_inversion_30d()
    compute_yc2s10s_inversion_today()
    compute_yc2s10s_inversion_30d()
    compute_inflation_metrics()
    compute_credit_levels()
    compute_credit_stress_flag()


    # 4) Gather latest values for the log
    ts_spread, spread_bp = _latest_value("derived/yield_curve.parquet", "spread_3m10y_bp")
    ts_today, inv_today = _latest_value("derived/signals/yc_inversion_today.parquet", "yc_inversion_today")
    ts_30d, inv_30d = _latest_value("derived/signals/yc_inversion_30d.parquet", "yc_inversion_30d")
    ts_spread2, spread2_bp = _latest_value("derived/yc_2s10s.parquet", "spread_2s10s_bp")
    ts_today2, inv2_today = _latest_value("derived/signals/yc2s10s_inversion_today.parquet", "yc2s10s_inversion_today")
    ts_30d2, inv2_30d = _latest_value("derived/signals/yc2s10s_inversion_30d.parquet", "yc2s10s_inversion_30d")

    # Prefer the newest timestamp we computed today
    ts_now = datetime.now(timezone.utc).isoformat()

    row = {
        "run_ts_utc": ts_now,
        "pulled_count": pulled,
        "spread_last_ts": ts_spread,
        "spread_3m10y_bp": spread_bp,
        "yc_inversion_today": bool(inv_today) if inv_today is not None else None,
        "yc_inversion_30d": bool(inv_30d) if inv_30d is not None else None,
        "spread2s10s_last_ts": ts_spread2,
        "spread_2s10s_bp": spread2_bp,
        "yc2s10s_inversion_today": bool(inv2_today) if inv2_today is not None else None,
        "yc2s10s_inversion_30d": bool(inv2_30d) if inv2_30d is not None else None,
    }

    _append_log(row, Path("logs/daily_run.csv"))

    print(
        "[daily_run] pulled:", pulled,
        "| 3m–10y(bp):", spread_bp,
        "| inv_today:", bool(inv_today) if inv_today is not None else None,
        "| inv_30d:", bool(inv_30d) if inv_30d is not None else None,
        "| 2s–10s(bp):", spread2_bp,
        "| fred:", fred_count,
        "| inv2_today:", bool(inv2_today) if inv2_today is not None else None,
        "| inv2_30d:", bool(inv2_30d) if inv2_30d is not None else None,
        "| log -> logs/daily_run.csv"
        )
