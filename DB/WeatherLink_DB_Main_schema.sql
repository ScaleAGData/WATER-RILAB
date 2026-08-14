-- database: ./WeatherLink_DB_Main_2026_08_03.db

-- ::::::::::::::::::::: CREATTING TABLES ::::::::::::::::::::: 
-- -- Base Tables :::::::::::::::::::::::::::::::::::::::::::::
CREATE TABLE IF NOT EXISTS STATIONS(
    station_id              INTEGER PRIMARY KEY,
    station_id_uuid         TEXT,
    station_name            TEXT,
    gateway_id              INTEGER,
    gateway_id_hex          TEXT,
    product_number          TEXT,
    username                TEXT,       
    user_email              TEXT,       
    company_name            TEXT,       
    active                  INTEGER,    
    is_private              INTEGER,    -- name of column modified from (private)
    recording_interval      INTEGER,
    firmware_version        TEXT,
    imei                    TEXT,
    registered_date         INTEGER,    -- INT because DATETIME not supported
    subscription_end_date   INTEGER,    -- INT because DATETIME not supported 
    time_zone               TEXT,
    city                    TEXT,
    region                  TEXT,
    country                 TEXT,
    latitude                FLOAT,
    longitude               FLOAT,
    elevation               FLOAT,
    gateway_type            TEXT,
    relationship_type       TEXT,
    subscription_type       TEXT  
); 


CREATE TABLE IF NOT EXISTS NODES(
    lsid                    INTEGER PRIMARY KEY,
    sensor_type             INTEGER,
    category                TEXT,
    manufacturer            TEXT,
    product_name            TEXT,
    product_number          TEXT,
    rain_collector_type     INTEGER, 
    active                  INTEGER, -- This is a boolean
    created_date            INTEGER, -- INT because DATETIME not supported
    modified_date           INTEGER, -- INT because DATETIME not supported
    station_id              INTEGER, -- FK
    station_id_uuid         TEXT,
    station_name            TEXT,
    parent_device_type      TEXT,
    parent_device_name      TEXT,
    parent_device_id        TEXT,
    parent_device_id_hex    TEXT,
    port_number             INTEGER,
    latitude                FLOAT,
    longitude               FLOAT,
    elevation               FLOAT,
    tx_id                   TEXT,       

    FOREIGN KEY (station_id) REFERENCES STATIONS(station_id),
    FOREIGN KEY (station_id_uuid) REFERENCES STATIONS(station_id_uuid)
    FOREIGN KEY (station_name) REFERENCES STATIONS(station_name)

);




-- -- Data Tables :::::::::::::::::::::::::::::::::::::::::::::
-- missing sensor_type 4 SOLAR RADIATION
-- Pressure sensors have a sensor_type of 3
CREATE TABLE IF NOT EXISTS NODE_barometer_DATA(
    lsid                INTEGER,
    ts                  INTEGER, -- INT because DATETIME not supported
    tz_offset           INTEGER,
    sensor_type         INTEGER, 
    data_structure_type INTEGER, 

    -- Data columns for the table
    bar_trend_3_hr      FLOAT,   -- INFO: Inches of mercury  
    pressure_last       FLOAT,   -- INFO: Inches of mercury   

    PRIMARY KEY (lsid, ts),      -- Ensures unique data values        
    FOREIGN KEY (lsid) REFERENCES NODES(lsid),
    FOREIGN KEY (sensor_type) REFERENCES NODES(sensor_type)

);

