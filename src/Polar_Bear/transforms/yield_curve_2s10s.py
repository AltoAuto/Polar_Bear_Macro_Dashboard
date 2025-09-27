# transforms/yield_curve_2s10s.py
"""
PURPOSE
-------
Compute the 2s–10s yield curve spread (basis points) from:
- 10-year (^TNX) pulled via yfinance → saved at data/raw/market/^TNX.parquet (percent)
- 2-year (DGS2) pulled via FRED      → saved at data/raw/fred/DGS2.parquet (percent)

OUTPUT
------
data/derived/yc_2s10s.parquet
  index  : DatetimeIndex (UTC)
  columns: ['spread_2s10s_bp']  (float, basis points)
"""

import pandas as pd
from storage.io_parquet import load_parquet, save_parquet

def compute_yield_spread_2s10s(
    in_10y: str = "raw/market/^TNX.parquet",
    in_2y: str = "raw/fred/DGS2.parquet",
    out_path: str = "derived/yc_2s10s.parquet",
) -> pd.DataFrame:
    # 1) Load raw inputs (both in percent)
    tnx = load_parquet(in_10y)   # columns: value, series_id, source
    dgs2 = load_parquet(in_2y)   # columns: value, series_id, source

    if tnx.empty or dgs2.empty:
        raise ValueError("Missing input: ^TNX or DGS2 parquet is empty. Pull data first.")

    # 2) Select 1D Series and align by timestamp (inner join)
    y10 = tnx["value"].astype(float)
    y10.name = "y10"
    y2  = dgs2["value"].astype(float)
    y2.name = "y2"

    df = pd.concat([y10, y2], axis=1, join="inner").dropna()
    if df.empty:
        raise ValueError("No overlapping dates between ^TNX and DGS2 after alignment.")

    # 3) Compute spread in basis points
    spread_bp = (df["y10"] - df["y2"]) * 100.0
    out = spread_bp.to_frame(name="spread_2s10s_bp")
    out.index.name = df.index.name or "Date"

    # 4) Persist
    save_parquet(out, out_path)
    print(
        f"[yc_2s10s] wrote {len(out):,} rows → data/{out_path} | "
        f"range: {out.index.min()} → {out.index.max()}"
    )
    return out
