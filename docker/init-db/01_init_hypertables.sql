-- Initialize TimescaleDB Extension and Hypertables for Shiro MLOps Platform
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- 1. Raw Taipower Load Table & Hypertable
CREATE TABLE IF NOT EXISTS raw_taipower_load (
    time TIMESTAMPTZ NOT NULL,
    location VARCHAR(64) NOT NULL,
    load_mw DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (time, location)
);

SELECT create_hypertable(
    'raw_taipower_load',
    'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- 2. 舊版 CWA 氣象資料。這些列缺乏可信的 StationId provenance，
-- 僅為稽核保留；canonical 消費端使用下方的測站觀測資料。
CREATE TABLE IF NOT EXISTS legacy_cwa_weather (
    time TIMESTAMPTZ NOT NULL,
    location VARCHAR(64) NOT NULL,
    temperature DOUBLE PRECISION,
    relative_humidity DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (time, location)
);

SELECT create_hypertable(
    'legacy_cwa_weather',
    'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- 3. Canonical CWA observation batches and typed station observations
CREATE TABLE IF NOT EXISTS raw_cwa_observation_batch (
    fetched_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(16) NOT NULL,
    missing_station_ids JSONB NOT NULL,
    raw_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (fetched_at)
);

CREATE TABLE IF NOT EXISTS raw_cwa_station_observation (
    observed_at TIMESTAMPTZ NOT NULL,
    station_id VARCHAR(16) NOT NULL,
    station_name VARCHAR(128),
    town_code VARCHAR(16),
    temperature_c DOUBLE PRECISION,
    relative_humidity_pct DOUBLE PRECISION,
    air_pressure_hpa DOUBLE PRECISION,
    precipitation_mm DOUBLE PRECISION,
    wind_speed_m_s DOUBLE PRECISION,
    wind_direction_deg DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (observed_at, station_id)
);

SELECT create_hypertable(
    'raw_cwa_station_observation',
    'observed_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- 4. Canonical CWA forecast releases and typed township forecast rows
CREATE TABLE IF NOT EXISTS raw_cwa_forecast_release (
    dataset_id VARCHAR(16) NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(16) NOT NULL,
    missing_geocodes JSONB NOT NULL,
    raw_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (dataset_id, issued_at, source_updated_at)
);

CREATE TABLE IF NOT EXISTS raw_cwa_township_forecast (
    dataset_id VARCHAR(16) NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    geocode VARCHAR(16) NOT NULL,
    location_name VARCHAR(128),
    temperature_c DOUBLE PRECISION,
    dew_point_c DOUBLE PRECISION,
    apparent_temperature_c DOUBLE PRECISION,
    relative_humidity_pct DOUBLE PRECISION,
    probability_of_precipitation_pct DOUBLE PRECISION,
    wind_speed_m_s DOUBLE PRECISION,
    wind_direction VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (dataset_id, issued_at, source_updated_at, valid_from, valid_to, geocode)
);

ALTER TABLE raw_cwa_township_forecast
ADD COLUMN IF NOT EXISTS location_name VARCHAR(128);

SELECT create_hypertable(
    'raw_cwa_township_forecast',
    'valid_from',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- 5. Read-only archive target for ambiguous legacy weather rows
CREATE TABLE IF NOT EXISTS legacy_cwa_weather (
    time TIMESTAMPTZ NOT NULL,
    location VARCHAR(64) NOT NULL,
    temperature DOUBLE PRECISION,
    relative_humidity DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (time, location)
);

-- 3. 台電電力供需快照：與逐時負載分表保存，避免快照資料混入訓練序列。
CREATE TABLE IF NOT EXISTS raw_taipower_supply_demand_snapshot (
    observed_at TIMESTAMPTZ NOT NULL,
    source_publish_time TIMESTAMPTZ,
    curr_load_wan_kw DOUBLE PRECISION NOT NULL,
    curr_util_rate_pct DOUBLE PRECISION NOT NULL,
    fore_maxi_sply_capacity_wan_kw DOUBLE PRECISION,
    fore_peak_dema_load_wan_kw DOUBLE PRECISION,
    fore_peak_resv_capacity_wan_kw DOUBLE PRECISION,
    fore_peak_resv_rate_pct DOUBLE PRECISION,
    fore_peak_resv_indicator VARCHAR(8),
    fore_peak_hour_range VARCHAR(32),
    yday_date DATE,
    yday_maxi_sply_capacity_wan_kw DOUBLE PRECISION,
    yday_peak_dema_load_wan_kw DOUBLE PRECISION,
    yday_peak_resv_capacity_wan_kw DOUBLE PRECISION,
    yday_peak_resv_rate_pct DOUBLE PRECISION,
    yday_peak_resv_indicator VARCHAR(8),
    real_hr_maxi_sply_capacity_wan_kw DOUBLE PRECISION,
    real_hr_peak_time TIMESTAMPTZ,
    raw_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (observed_at)
);

SELECT create_hypertable(
    'raw_taipower_supply_demand_snapshot',
    'observed_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- 4. 台電區域供需快照：北中南東分區發電／用電成對保存，不進入訓練特徵。
CREATE TABLE IF NOT EXISTS raw_taipower_regional_supply_demand_snapshot (
    observed_at TIMESTAMPTZ NOT NULL,
    region VARCHAR(16) NOT NULL,
    source_time TIMESTAMPTZ NOT NULL,
    generation_wan_kw DOUBLE PRECISION,
    load_wan_kw DOUBLE PRECISION NOT NULL,
    raw_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (observed_at, region)
);

SELECT create_hypertable(
    'raw_taipower_regional_supply_demand_snapshot',
    'observed_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- 5. 台電機組即時淨發電量快照：與供需／逐時負載分表保存，不進入訓練特徵。
CREATE TABLE IF NOT EXISTS raw_taipower_unit_generation_snapshot (
    observed_at TIMESTAMPTZ NOT NULL,
    unit_type VARCHAR(128) NOT NULL,
    unit_name VARCHAR(128) NOT NULL,
    source_time TIMESTAMPTZ NOT NULL,
    capacity_mw DOUBLE PRECISION,
    net_generation_mw DOUBLE PRECISION,
    capacity_ratio_pct DOUBLE PRECISION,
    remark VARCHAR(256),
    raw_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (observed_at, unit_type, unit_name)
);

SELECT create_hypertable(
    'raw_taipower_unit_generation_snapshot',
    'observed_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE,
    migrate_data => TRUE
);