-- -- Rain sensors have a sensor_type of 31
CREATE TABLE IF NOT EXISTS NODE_ISS_rain_DATA(
    lsid                    INTEGER,
    ts                      INTEGER,
    tz_offset               INTEGER,
    sensor_type             INTEGER, 
    data_structure_type     INTEGER, 

    -- Data columns for the table
    bar                     FLOAT,      -- INFO: units: Inches of mercury  
    bar_absolute            FLOAT,      
    bar_trend               INTEGER,    -- INFO: units: change in inches of mercury 

    dew_point               INTEGER,    -- INFO: units: degrees Fahrenheit
    et_day                  FLOAT,      -- INFO: units: inches
    forecast_rule           INTEGER,    
    forecast_desc           TEXT,       -- INFO: units: forecast messages if available
    heat_index              INTEGER,    -- INFO: units: degrees Fahrenheit
    hum_out                 INTEGER,    -- INFO: untis: percent relative humidity

    rain_15_min_clicks      INTEGER,    -- INFO: units: clicks
    rain_15_min_mm          FLOAT,      -- INFO: units: milimieters

    rain_60_min_clicks      INTEGER,    -- INFO: units: clicks
    rain_60_min_mm          FLOAT,      -- INFO: units: milimieters

    rain_24_hr_clicks       INTEGER,    -- INFO: units: clicks
    rain_24_hr_mm           FLOAT,      -- INFO: units: milimieters

    rain_day_clicks         INTEGER,    -- INFO: units: clicks for the day
    rain_day_mm             FLOAT,      -- INFO: units: millimeters for the day

    rain_rate_clicks        INTEGER,    -- INFO: unit: clicks per hour
    rain_rate_mm            FLOAT,      -- INFO: unit: mm per hour

    rain_storm_clicks       INTEGER,    -- INFO: units: clicks
    rain_storm_mm           FLOAT,      -- INFO: unitss: milimiters
    rain_storm_start_date   INTEGER,    -- INFO: unit: seconds

    solar_rad               INTEGER,    -- INFO: units: watts per square meter
    temp_out                FLOAT,      -- INFO: units: degrees Fahrenheit
    thsw_index              INTEGER,    -- INFO: units: degrees Fahrenheit
    uv                      FLOAT,      -- INFO: units: ultraviolet index

    wind_chill              FLOAT,      -- INFO: units: degrees Fahrenheit
    wind_dir                INTEGER,    -- INFO: untis: degrees of compass
    wind_dir_of_gust_10_min INTEGER,    -- INFO: untis: degrees of compass
    wind_gust_10_min        INTEGER,    -- INFO: units: miles per hour
    wind_speed              INTEGER,    -- INFO: units: miles per hour 
    wind_speed_2_min        FLOAT,      -- INFO: units: miles per hour
    wind_speed_10_min       INTEGER,    -- INFO: units: miles per hour
    wet_bulb                FLOAT,      -- INFO: units: degrees Fahrenheit

    PRIMARY KEY (lsid, ts),      -- Ensures unique data values  
    FOREIGN KEY (lsid) REFERENCES NODES(lsid),
    FOREIGN KEY (sensor_type) REFERENCES NODES(sensor_type)
);

-- -- Temperature probes have a sensor_type of 105
CREATE TABLE IF NOT EXISTS NODE_temp_probe_DATA (
    lsid                INTEGER,
    ts                  INTEGER, -- INT because DATETIME not supported
    tz_offset           INTEGER,
    sensor_type         INTEGER, 
    data_structure_type INTEGER, 

    -- Data columns for the table
    temp_last           FLOAT,      -- INFO: units: degrees Fahrenheit
    temp_avg            FLOAT,      -- INFO: units: degrees Fahrenheit

    temp_hi_at          INTEGER,    -- INFO: units: seconds
    temp_hi             FLOAT,      -- INFO: units: degrees Fahrenheit

    temp_lo_at          INTEGER,    -- INFO: units: seconds
    temp_lo             FLOAT,      -- INFO: units: degrees Fahrenheit

    PRIMARY KEY (lsid, ts),      -- Ensures unique data values  
    FOREIGN KEY (lsid) REFERENCES NODES(lsid),
    FOREIGN KEY (sensor_type) REFERENCES NODES(sensor_type)
);

-- -- Soil sensors have a sensor_type of 108
CREATE TABLE IF NOT EXISTS NODE_soil_moisture_DATA (
    lsid                INTEGER,
    ts                  INTEGER, -- INT because DATETIME not supported
    tz_offset           INTEGER, 
    sensor_type         INTEGER, 
    data_structure_type INTEGER, 

    -- Data columns for the table
    moist_soil_last     FLOAT,      -- INFO: units: centibars

    PRIMARY KEY (lsid, ts),      -- Ensures unique data values  
    FOREIGN KEY (lsid) REFERENCES NODES(lsid),
    FOREIGN KEY (sensor_type) REFERENCES NODES(sensor_type)
);

