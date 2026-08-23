# Frontend Dashboard

Streamlit-based interactive web dashboard for `shiro-mlops`.

## Features

- Real-time dynamic horizon load forecast visualization (1 to 72 hours).
- Dual-axis interactive chart comparing load (MW) with temperature (°C) via Plotly.
- Metric summary cards (Peak load, Average load, Max temperature).
- Backend service health and model status indicator.
- Downloadable forecast CSV data.

## Running Locally

1. Start the FastAPI backend server:

   ```bash
   make dev
   ```

2. Start the Streamlit frontend:

   ```bash
   uv run streamlit run frontend/app.py
   ```

   Dashboard is accessible at `http://localhost:8501`.
