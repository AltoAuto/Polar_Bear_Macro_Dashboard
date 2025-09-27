# pipelines/app_spread.py
"""
PURPOSE
-------
Pro-style view for the yield curve with:
- Curve toggle (3m–10y or 2s–10s)
- Daily vs Monthly snapshot
- Range presets + custom date window
- Zero-line and shaded inversion (spread < 0)
- Stats panel for the visible window

"""

# --- make project-root imports work when run via `streamlit run pipelines/app_spread.py`
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import datetime as dt
import pandas as pd
import streamlit as st
from storage.io_parquet import load_parquet
import altair as alt
from datetime import timedelta

st.set_page_config(page_title="Polar Bear — Macro Risk Dashboard", layout="wide")

@st.cache_data(ttl=300)
def load_data(curve: str) -> pd.DataFrame:
    """
    Load data for a chosen curve.
    Returns: index=DatetimeIndex (UTC), columns: spread_bp, inv_today, inv_30d, below_zero
    """
    if curve == "3m–10y":
        spread = load_parquet("derived/yield_curve.parquet").copy()
        s_today = load_parquet("derived/signals/yc_inversion_today.parquet").copy()
        s_30d   = load_parquet("derived/signals/yc_inversion_30d.parquet").copy()
        spread_col = "spread_3m10y_bp"
        inv_today_col = "yc_inversion_today"
        inv_30d_col = "yc_inversion_30d"
    else:  # "2s–10s"
        spread = load_parquet("derived/yc_2s10s.parquet").copy()
        s_today = load_parquet("derived/signals/yc2s10s_inversion_today.parquet").copy()
        s_30d   = load_parquet("derived/signals/yc2s10s_inversion_30d.parquet").copy()
        spread_col = "spread_2s10s_bp"
        inv_today_col = "yc2s10s_inversion_today"
        inv_30d_col = "yc2s10s_inversion_30d"

    df = spread.join(s_today, how="left").join(s_30d, how="left")
    df = df.rename(columns={
        spread_col: "spread_bp",
        inv_today_col: "inv_today",
        inv_30d_col: "inv_30d",
    }).sort_index()
    df["below_zero"] = df["spread_bp"] < 0
    return df

def month_end_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """Take last available observation each calendar month."""
    if df.empty:
        return df
    m = df.copy().sort_index()
    m = m.resample("ME").last()
    m["below_zero"] = m["spread_bp"] < 0
    return m

def slice_range(df: pd.DataFrame, preset: str, custom: tuple[dt.date, dt.date] | None) -> pd.DataFrame:
    """Return a windowed slice by preset or custom dates."""
    if df.empty:
        return df
    start = df.index.min().date()
    end = df.index.max().date()
    if preset == "Custom" and custom is not None:
        s, e = custom
        if s is None: s = start
        if e is None: e = end
        return df.loc[str(s):str(e)]
    # presets
    if preset == "6M":
        cut = end - dt.timedelta(days=183)
        return df.loc[str(cut):]
    if preset == "1Y":
        cut = end - dt.timedelta(days=365)
        return df.loc[str(cut):]
    if preset == "3Y":
        cut = end - dt.timedelta(days=365*3)
        return df.loc[str(cut):]
    if preset == "5Y":
        cut = end - dt.timedelta(days=365*5)
        return df.loc[str(cut):]
    return df  # "Max"

def window_stats(df: pd.DataFrame) -> dict:
    """Compute stats on the visible window."""
    if df.empty:
        return {"min": None, "max": None, "mean": None, "days_inv": 0, "streak": 0}
    s = df["spread_bp"].astype(float)
    # current TRUE streak length (days below zero ending today)
    inv = (s < 0)
    rev = inv[::-1]
    streak = int((rev.cumsum() - rev.cumsum().where(~rev).ffill().fillna(0)).iloc[0])
    return {
        "min": float(s.min()),
        "max": float(s.max()),
        "mean": float(s.mean()),
        "days_inv": int(inv.sum()),
        "streak": streak,
    }

