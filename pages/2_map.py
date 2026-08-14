from __future__ import annotations

import os

# Prevents an external PostgreSQL/PostGIS PROJ installation
# from overriding the PROJ data bundled with Python geospatial packages.
os.environ.pop("PROJ_DATA", None)
os.environ.pop("PROJ_LIB", None)

import base64
import io
import math
import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import streamlit as st
import plotly.graph_objects as go

from branca.colormap import LinearColormap
from branca.element import Element, MacroElement, Template
from matplotlib.colors import LinearSegmentedColormap, Normalize, to_hex
from PIL import Image
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.transform import array_bounds
from rasterio.warp import (
    Resampling,
    calculate_default_transform,
    reproject,
)
from streamlit_folium import st_folium
from config import (
    FIELD_SHP,
    ET_TIFF_FILES_DIR,
    SM_TIFF_FILES_DIR,
    DB_DIR,
    LATVIA_TZ,
    VRI_ICON, 
)
from environment_cache import (
    CACHE_VERSION,
    get_cached_value,
    make_fingerprint,
    set_cached_value,
)


# ============================================================
# PAGE CONFIGURATION AND CONSTANTS
# ============================================================

if os.environ.get("DHI_PRECOMPUTE_MODE") != "1":
    st.set_page_config(
        page_title="SM, ET and SMD Map",
        page_icon=VRI_ICON,
        layout="wide",
    )

st.sidebar.markdown("Institute for Environmental Solutions")

SM_VMIN = 0.0
SM_VMAX = 100.0

# ET_VMAX=None makes the ET legend use a rounded upper bound
# calculated from the selected ET TIFF. Set a fixed number here,
# for example 8.0, if every ET date must use the same colour scale.
ET_VMIN = 0.0
ET_VMAX: float | None = None

# Common raster values that may represent nodata when the TIFF
# metadata does not declare a nodata value. These are masked before ET is
# used in the deficit calculation.
COMMON_ET_NODATA_VALUES = (
    -99999.0,
    -9999.0,
    -32768.0,
    32767.0,
    65535.0,
    9999.0,
    99999.0,
)

# Values with an absurd floating-point magnitude are treated as nodata.
EXTREME_ET_ABS_LIMIT = 1e20

# Increment this whenever raster values are decoded differently. It is included
# in both overlay and time-series fingerprints so persistent cached raw ET
# values are not reused after a processing change.
RASTER_VALUE_PROCESSING_VERSION = "scale-offset-and-et-nodata-v1"

SMD_VMIN = 0.0
SMD_VMAX: float | None = None

RASTER_OPACITY = 0.80
SMD_RASTER_OPACITY = 1.0
SMD_STYLE_VERSION = "categorical-grid-v2"
TIME_SERIES_PLOT_HEIGHT = 230
PLOT_YEAR_OPTIONS = (2023, 2024, 2025, 2026)


LOW_COLOR = "#ca0020"
MIDDLE_COLOR = "#f2f4f6"
HIGH_COLOR = "#0571b0"

RASTER_COLORMAP = LinearSegmentedColormap.from_list(
    "sm_et_colormap",
    [
        LOW_COLOR,
        MIDDLE_COLOR,
        HIGH_COLOR,
    ],
    N=256,
)

SOIL_WATER_DEFICIT_STATUS = {
    "Wet": "#317bfd",
    "Optimal": "#38ce1b",
    "Moderate deficit": "#f5c542",
    "High deficit": "#FAAE6B",
    "Severe deficit": "#f50000",
}

SMD_STATUS_BANDS = [
    {
        "label": "Wet",
        "minimum": 0.0,
        "maximum": 4.8935,
        "color": SOIL_WATER_DEFICIT_STATUS["Wet"],
        "range_label": "0\u20134.8935 mm",
    },
    {
        "label": "Optimal",
        "minimum": 4.8935,
        "maximum": 14.6653,
        "color": SOIL_WATER_DEFICIT_STATUS["Optimal"],
        "range_label": ">4.8935\u201314.6653 mm",
    },
    {
        "label": "Moderate",
        "minimum": 14.6653,
        "maximum": 29.3229,
        "color": SOIL_WATER_DEFICIT_STATUS["Moderate deficit"],
        "range_label": ">14.6653\u201329.3229 mm",
    },
    {
        "label": "High",
        "minimum": 29.3229,
        "maximum": 48.8665,
        "color": SOIL_WATER_DEFICIT_STATUS["High deficit"],
        "range_label": ">29.3229\u201348.8665 mm",
    },
    {
        "label": "Severe",
        "minimum": 48.8665,
        "maximum": None,
        "color": SOIL_WATER_DEFICIT_STATUS["Severe deficit"],
        "range_label": ">48.8665 mm",
    },
]

DATE_PATTERN = re.compile(r"_(\d{8})_")
DATE_CONTROL_MAGIC_LAT = 89.654321
DATASET_CONTROL_MAGIC_LAT = 89.754321
DATASET_CODES = ("SM", "ET", "SMD")

SECTOR_FIELD = "Sector"
SECTOR_SENSOR_MAP = {
    "S1": "Augsnes sensori #1",
    "S2": "Augsnes sensori #2",
    "S3": "Augsnes sensori #3",
    "S4": "Augsnes sensori #4",
}

DEVICE_COLOR_MAP = {
    "Augsnes sensori #1": "#1f77b4",
    "Augsnes sensori #2": "#ff7f0e",
    "Augsnes sensori #3": "#2ca02c",
    "Augsnes sensori #4": "#d62728",
}

PLOT_FALLBACK_LINE_COLOR = "#7f7f7f"

DEBUG = False


def get_dataset_settings(dataset_code: str) -> dict:
    """Return the display and raster settings for SM, ET or SMD."""
    if dataset_code == "SM":
        return {
            "code": "SM",
            "name": "Soil moisture",
            "short_name": "SM",
            "directory": SM_TIFF_FILES_DIR,
            "band_indexes": [1, 2],
            "unit": "%",
            "decimals": 1,
            "legend_caption": "Soil moisture (%)",
            "tooltip_alias": "Mean soil moisture:",
            "vmin": SM_VMIN,
            "vmax": SM_VMAX,
            "processing_note": "Bands 1 and 2 averaged",
            "reverse_colormap": False,
        }

    if dataset_code == "ET":
        return {
            "code": "ET",
            "name": "Evapotranspiration",
            "short_name": "ET",
            "directory": ET_TIFF_FILES_DIR,
            "band_indexes": [1],
            "unit": "mm/day",
            "decimals": 2,
            "legend_caption": "Evapotranspiration (mm/day)",
            "tooltip_alias": "Mean evapotranspiration:",
            "vmin": ET_VMIN,
            "vmax": ET_VMAX,
            "processing_note": (
                "Band 1 displayed after applying TIFF scale/offset metadata; "
                "no accumulation"
            ),
            "reverse_colormap": False,
        }

    if dataset_code == "SMD":
        return {
            "code": "SMD",
            "name": "Soil moisture deficit",
            "short_name": "SMD",
            "directory": ET_TIFF_FILES_DIR,
            "band_indexes": [1],
            "unit": "mm",
            "decimals": 2,
            "legend_caption": "Soil moisture deficit (mm)",
            "tooltip_alias": "Mean soil moisture deficit:",
            "vmin": SMD_VMIN,
            "vmax": SMD_VMAX,
            "processing_note": (
                "Calendar-year cumulative TSEB ET minus "
                "Sector-matched precipitation on ET dates; missing dates are skipped"
            ),
            "reverse_colormap": False,
            "categorical_colormap": True,
        }

    raise ValueError(f"Unsupported dataset code: {dataset_code}")


# ============================================================
# FILE LOADING
# ============================================================

def get_date_from_filename(file_path: Path) -> date | None:
    """Extract a date stored as _YYYYMMDD_ from a filename."""
    match = DATE_PATTERN.search(file_path.name)

    if match is None:
        return None

    return datetime.strptime(
        match.group(1),
        "%Y%m%d",
    ).date()


@st.cache_data(show_spinner=False)
def find_dated_tiffs(
    tiff_dir: str,
    dataset_code: str,
) -> dict[date, Path]:
    """Find all dated TIFF files in one SM or ET directory."""
    directory = Path(tiff_dir)

    if not directory.exists():
        raise FileNotFoundError(
            f"{dataset_code} TIFF directory does not exist:\n{directory}"
        )

    dated_tiffs: dict[date, Path] = {}

    for file_path in directory.iterdir():
        if not file_path.is_file():
            continue

        if file_path.suffix.lower() not in {".tif", ".tiff"}:
            continue

        file_date = get_date_from_filename(file_path)

        if file_date is None:
            continue

        if file_date in dated_tiffs:
            raise ValueError(
                f"Multiple {dataset_code} TIFF files were found "
                f"for {file_date}:\n"
                f"{dated_tiffs[file_date].name}\n"
                f"{file_path.name}"
            )

        dated_tiffs[file_date] = file_path

    if not dated_tiffs:
        raise FileNotFoundError(
            f"No {dataset_code} TIFF files containing a _YYYYMMDD_ "
            f"date were found in:\n{directory}"
        )

    return dict(sorted(dated_tiffs.items()))


def get_shapefile_signature(
    shapefile_path: Path,
) -> tuple[tuple[str, int], ...]:
    """Track changes to the shapefile and its associated files."""
    suffixes = [
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".cpg",
    ]

    shapefile_parts = [
        shapefile_path.with_suffix(suffix)
        for suffix in suffixes
    ]

    return tuple(
        (
            str(file_path),
            file_path.stat().st_mtime_ns,
        )
        for file_path in shapefile_parts
        if file_path.exists()
    )


@st.cache_data(show_spinner=False)
def load_field_polygons(
    shapefile_path: str,
    shapefile_signature: tuple[tuple[str, int], ...],
) -> gpd.GeoDataFrame:
    """Load and validate the field polygons."""
    del shapefile_signature

    fields = gpd.read_file(shapefile_path)

    if fields.crs is None:
        raise ValueError(
            "The field shapefile has no CRS. "
            "Check that the .prj file exists."
        )

    fields = fields.loc[
        fields.geometry.notna()
        & ~fields.geometry.is_empty
    ].copy()

    if fields.empty:
        raise ValueError(
            "The field shapefile contains no valid geometries."
        )

    return fields


# ============================================================
# RASTER PROCESSING
# ============================================================

def get_nice_upper_bound(value: float) -> float:
    """Round a positive value upward to a readable 1, 2, 5 or 10 step."""
    if not np.isfinite(value) or value <= 0:
        return 1.0

    exponent = math.floor(math.log10(value))
    magnitude = 10 ** exponent
    fraction = value / magnitude

    if fraction <= 1:
        nice_fraction = 1
    elif fraction <= 2:
        nice_fraction = 2
    elif fraction <= 5:
        nice_fraction = 5
    else:
        nice_fraction = 10

    return float(nice_fraction * magnitude)


def array_to_data_url(
    raster_array: np.ndarray,
    vmin: float,
    vmax: float,
    opacity: float = RASTER_OPACITY,
    reverse_colormap: bool = False,
) -> str:
    """Convert a raster array into a transparent PNG data URL."""
    valid_pixels = np.isfinite(raster_array)

    if not valid_pixels.any():
        raise ValueError(
            "No valid raster pixels remain inside the fields."
        )

    values_for_colour = np.where(
        valid_pixels,
        raster_array,
        vmin,
    )

    normalised_values = Normalize(
        vmin=vmin,
        vmax=vmax,
        clip=True,
    )(values_for_colour)

    colormap = (
        SMD_RASTER_COLORMAP
        if reverse_colormap
        else RASTER_COLORMAP
    )

    rgba = np.round(
        colormap(normalised_values) * 255
    ).astype(np.uint8)

    rgba[..., 3] = np.where(
        valid_pixels,
        round(255 * opacity),
        0,
    ).astype(np.uint8)

    image = Image.fromarray(
        rgba,
        mode="RGBA",
    )

    image_buffer = io.BytesIO()
    image.save(
        image_buffer,
        format="PNG",
        optimize=True,
    )

    encoded_image = base64.b64encode(
        image_buffer.getvalue()
    ).decode("utf-8")

    return f"data:image/png;base64,{encoded_image}"


