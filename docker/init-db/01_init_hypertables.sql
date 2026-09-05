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
