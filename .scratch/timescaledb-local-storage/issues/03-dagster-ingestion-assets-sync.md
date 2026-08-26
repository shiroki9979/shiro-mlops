# 03: Integrate TimescaleDB Upsert into Dagster Ingestion Assets

**What to build:**
Refactor the Dagster Software-Defined Assets for raw data ingestion (`raw_taipower_load_data` and `raw_weather_obs_data`) to write incoming batches directly into TimescaleDB via `TimeSeriesRepository`, ensuring operational persistence upon every ingestion execution.

**Blocked by:** 02-timeseries-storage-client-and-upsert

**Status:** ready-for-agent

- [ ] Update Dagster asset `raw_taipower_load_data` to upsert fetched records into TimescaleDB before returning the DataFrame.
- [ ] Update Dagster asset `raw_weather_obs_data` to upsert fetched records into TimescaleDB before returning the DataFrame.
- [ ] Ensure graceful fallback or test-mode mock support when running Dagster offline unit tests.
- [ ] Add integration test verifying Dagster ingestion assets execute and successfully persist to database mock/fixture.
