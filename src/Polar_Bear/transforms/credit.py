# transforms/credit.py
"""
PURPOSE
-------
Create derived credit-stress data:
- Convert HY and IG OAS (from FRED) to basis points.
- Compute hy_ig_diff_bp = HY_OAS_bp - IG_OAS_bp.
- Create a simple stress signal: HY_OAS above its rolling 3y 80th percentile.

INPUTS (from FRED via daily_run.py)
-----------------------------------
data/raw/fred/BAMLH0A0HYM2.parquet  # HY OAS, percent
data/raw/fred/BAMLC0A0CM.parquet     # IG OAS, percent

OUTPUTS
-------
data/derived/credit.parquet
  index : DatetimeIndex (UTC)
  cols  : ['hy_oas_bp', 'ig_oas_bp', 'hy_ig_diff_bp']

data/derived/signals/credit_stress_3y80.parquet
  index : DatetimeIndex (UTC)
  cols  : ['credit_stress_3y80']  (bool)
"""

import pandas as pd
from storage.io_parquet import load_parquet, save_parquet

def compute_credit_levels(
    in_hy: str = "raw/fred/BAMLH0A0HYM2.parquet",
    in_ig: str = "raw/fred/BAMLC0A0CM.parquet",
    out_path: str = "derived/credit.parquet",
) -> pd.DataFrame:
    # 1) Load raw (FRED %)
    hy = load_parquet(in_hy)
    ig = load_parquet(in_ig)
    if hy.empty or ig.empty:
        raise ValueError("Missing HY or IG input parquet. Run daily_run.py first.")

    # 2) Select numeric series
    hy_s = hy["value"].astype(float).rename("hy_pct")
    ig_s = ig["value"].astype(float).rename("ig_pct")

    # 3) Align on shared dates
    df = pd.concat([hy_s, ig_s], axis=1, join="inner").dropna().sort_index()
    if df.empty:
        raise ValueError("No overlapping dates between HY and IG OAS.")

    # 4) Convert % → bp and compute diff
    df["hy_oas_bp"] = df["hy_pct"] * 100.0
    df["ig_oas_bp"] = df["ig_pct"] * 100.0
    df["hy_ig_diff_bp"] = df["hy_oas_bp"] - df["ig_oas_bp"]

    out = df[["hy_oas_bp", "ig_oas_bp", "hy_ig_diff_bp"]]
    save_parquet(out, out_path)
    print(f"[credit] wrote {len(out):,} rows → data/{out_path} | range: {out.index.min()} → {out.index.max()}")
    return out


def compute_credit_stress_flag(
    in_credit: str = "derived/credit.parquet",
    out_path: str = "derived/signals/credit_stress_3y80.parquet",
    window_days: int = 756,  # ≈ 3y of trading days
    percentile: float = 0.80,
) -> pd.DataFrame:
    """
    Stress = HY OAS in bp >= rolling 3-year 80th percentile.
    """
    df = load_parquet(in_credit)
    if df.empty or "hy_oas_bp" not in df.columns:
        raise ValueError("Missing derived credit levels. Run compute_credit_levels() first.")

    s = df["hy_oas_bp"].astype(float)
    # Rolling quantile (requires pandas >= 1.5). For older versions, use a custom pct function.
    q = s.rolling(window_days, min_periods=100).quantile(percentile)
    stress = (s >= q)

    out = stress.to_frame(name="credit_stress_3y80")
    out.index.name = df.index.name or "Date"
    save_parquet(out, out_path)
    print(f"[credit] wrote {len(out):,} rows → data/{out_path}")
    return out