# ---------- 1) Bloomberg-ish Altair theme ----------
def theme():
    return {
        "config": {
            "view": {"stroke": "transparent"},
            "background": "#0b0c10",             # page bg
            "axis": {
                "domainColor": "#62636a",        # axis line
                "grid": True,
                "gridColor": "#1b1d23",          # subtle grid
                "gridDash": [1, 0],
                "labelColor": "#d0d3d8",
                "labelFont": "Inter, Arial, Helvetica, sans-serif",
                "labelFontSize": 12,
                "tickColor": "#62636a",
                "titleColor": "#e5e7eb",
                "titleFont": "Inter, Arial, Helvetica, sans-serif",
                "titleFontSize": 12
            },
            "legend": {
                "labelColor": "#d0d3d8",
                "titleColor": "#e5e7eb",
                "titleFont": "Inter, Arial, Helvetica, sans-serif",
                "labelFont": "Inter, Arial, Helvetica, sans-serif",
                "orient": "top-left",
                "padding": 2,
                "fillColor": "#0b0c10"
            },
            "title": {
                "font": "Inter, Arial, Helvetica, sans-serif",
                "fontSize": 14,
                "fontWeight": "bold",
                "color": "#ffffff",
                "anchor": "start"
            },
            "range": {
                # two calm brand colors; red for negative already set in the layer below
                "category": ["#1f77b4", "#9b59b6", "#2ecc71", "#e67e22", "#3498db"]
            },
            "mark": {"color": "#1f77b4", "strokeWidth": 2}
        }
    }

alt.themes.register("bloomberg", theme)
alt.themes.enable("bloomberg")

# ---------- 2) Upgraded chart builder ----------
def build_chart(df: pd.DataFrame, title: str):
    """
    Bloomberg-style Altair chart:
    - Dark theme, subtle grid, thicker strokes
    - Zero-line emphasized
    - Shaded inversion area (spread < 0)
    - Hover readout crosshair
    - Last-value tag
    - Optional 20D rolling mean overlay
    - Scroll/zoom enabled
    """
    if df.empty:
        return alt.Chart(pd.DataFrame({"date": [], "spread_bp": []})).mark_line()

    # Ensure datetime index to a column named 'date'
    plot = df.reset_index().rename(columns={"index": "Date"})
    plot = plot.rename(columns={plot.columns[0]: "date"})
    # Negative area to shade inversions
    plot["neg_spread"] = plot["spread_bp"].clip(upper=0)
    # Rolling mean (tweak window as you like)
    plot["ma20"] = plot["spread_bp"].rolling(20, min_periods=1).mean()

    base = alt.Chart(plot).properties(
        title=title, width=840, height=380
    )

    # Emphasized zero line
    zero_rule = base.mark_rule(color="grey", strokeWidth=0.1,strokeDash=[4, 4]).encode(
        y=alt.datum(0)
    )

    # Shaded inversion area (below zero)
    invert_area = base.mark_area(opacity=0.25, color="#ff3b3b").encode(
        x="date:T",
        y="neg_spread:Q",
        y2=alt.value(0),
        tooltip=[
            alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("spread_bp:Q", title="Spread (bp)", format=".1f")
        ],
    )

    # Main spread line: blue above zero, red below zero
    spread_line = base.mark_line().encode(
        x=alt.X("date:T", axis=alt.Axis(title=None)),
        y=alt.Y("spread_bp:Q", title="Basis points"),
        color=alt.condition("datum.spread_bp < 0",
                            alt.value("#ff3b3b"),  # red if negative
                            alt.value("#1f77b4")), # blue if positive
        tooltip=[
            alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("spread_bp:Q", title="Spread (bp)", format=".1f")
        ]
    )

    # Rolling mean overlay (muted purple)
    ma_line = base.mark_line(strokeDash=[6,4], color="#9b59b6", opacity=0.9).encode(
        x="date:T",
        y="ma20:Q",
        tooltip=[
            alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("ma20:Q", title="20D MA (bp)", format=".1f")
        ]
    )

    # Hover interaction: vertical rule + crosshair tooltips
    hover = alt.selection_point(
        fields=["date"],
        nearest=True,
        on="mousemove",  # update continuously as mouse moves
        empty=False
    )

    # Transparent catcher: spans the whole chart to update hover
    hover_base = base.mark_rule(opacity=0).encode(
        x="date:T",
        y="spread_bp:Q",
        tooltip=[
            alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("spread_bp:Q", title="Spread (bp)", format=".1f")
        ]
    ).add_params(hover)

    # Point marker (follows mouse x-position, snaps to y-value)
    hover_points = base.mark_point(size=35, filled=True, color="#ffffff").encode(
        x="date:T",
        y="spread_bp:Q",
        tooltip=[
            alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("spread_bp:Q", title="Spread (bp)", format=".1f")
        ]
    ).transform_filter(hover)

    chart = (
        zero_rule
        + invert_area
        + spread_line
        + ma_line
        + hover_base
        + hover_points
    ).interactive()

    return chart