def smd_array_to_data_url(
    raster_array: np.ndarray,
    opacity: float = SMD_RASTER_OPACITY,
) -> str:
    """Convert SMD values to a PNG using fixed status-band colours.

    An all-NaN array produces a fully transparent image. This lets the map
    remain usable and display ``No data`` labels instead of crashing when an
    ET acquisition contains no valid pixels inside the field polygons.
    """
    valid_pixels = np.isfinite(raster_array)

    rgba = np.zeros(
        (*raster_array.shape, 4),
        dtype=np.uint8,
    )

    for band in SMD_STATUS_BANDS:
        lower_bound = band["minimum"]
        upper_bound = band["maximum"]

        if band["label"] == "Wet":
            band_mask = valid_pixels & (raster_array <= upper_bound)
        elif upper_bound is None:
            band_mask = valid_pixels & (raster_array > lower_bound)
        else:
            band_mask = (
                valid_pixels
                & (raster_array > lower_bound)
                & (raster_array <= upper_bound)
            )

        hex_color = band["color"].lstrip("#")
        rgb = tuple(
            int(hex_color[index:index + 2], 16)
            for index in (0, 2, 4)
        )

        rgba[band_mask, 0] = rgb[0]
        rgba[band_mask, 1] = rgb[1]
        rgba[band_mask, 2] = rgb[2]
        rgba[band_mask, 3] = round(255 * opacity)

    image = Image.fromarray(rgba, mode="RGBA")
    image_buffer = io.BytesIO()
    image.save(
        image_buffer,
        format="PNG",
        optimize=True,
    )

    encoded_image = base64.b64encode(
        image_buffer.getvalue()
    ).decode("utf-8")

    return f"data:image/png;base64,{encoded_image}"


class InMapSmdStatusLegend(MacroElement):
    """Add a horizontal SMD legend beside the dataset selector."""

    _template = Template(
        """
        {% macro script(this, kwargs) %}
        (function () {
            const map = {{ this._parent.get_name() }};
            const mapContainer = map.getContainer();

            const legend = L.DomUtil.create(
                "div",
                "smd-status-legend",
                mapContainer
            );

            legend.innerHTML = {{ this.legend_html | tojson }};

            L.DomEvent.disableClickPropagation(legend);
            L.DomEvent.disableScrollPropagation(legend);

            function positionLegend() {
                const toggle = mapContainer.querySelector(
                    ".dataset-toggle-control"
                );

                if (!toggle) {
                    return;
                }

                const legendLeft = (
                    toggle.offsetLeft + toggle.offsetWidth + 10
                );
                const availableWidth = Math.max(
                    260,
                    mapContainer.clientWidth - legendLeft - 10
                );

                legend.style.top = `${toggle.offsetTop}px`;
                legend.style.left = `${legendLeft}px`;
                legend.style.maxWidth = `${availableWidth}px`;
            }

            positionLegend();
            window.addEventListener("resize", positionLegend);
        })();
        {% endmacro %}
        """
    )

    def __init__(self) -> None:
        super().__init__()
        self._name = "InMapSmdStatusLegend"

        legend_items = "".join(
            f"""
            <div class="smd-status-legend-item">
                <span
                    class="smd-status-legend-swatch"
                    style="background:{band['color']};"
                ></span>
                <span class="smd-status-legend-text">
                    <strong>{band['label']}</strong>
                </span>
            </div>
            """
            for band in SMD_STATUS_BANDS
        )

        self.legend_html = (
            '<div class="smd-status-legend-title">'
            'Soil moisture deficit'
            '</div>'
            f'<div class="smd-status-legend-items">{legend_items}</div>'
        )


def add_smd_status_legend(field_map: folium.Map) -> None:
    """Add the horizontal categorical SMD legend to the map."""
    field_map.add_child(InMapSmdStatusLegend())


@st.cache_data(
    show_spinner=False,
    max_entries=100,
)
def prepare_raster_overlay(
    tiff_path: str,
    tiff_mtime_ns: int,
    shapefile_path: str,
    shapefile_signature: tuple[tuple[str, int], ...],
    dataset_code: str,
    force_refresh: bool = False,
) -> dict:
    """
    Process one SM or ET TIFF and calculate a mean for each polygon.

    SM uses the per-pixel average of bands 1 and 2.
    ET uses band 1 after applying the TIFF's scale and offset metadata.
    """
    cache_key = f"{dataset_code}:{Path(tiff_path).name}"
    input_fingerprint = make_fingerprint(
        {
            "version": CACHE_VERSION,
            "raster_value_processing": RASTER_VALUE_PROCESSING_VERSION,
            "dataset": dataset_code,
            "tiff_path": str(Path(tiff_path).resolve()),
            "tiff_mtime_ns": tiff_mtime_ns,
            "tiff_size": Path(tiff_path).stat().st_size,
            "shapefile_signature": shapefile_signature,
        }
    )

    if not force_refresh:
        cached_overlay = get_cached_value(
            "raster_overlay",
            cache_key,
            input_fingerprint,
        )
        if cached_overlay is not None:
            return cached_overlay

    settings = get_dataset_settings(dataset_code)
    band_indexes = settings["band_indexes"]

    fields = load_field_polygons(
        shapefile_path=shapefile_path,
        shapefile_signature=shapefile_signature,
    )

    destination_crs = "EPSG:4326"
    temporary_nodata = -9999.0

    with rasterio.open(tiff_path) as src:
        if src.crs is None:
            raise ValueError(
                f"The {dataset_code} TIFF has no CRS:\n{tiff_path}"
            )

        if src.count < max(band_indexes):
            raise ValueError(
                f"The {dataset_code} TIFF requires raster band(s) "
                f"{band_indexes}, but contains only {src.count} band(s):\n"
                f"{tiff_path}"
            )

        fields_in_raster_crs = fields.to_crs(src.crs)

        field_geometries = [
            geometry.__geo_interface__
            for geometry in fields_in_raster_crs.geometry
        ]

        masked_bands, cropped_transform = mask(
            dataset=src,
            shapes=field_geometries,
            indexes=band_indexes,
            crop=True,
            filled=False,
        )

        band_arrays = [
            np.asarray(masked_band.data, dtype=np.float64)
            for masked_band in masked_bands
        ]

        invalid_pixels = np.zeros(
            band_arrays[0].shape,
            dtype=bool,
        )

        for masked_band, band_array in zip(
            masked_bands,
            band_arrays,
        ):
            invalid_pixels |= np.ma.getmaskarray(masked_band)
            invalid_pixels |= ~np.isfinite(band_array)

        if dataset_code == "SM":
            raster_values = np.mean(
                np.stack(band_arrays, axis=0),
                axis=0,
                dtype=np.float64,
            )
        else:
            raw_et = band_arrays[0]

            # Some ET rasters are stored as scaled integers (for example,
            # 60000 with a scale of 0.0001 represents 6 mm/day). Rasterio
            # exposes that metadata but does not apply it automatically when
            # reading pixel arrays.
            scale = 1.0
            offset = 0.0
            band_position = band_indexes[0] - 1

            if (
                src.scales
                and len(src.scales) > band_position
                and np.isfinite(src.scales[band_position])
            ):
                scale = float(src.scales[band_position])
            if (
                src.offsets
                and len(src.offsets) > band_position
                and np.isfinite(src.offsets[band_position])
            ):
                offset = float(src.offsets[band_position])

            if src.nodata is not None and np.isfinite(src.nodata):
                nodata_atol = max(1e-6, abs(float(src.nodata)) * 1e-7)
                invalid_pixels |= np.isclose(
                    raw_et,
                    float(src.nodata),
                    rtol=0.0,
                    atol=nodata_atol,
                )

            for sentinel in COMMON_ET_NODATA_VALUES:
                invalid_pixels |= np.isclose(
                    raw_et,
                    sentinel,
                    rtol=0.0,
                    atol=1e-6,
                )

            invalid_pixels |= np.abs(raw_et) >= EXTREME_ET_ABS_LIMIT
            raster_values = raw_et * scale + offset
            invalid_pixels |= ~np.isfinite(raster_values) | (raster_values < 0.0)

        raster_values[invalid_pixels] = np.nan

        polygon_means: list[float | None] = []

        for geometry in fields_in_raster_crs.geometry:
            inside_polygon = geometry_mask(
                geometries=[geometry.__geo_interface__],
                out_shape=raster_values.shape,
                transform=cropped_transform,
                invert=True,
            )

            polygon_values = raster_values[
                inside_polygon
                & np.isfinite(raster_values)
            ]

            polygon_means.append(
                float(polygon_values.mean())
                if polygon_values.size > 0
                else None
            )

        source_height, source_width = raster_values.shape

        west, south, east, north = array_bounds(
            source_height,
            source_width,
            cropped_transform,
        )

        (
            destination_transform,
            destination_width,
            destination_height,
        ) = calculate_default_transform(
            src.crs,
            destination_crs,
            source_width,
            source_height,
            west,
            south,
            east,
            north,
        )

        source_data = np.where(
            np.isfinite(raster_values),
            raster_values,
            temporary_nodata,
        ).astype(np.float32)

        destination_data = np.full(
            (
                destination_height,
                destination_width,
            ),
            temporary_nodata,
            dtype=np.float32,
        )

        reproject(
            source=source_data,
            destination=destination_data,
            src_transform=cropped_transform,
            src_crs=src.crs,
            src_nodata=temporary_nodata,
            dst_transform=destination_transform,
            dst_crs=destination_crs,
            dst_nodata=temporary_nodata,
            resampling=Resampling.bilinear,
        )

    destination_data[
        np.isclose(
            destination_data,
            temporary_nodata,
        )
    ] = np.nan

    fields_wgs84 = fields.to_crs(destination_crs)

    inside_fields = geometry_mask(
        geometries=[
            geometry.__geo_interface__
            for geometry in fields_wgs84.geometry
        ],
        out_shape=destination_data.shape,
        transform=destination_transform,
        invert=True,
    )

    destination_data[~inside_fields] = np.nan

    raster_height, raster_width = destination_data.shape

    west, south, east, north = array_bounds(
        raster_height,
        raster_width,
        destination_transform,
    )

    valid_values = destination_data[
        np.isfinite(destination_data)
    ]

    if valid_values.size == 0:
        raise ValueError(
            f"The selected {dataset_code} TIFF contains no valid values "
            "inside the field polygons."
        )

    colour_vmin = float(settings["vmin"])
    configured_vmax = settings["vmax"]

    if configured_vmax is None:
        colour_vmax = get_nice_upper_bound(
            float(valid_values.max())
        )
    else:
        colour_vmax = float(configured_vmax)

    if colour_vmax <= colour_vmin:
        colour_vmax = colour_vmin + 1.0

    valid_polygon_means = np.asarray(
        [
            value
            for value in polygon_means
            if value is not None
        ],
        dtype=float,
    )

    mean_of_polygon_means = (
        float(valid_polygon_means.mean())
        if valid_polygon_means.size > 0
        else None
    )

    overlay = {
        "image_url": array_to_data_url(
            raster_array=destination_data,
            vmin=colour_vmin,
            vmax=colour_vmax,
            reverse_colormap=settings.get("reverse_colormap", False),
        ),
        "bounds": [
            [south, west],
            [north, east],
        ],
        "minimum": float(valid_values.min()),
        "maximum": float(valid_values.max()),
        "mean": float(valid_values.mean()),
        "polygon_means": polygon_means,
        "mean_of_polygon_means": mean_of_polygon_means,
        "legend_vmin": colour_vmin,
        "legend_vmax": colour_vmax,
        "legend_midpoint": (
            colour_vmin + colour_vmax
        ) / 2.0,
    }

    set_cached_value(
        "raster_overlay",
        cache_key,
        input_fingerprint,
        overlay,
    )
    return overlay


@st.cache_data(show_spinner=False, ttl=60)
def fetch_daily_precipitation_by_device(
    db_path: str,
    db_mtime_ns: int,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Return daily precipitation totals separately for each rain sensor.

    The 15-minute rainfall values are summed for each sensor and date.
    Polygon-to-sensor assignment is handled later through the shapefile's
    Sector field.
    """
    del db_mtime_ns

    start_datetime = datetime.combine(
        start_date,
        time.min,
        tzinfo=LATVIA_TZ,
    )
    end_datetime = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=LATVIA_TZ,
    )

    start_ts = int(start_datetime.timestamp())
    end_ts = int(end_datetime.timestamp())

    query = """
        SELECT
            nodes.parent_device_name,
            rain_data.ts,
            rain_data.rainfall_last_15_min_mm
        FROM NODE_rain_DATA rain_data
        JOIN NODES nodes
            ON rain_data.lsid = nodes.lsid
        WHERE rain_data.ts >= ?
          AND rain_data.ts < ?
          AND rain_data.rainfall_last_15_min_mm IS NOT NULL
        ORDER BY rain_data.ts
    """

    with sqlite3.connect(db_path) as connection:
        rainfall = pd.read_sql_query(
            query,
            connection,
            params=(start_ts, end_ts),
        )

    if rainfall.empty:
        return pd.DataFrame(
            columns=[
                "parent_device_name",
                "date",
                "precip_mm",
            ]
        )

    rainfall["date"] = [
        datetime.fromtimestamp(
            int(timestamp),
            tz=timezone.utc,
        ).astimezone(LATVIA_TZ).date()
        for timestamp in rainfall["ts"]
    ]

    rainfall["rainfall_last_15_min_mm"] = (
        pd.to_numeric(
            rainfall["rainfall_last_15_min_mm"],
            errors="coerce",
        )
        .fillna(0.0)
        .clip(lower=0.0)
    )

    return (
        rainfall
        .groupby(
            ["parent_device_name", "date"],
            as_index=False,
        )["rainfall_last_15_min_mm"]
        .sum()
        .rename(
            columns={"rainfall_last_15_min_mm": "precip_mm"}
        )
        .sort_values(["parent_device_name", "date"])
    )


def get_precipitation_input_signature(
    db_path: str,
    start_date: date,
    end_date: date,
) -> str:
    """Fingerprint only the rain records that can affect the requested dates."""
    start_datetime = datetime.combine(
        start_date,
        time.min,
        tzinfo=LATVIA_TZ,
    )
    end_datetime = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=LATVIA_TZ,
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*),
                MAX(rain_data.ts),
                SUM(CAST(rain_data.rainfall_last_15_min_mm AS REAL))
            FROM NODE_rain_DATA rain_data
            JOIN NODES nodes
                ON rain_data.lsid = nodes.lsid
            WHERE rain_data.ts >= ?
              AND rain_data.ts < ?
              AND rain_data.rainfall_last_15_min_mm IS NOT NULL
            """,
            (
                int(start_datetime.timestamp()),
                int(end_datetime.timestamp()),
            ),
        ).fetchone()

    return make_fingerprint(
        {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "row_count": row[0],
            "latest_ts": row[1],
            "rainfall_sum": row[2],
        }
    )


