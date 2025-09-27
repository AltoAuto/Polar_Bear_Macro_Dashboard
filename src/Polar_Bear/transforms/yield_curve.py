# transforms/yield_curve.py
import pandas as pd
from storage.io_parquet import load_parquet, save_parquet

def compute_yield_spread_3m10y(
    in_path_10: str = "raw/market/^TNX.parquet",
    in_path_3m: str = "raw/fred/DGS3MO.parquet",   # switched from ^IRX → DGS3MO
    out_path: str = "derived/yield_curve.parquet",
) -> pd.DataFrame:
    """
    Load 10y (^TNX, Yahoo) and 3m (DGS3MO, FRED par yield),
    compute 10y - 3m in basis points (bp),
    and save to data/derived/yield_curve.parquet.

    Output schema:
      index: DatetimeIndex (UTC)
      columns: ['spread_3m10y_bp']  (float)
    """
    # 1) Load raw inputs
    tnx = load_parquet(in_path_10)  # expects columns: value, series_id, source
    dgs3mo = load_parquet(in_path_3m)

    if tnx.empty or dgs3mo.empty:
        raise ValueError("Missing input data: ^TNX or DGS3MO parquet is empty.")

    # 2) Align by timestamp (inner join on the DatetimeIndex)
    y10 = tnx["value"].astype(float)
    y10.name = "y10"

    y3m = dgs3mo["value"].astype(float)
    y3m.name = "y3m"

    df = pd.concat([y10, y3m], axis=1, join="inner").dropna()
    df.columns = ["y10", "y3m"]

    print("[yield_curve] columns:", list(df.columns))
    print("[yield_curve] head:\n", df.head(3))

    if df.empty:
        raise ValueError("No overlapping dates between ^TNX and DGS3MO after alignment.")

    # 3) Compute spread in basis points
    spread_bp = (df["y10"] - df["y3m"]) * 100.0

    out = spread_bp.to_frame(name="spread_3m10y_bp")
    out.index.name = df.index.name or "Date"

    # 4) Persist
    save_parquet(out, out_path)

    print(
        f"[yield_curve] wrote {len(out):,} rows → data/{out_path} | "
        f"range: {out.index.min()} → {out.index.max()}"
    )
    return out
