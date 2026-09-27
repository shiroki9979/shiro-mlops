"""System-wide constants and column names."""

DATETIME_COL = "datetime"
# Persisted time-series tables name their Taiwan-local instant column ``time``.
STORAGE_TIME_COL = "time"
LOAD_MW_COL = "load_mw"
TEMPERATURE_COL = "temperature"
RELATIVE_HUMIDITY_COL = "relative_humidity"
LOCATION_COL = "location"
SUBJECT_COL = "subject"

# 預測對象識別負載序列本身，與天氣取自哪個氣象代表點無關（ADR-0009）。
NATIONWIDE_SUBJECT = "nationwide"
# 氣象代表點以 CWA 擷取目錄的 alias 引用；測站與鄉鎮代碼只存在於擷取目錄。
DEFAULT_WEATHER_REFERENCE_POINT = "Taipei"
DEFAULT_HORIZON_HOURS = 24
MAX_HORIZON_HOURS = 168  # 1 week, the longest horizon the API accepts and /ready verifies
DEFAULT_LAG_HOURS = [1, 2, 3, 24, 48, 168]  # 1h, 2h, 3h, 1d, 2d, 1w lags
DEFAULT_ROLLING_WINDOWS = [6, 24]

# Model defaults
DEFAULT_MODEL_NAME = "taipower_lightgbm_forecaster"
DEFAULT_EXPERIMENT_NAME = "taipower_load_forecasting"
