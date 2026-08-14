import streamlit as st

import numpy as np
from numpy.random import default_rng as rng
import pandas as pd
import sqlite3
from datetime import datetime, timedelta, timezone
import time
import base64
from textwrap import dedent
import streamlit.components.v1 as components

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import plotly.graph_objects as go
import plotly.express as px

from config import (
    VRI_ICON, 
    HORIZONTAL_VRI_ICON,
    DB_DIR,
    LATVIA_TZ,
)

## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::| Page configs and constants |::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

st.set_page_config(
    page_title="IES WeatherLink Dashboard",
    page_icon=VRI_ICON,
    layout="wide"
)



st.sidebar.markdown("Institute for Environmental Solutions")

TIME_24H = 86400
TIME_WEEK = 604800
TIME_MONTH = 2592000


ISS_HEADER_VARIABLES = [
    "temp_out",
    "wind_chill",
    "heat_index",
    "thsw_index",
    "dew_point",
    "wet_bulb",
    "rain_24_hr_mm",
    "et_day",
    "bar",
    "wind_dir",
    "hum_out",
    "rain_rate_mm",
    "bar_trend",
    "wind_speed",
]

ISS_LABEL_MAP = {
    "temp_out": "Outside Temperature",
    "wind_chill": "Wind Chill",
    "heat_index": "Heat Index",
    "thsw_index": "THSW Index",
    "dew_point": "Dew Point",
    "wet_bulb": "Wet Bulb",
    "rain_24_hr_mm": "Rain 24 hr mm",
    "et_day": "Evapotranspiration",   
    "bar": "Pressure",
    "wind_dir": "Wind Direction",
    "hum_out": "Humidity Out",
    "rain_rate_mm": "Rain Rate mm",
    "bar_trend": "Bar Trend",
    "wind_speed": "Wind Speed",
}

DEVICE_COLOR_MAP = {
    "Augsnes sensori #1": "#1f77b4",  # blue
    "Augsnes sensori #2": "#ff7f0e",  # orange
    "Augsnes sensori #3": "#2ca02c",  # green
    "Augsnes sensori #4": "#d62728",  # red
}


SOIL_MOISTURE_STATUS = {
    "Very dry":         "#f50000",   # Higher than 100 cbar      
    "Dry":              "#FAAE6B",   # 60 to 100
    "Moderately dry":   "#f5c542",   # 30 to 60
    "Optimal":          "#38ce1b",   # 10 to 30 
    "Wet":              "#317bfd",   # 0 to 10
}


SOIL_MOISTURE_BANDS = [
    {"label": "Wet", "y0": 0, "y1": 10, "color": SOIL_MOISTURE_STATUS["Wet"]},
    {"label": "Optimal", "y0": 10, "y1": 30, "color": SOIL_MOISTURE_STATUS["Optimal"]},
    {"label": "Moderately dry", "y0": 30, "y1": 60, "color": SOIL_MOISTURE_STATUS["Moderately dry"]},
    {"label": "Dry", "y0": 60, "y1": 100, "color": SOIL_MOISTURE_STATUS["Dry"]},
    {"label": "Very dry", "y0": 100, "y1": None, "color": SOIL_MOISTURE_STATUS["Very dry"]},
]


SOIL_WATER_DEFICIT_STATUS = {
    "Wet": "#317bfd",                # 0 to 4.8935 mm
    "Optimal": "#38ce1b",            # 4.8935 to 14.6653 mm
    "Moderate deficit": "#f5c542",   # 14.6653 to 29.3229 mm
    "High deficit": "#FAAE6B",       # 29.3229 to 48.8665 mm
    "Severe deficit": "#f50000",     # 48.8665 and higher mm
}

SOIL_WATER_DEFICIT_BANDS = [
    {"label": "Wet", "y0": 0, "y1": 4.8935, "color": SOIL_WATER_DEFICIT_STATUS["Wet"]},
    {"label": "Optimal", "y0": 4.8935, "y1": 14.6653, "color": SOIL_WATER_DEFICIT_STATUS["Optimal"]},
    {"label": "Moderate deficit", "y0": 14.6653, "y1": 29.3229, "color": SOIL_WATER_DEFICIT_STATUS["Moderate deficit"]},
    {"label": "High deficit", "y0": 29.3229, "y1": 48.8665, "color": SOIL_WATER_DEFICIT_STATUS["High deficit"]},
    {"label": "Severe deficit", "y0": 48.8665, "y1": None, "color": SOIL_WATER_DEFICIT_STATUS["Severe deficit"]},
]



DEFICIT_ANCHOR_DT = datetime(2026, 5, 29, 11, 0, 0, tzinfo=LATVIA_TZ)
DEFICIT_ANCHOR_TS = int(DEFICIT_ANCHOR_DT.timestamp())

DEFICIT_SEASONS = (
    {
        "year": 2025,
        "start_dt": datetime(2025, 4, 15, 0, 0, 0, tzinfo=LATVIA_TZ),
        "end_dt": datetime(2025, 10, 15, 23, 59, 59, tzinfo=LATVIA_TZ),
    },
    {
        "year": 2026,
        "start_dt": DEFICIT_ANCHOR_DT,
        "end_dt": None,
    },
)


## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::| Helpers / constants |:::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::


def f_to_c(x):
    return (x - 32) * 5.0 / 9.0


def inhg_to_hpa(x):
    return x * 33.8639


def mph_to_ms(x):
    return x * 0.44704


def order_devices(device_values):
    return sorted(
        pd.Series(device_values).dropna().unique(),
        key=lambda d: list(DEVICE_COLOR_MAP.keys()).index(d) if d in DEVICE_COLOR_MAP else 99
    )


def ts_to_local_datetime(ts_series):
    return pd.to_datetime(ts_series + 10800, unit="s", errors="coerce")


def f_to_c(x):
    return (x - 32) * 5.0 / 9.0