def render_curve_panel():
    # Controls row
    colA, colB, colC, colD = st.columns([1.2, 1, 1.4, 2])
    with colA:
        curve = st.selectbox("Curve", ["3m–10y", "2s–10s"], index=0)
    with colB:
        freq = st.radio("Frequency", ["Daily", "Monthly"], index=0, horizontal=True)
    with colC:
        preset = st.selectbox("Range", ["6M", "1Y", "3Y", "5Y", "Max", "Custom"], index=1)
    with colD:
        custom = None
        if preset == "Custom":
            df_all = load_data(curve)
            start = df_all.index.min().date() if not df_all.empty else dt.date(2000,1,1)
            end = df_all.index.max().date() if not df_all.empty else dt.date.today()
            custom = st.date_input("Custom window", value=(start, end))

    # Load + transform
    df = load_data(curve)
    if df.empty:
        st.error("No data found. Run pipelines/daily_run.py first.")
        return

    if freq == "Monthly":
        df = month_end_snapshot(df)

    df = slice_range(df, preset, custom)

    # KPI row
    last_ts = df.index.max()
    last_row = df.loc[last_ts]

    k1, k2, k3, k4, k5 = st.columns([1.4,1,1,1,1])
    with k1:
        st.metric(
            label=f"{curve} spread (bp) — {last_ts.date()}  ({freq})",
            value=f"{last_row['spread_bp']:.1f}",
        )
    with k2:
        st.markdown("✅ Inversion today" if bool(last_row["below_zero"]) else "⬜ No inversion today")
    with k3:
        st.markdown("**30d**")
        st.markdown("✅ Confirmed (30d)" if bool(last_row.get("inv_30d", False)) else "⬜ Not confirmed")
    stats = window_stats(df)
    with k4:
        st.metric("Min (bp)", f"{stats['min']:.1f}" if stats["min"] is not None else "—")
        st.caption("Window min")
    with k5:
        st.metric("Max (bp)", f"{stats['max']:.1f}" if stats["max"] is not None else "—")
        st.caption(f"Inverted days: {stats['days_inv']} • Streak: {stats['streak']}")

    st.divider()

    # Chart
    st.subheader(f"{curve} spread ({freq})")
    st.altair_chart(build_chart(df, f"{curve} — {freq}"), use_container_width=True)

    # Recent table
    start_date = last_ts.date() - timedelta(days=20)
    end_date = last_ts.date()

    st.subheader(f"Recent — {start_date} to {end_date} — ({freq})")
    st.dataframe(df[["spread_bp", "below_zero", "inv_30d"]].tail(15))

    st.caption(
        "Shaded area = inversion (spread < 0). "
        "30d confirmation = (spread < 0 for 30 consecutive trading days). "
        "Monthly = month-end snapshot."
    )

