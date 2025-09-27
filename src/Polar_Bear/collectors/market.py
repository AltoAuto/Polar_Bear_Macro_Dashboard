# collectors/market.py
import yfinance as yf
import pandas as pd
import yaml
from datetime import datetime, timedelta, timezone
from storage.io_parquet import save_parquet

def _standardize(df: pd.DataFrame, series_id: str) -> pd.DataFrame:
    """
    Convert Yahoo output to a standard schema:
      - index: UTC DatetimeIndex (no Ticker level)
      - columns: ['value', 'series_id', 'source']
      - units: PERCENT (e.g., 4.25 means 4.25%)
    Handles yfinance quirks (MultiIndex columns/index).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # --- 1) Flatten columns to get a single 'Close' series
    close = None
    if isinstance(df.columns, pd.MultiIndex):
        # common cases: ('Close', <ticker>) or (<ticker>, 'Close')
        lev0 = df.columns.get_level_values(0)
        lev1 = df.columns.get_level_values(1)
        if "Close" in lev0:
            close = df.loc[:, ("Close", slice(None))]
        elif "Close" in lev1:
            close = df.loc[:, (slice(None), "Close")]
        else:
            # fallback: try 'Adj Close'
            if "Adj Close" in lev0:
                close = df.loc[:, ("Adj Close", slice(None))]
            elif "Adj Close" in lev1:
                close = df.loc[:, (slice(None), "Adj Close")]

        # if we got a DataFrame with a single column, squeeze it
        if isinstance(close, pd.DataFrame) and close.shape[1] == 1:
            close = close.iloc[:, 0]
    else:
        # single-level columns
        if "Close" in df.columns:
            close = df["Close"]
        elif "Adj Close" in df.columns:
            close = df["Adj Close"]

    if close is None is None or close.empty:
        return pd.DataFrame()

    # --- 2) If 'close' still has a MultiIndex on columns (ticker), squeeze it
    if isinstance(close, pd.DataFrame) and close.shape[1] == 1:
        close = close.iloc[:, 0]

    # --- 3) Normalize index to pure DatetimeIndex (UTC), drop any Ticker level
    idx = df.index
    if isinstance(idx, pd.MultiIndex) and "Date" in (idx.names or []):
        try:
            # typical yfinance row index: levels ('Ticker','Date')
            close.index = close.index.droplevel(0)
        except Exception:
            pass

    close.index = pd.to_datetime(close.index, utc=True)

    # --- 4) Build flat DataFrame
    out = pd.DataFrame({"value": pd.to_numeric(close, errors="coerce")}).dropna()

    # --- 5) Unit normalization to PERCENT
    v = out["value"]
    med = v.dropna().median()

    if series_id == "^TNX":
        # expected percent around ~4–5
        if med > 20:
            out["value"] = v / 10.0        # 42.96 -> 4.296
        elif med < 1:
            out["value"] = v * 100.0       # 0.04296 -> 4.296
        # else assume it is already ~4.296
    elif series_id == "^IRX":
        # expected percent around ~4–6
        if med > 50:
            out["value"] = v / 100.0       # 505.5 -> 5.055
        elif med < 1:
            out["value"] = v * 100.0       # 0.05055 -> 5.055
        # else assume 5.055 already

    # --- 6) Final columns
    out["series_id"] = series_id
    out["source"] = "yfinance"
    out = out.sort_index()
    return out


def fetch_market_from_config(cfg_path="D:\Polar_Bear\config\sources.yaml", lookback_days=8000) -> int:
    with open(cfg_path, "r") as f:
        cfg = yaml.safe_load(f) or {}
    tickers = (cfg.get("market") or {}).get("tickers") or []

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)

    fetched = 0
    for t in tickers:
        df = yf.download(t, start=start, end=end, progress=False, auto_adjust=False, interval="1d")
        std = _standardize(df, t)
        if std is not None and not std.empty:
            save_parquet(std, f"raw/market/{t}.parquet")
            fetched += 1
    print(f"Fetched {fetched}/{len(tickers)} market series.")
    return fetched