def deg_to_compass(deg):
    if pd.isna(deg):
        return None

    directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]

    idx = int((deg + 11.25) // 22.5) % 16
    return directions[idx]

def inches_to_mm(x):
    return x * 25.4


ISS_UNIT_CONVERSION = {
    "temp_out": ("°C", f_to_c),
    "wind_chill": ("°C", f_to_c),
    "heat_index": ("°C", f_to_c),
    "thsw_index": ("°C", f_to_c),
    "dew_point": ("°C", f_to_c),
    "wet_bulb": ("°C", f_to_c),
    "bar": ("hPa", inhg_to_hpa),
    "bar_trend": ("hPa", inhg_to_hpa),
    "wind_speed": ("m/s", mph_to_ms),
    "rain_24_hr_mm": ("mm", lambda x: x),
    "et_day": ("mm", inches_to_mm),
    "rain_rate_mm": ("mm/hr", lambda x: x),
    "wind_dir": ("°", lambda x: x),
    "hum_out": ("%", lambda x: x),
}

## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::| Data fetching from db |:::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

## --| ISS DATA |---------------------------------------------
@st.cache_data(show_spinner=False, ttl=60)
def run_query(query, params=None):
    conn = sqlite3.connect(DB_DIR)
    try:
        df = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()
    return df


@st.cache_data(show_spinner=False, ttl=60)
def get_last_update_time():
    query = """
        SELECT MAX(ts) AS latest_ts
        FROM (
            SELECT ts FROM NODE_ISS_rain_DATA
            UNION ALL
            SELECT ts FROM NODE_barometer_DATA
            UNION ALL
            SELECT ts FROM NODE_temp_probe_DATA
            UNION ALL
            SELECT ts FROM NODE_soil_moisture_DATA
            UNION ALL
            SELECT ts FROM NODE_rain_DATA
        )
    """
    df = run_query(query)

    if df.empty or df["latest_ts"].isna().all():
        return None

    latest_ts = int(df.loc[0, "latest_ts"])
    return datetime.fromtimestamp(latest_ts, tz=timezone.utc).astimezone(LATVIA_TZ)


def get_snapshot_datetime():
    """Return the end of the static dataset in local time."""
    return get_last_update_time() or datetime.now(tz=LATVIA_TZ)


def get_snapshot_date():
    return get_snapshot_datetime().date()


def date_to_timestamp(value, end_of_day=False):
    """Convert a selected local date to a timezone-aware Unix timestamp."""
    selected_time = datetime.max.time() if end_of_day else datetime.min.time()
    return int(datetime.combine(value, selected_time, tzinfo=LATVIA_TZ).timestamp())


@st.cache_data(show_spinner=False, ttl=60)
def fetch_latest_iss_rows(limit=2):
    columns_sql = ",\n            ".join(ISS_HEADER_VARIABLES)

    query = f"""
        SELECT
            ts,
            {columns_sql}
        FROM NODE_ISS_rain_DATA
        ORDER BY ts DESC
        LIMIT ?
    """
    return run_query(query, params=(limit,))


def format_metric_value(value, unit):
    if pd.isna(value):
        return "N/A"

    if unit == "°":
        return f"{value:.0f}{unit}"
    if unit == "%":
        return f"{value:.0f}{unit}"
    return f"{value:.2f} {unit}"


def format_metric_delta(current, previous, unit):
    if pd.isna(current) or pd.isna(previous):
        return None

    delta = current - previous

    if unit == "°":
        return "-"
    if unit == "%":
        return f"{delta:.0f}{unit}"
    return f"{delta:.2f} {unit}"


def convert_iss_value(variable, value):
    unit, converter = ISS_UNIT_CONVERSION.get(variable, ("", lambda x: x))
    if pd.isna(value):
        return np.nan, unit
    return converter(value), unit


def build_header_metrics_data():
    df = fetch_latest_iss_rows(limit=2)

    if df.empty:
        return []

    current_row = df.iloc[0]
    previous_row = df.iloc[1] if len(df) > 1 else df.iloc[0]

    metrics = []

    for variable in ISS_HEADER_VARIABLES:
        current_value, unit = convert_iss_value(variable, current_row.get(variable))
        previous_value, _ = convert_iss_value(variable, previous_row.get(variable))

        # Special handling for wind direction
        if variable == "wind_dir" and pd.notna(current_value):
            compass = deg_to_compass(current_value)
            display_value = f"{current_value:.0f}° ({compass})"
            delta = None  # direction delta is meaningless
        else:
            display_value = format_metric_value(current_value, unit)
            delta = format_metric_delta(current_value, previous_value, unit)

        metrics.append(
            {
                "label": ISS_LABEL_MAP.get(variable, variable),
                "value": display_value,
                "delta": delta,
            }
        )

    return metrics


def get_metric_by_label(metrics, label):
    for metric in metrics:
        if metric["label"] == label:
            return metric
    return {"label": label, "value": "N/A", "delta": None}


## --| BAROMETER DATA |-------------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=60)
def fetch_barometer_data(time_range_sec):
    query = """
    WITH bounds AS (
        SELECT MAX(ts) AS end_ts
        FROM NODE_barometer_DATA
    )
    SELECT
        nodes.lsid,
        nodes.parent_device_name,
        barometer_data.ts,
        barometer_data.pressure_last,
        barometer_data.bar_trend_3_hr
    FROM NODE_barometer_DATA barometer_data
    JOIN NODES nodes ON barometer_data.lsid = nodes.lsid
    CROSS JOIN bounds
    WHERE barometer_data.ts BETWEEN bounds.end_ts - ? AND bounds.end_ts
    """
    return run_query(query, params=(time_range_sec,))

def plot_barometer(time_range_sec):
    df = fetch_barometer_data(time_range_sec)

    if df.empty:
        st.warning("No barometer data available.")
        return

    df["datetime"] = pd.to_datetime(df["ts"] + 10800, unit="s")
    df = df.sort_values("datetime")

    fig = go.Figure()

    for device in df["parent_device_name"].unique():
        subset = df[df["parent_device_name"] == device]

        fig.add_trace(
            go.Scatter(
                x=subset["datetime"],
                y=subset["pressure_last"],
                mode="lines",
                name=f"{device} - pressure",
                yaxis="y1",
                line=dict(color="#6255a3"),
            )
        )

        fig.add_trace(
            go.Scatter(
                x=subset["datetime"],
                y=subset["bar_trend_3_hr"],
                mode="lines",
                name=f"{device} - trend",
                yaxis="y2",
                line=dict(dash="dash", color="#30a579"),
                opacity=0.7,
            )
        )

    # Human-readable titles 
    if time_range_sec == 86400:
        title = "Barometer (last 24h)"
    elif time_range_sec == 604800:
        title = "Barometer (last week)"
    elif time_range_sec == 2592000:
        title = "Barometer (last month)"
    else:
        title = f"Barometer (last {time_range_sec // 3600}h)"

    fig.update_layout(
        title=title,
        xaxis=dict(title="Date"),
        yaxis=dict(title="Pressure (inHg)"),
        yaxis2=dict(
            title="3h Trends",
            overlaying="y",
            side="right"
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.99,
            xanchor="center",
            x=0.5,
        ),
        height=450,
        margin=dict(l=40, r=40, t=60, b=40),
    )

    st.plotly_chart(fig, use_container_width=True)

@st.cache_data(show_spinner=False, ttl=60)
def fetch_barometer_data_by_range(start_ts, end_ts):
    query = """
    SELECT
        nodes.lsid,
        nodes.parent_device_name,
        barometer_data.ts,
        barometer_data.pressure_last,
        barometer_data.bar_trend_3_hr
    FROM NODE_barometer_DATA barometer_data
    JOIN NODES nodes ON barometer_data.lsid = nodes.lsid
    WHERE barometer_data.ts BETWEEN ? AND ?
    """
    return run_query(query, params=(start_ts, end_ts))

def plot_barometer_by_range(start_ts, end_ts):
    df = fetch_barometer_data_by_range(start_ts, end_ts)

    if df.empty:
        st.warning("There is no barometer data available in the selected range.")
        return

    df["datetime"] = pd.to_datetime(df["ts"] + 10800, unit="s", errors="coerce")
    df = df.dropna(subset=["datetime"]).sort_values("datetime")

    if df.empty:
        st.warning("There is no barometer data available in the selected range.")
        return

    fig = go.Figure()

    for device in df["parent_device_name"].dropna().unique():
        subset = df[df["parent_device_name"] == device]

        fig.add_trace(
            go.Scatter(
                x=subset["datetime"],
                y=subset["pressure_last"],
                mode="lines",
                name=f"{device} - pressure",
                yaxis="y1",
                line=dict(color="#6255a3"),
            )
        )

        fig.add_trace(
            go.Scatter(
                x=subset["datetime"],
                y=subset["bar_trend_3_hr"],
                mode="lines",
                name=f"{device} - trend",
                yaxis="y2",
                line=dict(dash="dash", color="#30a579"),
                opacity=0.7,
            )
        )

    min_dt = df["datetime"].min()
    max_dt = df["datetime"].max()

    fig.update_layout(
        title=f"Barometer ({min_dt.strftime('%Y-%m-%d')} to {max_dt.strftime('%Y-%m-%d')})",
        xaxis=dict(title="Date"),
        yaxis=dict(title="Pressure (inHg)"),
        yaxis2=dict(
            title="3h Trend",
            overlaying="y",
            side="right",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.99,
            xanchor="center",
            x=0.5,
        ),
        height=450,
        margin=dict(l=40, r=40, t=60, b=40),
    )

    st.plotly_chart(fig, use_container_width=True)


@st.cache_data(show_spinner=False, ttl=60)
def fetch_latest_barometer_rows(limit=2):
    query = """
    SELECT
        nodes.parent_device_name,
        barometer_data.ts,
        barometer_data.pressure_last
    FROM NODE_barometer_DATA barometer_data
    JOIN NODES nodes
        ON barometer_data.lsid = nodes.lsid
    ORDER BY barometer_data.ts DESC
    LIMIT ?
    """
    return run_query(query, params=(limit,))


def build_barometer_metrics():
    df = fetch_latest_barometer_rows(limit=17376)

    if df.empty:
        return {
            "latest": {"label": "Latest Pressure", "value": "N/A", "delta": None},
            "max": {"label": "Max Pressure", "value": "N/A", "delta": None},
            "min": {"label": "Min Pressure", "value": "N/A", "delta": None},
        }

    df = df.dropna(subset=["pressure_last"]).copy()

    if df.empty:
        return {
            "latest": {"label": "Latest Pressure", "value": "N/A", "delta": None},
            "max": {"label": "Max Pressure", "value": "N/A", "delta": None},
            "min": {"label": "Min Pressure", "value": "N/A", "delta": None},
        }

    # If fetch_latest_barometer_rows already returns newest first, this is optional.
    # Keeping it here makes the function safer.
    df = df.sort_values("ts", ascending=False).reset_index(drop=True)

    # Latest + delta
    current_row = df.iloc[0]
    previous_row = df.iloc[1] if len(df) > 1 else df.iloc[0]

    device_name = current_row["parent_device_name"]

    current_pressure = current_row["pressure_last"]
    previous_pressure = previous_row["pressure_last"]

    latest_value = f"{current_pressure:.2f} inHg"

    latest_delta = (
        f"{current_pressure - previous_pressure:.2f}"
        if pd.notna(previous_pressure)
        else None
    )

    # Max / Min rows
    max_idx = df["pressure_last"].idxmax()
    min_idx = df["pressure_last"].idxmin()

    max_row = df.loc[max_idx]
    min_row = df.loc[min_idx]

    max_pressure = max_row["pressure_last"]
    min_pressure = min_row["pressure_last"]

    max_ts = pd.to_datetime(max_row["ts"] + 10800, unit="s", errors="coerce")
    min_ts = pd.to_datetime(min_row["ts"] + 10800, unit="s", errors="coerce")

    max_delta = f"**{max_ts.strftime('%Y-%m-%d on %H:%M')}**" if pd.notna(max_ts) else None
    min_delta = f"**{min_ts.strftime('%Y-%m-%d on %H:%M')}**" if pd.notna(min_ts) else None

    return {
        "latest": {
            "label": f"Last Pressure ({device_name})",
            "value": latest_value,
            "delta": latest_delta,
            "delta_color": "normal",
            "delta_arrow": "auto",
        },
        "max": {
            "label": "MAX Pressure (last 6 months)",
            "value": f"{max_pressure:.2f} inHg",
            "delta": max_delta,
            "delta_color": "off",
            "delta_arrow": "off",
        },
        "min": {
            "label": "MIN Pressure (last 6 months)",
            "value": f"{min_pressure:.2f} inHg",
            "delta": min_delta,
            "delta_color": "off",
            "delta_arrow": "off",
        },
    }


## --| TEMPERATURE DATA |-------------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=60)
def fetch_temperature_data(time_range_sec):
    query = """
    WITH bounds AS (
        SELECT MAX(ts) AS end_ts
        FROM NODE_temp_probe_DATA
    )
    SELECT
        nodes.lsid,
        nodes.parent_device_name,
        temp_probe_data.ts,
        temp_probe_data.temp_last,
        temp_probe_data.temp_avg,
        temp_probe_data.temp_hi_at,
        temp_probe_data.temp_hi,
        temp_probe_data.temp_lo_at,
        temp_probe_data.temp_lo
    FROM NODE_temp_probe_DATA temp_probe_data
    JOIN NODES nodes ON temp_probe_data.lsid = nodes.lsid
    CROSS JOIN bounds
    WHERE temp_probe_data.ts BETWEEN bounds.end_ts - ? AND bounds.end_ts
    """
    return run_query(query, params=(time_range_sec,))


@st.cache_data(show_spinner=False, ttl=60)
def fetch_temperature_data_by_range(start_ts, end_ts):
    query = """
    SELECT
        nodes.lsid,
        nodes.parent_device_name,
        temp_probe_data.ts,
        temp_probe_data.temp_last,
        temp_probe_data.temp_avg,
        temp_probe_data.temp_hi_at,
        temp_probe_data.temp_hi,
        temp_probe_data.temp_lo_at,
        temp_probe_data.temp_lo
    FROM NODE_temp_probe_DATA temp_probe_data
    JOIN NODES nodes ON temp_probe_data.lsid = nodes.lsid
    WHERE temp_probe_data.ts BETWEEN ? AND ?
    """
    return run_query(query, params=(start_ts, end_ts))


@st.cache_data(show_spinner=False, ttl=60)
def fetch_latest_temperature_rows(device_name, limit=2):
    query = """
    SELECT
        nodes.parent_device_name,
        temp_probe_data.ts,
        temp_probe_data.temp_last
    FROM NODE_temp_probe_DATA temp_probe_data
    JOIN NODES nodes ON temp_probe_data.lsid = nodes.lsid
    WHERE nodes.parent_device_name = ?
    ORDER BY temp_probe_data.ts DESC
    LIMIT ?
    """
    return run_query(query, params=(device_name, limit))


def plot_temperature(variable, time_range_sec):
    df = fetch_temperature_data(time_range_sec)

    if df.empty:
        st.warning("No temperature data available.")
        return

    for col in ["temp_last", "temp_avg", "temp_hi", "temp_lo"]:
        df[col] = df[col].apply(lambda x: f_to_c(x) if pd.notna(x) else np.nan)

    df["datetime"] = ts_to_local_datetime(df["ts"])
    df = df.dropna(subset=["datetime"]).sort_values("datetime")

    variable_title_map = {
        "temp_last": "Last temperature",
        "temp_avg": "Average temperature",
        "temp_hi": "Maximum temperature",
        "temp_lo": "Minimum temperature",
    }

    if time_range_sec == TIME_24H:
        title = f"{variable_title_map[variable]} (last 24h)"
    elif time_range_sec == TIME_WEEK:
        title = f"{variable_title_map[variable]} (last week)"
    elif time_range_sec == TIME_MONTH:
        title = f"{variable_title_map[variable]} (last month)"
    else:
        title = variable_title_map[variable]

    fig = go.Figure()

    for device in order_devices(df["parent_device_name"]):
        subset = df[df["parent_device_name"] == device]
        fig.add_trace(go.Scatter(
            x=subset["datetime"],
            y=subset[variable],
            mode="lines",
            name=device,
            line=dict(color=DEVICE_COLOR_MAP.get(device))
        ))

    fig.update_layout(
        title=title,
        xaxis=dict(title="Time"),
        yaxis=dict(title="Temperature (°C)"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.99,
            xanchor="center",
            x=0.5
        ),
        height=500,
        margin=dict(l=40, r=40, t=60, b=40)
    )

    st.plotly_chart(fig, use_container_width=True)


def plot_temperature_by_range(start_ts, end_ts, variable):
    df = fetch_temperature_data_by_range(start_ts, end_ts)

    if df.empty:
        st.warning("No temperature data available in the selected range.")
        return

    for col in ["temp_last", "temp_avg", "temp_hi", "temp_lo"]:
        df[col] = df[col].apply(lambda x: f_to_c(x) if pd.notna(x) else np.nan)

    df["datetime"] = ts_to_local_datetime(df["ts"])
    df = df.dropna(subset=["datetime"]).sort_values("datetime")

    if df.empty:
        st.warning("No valid timestamps found in the selected range.")
        return

    variable_title_map = {
        "temp_last": "Last temperature",
        "temp_avg": "Average temperature",
        "temp_hi": "Maximum temperature",
        "temp_lo": "Minimum temperature",
    }

    fig = go.Figure()

    for device in order_devices(df["parent_device_name"]):
        subset = df[df["parent_device_name"] == device]
        fig.add_trace(go.Scatter(
            x=subset["datetime"],
            y=subset[variable],
            mode="lines",
            name=device,
            line=dict(color=DEVICE_COLOR_MAP.get(device))
        ))

    fig.update_layout(
        title=f"{variable_title_map[variable]} ({df['datetime'].min().strftime('%Y-%m-%d')} to {df['datetime'].max().strftime('%Y-%m-%d')})",
        xaxis=dict(title="Time"),
        yaxis=dict(title="Temperature (°C)"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.99,
            xanchor="center",
            x=0.5
        ),
        height=500,
        margin=dict(l=40, r=40, t=60, b=40)
    )

    st.plotly_chart(fig, use_container_width=True)




## --| SOIL MOISTURE DATA | -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=60)
def fetch_soil_moisture_data(time_range_sec):
    query = """
    WITH bounds AS (
        SELECT MAX(ts) AS end_ts
        FROM NODE_soil_moisture_DATA
    )
    SELECT
        nodes.lsid,
        nodes.parent_device_name,
        d.ts,
        d.moist_soil_last
    FROM NODE_soil_moisture_DATA d
    JOIN NODES nodes ON d.lsid = nodes.lsid
    CROSS JOIN bounds
    WHERE d.ts BETWEEN bounds.end_ts - ? AND bounds.end_ts
    """
    return run_query(query, params=(time_range_sec,))


@st.cache_data(show_spinner=False, ttl=60)
def fetch_soil_moisture_data_by_range(start_ts, end_ts):
    query = """
    SELECT
        nodes.lsid,
        nodes.parent_device_name,
        d.ts,
        d.moist_soil_last
    FROM NODE_soil_moisture_DATA d
    JOIN NODES nodes ON d.lsid = nodes.lsid
    WHERE d.ts BETWEEN ? AND ?
    """
    return run_query(query, params=(start_ts, end_ts))


@st.cache_data(show_spinner=False, ttl=60)
def fetch_latest_soil_moisture_rows(device_name, limit=2):
    query = """
    SELECT
        nodes.parent_device_name,
        d.ts,
        d.moist_soil_last
    FROM NODE_soil_moisture_DATA d
    JOIN NODES nodes ON d.lsid = nodes.lsid
    WHERE nodes.parent_device_name = ?
    ORDER BY d.ts DESC
    LIMIT ?
    """
    return run_query(query, params=(device_name, limit))


def build_soil_moisture_metrics():
    metrics = []

    for device_name in DEVICE_COLOR_MAP.keys():
        df = fetch_latest_soil_moisture_rows(device_name, limit=2)

        if df.empty:
            metrics.append({
                "label": device_name,
                "value": "N/A",
                "status": "Unknown",
            })
            continue

        current_value = df.iloc[0]["moist_soil_last"]
        status = get_soil_moisture_status(current_value)

        metrics.append({
            "label": device_name,
            "value": f"{current_value:.1f} cbar" if pd.notna(current_value) else "N/A",
            "status": status,
        })

    return metrics


def plot_soil_moisture(time_range_sec):
    df = fetch_soil_moisture_data(time_range_sec)

    if df.empty:
        st.warning("No soil moisture data available.")
        return

    df["datetime"] = ts_to_local_datetime(df["ts"])
    df = df.dropna(subset=["datetime"]).sort_values("datetime")

    if time_range_sec == TIME_24H:
        title = "Soil Moisture (last 24h)"
    elif time_range_sec == TIME_WEEK:
        title = "Soil Moisture (last week)"
    elif time_range_sec == TIME_MONTH:
        title = "Soil Moisture (last month)"
    else:
        title = "Soil Moisture"

    fig = go.Figure()

    max_y = df["moist_soil_last"].max()
    add_soil_moisture_status_background(fig, max_y)

    for device in order_devices(df["parent_device_name"]):
        subset = df[df["parent_device_name"] == device]

        fig.add_trace(go.Scatter(
            x=subset["datetime"],
            y=subset["moist_soil_last"],
            mode="lines",
            name=device,
            line=dict(
                color=DEVICE_COLOR_MAP.get(device),
                width=2.5,
            )
        ))

    fig.update_layout(
        title=title,
        xaxis=dict(title="Time"),
        yaxis=dict(title="Soil Moisture (centibars)"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.99,
            xanchor="center",
            x=0.5
        ),
        height=500,
        margin=dict(l=40, r=40, t=60, b=40)
    )

    st.plotly_chart(fig, use_container_width=True)


def plot_soil_moisture_by_range(start_ts, end_ts):
    df = fetch_soil_moisture_data_by_range(start_ts, end_ts)

    if df.empty:
        st.warning("No soil moisture data available in the selected range.")
        return

    df["datetime"] = ts_to_local_datetime(df["ts"])
    df = df.dropna(subset=["datetime"]).sort_values("datetime")

    if df.empty:
        st.warning("No valid timestamps found in the selected range.")
        return

    fig = go.Figure()

    max_y = df["moist_soil_last"].max()
    add_soil_moisture_status_background(fig, max_y)

    for device in order_devices(df["parent_device_name"]):
        subset = df[df["parent_device_name"] == device]

        fig.add_trace(go.Scatter(
            x=subset["datetime"],
            y=subset["moist_soil_last"],
            mode="lines",
            name=device,
            line=dict(
                color=DEVICE_COLOR_MAP.get(device),
                width=2.5,
            )
        ))

    fig.update_layout(
        title=f"Soil Moisture ({df['datetime'].min().strftime('%Y-%m-%d')} to {df['datetime'].max().strftime('%Y-%m-%d')})",
        xaxis=dict(title="Time"),
        yaxis=dict(title="Soil Moisture (centibars)"),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.18,
            xanchor="center",
            x=0.5
        ),
        height=600,
        margin=dict(l=40, r=40, t=95, b=40)
    )

    st.plotly_chart(fig, use_container_width=True)