def complete_daily_precipitation_without_fallback(
    precipitation: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Create one direct precipitation value per mapped sensor and date.

    No cross-sensor or zero-rain fallback is applied. If the mapped sensor
    has no precipitation record for a date, ``precip_mm`` remains NaN. Since
    SMD is cumulative, a missing precipitation day makes that sector's SMD
    unknown from that interval onward within the selected calendar year.
    """
    all_dates = [
        timestamp.date()
        for timestamp in pd.date_range(
            start=start_date,
            end=end_date,
            freq="D",
        )
    ]
    sensor_names = list(SECTOR_SENSOR_MAP.values())

    complete_grid = pd.MultiIndex.from_product(
        [sensor_names, all_dates],
        names=["parent_device_name", "date"],
    ).to_frame(index=False)

    observed = precipitation.copy()
    if observed.empty:
        observed = pd.DataFrame(
            columns=[
                "parent_device_name",
                "date",
                "precip_mm",
            ]
        )

    observed["precip_mm"] = pd.to_numeric(
        observed.get("precip_mm"),
        errors="coerce",
    )

    complete = complete_grid.merge(
        observed[
            ["parent_device_name", "date", "precip_mm"]
        ],
        on=["parent_device_name", "date"],
        how="left",
    )

    complete["precip_mm"] = complete["precip_mm"].clip(lower=0.0)
    complete["precip_source"] = np.where(
        complete["precip_mm"].notna(),
        "mapped sensor",
        "missing mapped-sensor data",
    )

    return complete


def normalise_and_validate_sectors(
    fields: gpd.GeoDataFrame,
) -> list[str]:
    """Return normalised sector values and validate their sensor mapping."""
    if SECTOR_FIELD not in fields.columns:
        raise ValueError(
            f"The field shapefile must contain a '{SECTOR_FIELD}' column "
            "for the SMD precipitation assignment."
        )

    sectors = (
        fields[SECTOR_FIELD]
        .astype("string")
        .str.strip()
        .str.upper()
    )

    missing_sector_rows = sectors.isna() | sectors.eq("")
    if missing_sector_rows.any():
        missing_count = int(missing_sector_rows.sum())
        raise ValueError(
            f"{missing_count} polygon(s) have no value in the "
            f"'{SECTOR_FIELD}' field."
        )

    unsupported_sectors = sorted(
        set(sectors.tolist()) - set(SECTOR_SENSOR_MAP)
    )
    if unsupported_sectors:
        raise ValueError(
            "Unsupported Sector value(s) in the shapefile: "
            + ", ".join(unsupported_sectors)
            + ". Expected S1, S2, S3 or S4."
        )

    return sectors.tolist()


def build_polygon_sensor_masks(
    fields: gpd.GeoDataFrame,
    sectors: list[str],
    reference_crs,
    reference_shape: tuple[int, int],
    reference_transform,
) -> list[tuple[np.ndarray, str, str]]:
    """Build one raster mask and mapped sensor name per polygon."""
    fields_in_reference_crs = fields.to_crs(reference_crs)

    return [
        (
            geometry_mask(
                geometries=[geometry.__geo_interface__],
                out_shape=reference_shape,
                transform=reference_transform,
                invert=True,
            ),
            sector,
            SECTOR_SENSOR_MAP[sector],
        )
        for geometry, sector in zip(
            fields_in_reference_crs.geometry,
            sectors,
        )
    ]


def build_sector_precipitation_raster(
    polygon_sensor_masks: list[tuple[np.ndarray, str, str]],
    precipitation_lookup: dict[tuple[str, date], float],
    interval_dates: list[date],
    reference_shape: tuple[int, int],
) -> np.ndarray:
    """Assign direct mapped-sensor precipitation to each polygon.

    An interval total is valid only when the mapped sensor has a value for
    every day in the interval. One missing day makes that sector's interval
    precipitation NaN, preventing an unsupported SMD estimate.
    """
    precipitation_raster = np.full(
        reference_shape,
        np.nan,
        dtype=np.float32,
    )

    sensor_interval_totals: dict[str, float] = {}

    for sensor_name in SECTOR_SENSOR_MAP.values():
        daily_values = np.asarray(
            [
                precipitation_lookup.get(
                    (sensor_name, interval_date),
                    np.nan,
                )
                for interval_date in interval_dates
            ],
            dtype=float,
        )

        sensor_interval_totals[sensor_name] = (
            float(daily_values.sum())
            if daily_values.size > 0 and np.isfinite(daily_values).all()
            else np.nan
        )

    for polygon_mask, _, sensor_name in polygon_sensor_masks:
        precipitation_raster[polygon_mask] = (
            sensor_interval_totals[sensor_name]
        )

    return precipitation_raster


def read_et_raster_on_reference_grid(
    tiff_path: str,
    fields: gpd.GeoDataFrame,
    reference_shape: tuple[int, int] | None = None,
    reference_transform=None,
    reference_crs=None,
) -> tuple[np.ndarray, object, object, dict]:
    """Read and clip ET band 1, optionally aligning it to a reference grid.

    Raster masks, declared nodata values, common undeclared sentinel values,
    non-finite values and negative ET values are excluded. No arbitrary upper
    ET threshold is applied because that can erase an otherwise valid raster.
    Band scale and offset metadata are applied when present.
    """
    temporary_nodata = -9999.0

    with rasterio.open(tiff_path) as src:
        if src.crs is None:
            raise ValueError(f"The ET TIFF has no CRS:\n{tiff_path}")

        fields_in_raster_crs = fields.to_crs(src.crs)
        field_geometries = [
            geometry.__geo_interface__
            for geometry in fields_in_raster_crs.geometry
        ]

        masked_et, clipped_transform = mask(
            dataset=src,
            shapes=field_geometries,
            indexes=[1],
            crop=True,
            filled=False,
        )

        raw_et = np.asarray(
            masked_et[0].data,
            dtype=np.float64,
        )
        geometry_or_dataset_mask = np.ma.getmaskarray(masked_et[0])

        raw_inside = raw_et[
            ~geometry_or_dataset_mask & np.isfinite(raw_et)
        ]

        invalid_pixels = (
            geometry_or_dataset_mask
            | ~np.isfinite(raw_et)
            | (np.abs(raw_et) >= EXTREME_ET_ABS_LIMIT)
        )

        if src.nodata is not None and np.isfinite(src.nodata):
            nodata_atol = max(1e-6, abs(float(src.nodata)) * 1e-7)
            invalid_pixels |= np.isclose(
                raw_et,
                float(src.nodata),
                rtol=0.0,
                atol=nodata_atol,
            )

        for sentinel in COMMON_ET_NODATA_VALUES:
            invalid_pixels |= np.isclose(
                raw_et,
                sentinel,
                rtol=0.0,
                atol=1e-6,
            )

        scale = 1.0
        offset = 0.0

        if src.scales and np.isfinite(src.scales[0]):
            scale = float(src.scales[0])
        if src.offsets and np.isfinite(src.offsets[0]):
            offset = float(src.offsets[0])

        et_array = raw_et * scale + offset
        invalid_pixels |= ~np.isfinite(et_array) | (et_array < 0.0)
        et_array[invalid_pixels] = np.nan
        et_array = et_array.astype(np.float32)

        valid_before_alignment = et_array[np.isfinite(et_array)]
        diagnostics = {
            "filename": Path(tiff_path).name,
            "declared_nodata": (
                None if src.nodata is None else float(src.nodata)
            ),
            "scale": scale,
            "offset": offset,
            "raw_min": (
                float(raw_inside.min()) if raw_inside.size else None
            ),
            "raw_max": (
                float(raw_inside.max()) if raw_inside.size else None
            ),
            "valid_min": (
                float(valid_before_alignment.min())
                if valid_before_alignment.size
                else None
            ),
            "valid_max": (
                float(valid_before_alignment.max())
                if valid_before_alignment.size
                else None
            ),
            "valid_pixel_count": int(valid_before_alignment.size),
        }

        if reference_shape is None:
            return et_array, clipped_transform, src.crs, diagnostics

        same_grid = (
            et_array.shape == reference_shape
            and clipped_transform == reference_transform
            and src.crs == reference_crs
        )

        if same_grid:
            return et_array, reference_transform, reference_crs, diagnostics

        source_data = np.where(
            np.isfinite(et_array),
            et_array,
            temporary_nodata,
        ).astype(np.float32)

        aligned_et = np.full(
            reference_shape,
            temporary_nodata,
            dtype=np.float32,
        )

        reproject(
            source=source_data,
            destination=aligned_et,
            src_transform=clipped_transform,
            src_crs=src.crs,
            src_nodata=temporary_nodata,
            dst_transform=reference_transform,
            dst_crs=reference_crs,
            dst_nodata=temporary_nodata,
            resampling=Resampling.bilinear,
        )

    aligned_et[np.isclose(aligned_et, temporary_nodata)] = np.nan
    diagnostics["valid_pixel_count_after_alignment"] = int(
        np.isfinite(aligned_et).sum()
    )
    return aligned_et, reference_transform, reference_crs, diagnostics


@st.cache_data(
    show_spinner=False,
    max_entries=30,
)
def prepare_smd_overlay(
    et_tiff_records: tuple[tuple[str, str, int], ...],
    selected_date_iso: str,
    shapefile_path: str,
    shapefile_signature: tuple[tuple[str, int], ...],
    db_path: str,
    db_mtime_ns: int,
    style_version: str,
    force_refresh: bool = False,
) -> dict:
    """
    Build a spatial cumulative soil moisture deficit raster.

    Acquisition-date update:
        SMD = max(0, previous SMD + ET - Sector-matched precipitation)

    Each polygon receives precipitation only from the sensor mapped through
    its Sector value. No precipitation fallback is used. When precipitation
    is missing on a TSEB acquisition date, that date is shown as No data for
    the affected sector and the cumulative state is left unchanged. A later
    acquisition with measured precipitation can therefore continue from the
    last valid state. No ET or precipitation is interpolated across missing
    calendar dates.

    ``style_version`` is included in the cache key so changes to categorical
    colours regenerate the rendered SMD PNG instead of reusing stale pixels.
    """
    selected_date = date.fromisoformat(selected_date_iso)
    calculation_year = selected_date.year
    selected_records = [
        record
        for record in et_tiff_records
        if (
            date.fromisoformat(record[0]).year == calculation_year
            and date.fromisoformat(record[0]) <= selected_date
        )
    ]

    if not selected_records:
        raise ValueError(
            f"No ET TIFF is available in {calculation_year} on or before "
            f"{selected_date}."
        )

    first_date = date.fromisoformat(selected_records[0][0])
    precipitation_signature = get_precipitation_input_signature(
        db_path=db_path,
        start_date=first_date,
        end_date=selected_date,
    )
    cache_key = f"SMD:{selected_date_iso}"
    input_fingerprint = make_fingerprint(
        {
            "version": CACHE_VERSION,
            "style_version": style_version,
            "selected_records": selected_records,
            "shapefile_signature": shapefile_signature,
            "precipitation_signature": precipitation_signature,
        }
    )

    if not force_refresh:
        cached_overlay = get_cached_value(
            "smd_overlay",
            cache_key,
            input_fingerprint,
        )
        if cached_overlay is not None:
            return cached_overlay

    fields = load_field_polygons(
        shapefile_path=shapefile_path,
        shapefile_signature=shapefile_signature,
    )
    sectors = normalise_and_validate_sectors(fields)

    observed_precipitation = fetch_daily_precipitation_by_device(
        db_path=db_path,
        db_mtime_ns=db_mtime_ns,
        start_date=first_date,
        end_date=selected_date,
    )
    precipitation = complete_daily_precipitation_without_fallback(
        precipitation=observed_precipitation,
        start_date=first_date,
        end_date=selected_date,
    )

    precipitation_lookup = {
        (row.parent_device_name, row.date): float(row.precip_mm)
        for row in precipitation.itertuples(index=False)
    }

    smd_array = None
    smd_state = None
    reference_transform = None
    reference_crs = None
    reference_shape = None
    polygon_sensor_masks = None
    first_valid_et_date = None
    last_valid_et_date = None
    skipped_et_dates: list[date] = []
    missing_precipitation_dates: dict[str, list[date]] = {
        sector: [] for sector in SECTOR_SENSOR_MAP
    }
    et_diagnostics: list[dict] = []

    records_to_process = selected_records
    if len(selected_records) > 1 and not force_refresh:
        previous_records = selected_records[:-1]
        previous_date = date.fromisoformat(previous_records[-1][0])
        previous_precipitation_signature = get_precipitation_input_signature(
            db_path=db_path,
            start_date=first_date,
            end_date=previous_date,
        )
        previous_fingerprint = make_fingerprint(
            {
                "version": CACHE_VERSION,
                "style_version": style_version,
                "selected_records": previous_records,
                "shapefile_signature": shapefile_signature,
                "precipitation_signature": previous_precipitation_signature,
            }
        )
        previous_state = get_cached_value(
            "smd_state",
            f"SMD:{previous_date.isoformat()}",
            previous_fingerprint,
        )

        if previous_state is not None:
            smd_state = previous_state["smd_state"]
            reference_transform = previous_state["reference_transform"]
            reference_crs = previous_state["reference_crs"]
            reference_shape = tuple(previous_state["reference_shape"])
            first_valid_et_date = previous_state["first_valid_et_date"]
            last_valid_et_date = previous_state["last_valid_et_date"]
            skipped_et_dates = list(previous_state["skipped_et_dates"])
            missing_precipitation_dates = {
                sector: list(dates)
                for sector, dates in previous_state[
                    "missing_precipitation_dates"
                ].items()
            }
            et_diagnostics = list(previous_state["et_diagnostics"])
            polygon_sensor_masks = build_polygon_sensor_masks(
                fields=fields,
                sectors=sectors,
                reference_crs=reference_crs,
                reference_shape=reference_shape,
                reference_transform=reference_transform,
            )
            records_to_process = selected_records[-1:]

    for date_iso, tiff_path, _ in records_to_process:
        current_date = date.fromisoformat(date_iso)

        current_et, current_transform, current_crs, current_diagnostics = (
            read_et_raster_on_reference_grid(
                tiff_path=tiff_path,
                fields=fields,
                reference_shape=reference_shape,
                reference_transform=reference_transform,
                reference_crs=reference_crs,
            )
        )

        current_diagnostics["date"] = current_date.isoformat()
        et_diagnostics.append(current_diagnostics)

        if reference_shape is None:
            reference_shape = current_et.shape
            reference_transform = current_transform
            reference_crs = current_crs
            polygon_sensor_masks = build_polygon_sensor_masks(
                fields=fields,
                sectors=sectors,
                reference_crs=reference_crs,
                reference_shape=reference_shape,
                reference_transform=reference_transform,
            )
            smd_state = np.zeros(
                reference_shape,
                dtype=np.float32,
            )

        if not np.isfinite(current_et).any():
            skipped_et_dates.append(current_date)
            smd_array = np.full(
                reference_shape,
                np.nan,
                dtype=np.float32,
            )
            continue

        if first_valid_et_date is None:
            first_valid_et_date = current_date
        last_valid_et_date = current_date

        precipitation_raster = build_sector_precipitation_raster(
            polygon_sensor_masks=polygon_sensor_masks,
            precipitation_lookup=precipitation_lookup,
            interval_dates=[current_date],
            reference_shape=reference_shape,
        )

        for sector, sensor_name in SECTOR_SENSOR_MAP.items():
            precipitation_value = precipitation_lookup.get(
                (sensor_name, current_date),
                np.nan,
            )
            if not np.isfinite(precipitation_value):
                missing_precipitation_dates[sector].append(current_date)

        valid_pixels = (
            np.isfinite(current_et)
            & np.isfinite(precipitation_raster)
        )

        updated_state = smd_state.copy()
        updated_state[valid_pixels] = np.maximum(
            0.0,
            smd_state[valid_pixels]
            + current_et[valid_pixels]
            - precipitation_raster[valid_pixels],
        )
        smd_state = updated_state.astype(np.float32)

        # The selected acquisition displays No data where either ET or the
        # mapped precipitation sensor is missing. The internal cumulative
        # state is preserved there so later measured dates can continue from
        # the last valid estimate instead of being poisoned for the year.
        smd_array = np.where(
            valid_pixels,
            smd_state,
            np.nan,
        ).astype(np.float32)

    if smd_array is None:
        # No ET acquisition could be evaluated. Keep the map alive with a
        # transparent raster and explicit No data labels rather than raising
        # an exception.
        smd_array = np.full(
            reference_shape,
            np.nan,
            dtype=np.float32,
        )

    settings = get_dataset_settings("SMD")
    destination_crs = "EPSG:4326"
    temporary_nodata = -9999.0

    fields_in_reference_crs = fields.to_crs(reference_crs)
    polygon_means: list[float | None] = []

    for geometry in fields_in_reference_crs.geometry:
        inside_polygon = geometry_mask(
            geometries=[geometry.__geo_interface__],
            out_shape=smd_array.shape,
            transform=reference_transform,
            invert=True,
        )

        polygon_values = smd_array[
            inside_polygon & np.isfinite(smd_array)
        ]
        polygon_means.append(
            float(polygon_values.mean())
            if polygon_values.size > 0
            else None
        )

    source_height, source_width = smd_array.shape
    west, south, east, north = array_bounds(
        source_height,
        source_width,
        reference_transform,
    )

    (
        destination_transform,
        destination_width,
        destination_height,
    ) = calculate_default_transform(
        reference_crs,
        destination_crs,
        source_width,
        source_height,
        west,
        south,
        east,
        north,
    )

    source_data = np.where(
        np.isfinite(smd_array),
        smd_array,
        temporary_nodata,
    ).astype(np.float32)
    destination_data = np.full(
        (destination_height, destination_width),
        temporary_nodata,
        dtype=np.float32,
    )

    reproject(
        source=source_data,
        destination=destination_data,
        src_transform=reference_transform,
        src_crs=reference_crs,
        src_nodata=temporary_nodata,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=temporary_nodata,
        resampling=Resampling.bilinear,
    )

    destination_data[
        np.isclose(destination_data, temporary_nodata)
    ] = np.nan

    fields_wgs84 = fields.to_crs(destination_crs)
    inside_fields = geometry_mask(
        geometries=[
            geometry.__geo_interface__
            for geometry in fields_wgs84.geometry
        ],
        out_shape=destination_data.shape,
        transform=destination_transform,
        invert=True,
    )
    destination_data[~inside_fields] = np.nan

    raster_height, raster_width = destination_data.shape
    west, south, east, north = array_bounds(
        raster_height,
        raster_width,
        destination_transform,
    )

    valid_values = destination_data[np.isfinite(destination_data)]
    has_valid_smd = valid_values.size > 0

    colour_vmin = float(settings["vmin"])
    configured_vmax = settings["vmax"]
    colour_vmax = (
        get_nice_upper_bound(float(valid_values.max()))
        if has_valid_smd and configured_vmax is None
        else (
            float(configured_vmax)
            if configured_vmax is not None
            else 100.0
        )
    )
    if colour_vmax <= colour_vmin:
        colour_vmax = colour_vmin + 1.0

    valid_polygon_means = np.asarray(
        [value for value in polygon_means if value is not None],
        dtype=float,
    )

    calculation_start_date = first_valid_et_date or first_date
    calculation_end_date = last_valid_et_date or selected_date
    acquisition_dates = [
        date.fromisoformat(record[0])
        for record in selected_records
        if date.fromisoformat(record[0]) not in skipped_et_dates
    ]
    expected_acquisition_dates = len(acquisition_dates)
    precipitation_summaries = []

    for sector, sensor_name in SECTOR_SENSOR_MAP.items():
        measured_values = [
            precipitation_lookup.get((sensor_name, acquisition_date), np.nan)
            for acquisition_date in acquisition_dates
        ]
        measured_values = np.asarray(measured_values, dtype=float)
        measured_count = int(np.isfinite(measured_values).sum())
        missing_count = expected_acquisition_dates - measured_count
        total_precipitation = float(np.nansum(measured_values))
        total_text = (
            f"{total_precipitation:.2f} mm"
            if measured_count > 0
            else "no measured dates"
        )
        precipitation_summaries.append(
            f"{sector}: {total_text}; measured ET dates "
            f"{measured_count}/{expected_acquisition_dates}, "
            f"missing {missing_count}"
        )

    precipitation_note = (
        "Direct sector-sensor precipitation on ET acquisition dates only; "
        "missing dates are skipped without changing cumulative SMD; no fallback; "
        + " | ".join(precipitation_summaries)
    )

    overlay = {
        "image_url": smd_array_to_data_url(
            raster_array=destination_data,
        ),
        "bounds": [[south, west], [north, east]],
        "minimum": float(valid_values.min()) if has_valid_smd else None,
        "maximum": float(valid_values.max()) if has_valid_smd else None,
        "mean": float(valid_values.mean()) if has_valid_smd else None,
        "polygon_means": polygon_means,
        "mean_of_polygon_means": (
            float(valid_polygon_means.mean())
            if valid_polygon_means.size > 0
            else None
        ),
        "legend_vmin": colour_vmin,
        "legend_vmax": colour_vmax,
        "legend_midpoint": (colour_vmin + colour_vmax) / 2.0,
        "processing_note": (
            (
                f"{calculation_year} acquisition-date cumulative deficit from "
                f"{calculation_start_date:%Y-%m-%d} through "
                f"{calculation_end_date:%Y-%m-%d}; resets for each calendar year; "
                f"skipped ET acquisitions with no valid pixels: "
                f"{', '.join(d.isoformat() for d in skipped_et_dates) if skipped_et_dates else 'none'}; "
            )
            if has_valid_smd
            else (
                f"No usable ET pixels were found inside the fields for "
                f"{calculation_year} through {selected_date:%Y-%m-%d}. "
                f"The map is shown without an SMD raster instead of crashing. "
                f"ET diagnostics: "
                + " | ".join(
                    f"{item['date']} {item['filename']}: "
                    f"raw={item['raw_min']}..{item['raw_max']}, "
                    f"nodata={item['declared_nodata']}, "
                    f"scale={item['scale']}, offset={item['offset']}"
                    for item in et_diagnostics
                )
                + "; "
            )
        )
        + precipitation_note,
    }

    set_cached_value(
        "smd_overlay",
        cache_key,
        input_fingerprint,
        overlay,
    )
    set_cached_value(
        "smd_state",
        cache_key,
        input_fingerprint,
        {
            "smd_state": smd_state,
            "reference_transform": reference_transform,
            "reference_crs": reference_crs,
            "reference_shape": reference_shape,
            "first_valid_et_date": first_valid_et_date,
            "last_valid_et_date": last_valid_et_date,
            "skipped_et_dates": skipped_et_dates,
            "missing_precipitation_dates": missing_precipitation_dates,
            "et_diagnostics": et_diagnostics,
        },
    )
    return overlay


# ============================================================
# IN-MAP CONTROLS
# ============================================================

class InMapDateControl(MacroElement):
    """Add a date slider and previous/next buttons inside the map."""

    _template = Template(
        """
        {% macro script(this, kwargs) %}
        (function () {
        const map = {{ this._parent.get_name() }};
        const dates = {{ this.available_dates | tojson }};
        const magicLatitude = {{ this.magic_latitude }};
        let selectedIndex = {{ this.selected_index }};

        const control = L.DomUtil.create(
            "div",
            "sm-date-control",
            map.getContainer()
        );

        control.innerHTML = `
            <div class="sm-date-title">
                Selected date:
                <strong class="sm-date-value"></strong>
            </div>
            <div class="sm-date-controls-row">
                <input
                    class="sm-date-slider"
                    type="range"
                    min="0"
                    max="${dates.length - 1}"
                    step="1"
                    value="${selectedIndex}"
                    aria-label="Raster date"
                >
                <button
                    class="sm-date-button sm-date-previous"
                    type="button"
                    title="Previous available date"
                >◀</button>
                <button
                    class="sm-date-button sm-date-next"
                    type="button"
                    title="Next available date"
                >▶</button>
            </div>
        `;

        L.DomEvent.disableClickPropagation(control);
        L.DomEvent.disableScrollPropagation(control);

        const slider = control.querySelector(".sm-date-slider");
        const dateValue = control.querySelector(".sm-date-value");
        const previousButton = control.querySelector(
            ".sm-date-previous"
        );
        const nextButton = control.querySelector(
            ".sm-date-next"
        );

        function updateControl(index) {
            selectedIndex = Math.max(
                0,
                Math.min(index, dates.length - 1)
            );

            slider.value = selectedIndex;
            dateValue.textContent = dates[selectedIndex];
            previousButton.disabled = selectedIndex === 0;
            nextButton.disabled = (
                selectedIndex === dates.length - 1
            );
        }

        function requestDate(index) {
            updateControl(index);

            map.fire("click", {
                latlng: L.latLng(
                    magicLatitude,
                    selectedIndex
                )
            });
        }

        slider.addEventListener("input", function () {
            updateControl(Number(slider.value));
        });

        slider.addEventListener("change", function () {
            requestDate(Number(slider.value));
        });

        previousButton.addEventListener("click", function () {
            requestDate(selectedIndex - 1);
        });

        nextButton.addEventListener("click", function () {
            requestDate(selectedIndex + 1);
        });

        updateControl(selectedIndex);
        })();
        {% endmacro %}
        """
    )

    def __init__(
        self,
        available_dates: tuple[date, ...],
        selected_index: int,
    ) -> None:
        super().__init__()
        self._name = "InMapDateControl"
        self.available_dates = [
            available_date.strftime("%Y-%m-%d")
            for available_date in available_dates
        ]
        self.selected_index = selected_index
        self.magic_latitude = DATE_CONTROL_MAGIC_LAT


class InMapDatasetControl(MacroElement):
    """Add the SM/ET/SMD dataset selector to the top-left of the map."""

    _template = Template(
        """
        {% macro script(this, kwargs) %}
        (function () {
        const map = {{ this._parent.get_name() }};
        const selectedDataset = {{ this.selected_dataset | tojson }};
        const magicLatitude = {{ this.magic_latitude }};

        const control = L.DomUtil.create(
            "div",
            "dataset-toggle-control",
            map.getContainer()
        );

        control.innerHTML = `
            <button
                class="dataset-toggle-button"
                data-dataset="SM"
                type="button"
                title="Show soil moisture"
            >SM</button>
            <button
                class="dataset-toggle-button"
                data-dataset="ET"
                type="button"
                title="Show evapotranspiration"
            >ET</button>
            <button
                class="dataset-toggle-button"
                data-dataset="SMD"
                type="button"
                title="Show soil moisture deficit"
            >SMD</button>
        `;

        L.DomEvent.disableClickPropagation(control);
        L.DomEvent.disableScrollPropagation(control);

        const buttons = control.querySelectorAll(
            ".dataset-toggle-button"
        );

        buttons.forEach(function (button) {
            const dataset = button.dataset.dataset;
            button.classList.toggle(
                "active",
                dataset === selectedDataset
            );

            button.addEventListener("click", function () {
                if (dataset === selectedDataset) {
                    return;
                }

                const datasetIndex = ["SM", "ET", "SMD"].indexOf(dataset);

                map.fire("click", {
                    latlng: L.latLng(
                        magicLatitude,
                        datasetIndex
                    )
                });
            });
        });
        })();
        {% endmacro %}
        """
    )

    def __init__(self, selected_dataset: str) -> None:
        super().__init__()
        self._name = "InMapDatasetControl"
        self.selected_dataset = selected_dataset
        self.magic_latitude = DATASET_CONTROL_MAGIC_LAT


# ============================================================
# MAP CREATION
# ============================================================

def add_map_css(field_map: folium.Map) -> None:
    """Add styling for labels, date controls and the SM/ET toggle."""
    field_map.get_root().header.add_child(
        Element(
            """
            <style>
                .sm-div-icon {
                    background: transparent !important;
                    border: none !important;
                }

                .sm-polygon-label {
                    transform: translate(-50%, -50%);
                    width: max-content;
                    padding: 3px 7px;
                    border: 1px solid rgba(255, 255, 255, 0.9);
                    border-radius: 5px;
                    background: rgba(0, 0, 0, 0.72);
                    color: #ffffff;
                    font-size: 12px;
                    font-weight: 700;
                    line-height: 1.2;
                    text-align: center;
                    white-space: nowrap;
                    pointer-events: none;
                    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.45);
                }

                .sm-date-control {
                    position: absolute;
                    left: 50%;
                    bottom: 18px;
                    z-index: 1000;
                    width: min(560px, calc(100% - 28px));
                    box-sizing: border-box;
                    transform: translateX(-50%);
                    padding: 9px 11px 10px;
                    border: 1px solid rgba(255, 255, 255, 0.16);
                    border-radius: 9px;
                    background: rgba(17, 24, 39, 0.76);
                    box-shadow: 0 3px 14px rgba(0, 0, 0, 0.42);
                    color: #f9fafb;
                    font-family: Arial, sans-serif;
                    backdrop-filter: blur(8px);
                    -webkit-backdrop-filter: blur(8px);
                }

                .sm-date-title {
                    margin-bottom: 6px;
                    color: rgba(249, 250, 251, 0.88);
                    font-size: 13px;
                    text-align: center;
                }

                .sm-date-value {
                    color: #ffffff;
                    font-weight: 700;
                }

                .sm-date-controls-row {
                    display: flex;
                    align-items: center;
                    gap: 7px;
                }

                .sm-date-slider {
                    flex: 1 1 auto;
                    min-width: 100px;
                    height: 5px;
                    border-radius: 999px;
                    background: rgba(255, 255, 255, 0.24);
                    cursor: pointer;
                    appearance: none;
                    -webkit-appearance: none;
                }

                .sm-date-slider::-webkit-slider-runnable-track {
                    height: 5px;
                    border-radius: 999px;
                    background: rgba(255, 255, 255, 0.24);
                }

                .sm-date-slider::-webkit-slider-thumb {
                    width: 16px;
                    height: 16px;
                    margin-top: -5.5px;
                    border: 2px solid rgba(255, 255, 255, 0.85);
                    border-radius: 50%;
                    background: #4b9cff;
                    box-shadow: 0 1px 5px rgba(0, 0, 0, 0.45);
                    cursor: pointer;
                    appearance: none;
                    -webkit-appearance: none;
                }

                .sm-date-slider::-moz-range-track {
                    height: 5px;
                    border-radius: 999px;
                    background: rgba(255, 255, 255, 0.24);
                }

                .sm-date-slider::-moz-range-thumb {
                    width: 16px;
                    height: 16px;
                    border: 2px solid rgba(255, 255, 255, 0.85);
                    border-radius: 50%;
                    background: #4b9cff;
                    box-shadow: 0 1px 5px rgba(0, 0, 0, 0.45);
                    cursor: pointer;
                }

                .sm-date-button {
                    flex: 0 0 38px;
                    height: 30px;
                    border: 1px solid rgba(255, 255, 255, 0.18);
                    border-radius: 6px;
                    background: rgba(31, 41, 55, 0.78);
                    color: #f9fafb;
                    font-size: 14px;
                    cursor: pointer;
                    transition:
                        background 0.15s ease,
                        border-color 0.15s ease;
                }

                .sm-date-button:hover:not(:disabled) {
                    border-color: rgba(255, 255, 255, 0.32);
                    background: rgba(55, 65, 81, 0.95);
                }

                .sm-date-button:disabled {
                    cursor: default;
                    opacity: 0.36;
                }

                .dataset-toggle-control {
                    position: absolute;
                    top: 10px;
                    left: 50px;
                    right: auto;
                    z-index: 1000;
                    padding: 3px;
                    border: 1px solid rgba(255, 255, 255, 0.18);
                    border-radius: 8px;
                    background: rgba(17, 24, 39, 0.76);
                    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.38);
                    backdrop-filter: blur(8px);
                    -webkit-backdrop-filter: blur(8px);
                }

                .dataset-toggle-button {
                    min-width: 43px;
                    height: 32px;
                    padding: 0 11px;
                    border: 0;
                    border-radius: 5px;
                    background: transparent;
                    color: rgba(249, 250, 251, 0.72);
                    font-size: 13px;
                    font-weight: 700;
                    cursor: pointer;
                    transition:
                        background 0.15s ease,
                        color 0.15s ease;
                }

                .dataset-toggle-button:hover {
                    background: rgba(255, 255, 255, 0.10);
                    color: #ffffff;
                }

                .dataset-toggle-button.active {
                    background: rgba(75, 156, 255, 0.92);
                    color: #ffffff;
                    box-shadow: 0 1px 5px rgba(0, 0, 0, 0.30);
                }


                .smd-status-legend {
                    position: absolute;
                    z-index: 1000;
                    width: auto;
                    box-sizing: border-box;
                    padding: 6px 8px;
                    border: 1px solid rgba(255, 255, 255, 0.18);
                    border-radius: 8px;
                    background: rgba(17, 24, 39, 0.84);
                    color: #ffffff;
                    font-family: Arial, sans-serif;
                    font-size: 10px;
                    line-height: 1.15;
                    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.38);
                    backdrop-filter: blur(8px);
                    -webkit-backdrop-filter: blur(8px);
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    white-space: nowrap;
                }

                .smd-status-legend-title {
                    margin-bottom: 0;
                    font-size: 11px;
                    font-weight: 700;
                    text-align: left;
                    white-space: nowrap;
                    flex: 0 0 auto;
                }

                .smd-status-legend-items {
                    display: flex;
                    flex-wrap: nowrap;
                    align-items: center;
                    gap: 8px;
                }

                .smd-status-legend-item {
                    display: flex;
                    min-width: 0;
                    align-items: center;
                    gap: 5px;
                }

                .smd-status-legend-swatch {
                    display: inline-block;
                    flex: 0 0 14px;
                    width: 14px;
                    height: 14px;
                    border: 1px solid rgba(255, 255, 255, 0.82);
                    border-radius: 2px;
                    box-sizing: border-box;
                }

                .smd-status-legend-text {
                    display: inline-flex;
                    min-width: 0;
                    white-space: nowrap;
                }

                .smd-status-legend-text strong {
                    font-size: 10px;
                    line-height: 1.1;
                }

                .smd-status-legend-text span {
                    display: none;
                }
            </style>
            """
        )
    )


def format_raster_value(
    value: float | None,
    unit: str,
    decimals: int,
) -> str:
    """Format a polygon mean for its map label."""
    if value is None:
        return "No data"

    if unit == "%":
        return f"{value:.{decimals}f}%"

    return f"{value:.{decimals}f} {unit}"


def add_sensor_points(
    field_map: folium.Map,
    fields_wgs84: gpd.GeoDataFrame,
) -> None:
    """Add one sensor marker for each sector."""

    required_columns = {
        SECTOR_FIELD,
        "Latitude",
        "Longitude",
    }

    missing_columns = required_columns - set(fields_wgs84.columns)

    if missing_columns:
        raise ValueError(
            "Missing sensor coordinate fields: "
            + ", ".join(sorted(missing_columns))
        )

    sensor_points = fields_wgs84[
        [SECTOR_FIELD, "Latitude", "Longitude"]
    ].copy()

    sensor_points["Latitude"] = pd.to_numeric(
        sensor_points["Latitude"],
        errors="coerce",
    )

    sensor_points["Longitude"] = pd.to_numeric(
        sensor_points["Longitude"],
        errors="coerce",
    )

    sensor_points = (
        sensor_points
        .dropna(subset=["Latitude", "Longitude"])
        .drop_duplicates(subset=[SECTOR_FIELD])
    )

    for sensor in sensor_points.itertuples(index=False):
        sector = getattr(sensor, SECTOR_FIELD)
        device_name = SECTOR_SENSOR_MAP.get(
            sector,
            sector,
        )
        marker_color = DEVICE_COLOR_MAP.get(
            device_name,
            PLOT_FALLBACK_LINE_COLOR,
        )

        folium.CircleMarker(
            location=[
                sensor.Latitude,
                sensor.Longitude,
            ],
            radius=5,
            color="#ffffff",
            weight=2,
            fill=True,
            fill_color=marker_color,
            fill_opacity=0.8,
            tooltip=folium.Tooltip(
                f"{device_name}<br>"
                f"Sector: {sector}<br>"
                f"Latitude: {sensor.Latitude:.6f}<br>"
                f"Longitude: {sensor.Longitude:.6f}",
                sticky=False,
            ),
        ).add_to(field_map)

def create_environment_map(
    fields_wgs84: gpd.GeoDataFrame,
    raster_overlay: dict,
    dataset_code: str,
    available_dates: tuple[date, ...],
    selected_date: date,
) -> folium.Map:
    """Create the Folium map for the selected SM, ET or SMD raster."""
    settings = get_dataset_settings(dataset_code)

    min_x, min_y, max_x, max_y = (
        fields_wgs84.total_bounds
    )

    map_center = [
        (min_y + max_y) / 2,
        (min_x + max_x) / 2,
    ]

    field_map = folium.Map(
        location=map_center,
        tiles=None,
        zoom_control=True,
        control_scale=True,
        prefer_canvas=True,
    )

    add_map_css(field_map)

    folium.TileLayer(
        tiles=(
            "https://mt1.google.com/vt/"
            "lyrs=s&x={x}&y={y}&z={z}"
        ),
        attr="Google",
        name="Google Satellite",
        overlay=False,
        control=False,
        max_zoom=22,
    ).add_to(field_map)

    folium.raster_layers.ImageOverlay(
        image=raster_overlay["image_url"],
        bounds=raster_overlay["bounds"],
        name=(
            f"{settings['name']} "
            f"{selected_date:%Y-%m-%d}"
        ),
        opacity=1.0,
        interactive=False,
        zindex=1,
    ).add_to(field_map)

    polygon_labels = [
        format_raster_value(
            value=polygon_mean,
            unit=settings["unit"],
            decimals=settings["decimals"],
        )
        for polygon_mean in raster_overlay["polygon_means"]
    ]

    fields_for_map = fields_wgs84.copy()
    fields_for_map["mean_value"] = polygon_labels

    folium.GeoJson(
        data=fields_for_map.__geo_interface__,
        name="Field boundaries",
        style_function=lambda feature: {
            "color": "#ffffff",
            "weight": 2,
            "fillColor": "#ffffff",
            "fillOpacity": 0.0,
        },
        highlight_function=lambda feature: {
            "color": "#ffff00",
            "weight": 4,
            "fillOpacity": 0.05,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["mean_value"],
            aliases=[settings["tooltip_alias"]],
            sticky=False,
        ),
    ).add_to(field_map)

    label_points = (
        fields_wgs84.geometry
        .representative_point()
    )

    for label_point, polygon_label in zip(
        label_points,
        polygon_labels,
    ):
        folium.Marker(
            location=[
                label_point.y,
                label_point.x,
            ],
            icon=folium.DivIcon(
                html=(
                    '<div class="sm-polygon-label">'
                    f"{polygon_label}"
                    "</div>"
                ),
                class_name="sm-div-icon",
                icon_size=(0, 0),
                icon_anchor=(0, 0),
            ),
        ).add_to(field_map)

    # Add the physical sensor locations
    add_sensor_points(
        field_map=field_map,
        fields_wgs84=fields_wgs84,
    )

    if dataset_code == "SMD":
        add_smd_status_legend(field_map)
    else:
        legend_colors = (
            [HIGH_COLOR, MIDDLE_COLOR, LOW_COLOR]
            if settings.get("reverse_colormap", False)
            else [LOW_COLOR, MIDDLE_COLOR, HIGH_COLOR]
        )

        legend = LinearColormap(
            colors=legend_colors,
            index=[
                raster_overlay["legend_vmin"],
                raster_overlay["legend_midpoint"],
                raster_overlay["legend_vmax"],
            ],
            vmin=raster_overlay["legend_vmin"],
            vmax=raster_overlay["legend_vmax"],
            caption=settings["legend_caption"],
        )

        legend.add_to(field_map)

    field_map.get_root().html.add_child(
        folium.Element(
            """
            <style>
            .legend text {
                fill: #ffffff !important;
                color: #ffffff !important;
                text-shadow:
                    0 1px 2px rgba(0, 0, 0, 0.95),
                    0 0 3px rgba(0, 0, 0, 0.85);
            }
            </style>
            """
        )
    )

    selected_index = available_dates.index(
        selected_date
    )

    field_map.add_child(
        InMapDateControl(
            available_dates=available_dates,
            selected_index=selected_index,
        )
    )

    field_map.add_child(
        InMapDatasetControl(
            selected_dataset=dataset_code,
        )
    )

    field_map.fit_bounds(
        [
            [min_y, min_x],
            [max_y, max_x],
        ],
        padding=(20, 20),
    )

    return field_map


# ============================================================
# DATASET TIME-SERIES PLOT
# ============================================================

def get_polygon_display_names(fields: gpd.GeoDataFrame) -> list[str]:
    """Return compact hover labels for polygon time-series traces."""
    preferred_columns = [
        "Name", "name", "Field", "field", "ID", "Id", "id", "FID", "fid",
    ]

    for column in preferred_columns:
        if column not in fields.columns:
            continue

        values = fields[column].astype("string").fillna("").str.strip()
        if values.ne("").any():
            return [
                value if value else f"Polygon {index + 1}"
                for index, value in enumerate(values.tolist())
            ]

    if SECTOR_FIELD in fields.columns:
        sectors = (
            fields[SECTOR_FIELD]
            .astype("string")
            .fillna("")
            .str.strip()
            .str.upper()
            .tolist()
        )
        return [
            f"Polygon {index + 1} ({sector})" if sector else f"Polygon {index + 1}"
            for index, sector in enumerate(sectors)
        ]

    return [f"Polygon {index + 1}" for index in range(len(fields))]


def get_polygon_plot_metadata(fields: gpd.GeoDataFrame) -> list[dict]:
    """Return polygon labels plus sector/sensor colours for time-series traces."""
    polygon_names = get_polygon_display_names(fields)

    if SECTOR_FIELD in fields.columns:
        sectors = (
            fields[SECTOR_FIELD]
            .astype("string")
            .fillna("")
            .str.strip()
            .str.upper()
            .tolist()
        )
    else:
        sectors = [""] * len(fields)

    metadata: list[dict] = []
    for index, polygon_name in enumerate(polygon_names):
        sector = sectors[index] if index < len(sectors) else ""
        sensor_name = SECTOR_SENSOR_MAP.get(sector, "")
        line_color = DEVICE_COLOR_MAP.get(
            sensor_name,
            PLOT_FALLBACK_LINE_COLOR,
        )

        metadata.append(
            {
                "polygon_index": index,
                "polygon": polygon_name,
                "sector": sector,
                "sensor": sensor_name,
                "line_color": line_color,
            }
        )

    return metadata


def get_sensor_point_metadata(fields: gpd.GeoDataFrame) -> list[dict]:
    """Return one validated sensor location for each mapped sector."""
    required_columns = {SECTOR_FIELD, "Latitude", "Longitude"}
    missing_columns = required_columns - set(fields.columns)

    if missing_columns:
        raise ValueError(
            "The field shapefile is missing sensor coordinate field(s): "
            + ", ".join(sorted(missing_columns))
        )

    points = fields[[SECTOR_FIELD, "Latitude", "Longitude"]].copy()
    points[SECTOR_FIELD] = (
        points[SECTOR_FIELD]
        .astype("string")
        .str.strip()
        .str.upper()
    )
    points["Latitude"] = pd.to_numeric(points["Latitude"], errors="coerce")
    points["Longitude"] = pd.to_numeric(points["Longitude"], errors="coerce")
    points = points.dropna(
        subset=[SECTOR_FIELD, "Latitude", "Longitude"]
    )
    points = points[points[SECTOR_FIELD].isin(SECTOR_SENSOR_MAP)]

    conflicting_sectors = []
    for sector, subset in points.groupby(SECTOR_FIELD):
        unique_coordinates = subset[["Latitude", "Longitude"]].drop_duplicates()
        if len(unique_coordinates) > 1:
            conflicting_sectors.append(str(sector))

    if conflicting_sectors:
        raise ValueError(
            "Multiple sensor coordinates were found for sector(s): "
            + ", ".join(sorted(conflicting_sectors))
        )

    points = points.drop_duplicates(subset=[SECTOR_FIELD]).set_index(SECTOR_FIELD)

    missing_sectors = [
        sector for sector in SECTOR_SENSOR_MAP if sector not in points.index
    ]
    if missing_sectors:
        raise ValueError(
            "No valid sensor coordinates were found for sector(s): "
            + ", ".join(missing_sectors)
        )

    metadata = []
    for point_index, (sector, sensor_name) in enumerate(SECTOR_SENSOR_MAP.items()):
        point = points.loc[sector]
        metadata.append(
            {
                "point_index": point_index,
                "sector": sector,
                "sensor": sensor_name,
                "latitude": float(point["Latitude"]),
                "longitude": float(point["Longitude"]),
                "line_color": DEVICE_COLOR_MAP.get(
                    sensor_name,
                    PLOT_FALLBACK_LINE_COLOR,
                ),
            }
        )

    return metadata


@st.cache_data(show_spinner=False, max_entries=200)
def sample_raster_at_sensor_points(
    tiff_path: str,
    tiff_mtime_ns: int,
    dataset_code: str,
    sensor_metadata: tuple[tuple, ...],
) -> tuple[float | None, ...]:
    """Sample the raster cell containing each sensor coordinate."""
    del tiff_mtime_ns
    settings = get_dataset_settings(dataset_code)
    band_indexes = settings["band_indexes"]

    points_wgs84 = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(
            [point[4] for point in sensor_metadata],
            [point[3] for point in sensor_metadata],
        ),
        crs="EPSG:4326",
    )

    with rasterio.open(tiff_path) as src:
        if src.crs is None:
            raise ValueError(
                f"The {dataset_code} TIFF has no CRS:\n{tiff_path}"
            )
        if src.count < max(band_indexes):
            raise ValueError(
                f"The {dataset_code} TIFF requires band(s) {band_indexes}, "
                f"but contains only {src.count}:\n{tiff_path}"
            )

        points_in_raster_crs = points_wgs84.to_crs(src.crs)
        coordinates = [
            (geometry.x, geometry.y)
            for geometry in points_in_raster_crs.geometry
        ]
        samples = list(
            src.sample(
                coordinates,
                indexes=band_indexes,
                masked=True,
            )
        )

        scale = 1.0
        offset = 0.0
        declared_nodata = src.nodata
        if dataset_code == "ET":
            if src.scales and np.isfinite(src.scales[0]):
                scale = float(src.scales[0])
            if src.offsets and np.isfinite(src.offsets[0]):
                offset = float(src.offsets[0])

    point_values: list[float | None] = []
    for sample in samples:
        values = np.ma.asarray(sample, dtype=np.float64)
        if np.ma.getmaskarray(values).any():
            point_values.append(None)
            continue

        values = np.asarray(values, dtype=np.float64)
        if not np.isfinite(values).all():
            point_values.append(None)
            continue

        if dataset_code == "SM":
            point_value = float(values.mean())
        else:
            raw_point_value = float(values[0])
            is_common_nodata = any(
                np.isclose(raw_point_value, sentinel, rtol=0.0, atol=1e-6)
                for sentinel in COMMON_ET_NODATA_VALUES
            )
            is_declared_nodata = (
                declared_nodata is not None
                and np.isfinite(declared_nodata)
                and np.isclose(
                    raw_point_value,
                    float(declared_nodata),
                    rtol=0.0,
                    atol=max(1e-6, abs(float(declared_nodata)) * 1e-7),
                )
            )
            point_value = float(raw_point_value * scale + offset)
            if (
                is_common_nodata
                or is_declared_nodata
                or abs(raw_point_value) >= EXTREME_ET_ABS_LIMIT
                or abs(point_value) >= EXTREME_ET_ABS_LIMIT
                or point_value < 0.0
            ):
                point_values.append(None)
                continue

        point_values.append(point_value)

    return tuple(point_values)


@st.cache_data(show_spinner=False, max_entries=30)
def build_sensor_point_time_series(
    dataset_code: str,
    tiff_records: tuple[tuple[str, str, int], ...],
    sensor_metadata: tuple[tuple, ...],
    db_path: str,
    db_mtime_ns: int,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Build a time series from the raster cell at each sensor location."""
    if not tiff_records:
        return pd.DataFrame()

    record_dates = [date.fromisoformat(record[0]) for record in tiff_records]
    precipitation_signature = None
    if dataset_code == "SMD":
        precipitation_signature = get_precipitation_input_signature(
            db_path=db_path,
            start_date=min(record_dates),
            end_date=max(record_dates),
        )

    cache_key = f"{dataset_code}:{record_dates[0].year}:sensor_point"
    input_fingerprint = make_fingerprint(
        {
            "version": CACHE_VERSION,
            "raster_value_processing": RASTER_VALUE_PROCESSING_VERSION,
            "dataset": dataset_code,
            "tiff_records": tiff_records,
            "sensor_metadata": sensor_metadata,
            "precipitation_signature": precipitation_signature,
        }
    )

    if not force_refresh:
        cached_df = get_cached_value(
            "time_series",
            cache_key,
            input_fingerprint,
        )
        if cached_df is not None:
            return cached_df

    rows: list[dict] = []
    point_values_by_date: dict[date, tuple[float | None, ...]] = {}

    for date_iso, tiff_path, tiff_mtime_ns in tiff_records:
        acquisition_date = date.fromisoformat(date_iso)
        point_values_by_date[acquisition_date] = sample_raster_at_sensor_points(
            tiff_path=tiff_path,
            tiff_mtime_ns=tiff_mtime_ns,
            dataset_code="ET" if dataset_code == "SMD" else dataset_code,
            sensor_metadata=sensor_metadata,
        )

    precipitation_lookup: dict[tuple[str, date], float] = {}
    cumulative_smd = {
        point[1]: 0.0 for point in sensor_metadata
    }

    if dataset_code == "SMD":
        acquisition_dates = sorted(point_values_by_date)
        observed_precipitation = fetch_daily_precipitation_by_device(
            db_path=db_path,
            db_mtime_ns=db_mtime_ns,
            start_date=acquisition_dates[0],
            end_date=acquisition_dates[-1],
        )
        precipitation = complete_daily_precipitation_without_fallback(
            precipitation=observed_precipitation,
            start_date=acquisition_dates[0],
            end_date=acquisition_dates[-1],
        )
        precipitation_lookup = {
            (row.parent_device_name, row.date): float(row.precip_mm)
            for row in precipitation.itertuples(index=False)
        }

    for acquisition_date in sorted(point_values_by_date):
        sampled_values = point_values_by_date[acquisition_date]

        for point, sampled_value in zip(sensor_metadata, sampled_values):
            point_index, sector, sensor_name, latitude, longitude, line_color = point
            value = sampled_value

            if dataset_code == "SMD":
                precipitation_value = precipitation_lookup.get(
                    (sensor_name, acquisition_date),
                    np.nan,
                )
                if sampled_value is None or not np.isfinite(precipitation_value):
                    value = None
                else:
                    cumulative_smd[sector] = max(
                        0.0,
                        cumulative_smd[sector]
                        + float(sampled_value)
                        - float(precipitation_value),
                    )
                    value = cumulative_smd[sector]

            rows.append(
                {
                    "date": acquisition_date,
                    "polygon_index": point_index,
                    "polygon": sensor_name,
                    "sector": sector,
                    "sensor": sensor_name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "line_color": line_color,
                    "value": value,
                }
            )

    point_df = pd.DataFrame(rows)
    if point_df.empty:
        return point_df

    point_df["date"] = pd.to_datetime(point_df["date"])
    point_df["value"] = pd.to_numeric(point_df["value"], errors="coerce")
    point_df = point_df.sort_values(["polygon_index", "date"])
    set_cached_value(
        "time_series",
        cache_key,
        input_fingerprint,
        point_df,
    )
    return point_df


