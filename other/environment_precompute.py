import argparse
import importlib.util
import logging
import os
import sys
from datetime import date
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
if not (ROOT_DIR / "config.py").exists():
    ROOT_DIR = Path(__file__).resolve().parents[1]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config  # noqa: E402
from environment_cache import get_cache_counts  # noqa: E402


LOG_FILE = ROOT_DIR / "DB" / "environment_precompute.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def find_map_page():
    configured_path = getattr(config, "MAP_PAGE_PATH", None)
    candidates = []

    if configured_path:
        candidates.append(Path(configured_path))

    candidates.extend(
        [
            ROOT_DIR / "pages" / "2_map.py",
            ROOT_DIR / "2_map.py",
            ROOT_DIR / "other" / "2_map.py",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError(
        "Could not find map.py. Set MAP_PAGE_PATH in config.py to the "
        "full path of the Streamlit map page."
    )


def load_map_module():
    previous_mode = os.environ.get("DHI_PRECOMPUTE_MODE")
    os.environ["DHI_PRECOMPUTE_MODE"] = "1"
    try:
        map_path = find_map_page()
        spec = importlib.util.spec_from_file_location(
            "environment_map_page",
            map_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load the map module: {map_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous_mode is None:
            os.environ.pop("DHI_PRECOMPUTE_MODE", None)
        else:
            os.environ["DHI_PRECOMPUTE_MODE"] = previous_mode

    return module, map_path


def serialise_sensor_metadata(sensor_metadata):
    return tuple(
        (
            point["point_index"],
            point["sector"],
            point["sensor"],
            point["latitude"],
            point["longitude"],
            point["line_color"],
        )
        for point in sensor_metadata
    )


def build_tiff_records(selected_tiffs, plot_dates):
    return tuple(
        (
            available_date.isoformat(),
            str(file_path),
            file_path.stat().st_mtime_ns,
        )
        for available_date, file_path in selected_tiffs.items()
        if available_date in plot_dates
    )


def is_empty_field_raster_error(error):
    return "contains no valid values inside the field polygons" in str(error)


def update_environment_cache(force=False):
    map_page, map_path = load_map_module()
    logger.info("Using Streamlit map module: %s", map_path)

    shapefile_path = Path(config.FIELD_SHP)
    shapefile_signature = map_page.get_shapefile_signature(shapefile_path)
    fields = map_page.load_field_polygons(
        shapefile_path=str(shapefile_path),
        shapefile_signature=shapefile_signature,
    )
    polygon_metadata = tuple(
        map_page.get_polygon_plot_metadata(fields)
    )
    sensor_metadata = serialise_sensor_metadata(
        map_page.get_sensor_point_metadata(fields)
    )

    db_path = Path(config.DB_DIR)
    if not db_path.exists():
        raise FileNotFoundError(
            f"WeatherLink database does not exist: {db_path}"
        )
    db_mtime_ns = db_path.stat().st_mtime_ns

    tiffs_by_dataset = {
        dataset_code: map_page.find_dated_tiffs(
            tiff_dir=str(
                map_page.get_dataset_settings(dataset_code)["directory"]
            ),
            dataset_code=dataset_code,
        )
        for dataset_code in map_page.DATASET_CODES
    }

    processed_overlay_calls = 0
    skipped_rasters = []

    for dataset_code in ("SM", "ET"):
        for raster_date, tiff_path in tiffs_by_dataset[dataset_code].items():
            try:
                map_page.prepare_raster_overlay(
                    tiff_path=str(tiff_path),
                    tiff_mtime_ns=tiff_path.stat().st_mtime_ns,
                    shapefile_path=str(shapefile_path),
                    shapefile_signature=shapefile_signature,
                    dataset_code=dataset_code,
                    force_refresh=force,
                )
            except ValueError as error:
                if not is_empty_field_raster_error(error):
                    raise
                skipped = {
                    "dataset": dataset_code,
                    "date": raster_date.isoformat(),
                    "file": str(tiff_path),
                    "reason": str(error),
                }
                skipped_rasters.append(skipped)
                logger.warning("Skipping unusable raster: %s", skipped)
                continue
            processed_overlay_calls += 1

    et_tiffs = tiffs_by_dataset["SMD"]
    for calculation_year in sorted({item.year for item in et_tiffs}):
        year_tiffs = {
            raster_date: path
            for raster_date, path in et_tiffs.items()
            if raster_date.year == calculation_year
        }
        year_records = tuple(
            (
                raster_date.isoformat(),
                str(path),
                path.stat().st_mtime_ns,
            )
            for raster_date, path in year_tiffs.items()
        )

        for selected_date in year_tiffs:
            try:
                map_page.prepare_smd_overlay(
                    et_tiff_records=year_records,
                    selected_date_iso=selected_date.isoformat(),
                    shapefile_path=str(shapefile_path),
                    shapefile_signature=shapefile_signature,
                    db_path=str(db_path),
                    db_mtime_ns=db_mtime_ns,
                    style_version=map_page.SMD_STYLE_VERSION,
                    force_refresh=force,
                )
            except ValueError as error:
                if not is_empty_field_raster_error(error):
                    raise
                skipped = {
                    "dataset": "SMD",
                    "date": selected_date.isoformat(),
                    "file": str(year_tiffs[selected_date]),
                    "reason": str(error),
                }
                skipped_rasters.append(skipped)
                logger.warning("Skipping unusable raster: %s", skipped)
                continue
            processed_overlay_calls += 1

    processed_series = 0
    all_years = sorted(
        {
            raster_date.year
            for selected_tiffs in tiffs_by_dataset.values()
            for raster_date in selected_tiffs
        }
    )

    for dataset_code in map_page.DATASET_CODES:
        selected_tiffs = tiffs_by_dataset[dataset_code]

        for selected_year in all_years:
            plot_dates = tuple(
                raster_date
                for raster_date in selected_tiffs
                if raster_date.year == selected_year
            )
            if not plot_dates:
                continue

            tiff_records = build_tiff_records(
                selected_tiffs,
                plot_dates,
            )
            map_page.build_dataset_time_series(
                dataset_code=dataset_code,
                tiff_records=tiff_records,
                plot_dates=plot_dates,
                polygon_metadata=polygon_metadata,
                shapefile_path=str(shapefile_path),
                shapefile_signature=shapefile_signature,
                db_path=str(db_path),
                db_mtime_ns=db_mtime_ns,
                force_refresh=force,
            )
            map_page.build_sensor_point_time_series(
                dataset_code=dataset_code,
                tiff_records=tiff_records,
                sensor_metadata=sensor_metadata,
                db_path=str(db_path),
                db_mtime_ns=db_mtime_ns,
                force_refresh=force,
            )
            processed_series += 2

    result = {
        "overlay_calls": processed_overlay_calls,
        "time_series_calls": processed_series,
        "skipped_rasters": skipped_rasters,
        "cache_counts": get_cache_counts(),
    }
    logger.info("Environment cache update completed: %s", result)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Precompute Streamlit SM, ET and SMD map results."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recalculate entries even when their input fingerprint is unchanged.",
    )
    arguments = parser.parse_args()
    result = update_environment_cache(force=arguments.force)
    print("Environment cache updated successfully:")
    print(result)


if __name__ == "__main__":
    main()