def add_soil_moisture_status_background(fig, max_y):
    upper_y = max(max_y, 120)

    for band in SOIL_MOISTURE_BANDS:
        y1 = band["y1"] if band["y1"] is not None else upper_y

        fig.add_hrect(
            y0=band["y0"],
            y1=y1,
            fillcolor=band["color"],
            opacity=0.30,
            line_width=0,
            layer="below",
            annotation_text=band["label"],
            annotation_position="right",
            annotation_font_size=12,
        )

    fig.update_yaxes(range=[0, upper_y])


def get_soil_moisture_status(value):
    if pd.isna(value):
        return "Unknown"

    if value > 100:
        return "Very dry"
    if value > 60:
        return "Dry"
    if value > 30:
        return "Moderately dry"
    if value > 10:
        return "Optimal"
    return "Wet"



def inject_soil_card_css():
    st.markdown(
        """
        <style>
        @keyframes soil-pulse-alert {
            0% {
                box-shadow: 0 0 0 0 var(--pulse-color);
                transform: scale(1);
            }
            50% {
                box-shadow: 0 0 0 7px rgba(0, 0, 0, 0);
                transform: scale(1.015);
            }
            100% {
                box-shadow: 0 0 0 0 rgba(0, 0, 0, 0);
                transform: scale(1);
            }
        }

        .soil-card-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 1rem;
            width: 100%;

            margin-bottom: 2rem;
        }

        @media (max-width: 1000px) {
            .soil-card-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 385px) {
            .soil-card-grid {
                grid-template-columns: 1fr;
            }
        }

        .soil-card {
            border: 1px solid rgba(128, 128, 128, 0.35);
            border-radius: 0.75rem;
            padding: 1rem;
            min-height: 115px;
            background: var(--background-color);
            font-family: inherit;
        }

        .soil-card.alert {
            animation: soil-pulse-alert 1.6s infinite;
        }

        .soil-label {
            font-size: 0.9rem;
            opacity: 0.75;
            margin-bottom: 0.35rem;
        }

        .soil-value {
            font-size: 1.65rem;
            font-weight: 600;
            line-height: 1.2;
            margin-bottom: 0.35rem;
        }

        .soil-status {
            font-size: 0.95rem;
            font-weight: 700;
        }


        </style>
        """,
        unsafe_allow_html=True,
    )


