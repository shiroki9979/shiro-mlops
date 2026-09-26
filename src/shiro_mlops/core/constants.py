"""System-wide constants and column names."""

DATETIME_COL = "datetime"
LOAD_MW_COL = "load_mw"
TEMPERATURE_COL = "temperature"
RELATIVE_HUMIDITY_COL = "relative_humidity"
LOCATION_COL = "location"

DEFAULT_LOCATION = "Taipei"
DEFAULT_HORIZON_HOURS = 24
MAX_HORIZON_HOURS = 168  # 1 week, the longest horizon the API accepts and /ready verifies
DEFAULT_LAG_HOURS = [1, 2, 3, 24, 48, 168]  # 1h, 2h, 3h, 1d, 2d, 1w lags
DEFAULT_ROLLING_WINDOWS = [6, 24]

# Model defaults
DEFAULT_MODEL_NAME = "taipower_lightgbm_forecaster"
DEFAULT_EXPERIMENT_NAME = "taipower_load_forecasting"
