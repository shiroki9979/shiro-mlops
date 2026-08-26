# 01: Docker TimescaleDB Setup and DDL Schema Migration

**What to build:**
Upgrade the local Docker Compose configuration to run TimescaleDB instead of plain PostgreSQL, and provide an automated initialization/migration DDL script to provision `raw_taipower_load` and `raw_cwa_weather` Hypertables with composite primary keys `(time, location)` and 7-day chunk intervals.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Update `docker/docker-compose.yml` to use `timescale/timescaledb:latest-pg15` container image.
- [ ] Create DDL initialization SQL script in `docker/init-db/` or migrations directory creating `raw_taipower_load` and `raw_cwa_weather` Hypertables.
- [ ] Add TimescaleDB connection configuration parameters in `shiro_mlops.core.config.Settings`.
- [ ] Add unit test verifying DDL generation and database connection helper.
