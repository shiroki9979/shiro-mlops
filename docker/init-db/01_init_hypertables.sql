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

