"""LightGBM Recursive Multi-Step Time-Series Forecaster."""

from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from shiro_mlops.core.constants import (
    DATETIME_COL,
    DEFAULT_LAG_HOURS,
    DEFAULT_ROLLING_WINDOWS,
    LOAD_MW_COL,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.features.transformers import (
    create_calendar_features,
    create_lag_features,
    create_rolling_features,
)


class LightGBMRecursiveForecaster:
    """Recursive auto-regressive forecaster powered by LightGBM."""

    def __init__(
        self,
        lags: list[int] | None = None,
        windows: list[int] | None = None,
        params: dict | None = None,
    ):
        self.lags = lags or DEFAULT_LAG_HOURS
        self.windows = windows or DEFAULT_ROLLING_WINDOWS
        self.params = params or {
            "objective": "regression",
            "metric": "rmse",
            "boosting_type": "gbdt",
            "n_estimators": 100,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "random_state": 42,
            "verbose": -1,
        }
        self.model: lgb.LGBMRegressor | None = None
        self.feature_names: list[str] = []

    def fit(
        self, train_df: pd.DataFrame, feature_cols: list[str] | None = None
    ) -> "LightGBMRecursiveForecaster":
        """Train the LightGBM regressor on feature-engineered training data."""
        df = train_df.copy()
        if feature_cols is None:
            exclude_cols = {DATETIME_COL, LOAD_MW_COL, "location"}
            feature_cols = [c for c in df.columns if c not in exclude_cols]

        self.feature_names = feature_cols
        x_train = df[feature_cols]
        y_train = df[LOAD_MW_COL]

        self.model = lgb.LGBMRegressor(**self.params)
        self.model.fit(x_train, y_train)
        return self

    def predict_recursive(
        self,
        history_df: pd.DataFrame,
        future_weather_df: pd.DataFrame,
        horizon_hours: int = 24,
    ) -> pd.DataFrame:
        """Perform step-by-step recursive multi-step forecasting into the future horizon.

        Args:
            history_df: Historical load records (must contain at least max(lags) rows).
            future_weather_df: Exogenous weather forecast for future hours t=1..horizon_hours.
            horizon_hours: Number of future hours to predict.
        """
        if self.model is None:
            raise RuntimeError("Model must be fitted before predict_recursive can be called.")

        hist = history_df[[DATETIME_COL, LOAD_MW_COL]].copy()
        hist[DATETIME_COL] = pd.to_datetime(hist[DATETIME_COL])
        hist = hist.sort_values(DATETIME_COL).reset_index(drop=True)

        future_weather = future_weather_df.copy()
        future_weather[DATETIME_COL] = pd.to_datetime(future_weather[DATETIME_COL])
        future_weather = future_weather.sort_values(DATETIME_COL).reset_index(drop=True)

        if len(future_weather) < horizon_hours:
            horizon_hours = len(future_weather)

        predictions: list[dict] = []
        current_buffer = hist.copy()

        for step in range(horizon_hours):
            target_dt = future_weather.iloc[step][DATETIME_COL]
            target_temp = float(future_weather.iloc[step].get(TEMPERATURE_COL, 25.0))
            target_rh = float(future_weather.iloc[step].get(RELATIVE_HUMIDITY_COL, 70.0))

            # Create candidate row with dummy load to compute features
            dummy_row = pd.DataFrame(
                [
                    {
                        DATETIME_COL: target_dt,
                        LOAD_MW_COL: np.nan,
                        TEMPERATURE_COL: target_temp,
                        RELATIVE_HUMIDITY_COL: target_rh,
                    }
                ]
            )

            # Append dummy row to buffer to compute lag and rolling features
            extended = pd.concat(
                [current_buffer[[DATETIME_COL, LOAD_MW_COL]], dummy_row], ignore_index=True
            )
            extended = create_calendar_features(extended)
            extended = create_lag_features(extended, value_col=LOAD_MW_COL, lags=self.lags)
            extended = create_rolling_features(
                extended, value_col=LOAD_MW_COL, windows=self.windows
            )

            extended.loc[extended.index[-1], TEMPERATURE_COL] = target_temp
            extended.loc[extended.index[-1], RELATIVE_HUMIDITY_COL] = target_rh

            # Extract the last row features
            step_features = extended.iloc[[-1]][self.feature_names]

            # Predict current step load
            pred_value = float(self.model.predict(step_features)[0])

            predictions.append(
                {
                    DATETIME_COL: target_dt,
                    "predicted_load_mw": pred_value,
                    TEMPERATURE_COL: target_temp,
                    RELATIVE_HUMIDITY_COL: target_rh,
                }
            )

            # Update buffer with new prediction for subsequent recursive lags
            new_row = pd.DataFrame(
                [
                    {
                        DATETIME_COL: target_dt,
                        LOAD_MW_COL: pred_value,
                    }
                ]
            )
            current_buffer = pd.concat([current_buffer, new_row], ignore_index=True)

        return pd.DataFrame(predictions)

    def save(self, path: str | Path) -> None:
        """Save model artifact to disk."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "feature_names": self.feature_names,
                "lags": self.lags,
                "windows": self.windows,
            },
            path,
        )

    @classmethod
    def load(cls, path: str | Path) -> "LightGBMRecursiveForecaster":
        """Load model artifact from disk."""
        data = joblib.load(path)
        forecaster = cls(lags=data["lags"], windows=data["windows"])
        forecaster.model = data["model"]
        forecaster.feature_names = data["feature_names"]
        return forecaster
