# transforms/inflation.py
"""
PURPOSE
-------
Compute core inflation metrics for the dashboard:
- cpi_yoy_pct         : 12-month % change (headline CPI)
- cpi_3m_ann_pct      : 3-month annualized % change (headline CPI)
- core_yoy_pct        : 12-month % change (core CPI)
- breakeven_10y_pct   : 10-year breakeven (market implied, percent)

INPUTS (from FRED via daily_run.py)
-----------------------------------
data/raw/fred/CPIAUCSL.parquet
data/raw/fred/CPILFESL.parquet
data/raw/fred/T10YIE.parquet

OUTPUT
------
data/derived/inflation.parquet
  index : Month-end DatetimeIndex (UTC)
  cols  : ['cpi_yoy_pct', 'cpi_3m_ann_pct', 'core_yoy_pct', 'breakeven_10y_pct']
"""

import pandas as pd
from storage.io_parquet import load_parquet, save_parquet

def _month_end(series: pd.Series) -> pd.Series:
    """
    Resample any frequency to month-end by taking the last available observation.
    Keeps a UTC DatetimeIndex.
    """
    if series.empty:
        return series
    s = series.sort_index()
    # Resample to calendar month-end; FRED CPI is monthly, T10YIE is daily
    s = s.resample("ME").last()
    return s

def compute_inflation_metrics(
    in_cpi: str = "raw/fred/CPIAUCSL.parquet",
    in_core: str = "raw/fred/CPILFESL.parquet",
    in_be10: str = "raw/fred/T10YIE.parquet",
    out_path: str = "derived/inflation.parquet",
) -> pd.DataFrame:
    """
    Load CPI / Core CPI / 10y breakeven and compute monthly inflation indicators.
    Returns the DataFrame and writes it to data/derived/inflation.parquet.
    """

    # --- Load raw inputs (value in index=dates) ---
    cpi = load_parquet(in_cpi)
    core = load_parquet(in_core)
    be10 = load_parquet(in_be10)

    if cpi.empty or core.empty:
        raise ValueError("Missing CPI or Core CPI inputs. Did daily_run.py pull FRED series?")

    # Select numeric 'value' as Series
    cpi_s = cpi["value"].astype(float)
    core_s = core["value"].astype(float)
    be10_s = be10["value"].astype(float) if not be10.empty else pd.Series(dtype=float, index=cpi_s.index)

    # --- Align to month-end snapshots ---
    cpi_m = _month_end(cpi_s)
    core_m = _month_end(core_s)
    be10_m = _month_end(be10_s)

    # --- Compute YoY (12m % change) ---
    cpi_yoy = cpi_m.pct_change(12) * 100.0
    core_yoy = core_m.pct_change(12) * 100.0

    # --- Compute 3m annualized for CPI ---
    # formula: ((CPI_t / CPI_{t-3}) ** 4 - 1) * 100
    cpi_3m_ann = ((cpi_m / cpi_m.shift(3)) ** 4 - 1.0) * 100.0

    # --- Breakeven 10y (percent) ---
    # FRED T10YIE is already in percent (e.g., 2.35). Keep as-is.
    breakeven_10y = be10_m.rename("breakeven_10y_pct")

    # --- Combine, align on shared month-ends ---
    df = pd.concat(
        [
            cpi_yoy.rename("cpi_yoy_pct"),
            cpi_3m_ann.rename("cpi_3m_ann_pct"),
            core_yoy.rename("core_yoy_pct"),
            breakeven_10y,
        ],
        axis=1,
        join="inner",
    ).sort_index()

    # Drop leading NaNs from change calculations (first 12 months, etc.)
    df = df.dropna(how="all")

    # Persist
    save_parquet(df, out_path)
    print(
        f"[inflation] wrote {len(df):,} rows → data/{out_path} | "
        f"range: {df.index.min()} → {df.index.max()}"
    )
    return df
