# collectors/fred.py
"""
PURPOSE
-------
Minimal FRED collector to fetch a single series (e.g., DGS2 = 2-year Treasury).
Outputs a tidy DataFrame compatible with your storage layer:
  - index: DatetimeIndex (UTC)
  - columns: ['value', 'series_id', 'source']
  - units: percent for yields (as provided by FRED)
"""

import os
from datetime import datetime, timezone
import pandas as pd
import requests

FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

class FredError(Exception):
    pass

def fetch_fred_series(series_id: str, start: str = "2000-01-01") -> pd.DataFrame:
    """
    Download a FRED series by ID and return a standardized DataFrame.
    Example: series_id='DGS2' (2-year), 'DGS10' (10-year), 'TB3MS' (3-month).

    Returns:
        DataFrame with index UTC DatetimeIndex, columns: value, series_id, source.
    """
    if not FRED_API_KEY:
        raise FredError("FRED_API_KEY not set. Set environment variable 'FRED_API_KEY'.")

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": start,
    }
    r = requests.get(FRED_BASE, params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    obs = js.get("observations", [])
    if not obs:
        return pd.DataFrame()

    df = pd.DataFrame(obs)
    # FRED gives 'date' as YYYY-MM-DD
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"]).set_index("date").sort_index()
    df["series_id"] = series_id
    df["source"] = "fred"
    return df[["value", "series_id", "source"]]
