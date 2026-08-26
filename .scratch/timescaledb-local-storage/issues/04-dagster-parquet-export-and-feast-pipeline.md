# 04: TimescaleDB-to-Parquet Feature Materialization and Feast Pipeline Verification

**What to build:**
Connect the feature engineering pipeline and Feast export workflow to extract verified time-series ranges from TimescaleDB, compile `data/taipower_features.parquet` and `data/weather_features.parquet`, and verify end-to-end compatibility with Feast offline feature retrieval and LightGBM model training.

**Blocked by:** 03-dagster-ingestion-assets-sync

**Status:** ready-for-agent

- [ ] Ensure `engineered_features` Dagster asset extracts complete historical windows from TimescaleDB and outputs compliant Parquet files.
- [ ] Verify that Feast offline feature retrieval (`get_historical_features`) reads the materialized Parquet files without schema mismatch.
- [ ] Verify that `trained_forecaster_model` and `drift_monitoring_report` Dagster assets run cleanly end-to-end.
- [ ] Run full test suite (`uv run pytest tests/ -v`) and ensure 100% pass rate.
