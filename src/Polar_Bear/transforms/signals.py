# transforms/signals.py
import pandas as pd
from storage.io_parquet import load_parquet, save_parquet
def compute_yc_inversion_30d(
    in_path: str = "derived/yield_curve.parquet",
    out_path: str = "derived/signals/yc_inversion_30d.parquet",
    window_days: int = 30,
) -> pd.DataFrame:
    """
    Load the 3m–10y spread (bp) and compute a boolean signal:
      True  -> spread < 0 bp for 'window_days' consecutive trading days
      False -> otherwise

    Input schema:
      index: DatetimeIndex (UTC)
      columns: ['spread_3m10y_bp']

    Output schema:
      index: DatetimeIndex (UTC)
      columns: ['yc_inversion_30d']  (bool)
    """
    df = load_parquet(in_path)
    if df.empty or "spread_3m10y_bp" not in df.columns:
        raise ValueError(f"Missing or invalid input at data/{in_path}")

    s = df["spread_3m10y_bp"].astype(float)
    s = s.sort_index()

    # Condition: spread below 0 bp
    below_zero = s < 0.0

    # Rolling count of consecutive True values over the last 'window_days'
    # Note: this treats each row as a trading day (your data is daily market data).
    rolling_count = below_zero.rolling(window_days, min_periods=window_days).sum()

    # Signal is True only when we have 'window_days' Trues in the window (i.e., all days < 0)
    signal = (rolling_count == window_days)

    out = signal.to_frame(name="yc_inversion_30d")
    out.index.name = df.index.name or "Date"

    save_parquet(out, out_path)
    print(
        f"[signals] wrote {out.shape[0]:,} rows → data/{out_path} | "
        f"last={out.index.max()} | last_value={bool(out.iloc[-1, 0])}"
    )
    return out

def compute_yc_inversion_today(
    in_path: str = "derived/yield_curve.parquet",
    out_path: str = "derived/signals/yc_inversion_today.parquet",
) -> pd.DataFrame:
    """
    PURPOSE
    -------
    Produce a same-day inversion flag:
      True  -> the 3m–10y spread is below 0 bp on this date
      False -> otherwise

    INPUT
    -----
    data/derived/yield_curve.parquet
      index: DatetimeIndex (UTC)
      columns: ['spread_3m10y_bp']  (float, basis points)

    OUTPUT
    ------
    data/derived/signals/yc_inversion_today.parquet
      index: DatetimeIndex (UTC)
      columns: ['yc_inversion_today']  (bool)

    NOTES
    -----
    - This is the "raw" inversion flag (no persistence window).
    - Use together with `compute_yc_inversion_30d` for a stricter, confirmed regime.
    """
    df = load_parquet(in_path)
    if df.empty or "spread_3m10y_bp" not in df.columns:
        raise ValueError(f"Missing or invalid input at data/{in_path}")

    s = df["spread_3m10y_bp"].astype(float).sort_index()
    signal = (s < 0.0)

    out = signal.to_frame(name="yc_inversion_today")
    out.index.name = df.index.name or "Date"

    save_parquet(out, out_path)
    print(
        f"[signals] wrote {out.shape[0]:,} rows → data/{out_path} | "
        f"last={out.index.max()} | last_value={bool(out.iloc[-1, 0])}"
    )
    return out

def compute_yc2s10s_inversion_today(
    in_path: str = "derived/yc_2s10s.parquet",
    out_path: str = "derived/signals/yc2s10s_inversion_today.parquet",
) -> pd.DataFrame:
    """
    PURPOSE
    -------
    Produce a same-day inversion flag for 2s–10s spread:
      True  -> spread < 0 bp
      False -> otherwise

    INPUT
    -----
    data/derived/yc_2s10s.parquet
      index: DatetimeIndex (UTC)
      columns: ['spread_2s10s_bp']

    OUTPUT
    ------
    data/derived/signals/yc2s10s_inversion_today.parquet
      index: DatetimeIndex (UTC)
      columns: ['yc2s10s_inversion_today'] (bool)
    """
    df = load_parquet(in_path)
    if df.empty or "spread_2s10s_bp" not in df.columns:
        raise ValueError(f"Missing or invalid input at data/{in_path}")

    s = df["spread_2s10s_bp"].astype(float).sort_index()
    signal = (s < 0.0)

    out = signal.to_frame(name="yc2s10s_inversion_today")
    out.index.name = df.index.name or "Date"
    save_parquet(out, out_path)
    print(f"[signals] wrote {out.shape[0]:,} rows → data/{out_path}")
    return out


def compute_yc2s10s_inversion_30d(
    in_path: str = "derived/yc_2s10s.parquet",
    out_path: str = "derived/signals/yc2s10s_inversion_30d.parquet",
    window_days: int = 30,
) -> pd.DataFrame:
    """
    PURPOSE
    -------
    Produce a 30-day confirmed inversion flag for 2s–10s spread:
      True  -> spread < 0 bp for 'window_days' consecutive trading days
      False -> otherwise
    """
    df = load_parquet(in_path)
    if df.empty or "spread_2s10s_bp" not in df.columns:
        raise ValueError(f"Missing or invalid input at data/{in_path}")

    s = df["spread_2s10s_bp"].astype(float).sort_index()
    below_zero = s < 0.0
    rolling_count = below_zero.rolling(window_days, min_periods=window_days).sum()
    signal = (rolling_count == window_days)

    out = signal.to_frame(name="yc2s10s_inversion_30d")
    out.index.name = df.index.name or "Date"
    save_parquet(out, out_path)
    print(f"[signals] wrote {out.shape[0]:,} rows → data/{out_path}")
    return out