def build_soil_card_html(label, value, status, color, is_optimal=False):
    alert_class = "" if is_optimal else " alert"

    return f"""
    <div class="soil-card{alert_class}" style="--pulse-color: {color};">
        <div class="soil-label">{label}</div>
        <div class="soil-value">{value}</div>
        <div class="soil-status" style="color: {color};">{status}</div>
    </div>
    """


def test_soil_moisture_metrics_section():
    inject_soil_card_css()

    cards_html = [
        build_soil_card_html(
            label="Augsnes sensori #1",
            value="100.2 cbar",
            status="Dry",
            color="#f5c542",
        ),
        build_soil_card_html(
            label="Augsnes sensori #2",
            value="820.3 cbar",
            status="Moderately dry",
            color="#FAAE6BFF",
        ),
        build_soil_card_html(
            label="Augsnes sensori #3",
            value="150.2 cbar",
            status="Optimal",
            color="#21c55d",
            is_optimal=True,
        ),
        build_soil_card_html(
            label="Augsnes sensori #4",
            value="103.2 cbar",
            status="Wet",
            color="#3b82f6",
        ),
    ]

    st.markdown(
    f"""
    <div class="soil-card-grid">
        {''.join(cards_html)}
    </div>
    """,
        unsafe_allow_html=True,
    )


def soil_moisture_metrics_section():
    inject_soil_card_css()

    metrics = build_soil_moisture_metrics()

    cards_html = []

    for metric in metrics:
        status = metric["status"]
        color = SOIL_MOISTURE_STATUS.get(status, "#9ca3af")
        is_optimal = status == "Optimal"

        cards_html.append(
            build_soil_card_html(
                label=metric["label"],
                value=metric["value"],
                status=status,
                color=color,
                is_optimal=is_optimal,
            )
        )

    st.markdown(
        f"""
    <div class="soil-card-grid">
        {''.join(cards_html)}
    </div>
    """,
        unsafe_allow_html=True,
    )




@st.cache_data(show_spinner=False, ttl=60)
def fetch_daily_et_mm_from(start_ts: int):
    query = """
    SELECT ts, et_day
    FROM NODE_ISS_rain_DATA
    WHERE ts >= ? AND et_day IS NOT NULL
    ORDER BY ts
    """
    df = run_query(query, params=(start_ts,))
    if df.empty:
        return pd.DataFrame(columns=["date", "et_mm"])

    df["datetime"] = ts_to_local_datetime(df["ts"])
    df["date"] = df["datetime"].dt.date
    df["et_mm"] = df["et_day"].apply(lambda x: max(0.0, inches_to_mm(x)) if pd.notna(x) else 0.0)

    return df.groupby("date", as_index=False)["et_mm"].max().sort_values("date")