def initialise_selected_plot_year() -> int:
    """Initialise the year selector used by the time-series plot."""
    state_key = "selected_plot_year"

    if (
        state_key not in st.session_state
        or st.session_state[state_key] not in PLOT_YEAR_OPTIONS
    ):
        st.session_state[state_key] = max(PLOT_YEAR_OPTIONS)

    return int(st.session_state[state_key])


def render_plot_year_selector() -> int:
    """Render a compact year selector directly below the map."""
    selected_year = initialise_selected_plot_year()
    selector_column, _ = st.columns([0.14, 0.86])

    with selector_column:
        selected_year = st.selectbox(
            "Year",
            options=list(PLOT_YEAR_OPTIONS),
            index=list(PLOT_YEAR_OPTIONS).index(selected_year),
            key="selected_plot_year",
        )

    return int(selected_year)


def get_plot_dates(
    dataset_code: str,
    available_dates: tuple[date, ...],
    selected_year: int,
) -> tuple[date, ...]:
    """Return only acquisition dates from the user-selected plot year."""
    del dataset_code

    return tuple(
        available_date
        for available_date in available_dates
        if available_date.year == selected_year
    )


def build_dataset_time_series(
    dataset_code: str,
    tiff_records: tuple[tuple[str, str, int], ...],
    plot_dates: tuple[date, ...],
    polygon_metadata: tuple[dict, ...],
    shapefile_path: str,
    shapefile_signature: tuple[tuple[str, int], ...],
    db_path: str,
    db_mtime_ns: int,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Build one polygon-mean value per available dataset date."""
    if not plot_dates:
        return pd.DataFrame(
            columns=[
                "date",
                "polygon_index",
                "polygon",
                "sector",
                "sensor",
                "line_color",
                "value",
            ]
        )

    precipitation_signature = None
    if dataset_code == "SMD":
        precipitation_signature = get_precipitation_input_signature(
            db_path=db_path,
            start_date=min(plot_dates),
            end_date=max(plot_dates),
        )

    cache_key = f"{dataset_code}:{plot_dates[0].year}:polygon"
    input_fingerprint = make_fingerprint(
        {
            "version": CACHE_VERSION,
            "raster_value_processing": RASTER_VALUE_PROCESSING_VERSION,
            "dataset": dataset_code,
            "tiff_records": tiff_records,
            "plot_dates": plot_dates,
            "polygon_metadata": polygon_metadata,
            "shapefile_signature": shapefile_signature,
            "precipitation_signature": precipitation_signature,
        }
    )

    if not force_refresh:
        cached_df = get_cached_value(
            "time_series",
            cache_key,
            input_fingerprint,
        )
        if cached_df is not None:
            return cached_df

    rows: list[dict] = []
    tiff_lookup = {
        date.fromisoformat(date_iso): (tiff_path, tiff_mtime_ns)
        for date_iso, tiff_path, tiff_mtime_ns in tiff_records
    }

    if dataset_code == "SMD":
        smd_records_by_year = tuple(
            record
            for record in tiff_records
            if date.fromisoformat(record[0]).year == plot_dates[0].year
        )

        for plot_date in plot_dates:
            overlay = prepare_smd_overlay(
                et_tiff_records=smd_records_by_year,
                selected_date_iso=plot_date.isoformat(),
                shapefile_path=shapefile_path,
                shapefile_signature=shapefile_signature,
                db_path=db_path,
                db_mtime_ns=db_mtime_ns,
                style_version=SMD_STYLE_VERSION,
            )

            for polygon_info, polygon_mean in zip(
                polygon_metadata,
                overlay["polygon_means"],
            ):
                rows.append(
                    {
                        "date": plot_date,
                        "polygon_index": polygon_info["polygon_index"],
                        "polygon": polygon_info["polygon"],
                        "sector": polygon_info["sector"],
                        "sensor": polygon_info["sensor"],
                        "line_color": polygon_info["line_color"],
                        "value": polygon_mean,
                    }
                )
    else:
        for plot_date in plot_dates:
            tiff_info = tiff_lookup.get(plot_date)
            if tiff_info is None:
                polygon_means = [None] * len(polygon_metadata)
            else:
                tiff_path, tiff_mtime_ns = tiff_info
                try:
                    overlay = prepare_raster_overlay(
                        tiff_path=tiff_path,
                        tiff_mtime_ns=tiff_mtime_ns,
                        shapefile_path=shapefile_path,
                        shapefile_signature=shapefile_signature,
                        dataset_code=dataset_code,
                    )
                    polygon_means = overlay["polygon_means"]
                except ValueError:
                    polygon_means = [None] * len(polygon_metadata)

            for polygon_info, polygon_mean in zip(
                polygon_metadata,
                polygon_means,
            ):
                rows.append(
                    {
                        "date": plot_date,
                        "polygon_index": polygon_info["polygon_index"],
                        "polygon": polygon_info["polygon"],
                        "sector": polygon_info["sector"],
                        "sensor": polygon_info["sensor"],
                        "line_color": polygon_info["line_color"],
                        "value": polygon_mean,
                    }
                )

    plot_df = pd.DataFrame(rows)
    if plot_df.empty:
        set_cached_value(
            "time_series",
            cache_key,
            input_fingerprint,
            plot_df,
        )
        return plot_df

    plot_df["date"] = pd.to_datetime(plot_df["date"])
    plot_df["value"] = pd.to_numeric(plot_df["value"], errors="coerce")
    plot_df = plot_df.sort_values(["polygon_index", "date"])
    set_cached_value(
        "time_series",
        cache_key,
        input_fingerprint,
        plot_df,
    )
    return plot_df


def get_plot_y_range(values: pd.Series, dataset_code: str) -> tuple[float, float]:
    """Zoom the y-axis to the observed line values with a small pad."""
    finite_values = pd.to_numeric(values, errors="coerce").dropna()

    if finite_values.empty:
        settings = get_dataset_settings(dataset_code)
        y_min = float(settings["vmin"])
        configured_vmax = settings["vmax"]
        y_max = float(configured_vmax) if configured_vmax is not None else y_min + 1.0
        return y_min, max(y_max, y_min + 1.0)

    observed_min = float(finite_values.min())
    observed_max = float(finite_values.max())

    if np.isclose(observed_min, observed_max):
        padding = max(abs(observed_max) * 0.05, 0.25)
    else:
        padding = (observed_max - observed_min) * 0.08

    y_min = observed_min - padding
    y_max = observed_max + padding

    if dataset_code in {"ET", "SMD"}:
        y_min = max(0.0, y_min)
    elif dataset_code == "SM":
        y_min = max(0.0, y_min)
        y_max = min(100.0, y_max)

    if y_max <= y_min:
        y_max = y_min + max(abs(y_min) * 0.05, 1.0)

    return y_min, y_max


def get_plot_colour_scale_range(
    values: pd.Series,
    dataset_code: str,
    y_max: float,
) -> tuple[float, float]:
    """Return the value scale used to colour SM/ET plot backgrounds."""
    settings = get_dataset_settings(dataset_code)
    colour_vmin = float(settings["vmin"])
    configured_vmax = settings["vmax"]

    if configured_vmax is not None:
        colour_vmax = float(configured_vmax)
    else:
        finite_values = pd.to_numeric(values, errors="coerce").dropna()
        observed_max = float(finite_values.max()) if not finite_values.empty else y_max
        colour_vmax = get_nice_upper_bound(max(observed_max, y_max, colour_vmin + 1.0))

    if colour_vmax <= colour_vmin:
        colour_vmax = colour_vmin + 1.0

    return colour_vmin, colour_vmax


def get_plot_season_x_range(plot_df: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Use the first and last finite data date as the plot season window."""
    if plot_df.empty or "value" not in plot_df.columns:
        return None

    valid_dates = (
        plot_df.loc[plot_df["value"].notna(), "date"]
        .dropna()
        .sort_values()
    )

    if valid_dates.empty:
        return None

    season_start = pd.Timestamp(valid_dates.iloc[0])
    season_end = pd.Timestamp(valid_dates.iloc[-1])

    if season_start == season_end:
        pad = pd.Timedelta(days=3)
        return season_start - pad, season_end + pad

    return season_start, season_end


def add_dataset_plot_background(
    fig: go.Figure,
    dataset_code: str,
    y_min: float,
    y_max: float,
    values: pd.Series,
) -> None:
    """Colour the plot background using the map colour logic."""
    if y_max <= y_min:
        return

    if dataset_code == "SMD":
        for band in SMD_STATUS_BANDS:
            band_min = float(band["minimum"])
            band_max = y_max if band["maximum"] is None else float(band["maximum"])
            y0 = max(y_min, band_min)
            y1 = min(y_max, band_max)
            if y1 <= y0:
                continue
            fig.add_hrect(
                y0=y0,
                y1=y1,
                fillcolor=band["color"],
                opacity=0.18,
                line_width=0,
                layer="below",
            )
        return

    colour_vmin, colour_vmax = get_plot_colour_scale_range(
        values=values,
        dataset_code=dataset_code,
        y_max=y_max,
    )

    normalizer = Normalize(vmin=colour_vmin, vmax=colour_vmax, clip=True)
    steps = 48
    for step_index in range(steps):
        fraction_0 = step_index / steps
        fraction_1 = (step_index + 1) / steps
        y0 = y_min + (y_max - y_min) * fraction_0
        y1 = y_min + (y_max - y_min) * fraction_1
        y_mid = (y0 + y1) / 2.0
        fig.add_hrect(
            y0=y0,
            y1=y1,
            fillcolor=to_hex(RASTER_COLORMAP(normalizer(y_mid))),
            opacity=0.16,
            line_width=0,
            layer="below",
        )


def create_dataset_time_series_figure(
    plot_df: pd.DataFrame,
    dataset_code: str,
    selected_date: date,
    selected_year: int,
) -> go.Figure:
    """Create a compact Plotly line chart below the map."""
    settings = get_dataset_settings(dataset_code)
    unit = settings["unit"]
    decimals = settings["decimals"]
    values = plot_df.get("value", pd.Series(dtype=float))
    y_min, y_max = get_plot_y_range(values, dataset_code)
    season_x_range = get_plot_season_x_range(plot_df)

    fig = go.Figure()
    add_dataset_plot_background(
        fig=fig,
        dataset_code=dataset_code,
        y_min=y_min,
        y_max=y_max,
        values=values,
    )

    if not plot_df.empty:
        for _, subset in plot_df.groupby("polygon_index", sort=False):
            if subset["value"].notna().sum() == 0:
                continue

            polygon_name = str(subset["polygon"].iloc[0])
            sector = str(subset["sector"].iloc[0] or "")
            sensor_name = str(subset["sensor"].iloc[0] or "Unmapped sensor")
            line_color = str(
                subset["line_color"].iloc[0]
                or PLOT_FALLBACK_LINE_COLOR
            )

            fig.add_trace(
                go.Scatter(
                    x=subset["date"],
                    y=subset["value"],
                    mode="lines+markers",
                    name=polygon_name,
                    connectgaps=False,
                    marker={
                        "size": 5,
                        "color": line_color,
                    },
                    line={
                        "width": 1.6,
                        "color": line_color,
                    },
                    hovertemplate=(
                        f"{polygon_name}<br>"
                        f"Sector: {sector if sector else 'N/A'}<br>"
                        f"Sensor: {sensor_name}<br>"
                        "%{x|%Y-%m-%d}<br>"
                        f"%{{y:.{decimals}f}} {unit}"
                        "<extra></extra>"
                    ),
                )
            )

    if selected_date.year == selected_year:
        fig.add_vline(
            x=pd.Timestamp(selected_date),
            line_width=1,
            line_dash="dot",
        )

    fig.update_layout(
        height=TIME_SERIES_PLOT_HEIGHT + 58,
        margin={"l": 48, "r": 16, "t": 62, "b": 34},
        showlegend=True,
        legend={
            "title": {"text": "Click to show/hide"},
            "orientation": "h",
            "x": 0,
            "xanchor": "left",
            "y": 1.02,
            "yanchor": "bottom",
            "itemclick": "toggle",
            "itemdoubleclick": "toggleothers",
        },
        hovermode="closest",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(
        title_text=None,
        showgrid=True,
        gridcolor="rgba(128,128,128,0.25)",
        tickformat="%b %-d\n%Y",
        hoverformat="%Y-%m-%d",
        range=list(season_x_range) if season_x_range is not None else None,
    )
    fig.update_yaxes(
        title_text=unit,
        range=[y_min, y_max],
        showgrid=True,
        gridcolor="rgba(128,128,128,0.25)",
        zeroline=False,
    )

    return fig

def render_dataset_time_series_plot(
    dataset_code: str,
    available_dates: tuple[date, ...],
    selected_date: date,
    selected_year: int,
    selected_tiffs: dict[date, Path],
    fields: gpd.GeoDataFrame,
    shapefile_signature: tuple[tuple[str, int], ...],
    db_path: str,
    db_mtime_ns: int,
) -> None:
    """Render the selected dataset's polygon-mean time series below the map."""
    plot_dates = get_plot_dates(
        dataset_code=dataset_code,
        available_dates=available_dates,
        selected_year=selected_year,
    )

    if not plot_dates:
        st.caption(f"No {dataset_code} acquisition dates found for {selected_year}.")
        return

    tiff_records = tuple(
        (available_date.isoformat(), str(file_path), file_path.stat().st_mtime_ns)
        for available_date, file_path in selected_tiffs.items()
        if available_date in plot_dates
    )
    if not tiff_records:
        st.caption(f"No {dataset_code} TIFF records found for {selected_year}.")
        return

    polygon_metadata = tuple(get_polygon_plot_metadata(fields))
    plot_df = build_dataset_time_series(
        dataset_code=dataset_code,
        tiff_records=tiff_records,
        plot_dates=plot_dates,
        polygon_metadata=polygon_metadata,
        shapefile_path=str(FIELD_SHP),
        shapefile_signature=shapefile_signature,
        db_path=db_path,
        db_mtime_ns=db_mtime_ns,
    )

    if plot_df.empty or plot_df["value"].notna().sum() == 0:
        st.caption(f"No valid {dataset_code} polygon values found for {selected_year}.")
        return

    figure = create_dataset_time_series_figure(
        plot_df=plot_df,
        dataset_code=dataset_code,
        selected_date=selected_date,
        selected_year=selected_year,
    )

    st.markdown(
        """
        <style>
        div[data-testid="stPlotlyChart"] {
            margin-top: -0.9rem;
        }
        div[data-testid="stSelectbox"] {
            margin-top: -0.65rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})


def render_sensor_point_time_series_plot(
    dataset_code: str,
    available_dates: tuple[date, ...],
    selected_date: date,
    selected_year: int,
    selected_tiffs: dict[date, Path],
    fields: gpd.GeoDataFrame,
    db_path: str,
    db_mtime_ns: int,
) -> None:
    """Render values sampled at the four physical sensor locations."""
    plot_dates = get_plot_dates(
        dataset_code=dataset_code,
        available_dates=available_dates,
        selected_year=selected_year,
    )

    if not plot_dates:
        st.caption(
            f"No {dataset_code} acquisition dates found for {selected_year}."
        )
        return

    tiff_records = tuple(
        (
            available_date.isoformat(),
            str(file_path),
            file_path.stat().st_mtime_ns,
        )
        for available_date, file_path in selected_tiffs.items()
        if available_date in plot_dates
    )

    point_metadata = get_sensor_point_metadata(fields)
    serialised_metadata = tuple(
        (
            point["point_index"],
            point["sector"],
            point["sensor"],
            point["latitude"],
            point["longitude"],
            point["line_color"],
        )
        for point in point_metadata
    )

    point_df = build_sensor_point_time_series(
        dataset_code=dataset_code,
        tiff_records=tiff_records,
        sensor_metadata=serialised_metadata,
        db_path=db_path,
        db_mtime_ns=db_mtime_ns,
    )

    if point_df.empty or point_df["value"].notna().sum() == 0:
        st.caption(
            f"No valid {dataset_code} values were found at the sensor "
            f"locations for {selected_year}."
        )
        return


    figure = create_dataset_time_series_figure(
        plot_df=point_df,
        dataset_code=dataset_code,
        selected_date=selected_date,
        selected_year=selected_year,
    )

    st.plotly_chart(
        figure,
        use_container_width=True,
        config={"displayModeBar": False},
        key=f"sensor_point_plot_{dataset_code}_{selected_year}",
    )


# ============================================================
# MAP STATE
# ============================================================

def initialise_selected_dataset() -> str:
    """Initialise or validate the selected SM/ET/SMD dataset."""
    if (
        "selected_map_dataset" not in st.session_state
        or st.session_state["selected_map_dataset"]
        not in DATASET_CODES
    ):
        st.session_state["selected_map_dataset"] = "SM"

    return st.session_state["selected_map_dataset"]


def initialise_selected_date(
    dataset_code: str,
    available_dates: tuple[date, ...],
) -> date:
    """Maintain a separate selected date for each map dataset."""
    state_key = f"selected_{dataset_code.lower()}_date"

    if (
        state_key not in st.session_state
        or st.session_state[state_key]
        not in available_dates
    ):
        st.session_state[state_key] = available_dates[-1]

    return st.session_state[state_key]


def get_last_map_click(
    map_state: dict | None,
) -> tuple[float, float] | None:
    """Return the last synthetic or real map-click coordinates."""
    if not map_state:
        return None

    last_clicked = map_state.get("last_clicked")

    if not last_clicked:
        return None

    latitude = last_clicked.get("lat")
    longitude = last_clicked.get("lng")

    if latitude is None or longitude is None:
        return None

    return float(latitude), float(longitude)


def get_requested_date(
    map_state: dict | None,
    available_dates: tuple[date, ...],
) -> date | None:
    """Decode a date selection sent by the in-map slider."""
    clicked_coordinates = get_last_map_click(map_state)

    if clicked_coordinates is None:
        return None

    latitude, longitude = clicked_coordinates

    if not np.isclose(
        latitude,
        DATE_CONTROL_MAGIC_LAT,
        atol=1e-6,
    ):
        return None

    requested_index = int(round(longitude))

    if not 0 <= requested_index < len(available_dates):
        return None

    return available_dates[requested_index]


def get_requested_dataset(
    map_state: dict | None,
) -> str | None:
    """Decode an SM/ET/SMD selection sent by the top-left toggle."""
    clicked_coordinates = get_last_map_click(map_state)

    if clicked_coordinates is None:
        return None

    latitude, longitude = clicked_coordinates

    if not np.isclose(
        latitude,
        DATASET_CONTROL_MAGIC_LAT,
        atol=1e-6,
    ):
        return None

    requested_index = int(round(longitude))

    if not 0 <= requested_index < len(DATASET_CODES):
        return None

    return DATASET_CODES[requested_index]


# ============================================================
# COMPLETE MAP SECTION
# ============================================================

def render_map_section() -> None:
    """Render the map and process its in-map dataset/date controls."""
    tiffs_by_dataset = {
        dataset_code: find_dated_tiffs(
            tiff_dir=str(
                get_dataset_settings(dataset_code)["directory"]
            ),
            dataset_code=dataset_code,
        )
        for dataset_code in DATASET_CODES
    }

    selected_dataset = initialise_selected_dataset()
    selected_settings = get_dataset_settings(selected_dataset)

    selected_tiffs = tiffs_by_dataset[selected_dataset]
    available_dates = tuple(selected_tiffs.keys())

    selected_date = initialise_selected_date(
        dataset_code=selected_dataset,
        available_dates=available_dates,
    )

    shapefile_signature = get_shapefile_signature(
        FIELD_SHP
    )

    fields = load_field_polygons(
        shapefile_path=str(FIELD_SHP),
        shapefile_signature=shapefile_signature,
    )

    fields_wgs84 = fields.to_crs(epsg=4326)
    selected_tiff = selected_tiffs[selected_date]

    database_path = Path(DB_DIR)
    database_mtime_ns = (
        database_path.stat().st_mtime_ns
        if database_path.exists()
        else 0
    )

    with st.spinner(
        f"Loading {selected_settings['name'].lower()} for "
        f"{selected_date:%Y-%m-%d}..."
    ):
        if selected_dataset == "SMD":
            et_tiff_records = tuple(
                (
                    available_date.isoformat(),
                    str(file_path),
                    file_path.stat().st_mtime_ns,
                )
                for available_date, file_path in selected_tiffs.items()
                if (
                    available_date.year == selected_date.year
                    and available_date <= selected_date
                )
            )

            if not database_path.exists():
                raise FileNotFoundError(
                    f"The WeatherLink database does not exist:\n"
                    f"{database_path}"
                )

            raster_overlay = prepare_smd_overlay(
                et_tiff_records=et_tiff_records,
                selected_date_iso=selected_date.isoformat(),
                shapefile_path=str(FIELD_SHP),
                shapefile_signature=shapefile_signature,
                db_path=str(database_path),
                db_mtime_ns=database_mtime_ns,
                style_version=SMD_STYLE_VERSION,
            )
        else:
            raster_overlay = prepare_raster_overlay(
                tiff_path=str(selected_tiff),
                tiff_mtime_ns=selected_tiff.stat().st_mtime_ns,
                shapefile_path=str(FIELD_SHP),
                shapefile_signature=shapefile_signature,
                dataset_code=selected_dataset,
            )

        field_map = create_environment_map(
            fields_wgs84=fields_wgs84,
            raster_overlay=raster_overlay,
            dataset_code=selected_dataset,
            available_dates=available_dates,
            selected_date=selected_date,
        )

    map_state = st_folium(
        field_map,
        key=(
            f"field_map_{selected_dataset.lower()}_"
            f"{selected_date:%Y%m%d}_"
            f"{SMD_STYLE_VERSION if selected_dataset == 'SMD' else 'default'}"
        ),
        height=500,
        use_container_width=True,
        returned_objects=["last_clicked"],
    )

    requested_dataset = get_requested_dataset(
        map_state=map_state
    )

    if (
        requested_dataset is not None
        and requested_dataset != selected_dataset
    ):
        st.session_state[
            "selected_map_dataset"
        ] = requested_dataset
        st.rerun()

    requested_date = get_requested_date(
        map_state=map_state,
        available_dates=available_dates,
    )

    if (
        requested_date is not None
        and requested_date != selected_date
    ):
        st.session_state[
            f"selected_{selected_dataset.lower()}_date"
        ] = requested_date
        st.rerun()

    selected_plot_year = render_plot_year_selector()

    st.markdown("##### Polygon-average time series")
    with st.spinner("Loading polygon time series..."):
        render_dataset_time_series_plot(
            dataset_code=selected_dataset,
            available_dates=available_dates,
            selected_date=selected_date,
            selected_year=selected_plot_year,
            selected_tiffs=selected_tiffs,
            fields=fields,
            shapefile_signature=shapefile_signature,
            db_path=str(database_path),
            db_mtime_ns=database_mtime_ns,
        )

    st.markdown("##### Sensor-location pixel time series")
    with st.spinner("Loading sensor-location time series..."):
        render_sensor_point_time_series_plot(
            dataset_code=selected_dataset,
            available_dates=available_dates,
            selected_date=selected_date,
            selected_year=selected_plot_year,
            selected_tiffs=selected_tiffs,
            fields=fields,
            db_path=str(database_path),
            db_mtime_ns=database_mtime_ns,
        )

    decimals = selected_settings["decimals"]
    unit = selected_settings["unit"]

    minimum_text = format_raster_value(
        raster_overlay["minimum"],
        unit,
        decimals,
    )
    maximum_text = format_raster_value(
        raster_overlay["maximum"],
        unit,
        decimals,
    )
    pixel_mean_text = format_raster_value(
        raster_overlay["mean"],
        unit,
        decimals,
    )
    polygon_mean_text = format_raster_value(
        raster_overlay["mean_of_polygon_means"],
        unit,
        decimals,
    )

    if DEBUG == True:
        st.markdown(f"""
            **Dataset:** {selected_dataset} \n
            **Date:** {selected_date:%Y-%m-%d} \n
            **Range:** {minimum_text}\u2013{maximum_text} \n
            **Pixel mean:** {pixel_mean_text} \n 
            **Mean of polygon means:** {polygon_mean_text} \n
            **Processing notes:** {raster_overlay.get('processing_note', selected_settings['processing_note'])}     
        """)
    else:
        pass


# ============================================================
# PAGE CONTENT
# ============================================================

if os.environ.get("DHI_PRECOMPUTE_MODE") != "1":
    st.title("Soil Moisture, Evapotranspiration and Deficit Map")
    render_map_section()

  