def render_inflation_panel():
    st.header("Inflation")

    # -------- load ----------
    try:
        df = load_parquet("derived/inflation.parquet")
    except FileNotFoundError:
        st.error("No inflation data found. Run pipelines/daily_run.py first.")
        return
    if df.empty:
        st.warning("Inflation parquet is empty.")
        return

    # -------- controls ----------
    cA, cB, cC, cD = st.columns([1, 1, 1.4, 2])
    with cA:
        view = st.selectbox("View", ["CPI YoY vs 3m-Ann", "Core YoY vs Breakeven"], index=0, key="infl_view")
    with cB:
        freq = st.radio("Frequency", ["Monthly", "Daily"], index=0, horizontal=True, key="infl_freq")
    with cC:
        preset = st.selectbox("Range", ["6M", "1Y", "3Y", "5Y", "Max", "Custom"], index=1, key="infl_range")
    with cD:
        custom = None
        if preset == "Custom":
            start = df.index.min().date()
            end = df.index.max().date()
            custom = st.date_input("Custom window", value=(start, end), key="infl_custom_dates")

    # -------- resample & slice ----------
    df_plot = df.copy().sort_index()
    if freq == "Monthly":
        # month-end snapshot for mixed-frequency inputs
        df_plot = df_plot.resample("ME").last()
    df_plot = slice_range(df_plot, preset, custom)

    if df_plot.empty:
        st.warning("No data in selected window.")
        return

    last_ts = df_plot.index.max()
    last = df_plot.loc[last_ts]

    # -------- KPIs ----------
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("CPI YoY (%)",
                  f"{last.get('cpi_yoy_pct', float('nan')):.1f}" if 'cpi_yoy_pct' in df_plot.columns else "—")
    with k2:
        st.metric("CPI 3m Ann (%)",
                  f"{last.get('cpi_3m_ann_pct', float('nan')):.1f}" if 'cpi_3m_ann_pct' in df_plot.columns else "—")
    with k3:
        st.metric("Core CPI YoY (%)",
                  f"{last.get('core_yoy_pct', float('nan')):.1f}" if 'core_yoy_pct' in df_plot.columns else "—")
    with k4:
        st.metric("10y Breakeven (%)",
                  f"{last.get('breakeven_10y_pct', float('nan')):.2f}" if 'breakeven_10y_pct' in df_plot.columns else "—")

    # -------- narrative (momentum) ----------
    # momentum cooling if 3m-ann < YoY; count months in window
    note = ""
    if {"cpi_yoy_pct", "cpi_3m_ann_pct"}.issubset(df_plot.columns):
        window = df_plot[["cpi_yoy_pct", "cpi_3m_ann_pct"]].dropna()
        if not window.empty:
            cooling = (window["cpi_3m_ann_pct"] < window["cpi_yoy_pct"])
            months_cooling = int(cooling.sum())
            is_cooling_now = bool(cooling.iloc[-1])
            note = (
                       "Momentum **cooling**" if is_cooling_now else "Momentum **heating**") + f" • cooling months in window: {months_cooling}"
    if note:
        st.info(note)

    st.divider()

    # -------- pro chart (Altair) ----------
    # Build long-form dataframe for selected view
    def _chart_two_lines(df_in: pd.DataFrame, cols: list[str], title: str):

        data = df_in[cols].dropna().copy()
        if data.empty:
            return alt.Chart(pd.DataFrame({"date": [], "series": [], "value": []})).mark_line()

        # Long form for Altair
        data = data.reset_index().rename(columns={"index": "date"})
        data = data.melt("date", var_name="series", value_name="value")

        base = alt.Chart(data).encode(
            x=alt.X("date:T", title=""),
            y=alt.Y("value:Q", title="Percent"),
            color=alt.Color("series:N", title="", legend=alt.Legend(orient="top")),
        )

        # --- Hover interaction (Altair v5) ---
        hover = alt.selection_point(
            fields=["date"],
            nearest=True,
            on="mousemove",
            empty=False
        )

        # Main lines
        lines = base.mark_line().encode(
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("series:N", title="Series"),
                alt.Tooltip("value:Q", title="Value", format=".2f"),
            ]
        )

        # Transparent catcher to capture mouse movement over the whole x-range
        catcher = alt.Chart(data).mark_rule(opacity=0).encode(x="date:T").add_params(hover)

        # Points that snap to the hover x-position on each series
        hover_points = base.mark_point(size=50, filled=True, color="#ffffff", stroke="black").encode(
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("series:N", title="Series"),
                alt.Tooltip("value:Q", title="Value", format=".2f"),
            ]
        ).transform_filter(hover)

        # 2% target line
        target_rule = alt.Chart(pd.DataFrame({"y": [2.0]})).mark_rule(strokeDash=[4, 4], color="#666").encode(
            y="y:Q"
        )

        chart = (target_rule + lines + catcher +  hover_points).properties(
            title=title
        ).interactive()

        return chart

    if view == "CPI YoY vs 3m-Ann":
        cols = [c for c in ["cpi_yoy_pct", "cpi_3m_ann_pct"] if c in df_plot.columns]
        if len(cols) >= 1:
            chart = _chart_two_lines(df_plot, cols, f"CPI — {freq} ({preset})")
            st.altair_chart(chart, use_container_width=True)
        else:
            st.warning("No CPI series available to plot.")
    else:
        cols = [c for c in ["core_yoy_pct", "breakeven_10y_pct"] if c in df_plot.columns]
        if len(cols) >= 1:
            chart = _chart_two_lines(df_plot, cols, f"Core & Breakeven — {freq} ({preset})")
            st.altair_chart(chart, use_container_width=True)
        else:
            st.warning("No Core/Breakeven series available to plot.")

    # -------- recent table ----------
    st.subheader("Recent (last 12 months)")
    cols_show = [c for c in ["cpi_yoy_pct", "cpi_3m_ann_pct", "core_yoy_pct", "breakeven_10y_pct"] if
                 c in df_plot.columns]
    st.dataframe(df_plot[cols_show].tail(12))