@st.cache_data(show_spinner=False, ttl=60)
def fetch_daily_precip_mm_by_device_from(start_ts: int):
    query = """
    SELECT
        nodes.parent_device_name,
        rain_data.ts,
        rain_data.rainfall_last_15_min_mm
    FROM NODE_rain_DATA rain_data
    JOIN NODES nodes
        ON rain_data.lsid = nodes.lsid
    WHERE rain_data.ts >= ?
      AND rain_data.rainfall_last_15_min_mm IS NOT NULL
    ORDER BY rain_data.ts
    """

    df = run_query(query, params=(start_ts,))

    if df.empty:
        return pd.DataFrame(columns=["parent_device_name", "date", "precip_mm"])

    df["datetime"] = ts_to_local_datetime(df["ts"])
    df = df.dropna(subset=["datetime"])

    df["date"] = df["datetime"].dt.date
    df["precip_mm"] = df["rainfall_last_15_min_mm"].clip(lower=0)

    return (
        df.groupby(["parent_device_name", "date"], as_index=False)["precip_mm"]
        .sum()
        .sort_values(["parent_device_name", "date"])
    )



def calculate_deficit_series(df):
    deficits = []
    previous_deficit = 0.0

    for _, row in df.iterrows():
        et_mm = max(0.0, row["et_mm"]) if pd.notna(row["et_mm"]) else 0.0
        precip_mm = max(0.0, row["precip_mm"]) if pd.notna(row["precip_mm"]) else 0.0

        current_deficit = max(0.0, previous_deficit + et_mm - precip_mm)

        deficits.append(current_deficit)
        previous_deficit = current_deficit

    df = df.copy()
    df["deficit_mm"] = deficits

    return df


def get_soil_water_deficit_status(value):
    if pd.isna(value):
        return "Unknown"

    if value <= 4.8935:
        return "Wet"
    if value <= 14.6653:
        return "Optimal"
    if value <= 29.3229:
        return "Moderate deficit"
    if value <= 48.8665:
        return "High deficit"
    return "Severe deficit"


@st.cache_data(show_spinner=False, ttl=60)
def fetch_daily_et_mm(days=60):
    query = """
    WITH bounds AS (
        SELECT MAX(ts) AS end_ts
        FROM NODE_ISS_rain_DATA
        WHERE et_day IS NOT NULL
    )
    SELECT
        ts,
        et_day
    FROM NODE_ISS_rain_DATA
    CROSS JOIN bounds
    WHERE ts BETWEEN bounds.end_ts - ? AND bounds.end_ts
      AND et_day IS NOT NULL
    ORDER BY ts
    """
    df = run_query(query, params=(days * TIME_24H,))

    if df.empty:
        return pd.DataFrame(columns=["date", "et_mm"])

    df["datetime"] = ts_to_local_datetime(df["ts"])
    df["date"] = df["datetime"].dt.date
    df["et_mm"] = df["et_day"].apply(
        lambda x: max(0.0, inches_to_mm(x)) if pd.notna(x) else 0.0
    )

    return (
        df.groupby("date", as_index=False)["et_mm"]
        .max()
        .sort_values("date")
    )


@st.cache_data(show_spinner=False, ttl=60)
def fetch_daily_precip_mm_by_device(days=4):
    query = """
    WITH bounds AS (
        SELECT MAX(ts) AS end_ts
        FROM NODE_rain_DATA
        WHERE rainfall_mm IS NOT NULL
    )
    SELECT
        nodes.parent_device_name,
        rain_data.ts,
        rain_data.rainfall_mm
    FROM NODE_rain_DATA rain_data
    JOIN NODES nodes
        ON rain_data.lsid = nodes.lsid
    CROSS JOIN bounds
    WHERE rain_data.ts BETWEEN bounds.end_ts - ? AND bounds.end_ts
      AND rain_data.rainfall_mm IS NOT NULL
    ORDER BY rain_data.ts
    """
    df = run_query(query, params=(days * TIME_24H,))

    if df.empty:
        return pd.DataFrame(columns=["parent_device_name", "date", "precip_mm"])

    df["datetime"] = ts_to_local_datetime(df["ts"])
    df["date"] = df["datetime"].dt.date
    df["precip_mm"] = df["rainfall_mm"].apply(
        lambda x: max(0.0, x) if pd.notna(x) else 0.0
    )

    return (
        df.groupby(["parent_device_name", "date"], as_index=False)["precip_mm"]
        .max()
        .sort_values(["parent_device_name", "date"])
    )


def calculate_deficit_series(df):
    deficits = []
    previous_deficit = 0.0

    for _, row in df.iterrows():
        et_mm = max(0.0, row["et_mm"]) if pd.notna(row["et_mm"]) else 0.0
        precip_mm = max(0.0, row["precip_mm"]) if pd.notna(row["precip_mm"]) else 0.0

        current_deficit = max(0.0, previous_deficit + et_mm - precip_mm)

        deficits.append(current_deficit)
        previous_deficit = current_deficit

    df = df.copy()
    df["deficit_mm"] = deficits

    return df


def build_soil_water_deficit_daily_data(
    start_ts: int = DEFICIT_ANCHOR_TS,
    end_ts=None,
):
    et_df = fetch_daily_et_mm_from(start_ts)
    precip_df = fetch_daily_precip_mm_by_device_from(start_ts)

    if end_ts is not None:
        end_date = datetime.fromtimestamp(end_ts, tz=LATVIA_TZ).date()
        et_df = et_df[et_df["date"] <= end_date]
        precip_df = precip_df[precip_df["date"] <= end_date]

    all_device_data = []

    for device_name in DEVICE_COLOR_MAP.keys():
        device_precip = precip_df[precip_df["parent_device_name"] == device_name].copy()

        all_dates = pd.DataFrame({
            "date": sorted(set(et_df["date"]).union(set(device_precip["date"])))
        })

        if all_dates.empty:
            continue

        daily_df = (
            all_dates
            .merge(et_df, on="date", how="left")
            .merge(device_precip[["date", "precip_mm"]], on="date", how="left")
            .fillna({"et_mm": 0.0, "precip_mm": 0.0})
            .sort_values("date")
        )

        daily_df = calculate_deficit_series(daily_df)
        daily_df["parent_device_name"] = device_name
        daily_df["status"] = daily_df["deficit_mm"].apply(get_soil_water_deficit_status)

        all_device_data.append(daily_df)

    if not all_device_data:
        return pd.DataFrame(columns=[
            "date",
            "et_mm",
            "precip_mm",
            "deficit_mm",
            "parent_device_name",
            "status",
        ])

    return pd.concat(all_device_data, ignore_index=True)


def build_soil_water_deficit_data_for_range(start_ts: int, end_ts: int):
    """Build SWD data for every season intersecting the requested date range.

    Each season is calculated independently, so the accumulated deficit resets
    to zero at the beginning of the next season.
    """
    requested_start = datetime.fromtimestamp(start_ts, tz=LATVIA_TZ).date()
    requested_end = datetime.fromtimestamp(end_ts, tz=LATVIA_TZ).date()

    season_frames = []

    for season in DEFICIT_SEASONS:
        season_start = season["start_dt"].date()
        season_end = (
            season["end_dt"].date()
            if season["end_dt"] is not None
            else get_snapshot_date()
        )

        if requested_end < season_start or requested_start > season_end:
            continue

        season_end_ts = (
            int(season["end_dt"].timestamp())
            if season["end_dt"] is not None
            else None
        )

        season_df = build_soil_water_deficit_daily_data(
            start_ts=int(season["start_dt"].timestamp()),
            end_ts=season_end_ts,
        )

        if not season_df.empty:
            season_df = season_df.copy()
            season_df["season"] = season["year"]
            season_frames.append(season_df)

    if not season_frames:
        return pd.DataFrame(columns=[
            "date",
            "et_mm",
            "precip_mm",
            "deficit_mm",
            "parent_device_name",
            "status",
            "season",
        ])

    return pd.concat(season_frames, ignore_index=True)


def build_soil_water_deficit_metrics(start_ts=DEFICIT_ANCHOR_TS):
    df = build_soil_water_deficit_daily_data(start_ts)

    metrics = []

    for device_name in DEVICE_COLOR_MAP.keys():
        device_df = df[df["parent_device_name"] == device_name].sort_values("date")

        if device_df.empty:
            metrics.append({
                "label": device_name,
                "value": "N/A",
                "status": "Unknown",
                "caption": "No ET or precipitation data available.",
            })
            continue

        latest = device_df.iloc[-1]

        metrics.append({
            "label": device_name,
            "value": f"{latest['deficit_mm']:.2f} mm",
            "status": latest["status"],
            "caption": (
                f"Date: {latest['date']} | "
                f"ET: {latest['et_mm']:.2f} mm | "
                f"P: {latest['precip_mm']:.2f} mm"
            ),
        })

    return metrics




