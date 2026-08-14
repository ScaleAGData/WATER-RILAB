import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timezone

from config import DB_DIR, LATVIA_TZ, VRI_ICON


st.set_page_config(
    page_title="Latest Metrics",
    page_icon=VRI_ICON,
    layout="wide",
)

st.sidebar.markdown("Institute for Environmental Solutions")


def f_to_c(x):
    return (x - 32) * 5.0 / 9.0


def inhg_to_hpa(x):
    return x * 33.8639


def mph_to_ms(x):
    return x * 0.44704


def inch_to_mm(x):
    return x * 25.4


CONVERSIONS = {
    "temp_last": ("°C", f_to_c),
    "temp_avg": ("°C", f_to_c),
    "temp_hi": ("°C", f_to_c),
    "temp_lo": ("°C", f_to_c),
    "temp_out": ("°C", f_to_c),
    "dew_point": ("°C", f_to_c),
    "heat_index": ("°C", f_to_c),
    "wind_chill": ("°C", f_to_c),
    "wet_bulb": ("°C", f_to_c),
    "thsw_index": ("°C", f_to_c),

    "bar": ("hPa", inhg_to_hpa),
    "bar_absolute": ("hPa", inhg_to_hpa),
    "bar_trend": ("hPa", inhg_to_hpa),
    "bar_trend_3_hr": ("hPa", inhg_to_hpa),
    "pressure_last": ("hPa", inhg_to_hpa),

    "wind_speed": ("m/s", mph_to_ms),
    "wind_speed_2_min": ("m/s", mph_to_ms),
    "wind_speed_10_min": ("m/s", mph_to_ms),
    "wind_gust_10_min": ("m/s", mph_to_ms),

    "et_day": ("mm", inch_to_mm),

    "rain_15_min_mm": ("mm", lambda x: x),
    "rain_60_min_mm": ("mm", lambda x: x),
    "rain_24_hr_mm": ("mm", lambda x: x),
    "rain_day_mm": ("mm", lambda x: x),
    "rain_rate_mm": ("mm/hr", lambda x: x),
    "rain_storm_mm": ("mm", lambda x: x),
    "rainfall_mm": ("mm", lambda x: x),
    "rainfall_last_15_min_mm": ("mm", lambda x: x),
    "rainfall_last_60_min_mm": ("mm", lambda x: x),
    "rain_rate_last_mm": ("mm/hr", lambda x: x),
    "rain_rate_hi_mm": ("mm/hr", lambda x: x),
    "rain_rate_hi_last_15_min_mm": ("mm/hr", lambda x: x),

    "moist_soil_last": ("cbar", lambda x: x),
    "hum_out": ("%", lambda x: x),
    "wind_dir": ("°", lambda x: x),
    "uv": ("UV", lambda x: x),
    "solar_rad": ("W/m²", lambda x: x),
}


@st.cache_data(show_spinner=False, ttl=60)
def run_query(query, params=None):
    conn = sqlite3.connect(DB_DIR)
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


@st.cache_data(show_spinner=False, ttl=60)
def get_data_tables():
    query = """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name LIKE 'NODE_%'
          AND name LIKE '%_DATA'
        ORDER BY name
    """
    return run_query(query)["name"].tolist()


@st.cache_data(show_spinner=False, ttl=60)
def get_table_columns(table_name):
    return run_query(f"PRAGMA table_info({table_name})")["name"].tolist()


@st.cache_data(show_spinner=False, ttl=60)
def fetch_latest_rows_by_lsid(table_name):
    columns = get_table_columns(table_name)

    query = f"""
        SELECT
            d.*,
            n.parent_device_name,
            n.product_name,
            n.category
        FROM {table_name} d
        LEFT JOIN NODES n
            ON d.lsid = n.lsid
        INNER JOIN (
            SELECT lsid, MAX(ts) AS latest_ts
            FROM {table_name}
            GROUP BY lsid
        ) latest
            ON d.lsid = latest.lsid
           AND d.ts = latest.latest_ts
        ORDER BY d.ts DESC
    """
    return run_query(query)


def format_ts(ts):
    if pd.isna(ts):
        return "N/A"

    return (
        datetime.fromtimestamp(int(ts), tz=timezone.utc)
        .astimezone(LATVIA_TZ)
        .strftime("%Y-%m-%d %H:%M")
    )


def format_metric(column, value):
    if pd.isna(value):
        return "N/A"

    if column in CONVERSIONS:
        unit, converter = CONVERSIONS[column]
        value = converter(value)

        if unit in ["%", "°", "UV"]:
            return f"{value:.0f} {unit}"

        return f"{value:.2f} {unit}"

    if isinstance(value, float):
        return f"{value:.2f}"

    return str(value)


def prettify_name(name):
    return name.replace("_", " ").title()


def get_metric_columns(df):
    ignore_cols = {
        "lsid",
        "ts",
        "tz_offset",
        "sensor_type",
        "data_structure_type",
        "parent_device_name",
        "product_name",
        "category",
    }

    return [
        col for col in df.columns
        if col not in ignore_cols
        and pd.api.types.is_numeric_dtype(df[col])
    ]


def render_metric_grid(row, metric_columns):
    cols_per_row = 4

    for start in range(0, len(metric_columns), cols_per_row):
        cols = st.columns(cols_per_row)

        for col, metric_col in zip(cols, metric_columns[start:start + cols_per_row]):
            with col:
                st.metric(
                    label=prettify_name(metric_col),
                    value=format_metric(metric_col, row[metric_col]),
                    border=True,
                )


def render_table_section(table_name):
    df = fetch_latest_rows_by_lsid(table_name)

    st.subheader(table_name)

    if df.empty:
        st.warning("No data found.")
        return

    df["datetime"] = df["ts"].apply(format_ts)

    display_cols = [
        "datetime",
        "parent_device_name",
        "product_name",
        "category",
        "lsid",
    ]

    metric_columns = get_metric_columns(df)
    display_cols += metric_columns

    display_cols = [col for col in display_cols if col in df.columns]

    selected_label = st.selectbox(
        "Select sensor / node",
        options=df.index,
        format_func=lambda i: (
            f"{df.loc[i, 'parent_device_name'] or 'Unknown'} "
            f"| LSID: {df.loc[i, 'lsid']} "
            f"| {df.loc[i, 'datetime']}"
        ),
        key=f"{table_name}_selected_row",
    )

    selected_row = df.loc[selected_label]

    st.caption(
        f"Latest timestamp: **{selected_row['datetime']}** | "
        f"Device: **{selected_row.get('parent_device_name', 'Unknown')}** | "
        f"LSID: **{selected_row.get('lsid', 'Unknown')}**"
    )

    render_metric_grid(selected_row, metric_columns)

    with st.expander("Show latest rows table", expanded=False):
        st.dataframe(
            df[display_cols],
            use_container_width=True,
            hide_index=True,
        )


st.title("Latest Metrics From All Sensor Tables")

tables = get_data_tables()

if not tables:
    st.warning("No NODE_*_DATA tables found.")
    st.stop()

tabs = st.tabs([name.replace("NODE_", "").replace("_DATA", "") for name in tables])

for tab, table_name in zip(tabs, tables):
    with tab:
        render_table_section(table_name)