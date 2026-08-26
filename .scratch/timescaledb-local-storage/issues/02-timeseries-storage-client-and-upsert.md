# 02: TimeSeriesRepository Client and Batch Upsert Operations

**What to build:**
Implement a Python repository class (`TimeSeriesRepository`) that encapsulates database connections, SQLAlchemy/psycopg engine pooling, and batch upsert (`ON CONFLICT DO UPDATE`) operations for Taipower power load and CWA weather records, including query methods for date ranges.

**Blocked by:** 01-docker-timescaledb-setup-and-schema

**Status:** ready-for-agent

- [ ] Implement `TimeSeriesRepository` with `upsert_taipower_load(df: pd.DataFrame)` handling composite key conflicts on `(time, location)`.
- [ ] Implement `TimeSeriesRepository.upsert_cwa_weather(df: pd.DataFrame)` handling composite key conflicts on `(time, location)`.
- [ ] Implement query methods `fetch_load_range` and `fetch_weather_range` returning sorted pandas DataFrames.
- [ ] Add offline unit tests for `TimeSeriesRepository` testing insertion, duplicate upsert idempotency, and query filtering.