def soil_water_deficit_metrics_section():
    inject_soil_card_css()

    metrics = build_soil_water_deficit_metrics()

    cards_html = []

    for metric in metrics:
        status = metric["status"]
        color = SOIL_WATER_DEFICIT_STATUS.get(status, "#9ca3af")
        is_optimal = status == "Optimal"

        cards_html.append(
            build_soil_card_html(
                label=metric["label"],
                value=metric["value"],
                status=status,
                color=color,
                is_optimal=is_optimal,
            )
        )

    st.markdown(
        f"""
    <div class="soil-card-grid">
        {''.join(cards_html)}
    </div>
    """,
        unsafe_allow_html=True,
    )

    # for metric in metrics:
    #     st.caption(f"**{metric['label']}** - {metric['caption']}")


def add_soil_water_deficit_status_background(fig, max_y):
    upper_y = max(max_y, 55)

    for band in SOIL_WATER_DEFICIT_BANDS:
        y1 = band["y1"] if band["y1"] is not None else upper_y

        fig.add_hrect(
            y0=band["y0"],
            y1=y1,
            fillcolor=band["color"],
            opacity=0.30,
            line_width=0,
            layer="below",
            annotation_text=band["label"],
            annotation_position="right",
            annotation_font_size=12,
        )

    fig.update_yaxes(range=[0, upper_y])



def plot_soil_water_deficit_by_range(start_ts, end_ts, chart_key=None):
    df = build_soil_water_deficit_data_for_range(start_ts, end_ts)

    if df.empty:
        st.warning("No soil water deficit data available.")
        return

    df["datetime"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["datetime"])

    start_dt = datetime.fromtimestamp(start_ts, tz=LATVIA_TZ).date()
    end_dt = datetime.fromtimestamp(end_ts, tz=LATVIA_TZ).date()

    plot_df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]

    if plot_df.empty:
        st.warning("No soil water deficit data available in the selected range.")
        return

    fig = go.Figure()

    max_y = plot_df["deficit_mm"].max()
    add_soil_water_deficit_status_background(fig, max_y)

    for device in order_devices(plot_df["parent_device_name"]):
        device_df = plot_df[plot_df["parent_device_name"] == device]

        for season_index, season in enumerate(sorted(device_df["season"].unique())):
            subset = device_df[device_df["season"] == season].sort_values("datetime")

            fig.add_trace(go.Scatter(
                x=subset["datetime"],
                y=subset["deficit_mm"],
                mode="lines+markers",
                name=device,
                legendgroup=device,
                showlegend=season_index == 0,
                line=dict(
                    color=DEVICE_COLOR_MAP.get(device),
                    width=2.5,
                )
            ))

    fig.update_layout(
        title=f"Soil Water Deficit ({plot_df['datetime'].min().strftime('%Y-%m-%d')} to {plot_df['datetime'].max().strftime('%Y-%m-%d')})",
        xaxis=dict(title="Date"),
        yaxis=dict(title="Soil Water Deficit (mm)"),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.18,
            xanchor="center",
            x=0.5
        ),
        height=600,
        margin=dict(l=40, r=40, t=95, b=40)
    )

    st.plotly_chart(fig, use_container_width=True, key=chart_key)







@st.cache_data(show_spinner=False, ttl=60)
def fetch_latest_et_mm():
    query = """
    SELECT
        ts,
        et_day
    FROM NODE_ISS_rain_DATA
    WHERE et_day IS NOT NULL
    ORDER BY ts DESC
    LIMIT 1
    """
    df = run_query(query)

    if df.empty:
        return 0.0

    et_day_inches = df.iloc[0]["et_day"]
    return max(0.0, et_day_inches * 25.4) if pd.notna(et_day_inches) else 0.0


@st.cache_data(show_spinner=False, ttl=60)
def fetch_latest_rain_for_deficit_by_device():
    query = """
    SELECT
        nodes.parent_device_name,
        rain_data.ts,
        rain_data.rainfall_mm
    FROM NODE_rain_DATA rain_data
    JOIN NODES nodes
        ON rain_data.lsid = nodes.lsid
    WHERE rain_data.rainfall_mm IS NOT NULL
    ORDER BY rain_data.ts DESC
    """
    return run_query(query)


def calculate_soil_water_deficit(dp_mm, et_mm, precip_mm, irrigation_mm):
    dc = dp_mm + et_mm - precip_mm - irrigation_mm
    return max(0.0, dc)



## --| RAIN DATA |---------------------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=60)
def fetch_rain_data(time_range_sec):
    query = """
    WITH bounds AS (
        SELECT MAX(ts) AS end_ts
        FROM NODE_rain_DATA
    )
    SELECT
        nodes.lsid,
        nodes.parent_device_name,
        rain_data.ts,
        rain_data.rain_rate_hi_at,
        rain_data.rain_rate_hi_mm,
        rain_data.rain_rate_hi_last_15_min_mm,
        rain_data.rain_rate_last_mm,
        rain_data.rainfall_mm,
        rain_data.rainfall_last_15_min_mm,
        rain_data.rainfall_last_60_min_mm
    FROM NODE_rain_DATA rain_data
    JOIN NODES nodes ON rain_data.lsid = nodes.lsid
    CROSS JOIN bounds
    WHERE rain_data.ts BETWEEN bounds.end_ts - ? AND bounds.end_ts
    """
    return run_query(query, params=(time_range_sec,))


@st.cache_data(show_spinner=False, ttl=60)
def fetch_rain_data_by_range(start_ts, end_ts):
    query = """
    SELECT
        nodes.lsid,
        nodes.parent_device_name,
        rain_data.ts,
        rain_data.rain_rate_hi_at,
        rain_data.rain_rate_hi_mm,
        rain_data.rain_rate_hi_last_15_min_mm,
        rain_data.rain_rate_last_mm,
        rain_data.rainfall_mm,
        rain_data.rainfall_last_15_min_mm,
        rain_data.rainfall_last_60_min_mm
    FROM NODE_rain_DATA rain_data
    JOIN NODES nodes ON rain_data.lsid = nodes.lsid
    WHERE rain_data.ts BETWEEN ? AND ?
    """
    return run_query(query, params=(start_ts, end_ts))


@st.cache_data(show_spinner=False, ttl=60)
def fetch_latest_rain_rows(device_name, limit=2):
    query = """
    SELECT
        nodes.parent_device_name,
        rain_data.ts,
        rain_data.rainfall_mm
    FROM NODE_rain_DATA rain_data
    JOIN NODES nodes ON rain_data.lsid = nodes.lsid
    WHERE nodes.parent_device_name = ?
    ORDER BY rain_data.ts DESC
    LIMIT ?
    """
    return run_query(query, params=(device_name, limit))


def build_rain_metrics():
    metrics = []

    for device_name in DEVICE_COLOR_MAP.keys():
        df = fetch_latest_rain_rows(device_name, limit=2)

        if df.empty:
            metrics.append({
                "label": device_name,
                "value": "N/A",
                "delta": None,
            })
            continue

        current_value = df.iloc[0]["rainfall_mm"]
        previous_value = df.iloc[1]["rainfall_mm"] if len(df) > 1 else current_value

        metrics.append({
            "label": device_name,
            "value": f"{current_value:.2f} mm" if pd.notna(current_value) else "N/A",
            "delta": f"{current_value - previous_value:.2f} mm" if pd.notna(current_value) and pd.notna(previous_value) else None,
        })

    return metrics


@st.cache_data(show_spinner=False, ttl=60)
def fetch_rain_data(time_range_sec):
    query = """
    WITH bounds AS (
        SELECT MAX(ts) AS end_ts
        FROM NODE_rain_DATA
    )
    SELECT
        nodes.lsid,
        nodes.parent_device_name,
        rain_data.ts,
        rain_data.rain_rate_hi_at,
        rain_data.rain_rate_hi_mm,
        rain_data.rain_rate_hi_last_15_min_mm,
        rain_data.rain_rate_last_mm,
        rain_data.rainfall_mm,
        rain_data.rainfall_last_15_min_mm,
        rain_data.rainfall_last_60_min_mm
    FROM NODE_rain_DATA rain_data
    JOIN NODES nodes ON rain_data.lsid = nodes.lsid
    CROSS JOIN bounds
    WHERE rain_data.ts BETWEEN bounds.end_ts - ? AND bounds.end_ts
    """
    return run_query(query, params=(time_range_sec,))