def render_credit_panel():
    """
    CREDIT & STRESS PANEL
    ---------------------
    Views:
      1) "HY - IG (levels) (diff)"
         - HY vs IG levels (bp)
         - HY−IG diff (bp) with stress shading + optional VIX overlay (z-score)
      2) "VIX" (level, z-score, optional MAs)

    Inputs:
      - data/derived/credit.parquet                      (hy_oas_bp, ig_oas_bp, hy_ig_diff_bp)
      - data/derived/signals/credit_stress_3y80.parquet  (credit_stress_3y80)
      - data/raw/market/^VIX.parquet                     (value)
    """
    st.header("Credit & Stress")

    # ---------- Load ----------
    try:
        levels = load_parquet("derived/credit.parquet")
    except FileNotFoundError:
        levels = pd.DataFrame()

    try:
        stress = load_parquet("derived/signals/credit_stress_3y80.parquet")
    except FileNotFoundError:
        stress = pd.DataFrame()

    if not levels.empty:
        df_all = levels.join(stress, how="left").sort_index()
        if "credit_stress_3y80" not in df_all.columns:
            df_all["credit_stress_3y80"] = False
        df_all["credit_stress_3y80"] = df_all["credit_stress_3y80"].fillna(False).astype(bool)
    else:
        df_all = pd.DataFrame()

    vix_available = True
    try:
        vix_raw = load_parquet("raw/market/^VIX.parquet")
        vix_all = vix_raw["value"].astype(float).rename("vix").to_frame()
    except FileNotFoundError:
        vix_available = False
        vix_all = pd.DataFrame()

    # ---------- Controls ----------
    cA, cB, cC, cD = st.columns([1, 1.3, 1.2, 2])
    with cA:
        freq = st.radio("Frequency", ["Daily", "Monthly"], index=0, horizontal=True, key="credit_freq")
    with cB:
        view = st.selectbox("View", ["HY - IG (levels) (diff)", "VIX"], index=0, key="credit_view")
    with cC:
        preset = st.selectbox("Range", ["6M", "1Y", "3Y", "5Y", "Max", "Custom"], index=1, key="credit_range")
    with cD:
        if view == "VIX" and not vix_all.empty:
            min_d, max_d = vix_all.index.min().date(), vix_all.index.max().date()
        else:
            if df_all.empty:
                min_d, max_d = dt.date(2000, 1, 1), dt.date.today()
            else:
                min_d, max_d = df_all.index.min().date(), df_all.index.max().date()
        custom = st.date_input("Custom window", value=(min_d, max_d), key="credit_custom_dates") if preset == "Custom" else None

    # ---------- Range helper ----------
    def _slice_range(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        start = df.index.min().date()
        end = df.index.max().date()
        if preset == "Custom" and custom is not None:
            s, e = custom
            return df.loc[str(s or start): str(e or end)]
        days = {"6M": 183, "1Y": 365, "3Y": 365*3, "5Y": 365*5}.get(preset)
        return df.loc[str(end - dt.timedelta(days=days)):] if days else df

    # ---------- Minimalist hover pattern ----------
    def _two_lines(df_in: pd.DataFrame, cols: list[str], title: str, y_title: str):
        data = df_in[cols].dropna(how="all").copy()
        if data.empty:
            return alt.Chart(pd.DataFrame({"date": [], "series": [], "value": []})).mark_line()

        data = data.reset_index().rename(columns={"index": "date"}).melt("date", var_name="series", value_name="value").dropna(subset=["value"])
        base = alt.Chart(data).encode(
            x=alt.X("date:T", title=""),
            y=alt.Y("value:Q", title=y_title),
            color=alt.Color("series:N", title="", legend=alt.Legend(orient="top")),
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("series:N", title="Series"),
                alt.Tooltip("value:Q", title=y_title, format=".0f"),
            ]
        )

        hover = alt.selection_point(fields=["date"], nearest=True, on="mousemove", empty=False)

        lines = base.mark_line().encode(
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("series:N", title="Series"),
                alt.Tooltip("value:Q", title=y_title, format=".0f"),
            ]
        )

        catcher = alt.Chart(data).mark_rule(opacity=0).encode(x="date:T").add_params(hover)
        hover_pts = base.mark_point(size=50, filled=True, color="#ffffff", stroke="black").transform_filter(hover)

        return (lines + catcher + hover_pts).properties(title=title).interactive()

    def _single_line_with_shading(
            df_in: pd.DataFrame,
            y_col: str,
            stress_col: str | None,
            title: str,
            y_title: str,
            overlay_df: pd.DataFrame | None = None,
            overlay_label: str = "Overlay (z-score)"
    ):

        if y_col not in df_in.columns:
            return alt.Chart(pd.DataFrame({"date": [], y_col: []})).mark_line()

        data = df_in[[y_col]].copy()
        if stress_col and stress_col in df_in.columns:
            data[stress_col] = df_in[stress_col].astype(bool)
        if overlay_df is not None:
            data = data.join(overlay_df, how="left")

        plot = data.reset_index().rename(columns={"index": "date"})

        # --- Stress shading (contiguous width via lead(date)) ---
        stress_rect = None
        if stress_col and stress_col in plot.columns and plot[stress_col].any():
            stress_base = (
                alt.Chart(plot)
                .transform_filter(f"datum.{stress_col} == true")
                .transform_window(next_date="lead(date)", sort=[alt.SortField("date")])
            )
            stress_rect = stress_base.mark_rect(opacity=0.12, color="#d62728").encode(
                x="date:T", x2="next_date:T"
            )

        base = alt.Chart(plot)
        hover = alt.selection_point(fields=["date"], nearest=True, on="mousemove", empty=False)

        # Main line
        main = base.mark_line(color="#1f77b4").encode(
            x=alt.X("date:T", title=""),
            y=alt.Y(f"{y_col}:Q", title=y_title),
            tooltip=[alt.Tooltip("date:T", title="Date"),
                     alt.Tooltip(f"{y_col}:Q", title=y_title, format=".0f")],
        )

        # Hover mechanics: invisible catcher + vertical rule + point WITH tooltip
        catcher = base.mark_rule(opacity=0).encode(x="date:T").add_params(hover)
        hover_pt = base.mark_point(size=50, filled=True, color="#ffffff", stroke="black").encode(
            x="date:T",
            y=f"{y_col}:Q",
            tooltip=[  # <-- ensure tooltip lives on the hovered point
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip(f"{y_col}:Q", title=y_title, format=".0f"),
            ],
        ).transform_filter(hover)

        chart = main + catcher + hover_pt
        if stress_rect is not None:
            chart = stress_rect + chart  # keep shading beneath the line

        # Optional overlay (e.g., VIX z×100)
        if overlay_df is not None:
            for oc in [c for c in overlay_df.columns if c != y_col]:
                ov_line = alt.Chart(plot).mark_line(strokeDash=[2, 1], color="#9467bd").encode(
                    x="date:T",
                    y=alt.Y(f"{oc}:Q", title=""),
                    tooltip=[alt.Tooltip("date:T", title="Date"),
                             alt.Tooltip(f"{oc}:Q", title=overlay_label, format=".0f")],
                )
                ov_pt = alt.Chart(plot).mark_point(size=40, filled=True, color="#f4e8ff", stroke="#9467bd").encode(
                    x="date:T",
                    y=f"{oc}:Q",
                    tooltip=[alt.Tooltip("date:T", title="Date"),
                             alt.Tooltip(f"{oc}:Q", title=overlay_label, format=".0f")],
                ).transform_filter(hover)
                chart = chart + ov_line + ov_pt

        return chart.properties(title=title).interactive()

    def _multi_lines_simple(data_long: pd.DataFrame, title: str, y_title: str, value_fmt: str = ".1f"):
        import altair as alt
        if data_long.empty:
            return alt.Chart(pd.DataFrame({"date": [], "series": [], "value": []})).mark_line()

        base = alt.Chart(data_long).encode(
            x=alt.X("date:T", title=""),
            y=alt.Y("value:Q", title=y_title),
            color=alt.Color("series:N", title="", legend=alt.Legend(orient="top")),
        )

        # same hover pattern as HY-IG
        hover = alt.selection_point(fields=["date"], nearest=True, on="mousemove", empty=False)

        lines = base.mark_line().encode(
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("series:N", title="Series"),
                alt.Tooltip("value:Q", title=y_title, format=value_fmt),
            ]
        )

        catcher = alt.Chart(data_long).mark_rule(opacity=0).encode(x="date:T").add_params(hover)

        hover_pts = base.mark_point(size=50, filled=True, color="#ffffff", stroke="black").encode(
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("series:N", title="Series"),
                alt.Tooltip("value:Q", title=y_title, format=value_fmt),
            ]
        ).transform_filter(hover)

        return (lines + catcher + hover_pts).properties(title=title).interactive()

    def _reset_with_date(df: pd.DataFrame) -> pd.DataFrame:
        """Reset index and guarantee the first column is named 'date'."""
        out = df.reset_index()
        first = out.columns[0]
        if first != "date":
            out = out.rename(columns={first: "date"})
        return out

    # ---------- VIX view ----------
    # --- VIX view (uses the same hover as HY-IG) ---
    if view == "VIX":
        if vix_all.empty:
            st.error("VIX data not available. Add '^VIX' to config/sources.yaml and run daily_run.py.")
            return

        df_vix = vix_all.copy()
        df_vix["vix"] = pd.to_numeric(df_vix["vix"], errors="coerce")
        df_vix = df_vix.dropna(subset=["vix"])

        if freq == "Monthly":
            df_vix = df_vix.resample("ME").last()

        df_vix = _slice_range(df_vix)
        if df_vix.empty:
            st.warning("No VIX data in selected window.")
            return

        # KPIs
        last_ts = df_vix.index.max()
        last_vix = float(df_vix.loc[last_ts, "vix"])
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("VIX (last)", f"{last_vix:.1f}")
        with c2:
            win = 20 if freq == "Daily" else 3
            sma = df_vix["vix"].rolling(win, min_periods=win).mean()
            st.metric(f"{win}-period MA", f"{float(sma.dropna().iloc[-1]):.1f}" if not sma.dropna().empty else "—")
        with c3:
            mu, sd = float(df_vix["vix"].mean()), float(df_vix["vix"].std()) or 1.0
            st.metric("VIX z-score", f"{(last_vix - mu) / sd:.2f}")
        with c4:
            st.metric("80th pct (window)", f"{df_vix['vix'].quantile(0.80):.1f}")

        st.divider()
        show_ma = st.checkbox("Show 20/60 MAs", value=True, key="vix_show_ma")
        show_z = st.checkbox("Show z-score (scaled ×10)", value=False, key="vix_show_z")

        # ---- build ONE long dataframe (like HY-IG) ----
        # ---- build ONE long dataframe (like HY-IG) ----
        df_long = df_vix[["vix"]].rename(columns={"vix": "VIX"}).copy()

        if show_ma:
            win1 = 20 if freq == "Daily" else 3
            win2 = 60 if freq == "Daily" else 6
            df_long["MA20" if freq == "Daily" else "MA3"] = df_vix["vix"].rolling(win1, min_periods=win1).mean()
            df_long["MA60" if freq == "Daily" else "MA6"] = df_vix["vix"].rolling(win2, min_periods=win2).mean()

        if show_z:
            df_long["Zx10"] = ((df_vix["vix"] - df_vix["vix"].mean()) / (df_vix["vix"].std() or 1.0)) * 10.0

        # robust reset so 'date' always exists
        df_long = _reset_with_date(df_long)

        # melt to long so hover applies to all series uniformly
        df_long = df_long.melt("date", var_name="series", value_name="value").dropna(subset=["value"])

        # before resampling/slicing
        df_vix.index = pd.to_datetime(df_vix.index, errors="coerce")
        df_vix = df_vix.sort_index()
        df_vix["vix"] = pd.to_numeric(df_vix["vix"], errors="coerce")
        df_vix = df_vix.dropna(subset=["vix"])

        chart = _multi_lines_simple(
            df_long,
            title=f"VIX — {freq} ({preset})",
            y_title="Value",
            value_fmt=".1f"
        )
        st.altair_chart(chart, use_container_width=True)

        st.subheader("Recent (last 12)")
        st.dataframe(df_vix.tail(12))
        return

    # ---------- HY/IG view ----------
    if df_all.empty:
        st.error("No credit data available. Run pipelines/daily_run.py first.")
        return

    df_plot = df_all.copy()
    if freq == "Monthly":
        df_plot = df_plot.resample("M").last()
    df_plot = _slice_range(df_plot)
    if df_plot.empty:
        st.warning("No credit data in selected window.")
        return

    # KPIs
    last = df_plot.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("HY OAS (bp)", f"{last['hy_oas_bp']:.0f}" if "hy_oas_bp" in df_plot.columns else "—")
    with c2:
        st.metric("IG OAS (bp)", f"{last['ig_oas_bp']:.0f}" if "ig_oas_bp" in df_plot.columns else "—")
    with c3:
        st.metric("HY − IG (bp)", f"{last['hy_ig_diff_bp']:.0f}" if "hy_ig_diff_bp" in df_plot.columns else "—")
    with c4:
        st.metric("Stress (3y 80th%)", "✅ YES" if bool(last.get("credit_stress_3y80", False)) else "⬜ NO")

    st.divider()

    def _chart_levels(df_in: pd.DataFrame):
        return _two_lines(
            df_in, ["hy_oas_bp", "ig_oas_bp"],
            title=f"Credit Spreads — HY vs IG ({freq} / {preset})",
            y_title="OAS (bp)"
        )

    def _chart_diff_with_optional_vix(df_in: pd.DataFrame, overlay: bool):
        data = df_in[["hy_ig_diff_bp", "credit_stress_3y80"]].dropna(subset=["hy_ig_diff_bp"]).copy()

        overlay_df = None
        if overlay and vix_available:
            vix = vix_all.copy()
            if freq == "Monthly":
                vix = vix.resample("M").last()
            # z-score within visible window, scaled to bp-like magnitude
            vix = vix.reindex(df_in.index)
            mu, sd = float(vix["vix"].mean()), float(vix["vix"].std()) or 1.0
            overlay_df = (((vix["vix"] - mu) / sd) * 100.0).rename("vix_z_scaled").to_frame()

        return _single_line_with_shading(
            df_in=data,
            y_col="hy_ig_diff_bp",
            stress_col="credit_stress_3y80",
            title=f"HY − IG (bp) & Stress ({freq} / {preset})",
            y_title="HY − IG (bp)",
            overlay_df=overlay_df,
            overlay_label="VIX z×100"
        )

    tab_levels, tab_diff = st.tabs(["HY vs IG (levels)", "HY − IG (diff)"])
    with tab_levels:
        st.altair_chart(_chart_levels(df_plot), use_container_width=True)
    with tab_diff:
        overlay = st.checkbox("Overlay VIX (z-score)", value=vix_available, key="credit_vix_overlay")
        st.altair_chart(_chart_diff_with_optional_vix(df_plot, overlay=overlay), use_container_width=True)

    st.subheader("Recent (last 12 months)")
    cols = [c for c in ["hy_oas_bp", "ig_oas_bp", "hy_ig_diff_bp", "credit_stress_3y80"] if c in df_plot.columns]
    st.dataframe(df_plot[cols].tail(12))




def main():
    st.title("Polar Bear Macro Risk Dashboard")

    tab1, tab2, tab3 = st.tabs(["Yield Curve", "Inflation", "Credit & Stress"])

    with tab1:
        render_curve_panel()

    with tab2:
        render_inflation_panel()

    with tab3:
        render_credit_panel()



if __name__ == "__main__":
    main()