-- sensor_type of 299
CREATE TABLE IF NOT EXISTS NODE_rain_DATA (
    lsid                                INTEGER,
    ts                                  INTEGER,
    tz_offset                           INTEGER,
    sensor_type                         INTEGER, 
    data_structure_type                 INTEGER, 

    -- Data columns for the table
    rain_rate_hi_at                     INTEGER,    -- INFO: units: seconds
    rain_rate_hi_clicks                 INTEGER,    -- INFO: units: clicks
    rain_rate_hi_mm                     FLOAT,      -- INFO: untis: milimeters

    rain_rate_hi_last_15_min_clicks     INTEGER,    -- INFO: units: clicks
    rain_rate_hi_last_15_min_mm         FLOAT,      -- INFO: untis: milimeters

    rain_rate_last_clicks               INTEGER,    -- INFO: units: clicks
    rain_rate_last_mm                   FLOAT,      -- INFO: untis: milimeters

    rainfall_clicks                     INTEGER,    -- INFO: units: clicks
    rainfall_mm                         FLOAT,      -- INFO: untis: milimeters

    rainfall_last_15_min_clicks         INTEGER,    -- INFO: units: clicks
    rainfall_last_15_min_mm             FLOAT,      -- INFO: units: milimeters
    
    rainfall_last_60_min_clicks         INTEGER,    -- INFO: units: clicks
    rainfall_last_60_min_mm             FLOAT,      -- INFO: untis: milimeters

    PRIMARY KEY (lsid, ts),      -- Ensures unique data values  
    FOREIGN KEY (lsid) REFERENCES NODES(lsid),
    FOREIGN KEY (sensor_type) REFERENCES NODES(sensor_type)
);





-- -- Sensor Health Tables :::::::::::::::::::::::::::::::::::::::::::::
-- -- Health sensors have a sensor_type of 501
CREATE TABLE IF NOT EXISTS NODE_health_DATA (
    lsid                            INTEGER,
    ts                              INTEGER,    -- INT because DATETIME not supported, unix time
    sensor_type                     INTEGER, 
    data_structure_type             INTEGER,  
    tz_offset                       INTEGER,

    -- Data columns for the table
    application_firmware_version    INTEGER,
    beacon_interval                 INTEGER,    -- INFO: units: miliseconds
    bluetooth_firmware_version      INTEGER,
    
    dcell_battery_voltage           INTEGER,    -- INFO: units: milivolts
    door_switch_status              INTEGER,    
    
    etx                             INTEGER,
    
    false_wakeup_count              INTEGER,
    false_wakeup_rssi               INTEGER,    -- INFO: units: recieved signal strength indicator
    
    health_version                  INTEGER,    
    
    inside_box_temp                 FLOAT,      -- INFO: units: degrees Fahrenheit
    
    last_parent_rtt_ping            INTEGER,    -- INFO: units: miliseconds
    last_rx_rssi                    INTEGER,    -- INFO: units: received signal strength indicator
    li_ion_cell_voltage             INTEGER,    -- INFO: units: milivolts
    link_layer_packets_received     INTEGER,
    
    node_rank                       INTEGER,
    noise_floor_rssi                INTEGER,    -- INFO: units: received signal strength indicator
    number_of_neighbors             INTEGER,    
    
    platform_id                     INTEGER,
    port_energy_consumed_1          INTEGER,    -- INFO: units: milijoules
    port_energy_consumed_2          INTEGER,    -- INFO: units: milijoules   
    port_energy_consumed_3          INTEGER,    -- INFO: units: milijoules
    port_energy_consumed_4          INTEGER,    -- INFO: units: milijoules
    power_percentage_mcu            INTEGER,    -- INFO: units: precent
    power_percentage_rx             INTEGER,    -- INFO: units: precent
    power_percentage_tx             INTEGER,    -- INFO: units: precent

    rpl_mode                        INTEGER,    -- This is a boolan
    rpl_parent_node_id              INTEGER,
    
    solar_panel_voltage             INTEGER,    -- INFO: units: milivolts
    
    uptime                          INTEGER,    -- INFO: units: seconds

    PRIMARY KEY (lsid, ts),                     -- Ensures unique data values  
    FOREIGN KEY (lsid) REFERENCES NODES(lsid),
    FOREIGN KEY (sensor_type) REFERENCES NODES(sensor_type)

);