@st.cache_data(show_spinner=False, ttl=60)
def fetch_rain_data_by_range(start_ts, end_ts):
    query = """
    SELECT
        nodes.lsid,
        nodes.parent_device_name,
        rain_data.ts,
        rain_data.rain_rate_hi_at,
        rain_data.rain_rate_hi_mm,
        rain_data.rain_rate_hi_last_15_min_mm,
        rain_data.rain_rate_last_mm,
        rain_data.rainfall_mm,
        rain_data.rainfall_last_15_min_mm,
        rain_data.rainfall_last_60_min_mm
    FROM NODE_rain_DATA rain_data
    JOIN NODES nodes ON rain_data.lsid = nodes.lsid
    WHERE rain_data.ts BETWEEN ? AND ?
    """
    return run_query(query, params=(start_ts, end_ts))


@st.cache_data(show_spinner=False, ttl=60)
def fetch_latest_rain_rows(device_name, limit=2):
    query = """
    SELECT
        nodes.parent_device_name,
        rain_data.ts,
        rain_data.rainfall_mm
    FROM NODE_rain_DATA rain_data
    JOIN NODES nodes ON rain_data.lsid = nodes.lsid
    WHERE nodes.parent_device_name = ?
    ORDER BY rain_data.ts DESC
    LIMIT ?
    """
    return run_query(query, params=(device_name, limit))


def build_rain_metrics():
    metrics = []

    for device_name in DEVICE_COLOR_MAP.keys():
        df = fetch_latest_rain_rows(device_name, limit=2)

        if df.empty:
            metrics.append({
                "label": device_name,
                "value": "N/A",
                "delta": None,
            })
            continue

        current_value = df.iloc[0]["rainfall_mm"]
        previous_value = df.iloc[1]["rainfall_mm"] if len(df) > 1 else current_value

        metrics.append({
            "label": device_name,
            "value": f"{current_value:.2f} mm" if pd.notna(current_value) else "N/A",
            "delta": f"{current_value - previous_value:.2f} mm" if pd.notna(current_value) and pd.notna(previous_value) else None,
        })

    return metrics


def plot_rain(variable, time_range_sec):
    df = fetch_rain_data(time_range_sec)

    if df.empty:
        st.warning("No rain data available.")
        return

    df["datetime"] = ts_to_local_datetime(df["ts"])
    df = df.dropna(subset=["datetime"]).sort_values("datetime")

    variable_title_map = {
        "rainfall_mm": "Rainfall",
        "rainfall_last_15_min_mm": "Rainfall last 15 min",
        "rainfall_last_60_min_mm": "Rainfall last 60 min",
        "rain_rate_last_mm": "Rain rate last",
        "rain_rate_hi_mm": "Rain rate high",
        "rain_rate_hi_last_15_min_mm": "Rain rate high last 15 min",
    }

    if time_range_sec == TIME_24H:
        title = f"{variable_title_map[variable]} (last 24h)"
    elif time_range_sec == TIME_WEEK:
        title = f"{variable_title_map[variable]} (last week)"
    elif time_range_sec == TIME_MONTH:
        title = f"{variable_title_map[variable]} (last month)"
    else:
        title = variable_title_map[variable]

    fig = go.Figure()

    for device in order_devices(df["parent_device_name"]):
        subset = df[df["parent_device_name"] == device]
        fig.add_trace(go.Scatter(
            x=subset["datetime"],
            y=subset[variable],
            mode="lines",
            name=device,
            line=dict(color=DEVICE_COLOR_MAP.get(device))
        ))

    fig.update_layout(
        title=title,
        xaxis=dict(title="Time"),
        yaxis=dict(title="Rain (mm)"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.99,
            xanchor="center",
            x=0.5
        ),
        height=500,
        margin=dict(l=40, r=40, t=60, b=40)
    )

    st.plotly_chart(fig, use_container_width=True)


def add_rainfall_day_mm(df):
    df = df.copy()

    df["date"] = df["datetime"].dt.date

    daily_df = (
        df.dropna(subset=["rainfall_mm"])
        .groupby(["parent_device_name", "date"], as_index=False)["rainfall_mm"]
        .max()
        .rename(columns={"rainfall_mm": "rainfall_day_mm"})
    )

    daily_df["datetime"] = pd.to_datetime(daily_df["date"])

    return daily_df




def plot_rain_by_range(start_ts, end_ts, variable):
    df = fetch_rain_data_by_range(start_ts, end_ts)

    if df.empty:
        st.warning("No rain data available in the selected range.")
        return

    df["datetime"] = ts_to_local_datetime(df["ts"])
    df = df.dropna(subset=["datetime"]).sort_values("datetime")

    if df.empty:
        st.warning("No valid timestamps found in the selected range.")
        return

    variable_title_map = {
        "rainfall_mm": "Rainfall",
        "rainfall_day_mm": "Rainfall per day",
        "rainfall_last_15_min_mm": "Rainfall last 15 min",
        "rainfall_last_60_min_mm": "Rainfall last 60 min",
        "rain_rate_last_mm": "Rain rate last",
        "rain_rate_hi_mm": "Rain rate high",
        "rain_rate_hi_last_15_min_mm": "Rain rate high last 15 min",
    }

    if variable == "rainfall_day_mm":
        plot_df = add_rainfall_day_mm(df)
        x_col = "datetime"
        mode = "lines+markers"
    else:
        plot_df = df
        x_col = "datetime"
        mode = "lines"

    fig = go.Figure()

    for device in order_devices(plot_df["parent_device_name"]):
        subset = plot_df[plot_df["parent_device_name"] == device]

        fig.add_trace(go.Scatter(
            x=subset[x_col],
            y=subset[variable],
            mode=mode,
            name=device,
            line=dict(color=DEVICE_COLOR_MAP.get(device))
        ))

    fig.update_layout(
        title=f"{variable_title_map[variable]} ({plot_df['datetime'].min().strftime('%Y-%m-%d')} to {plot_df['datetime'].max().strftime('%Y-%m-%d')})",
        xaxis=dict(title="Date" if variable == "rainfall_day_mm" else "Time"),
        yaxis=dict(title="Rain (mm)"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.99,
            xanchor="center",
            x=0.5
        ),
        height=500,
        margin=dict(l=40, r=40, t=60, b=40)
    )

    st.plotly_chart(fig, use_container_width=True)


## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::| Page Templates |::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
def template_header_metrics(name, passed_value, passed_delta=None):
    return st.metric(
        label=name,
        value=passed_value,
        delta=passed_delta,
        border=True,
    )

def build_temperature_metrics():
    metrics = []

    for device_name in DEVICE_COLOR_MAP.keys():
        df = fetch_latest_temperature_rows(device_name, limit=2)

        if df.empty:
            metrics.append({
                "label": device_name,
                "value": "N/A",
                "delta": None,
            })
            continue

        current_f = df.iloc[0]["temp_last"]
        previous_f = df.iloc[1]["temp_last"] if len(df) > 1 else current_f

        current_c = f_to_c(current_f) if pd.notna(current_f) else np.nan
        previous_c = f_to_c(previous_f) if pd.notna(previous_f) else np.nan

        metrics.append({
            "label": device_name,
            "value": f"{current_c:.2f} °C" if pd.notna(current_c) else "N/A",
            "delta": f"{current_c - previous_c:.2f} °C" if pd.notna(current_c) and pd.notna(previous_c) else None,
        })

    return metrics




## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::| Page Sections |:::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
def section_last_update(sensor_name, sensor_type):
    last_update = get_last_update_time()

    if last_update:
        st.markdown(
            f"""
            :gray-badge[:material/nest_remote_comfort_sensor: Sensor: **{sensor_name}**, Sensor type: **{sensor_type}**]
            :green-badge[:material/database: DB Snapshot: **{last_update.strftime('%Y-%m-%d at %H:%M')}**]"""
        )
    else:
        st.markdown(":gray-badge[:material/nest_remote_comfort_sensor: Sensor: **Unknown**, sensor type: **Unknown**] :gray-badge[:material/database: Snapshot date: **Unknown**]")


def section_header_metrics():
    metrics = build_header_metrics_data()

    if not metrics:
        st.warning("No ISS header metrics available.")
        return

    temperature_row = st.container(
        horizontal=True,
        horizontal_alignment="distribute",
    )
    with temperature_row:
        for label in [
            "Outside Temperature",
            "Wind Chill",
            "Heat Index",
            "THSW Index",
            "Dew Point",
            "Wet Bulb",
            "Evapotranspiration",
        ]:
            metric = get_metric_by_label(metrics, label)
            template_header_metrics(metric["label"], metric["value"], metric["delta"])

    other_data_row = st.container(
        horizontal=True,
        horizontal_alignment="distribute",
    )
    with other_data_row:
        for label in [
            "Rain 24 hr mm",
            "Rain Rate mm",
            "Humidity Out",
            "Pressure",
            "Bar Trend",
            "Wind Speed",
            "Wind Direction",
            
        ]:
            metric = get_metric_by_label(metrics, label)
            template_header_metrics(metric["label"], metric["value"], metric["delta"])

