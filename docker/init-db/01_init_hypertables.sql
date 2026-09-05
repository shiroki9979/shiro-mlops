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

-- 2. Raw CWA Weather Observations Table & Hypertable
CREATE TABLE IF NOT EXISTS raw_cwa_weather (
    time TIMESTAMPTZ NOT NULL,
    location VARCHAR(64) NOT NULL,
    temperature DOUBLE PRECISION,
    relative_humidity DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (time, location)
);

SELECT create_hypertable(
    'raw_cwa_weather',
    'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- 3. Raw Taipower Power Supply-Demand Snapshot Table & Hypertable
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