-- -- Health sensor gateway sensor_type of 507
CREATE TABLE IF NOT EXISTS NODE_health_gateway_GATEWAY(
    lsid                                INTEGER, 
    ts                                  INTEGER,
    tz_offset                           INTEGER,
    sensor_type                         INTEGER, 
    data_structure_type                 INTEGER, 

    -- Data columns for the table
    afc_setting                         INTEGER,
    
    beacon_interval                     INTEGER,    -- INFO: units: miliseconds
    bluetooth_firmware_version          INTEGER,
    bootloader_version                  INTEGER,
    
    cc1310_firmware_version             INTEGER,
    cell_channel                        INTEGER,
    cell_id                             INTEGER,
    cme                                 INTEGER, 
    cereg                               INTEGER,    -- INFO: units: 0 = not registered, is not currently searching a new operator to register to; 1 = registered, home network; 2 = not registered, but currently searching a new operator to register to; 3 = registration denied; 4 = unknown; 5 = registered, roaming
    crc_errors                          INTEGER,
    creg_cgreg                          INTEGER,    -- INFO: units: lower nibble of first byte (creg)/upper nibble of first byte (cgreg) : 0 = not registered, is not currently searching a new operator to register to; 1 = registered, home network; 2 = not registered, but currently searching a new operator to register to; 3 = registration denied; 4 = unknown; 5 = registered, roaming

    davistalk_rssi                      INTEGER,    -- INFO: units: received signal strenght indicator 
    
    elevation                           INTEGER,    -- INFO: units: feet
    etx                                 INTEGER,
    
    false_wakeup_count                  INTEGER,    
    false_wakeup_rssi                   INTEGER,    -- INFO: units: received signal strength indicator
    
    good_packet_streak                  INTEGER,
    
    health_version                      INTEGER,
    
    inside_box_temp                     FLOAT,      -- INFO: units: degrees fahrenheit
    iss_solar_panel_voltage             FLOAT,      -- INFO: units: volts 
    iss_super_cap_voltage               FLOAT,      -- INFO: units: volts 
    iss_transmitter_battery_voltage     FLOAT,      -- INFO: units: volts 

    last_cme_error_timestamp            INTEGER,
    last_gps_reading_timestamp          INTEGER,
    last_parent_rtt_ping                INTEGER,    -- INFO: units: miliseconds
    last_rx_rssi                        INTEGER,    -- INFO: units: received signal strength indicator
    latitude                            FLOAT,      -- INFO: units: degrees
    lead_acid_battery_voltage           INTEGER,    -- INFO: units: millivolts
    link_layer_packets_received         INTEGER,
    link_uptime                         INTEGER,    -- INFO: units: seconds
    location_area_code                  INTEGER,
    longitude                           FLOAT,      -- INFO: units: degrees    

    mcc_mnc                             INTEGER,

    noise_floor_rssi                    INTEGER,    -- INFO: units: received signal strength indicator
    node_rank                           INTEGER,
    number_of_neighbors                 INTEGER,
    
    overall_access_technology           INTEGER,    -- INFO: units: 0 = GSM; 2 = UTRAN; 3 = GSM W/EGPRS; 4 = UTRAN W/HSDPA; 5 = UTRAN W/HSUPA; 6 = UTRAN W/HSDPA and HSUPA; 7 = E-UTRAN

    platform_id                         INTEGER,
    power_percentage_mcu                INTEGER,    -- INFO: units: percent
    power_percentage_rx                 INTEGER,    -- INFO: units: percent
    power_percentage_tx                 INTEGER,    -- INFO: units: percent

    reception_percent                   INTEGER,    -- INFO: units: percent
    resyncs                             INTEGER,
    rpl_mode                            INTEGER,
    rpl_parent_node_id                  INTEGER,
    rssi                                INTEGER,    -- INFO: units: received signal strength indicator : 0 = -113dBm or less; 1 = -111dBm; 2 through 30 = -109dBm through -53dBm; 31 = -51dBm or greater; 99 = Not known or not detectable; 100 = -116dBm or less; 101 = -115dBm; 102 through 190 = -114dBm through -26dBm; 191 = -25dBm or greater; 199 = Not known or not detectable; 100~199 = Extended to be used in TD-SCDMA indicating received signal code power (RSCP)
    rx_bytes                            INTEGER,

    solar_panel_voltage                 INTEGER,    -- INFO: units: millivolts
    
    tiva_application_firmware_version   INTEGER,
    transmitter_battery_state           INTEGER,
    tx_bytes                            INTEGER,
    
    uptime                              INTEGER,    -- INFO: units: seconds

    
    PRIMARY KEY (lsid, ts),      -- Ensures unique data values  
    FOREIGN KEY (lsid) REFERENCES NODES(lsid),
    FOREIGN KEY (sensor_type) REFERENCES NODES(sensor_type)

);






















