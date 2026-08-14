from datetime import datetime, timedelta, timezone
from pathlib import Path

VRI_ICON = "static/favicon.ico"
HORIZONTAL_VRI_ICON = "static/vri_logo.drawio.png"

# DB_DIR = "DB/WeatherLink_DB_Main.db"
DB_DIR = "DB/WeatherLink_DB_Main_2026_08_03.db"
BACKUP_DB_DIR = "Backup/"
LATVIA_TZ = timezone(timedelta(hours=3))


# VRI Meteo station
STATION_ID = '164681'

# ::| DHI DATA PATHS |:::::::::::::::::::::::::::::::::::::::::::::::::::::::
MAIN_DATA_DIR = Path("DB/")


FIELD_SHP = Path("static/field_shp/metra_lauka_poligons_2024_with_coords.shp")


# These .tiff files contain the ET and SM data
# - The dates for these files is saved in the file name like this: _20230401_ (yyyymmdd)
# - The date range in the folder is from 2023-04-01 to 2026-06-30
TIFF_FILES_DIR = MAIN_DATA_DIR / "DHI_data/Ins4EnvSolutions"

# The SM data is expressed as a %
# The SM files have 3 bands:
# - Band 1: SM from 0 to 10cm depth 
# - Band 2: SM from 10 to 35cm depth
# - Band 3: SM from 35 to 70cm depth  
# Based on our experience, we have noticed that aggregating (e.g., average, or weighted average) 
# the first two bands yield more accurate results, so we suggest you do that.
SM_TIFF_FILES_DIR = TIFF_FILES_DIR / "SM"

# The ET files have only one singular band which shows the ET in mm/day, no scaling factor 
# is applied and there is no accumulation 
ET_TIFF_FILES_DIR = TIFF_FILES_DIR / "ET"