def section_barometer():
    
    st.header("Barometer")

    section_last_update("Barometer", "3")

    metrics = build_barometer_metrics()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            metrics["latest"]["label"],
            metrics["latest"]["value"],
            metrics["latest"]["delta"],
            delta_color=metrics["latest"]["delta_color"],
            delta_arrow=metrics["latest"]["delta_arrow"],
            border=True,
        )

    with col2:
        st.metric(
            metrics["max"]["label"],
            metrics["max"]["value"],
            metrics["max"]["delta"],
            delta_color=metrics["max"]["delta_color"],
            delta_arrow=metrics["max"]["delta_arrow"],
            border=True,
        )

    with col3:
        st.metric(
            metrics["min"]["label"],
            metrics["min"]["value"],
            metrics["min"]["delta"],
            delta_color=metrics["min"]["delta_color"],
            delta_arrow=metrics["min"]["delta_arrow"],
            border=True,
        )


    tab1, tab2, tab3, tab4 = st.tabs(["24h", "Week", "Month", "Custom Range"])

    with tab1:
        plot_barometer(TIME_24H)

    with tab2:
        plot_barometer(TIME_WEEK)

    with tab3:
        plot_barometer(TIME_MONTH)

    with tab4:
        snapshot_date = get_snapshot_date()
        default_start = snapshot_date - timedelta(days=7)

        date_range = st.date_input(
            "Date Range",
            value=(default_start, snapshot_date),
            key="barometer_custom_date_range",
        )

        if len(date_range) == 2:
            start_date, end_date = date_range

            start_ts = date_to_timestamp(start_date)
            end_ts = date_to_timestamp(end_date, end_of_day=True)

            plot_barometer_by_range(start_ts, end_ts)


def section_thermometer():
    st.header("Temperature Probes")
    section_last_update("Temperature Probes", "105")

    metrics = build_temperature_metrics()

    col1, col2, col3, col4 = st.columns(4)

    for col, metric in zip([col1, col2, col3, col4], metrics):
        with col:
            st.metric(metric["label"], metric["value"], metric["delta"], border=True)

    tab1, tab2, tab3, tab4 = st.tabs(["24h", "Week", "Month", "Custom Range"])

    with tab1:
        plot_temperature("temp_last", TIME_24H)

    with tab2:
        plot_temperature("temp_last", TIME_WEEK)

    with tab3:
        plot_temperature("temp_last", TIME_MONTH)

    with tab4:
        snapshot_date = get_snapshot_date()
        default_start = snapshot_date - timedelta(days=7)

        col1, col2 = st.columns(2)
        
        with col1:
            date_range = st.date_input(
                "Date range",
                value=(default_start, snapshot_date),
                key="temp_custom_date_range",
            )

        with col2:
            variable = st.selectbox(
                "Variable",
                ["temp_last", "temp_avg", "temp_hi", "temp_lo"],
                key="temp_variable_select",
            )

        if len(date_range) == 2:
            start_date, end_date = date_range
            start_ts = date_to_timestamp(start_date)
            end_ts = date_to_timestamp(end_date, end_of_day=True)

            plot_temperature_by_range(start_ts, end_ts, variable)


def section_soil_moisture():
    st.header("Soil Moisture")
    section_last_update("Soil Moisture", "108")

    soil_moisture_metrics_section()

    tab1, tab2, tab3, tab4 = st.tabs(["24h", "Week", "Month", "Custom Range"])

    with tab1:
        plot_soil_moisture(TIME_24H)

    with tab2:
        plot_soil_moisture(TIME_WEEK)

    with tab3:
        plot_soil_moisture(TIME_MONTH)

    with tab4:
        snapshot_date = get_snapshot_date()
        default_start = snapshot_date - timedelta(days=4)

        date_range = st.date_input(
            "Date range",
            value=(default_start, snapshot_date),
            key="soil_custom_date_range",
        )

        if len(date_range) == 2:
            start_date, end_date = date_range
            start_ts = date_to_timestamp(start_date)
            end_ts = date_to_timestamp(end_date, end_of_day=True)

            plot_soil_moisture_by_range(start_ts, end_ts)


    # Soil water deficit
    st.divider()
    st.header("Soil water deficit assessment")



    soil_water_deficit_metrics_section()


    def plot_soil_water_deficit_recent(days, chart_key):
        snapshot_date = get_snapshot_date()
        start_date = snapshot_date - timedelta(days=days)

        start_ts = date_to_timestamp(start_date)
        end_ts = date_to_timestamp(snapshot_date, end_of_day=True)

        plot_soil_water_deficit_by_range(
            start_ts,
            end_ts,
            chart_key=chart_key
        )


    def plot_soil_water_deficit_custom_range():
        snapshot_date = get_snapshot_date()
        default_start = snapshot_date - timedelta(days=7)

        date_range = st.date_input(
            "Soil water deficit date range",
            value=(default_start, snapshot_date),
            key="soil_water_deficit_custom_date_range",
        )

        if len(date_range) == 2:
            start_date, end_date = date_range

            start_ts = date_to_timestamp(start_date)
            end_ts = date_to_timestamp(end_date, end_of_day=True)

            plot_soil_water_deficit_by_range(
                start_ts,
                end_ts,
                chart_key="soil_water_deficit_custom"
            )


    tab1, tab2, tab3, tab4 = st.tabs(["24h", "Week", "Month", "Custom Range"])

    with tab1:
        plot_soil_water_deficit_recent(3, "soil_water_deficit_24h")

    with tab2:
        plot_soil_water_deficit_recent(7, "soil_water_deficit_week")

    with tab3:
        plot_soil_water_deficit_recent(30, "soil_water_deficit_month")

    with tab4:
        plot_soil_water_deficit_custom_range()
        
    
    
def section_rain():
    st.header("Rain data")
    section_last_update("Rain", "299")

    metrics = build_rain_metrics()

    col1, col2, col3, col4 = st.columns(4)

    for col, metric in zip([col1, col2, col3, col4], metrics):
        with col:
            st.metric(metric["label"], metric["value"], metric["delta"], border=True)

    tab1, tab2, tab3, tab4 = st.tabs(["24h", "Week", "Month", "Custom Range"])

    with tab1:
        plot_rain("rainfall_mm", TIME_24H)

    with tab2:
        plot_rain("rainfall_mm", TIME_WEEK)

    with tab3:
        plot_rain("rainfall_mm", TIME_MONTH)

    with tab4:
        snapshot_date = get_snapshot_date()
        default_start = snapshot_date - timedelta(days=7)


        col1, col2 = st.columns(2)

        with col1:
            date_range = st.date_input(
                "Date range",
                value=(default_start, snapshot_date),
                key="rain_custom_date_range",
            )

        with col2:
            variable = st.selectbox(
                "Variable",
                [
                    "rainfall_mm",
                    "rainfall_day_mm",
                    "rainfall_last_15_min_mm",
                    "rainfall_last_60_min_mm",
                    "rain_rate_last_mm",
                    "rain_rate_hi_mm",
                    "rain_rate_hi_last_15_min_mm",
                ],
                key="rain_variable_select",
            )

        if len(date_range) == 2:
            start_date, end_date = date_range
            start_ts = date_to_timestamp(start_date)
            end_ts = date_to_timestamp(end_date, end_of_day=True)

            plot_rain_by_range(start_ts, end_ts, variable)


def section_tabs():
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "⏲ Pressure", 
        ":material/device_thermostat: Temperature", 
        ":material/water_drop: Soil moisture", 
        ":material/rainy: Rain"
    ])

    with tab1:
        section_barometer()
    with tab2:
        section_thermometer()
    with tab3:
        section_soil_moisture()
    with tab4:
        section_rain()










## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::| Page Section Execution |::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
## ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
# st.header("🌦️ IES WeatherLink Dashboard")


def img_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

img_base64 = img_to_base64("static/favicon.ico")

st.markdown(
    f"""
    <h1 style="display:flex; align-items:center; gap:10px;">
        <img src="data:static/png;base64,{img_base64}" width="40">
        IES WeatherLink Dashboard 🌦️
    </h1>
    """,
    unsafe_allow_html=True
)


st.divider()

section_last_update("ISS", "31")
section_header_metrics()

section_tabs()







