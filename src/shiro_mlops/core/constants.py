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
HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7
# pandas dayofweek：Monday = 0，故 Saturday 起（5、6）為週末。
SATURDAY = 5
DEFAULT_HORIZON_HOURS = 24
MAX_HORIZON_HOURS = 168  # 1 week, the longest horizon the API accepts and /ready verifies

# Model defaults
DEFAULT_MODEL_NAME = "taipower_lightgbm_forecaster"
