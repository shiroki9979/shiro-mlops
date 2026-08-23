"""Streamlit interactive frontend dashboard for shiro-mlops."""

import os

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

st.set_page_config(
    page_title="shiro-mlops | 台電用電負載動態預測平台",
    page_icon="⚡",
    layout="wide",
)

DEFAULT_API_URL = os.getenv("API_URL", "http://localhost:8000")


def check_api_health(api_url: str) -> dict | None:
    """Check health and model status of FastAPI backend."""
    try:
        resp = httpx.get(f"{api_url}/health", timeout=3.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_prediction(api_url: str, horizon_hours: int, location: str) -> dict | None:
    """Send prediction request to FastAPI /predict endpoint."""
    try:
        resp = httpx.post(
            f"{api_url}/predict",
            json={"horizon_hours": horizon_hours, "location": location},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json()
        st.error(f"API 回應錯誤 ({resp.status_code}): {resp.text}")
    except Exception as e:
        st.error(f"無法連線至後端 API: {e}")
    return None


# Sidebar
st.sidebar.title("⚡ 預報控制面板")
api_base_url = st.sidebar.text_input("後端 API 端點", value=DEFAULT_API_URL)
horizon = st.sidebar.slider("預測視界 (Horizon Hours)", min_value=1, max_value=72, value=24, step=1)
location = st.sidebar.selectbox(
    "觀測與預報區域", options=["Taipei", "Taichung", "Kaohsiung"], index=0
)
predict_btn = st.sidebar.button("發送隨需預測請求", type="primary", use_container_width=True)

# Main layout
st.title("⚡ 台電用電負載動態預測平台 (shiro-mlops)")
st.caption("基於 Feast 特徵庫、Dagster 流程編排與 LightGBM 遞迴自回歸之混合架構預測系統")

health = check_api_health(api_base_url)
col_h1, col_h2, col_h3 = st.columns(3)

with col_h1:
    if health and health.get("status") == "ok":
        st.success(f"後端服務正常 (v{health.get('version', '0.1.0')})")
    else:
        st.warning("⚠️ 後端服務離線或無法連線")

with col_h2:
    env_name = health.get("environment", "unknown") if health else "unknown"
    st.info(f"運行環境：{env_name.upper()}")

with col_h3:
    model_loaded = health.get("model_loaded", False) if health else False
    st.info(f"模型狀態：{'已載入 (Ready)' if model_loaded else '未就緒'}")

st.divider()

if predict_btn or "last_prediction" in st.session_state:
    if predict_btn:
        with st.spinner("正在向後端取得最新特徵並執行遞迴預測..."):
            pred_data = fetch_prediction(api_base_url, horizon, location)
            if pred_data:
                st.session_state["last_prediction"] = pred_data

    pred_data = st.session_state.get("last_prediction")

    if pred_data and "predictions" in pred_data:
        records = pred_data["predictions"]
        df = pd.DataFrame(records)
        df["datetime"] = pd.to_datetime(df["datetime"])

        # Metric summary cards
        peak_load = df["predicted_load_mw"].max()
        avg_load = df["predicted_load_mw"].mean()
        max_temp = df["temperature"].max()

        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("預測視界長度", f"{len(df)} 小時")
        m_col2.metric("預估尖峰負載", f"{peak_load:,.1f} MW")
        m_col3.metric("預估平均負載", f"{avg_load:,.1f} MW")
        m_col4.metric("最高氣溫預報", f"{max_temp:.1f} °C")

        # Interactive Plotly Dual Axis Chart
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # Load trace
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=df["predicted_load_mw"],
                name="預估用電負載 (MW)",
                line=dict(color="#38bdf8", width=3),
                mode="lines+markers",
            ),
            secondary_y=False,
        )

        # Temperature trace
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=df["temperature"],
                name="預報氣溫 (°C)",
                line=dict(color="#f97316", width=2, dash="dot"),
                mode="lines+markers",
            ),
            secondary_y=True,
        )

        fig.update_layout(
            title="未來動態視界用電負載與氣象預報疊圖",
            template="plotly_dark",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=20, r=20, t=60, b=20),
            height=480,
        )

        fig.update_yaxes(title_text="用電負載 (MW)", secondary_y=False, gridcolor="#334155")
        fig.update_yaxes(title_text="氣溫 (°C)", secondary_y=True, showgrid=False)

        st.plotly_chart(fig, use_container_width=True)

        # Tabular view & download
        with st.expander("檢視預測明細數據表格"):
            st.dataframe(df, use_container_width=True)
            csv_data = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="下載預報 CSV 檔案",
                data=csv_data,
                file_name=f"taipower_forecast_{location}_{len(df)}h.csv",
                mime="text/csv",
            )
else:
    st.info("請於左側側邊欄調整預測視界長度，並點擊「發送隨需預測請求」以繪製預報圖表。")
