from pathlib import Path
import pandas as pd

# Always resolve relative to the project root (where this file lives, go up 1 directory)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"

def save_parquet(df: pd.DataFrame, rel_path: str) -> None:
    p = DATA_ROOT / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=True)

def load_parquet(rel_path: str) -> pd.DataFrame:
    p = DATA_ROOT / rel_path
    if not p.exists():
        raise FileNotFoundError(f"Parquet file not found: {p}")
    return pd.read_parquet(p)
