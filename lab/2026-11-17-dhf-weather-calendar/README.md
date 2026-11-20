# `dynamic_horizon_forecast` 加權天氣與放假日採用研究

> [!NOTE]
> **狀態：尚未執行。** 研究腳本已備妥，待正式資料的有效評估起點涵蓋至少 7 個日曆日後執行（[GitHub #98](https://github.com/shiroki9979/shiro-mlops/issues/98)）。執行後依 [研究空間 §5](../../docs/reference/lab.md#5-研究報告labyyyy-mm-dd-topicreadmemd) 的固定段落與重現紀錄欄位改寫本檔，下列各段的數字必須來自同一次執行。

---

## 1. 問題 (Problem)

`dynamic_horizon_forecast` 的氣象輸入只有臺北一個氣象代表點，日曆特徵也分不出國定假日與補假。能力段（TICKET-301、302）已讓任務設定支援三點加權天氣與放假日特徵；本研究判定是否在 `dynamic_horizon_forecast.toml` 採用（[ADR-0012](../../docs/adr/0012-combine-weather-reference-points-into-weighted-weather.md)、[GitHub #95](https://github.com/shiroki9979/shiro-mlops/issues/95)）。

## 2. 快照 (Snapshot)

訓練表只保存加權後的天氣，因此每組天氣各凍結一份快照，兩份使用相同的 `as_of`；放假日只改 `[params]`，與同天氣的候選共用快照。

1. 推算權重並記錄計算期間、有效樣本數與四區占比：

   ```bash
   uv run --package lab python -m lab.regional_weights --start <start> --end <end>
   ```

2. 凍結基線快照與 `three-point` 快照：

   ```bash
   uv run --package lab python -m lab.snapshot dynamic_horizon_forecast --as-of <as_of>
   ```

   ```bash
   uv run --package lab python -m lab.snapshot dynamic_horizon_forecast --as-of <as_of> --variant three-point --reference-points Taipei Taichung Kaohsiung --weights <w_taipei> <w_taichung> <w_kaohsiung>
   ```

3. 確認兩份快照都提供足夠起點，兩次輸出的 `sufficient` 皆須為 `yes`：

   ```bash
   uv run --package lab python -m lab.origins dynamic_horizon_forecast --as-of <as_of>
   ```

   ```bash
   uv run --package lab python -m lab.origins dynamic_horizon_forecast --as-of <as_of> --variant three-point --reference-points Taipei Taichung Kaohsiung --weights <w_taipei> <w_taichung> <w_kaohsiung>
   ```

執行後在此記錄兩份快照的路徑（code span）、SHA-256、列數與時間範圍。

## 3. 回測設定 (Backtest Settings)

```bash
uv run --package lab python lab/2026-11-17-dhf-weather-calendar/study.py --as-of <as_of> --weights <w_taipei> <w_taichung> <w_kaohsiung> --output data/lab/dhf-weather-calendar-summary.json
```

- **研究腳本**：[`study.py`](study.py)（Jupytext `percent` 格式）。
- **預報視界**：`24` 小時；最低累積沿用 `policies.min_training_hours = 672`，不覆寫。
- **起點**：取四個候選合格起點的交集，每 6 小時取一個整點；評估起點為最後 7 個日曆日，搜尋起點為更早且目標時段不重疊者。交集不足 7 個日曆日時，腳本改以一半的日曆日作為評估起點，並輸出 `adoption_eligible: false`。
- **MLflow**：experiment `lab/dhf-weather-calendar`，每個候選一個 run，不建立 registered model。
- **觀測氣象聲明**：回測使用觀測氣象，結果為「氣象已知」條件下的條件式數字，不代表正式 serving 誤差。

## 4. 基線 (Baseline)

`baseline`：任務設定 TOML 的現行參數（臺北權重 1，`day_off = false`）。執行後記錄搜尋與評估起點的整體 MAPE、`1..24` 各分組 MAPE 與訓練列數。

## 5. 候選 (Candidates)

| 候選 | 天氣 | 放假日 |
| :--- | :--- | :--- |
| `day_off` | 臺北 | 開 |
| `three_point` | 臺北／臺中／高雄加權 | 關 |
| `three_point_day_off` | 臺北／臺中／高雄加權 | 開 |

執行後逐一記錄與基線相同的欄位；三點候選的訓練列數少於基線的部分，即為三點嚴格缺值造成的訓練列損失。

## 6. 結論 (Conclusion)

待執行。腳本以搜尋起點的整體 MAPE 選出最佳候選（`best_candidate_on_search`），再於評估起點與基線比較（`best_beats_baseline_on_eval`）。

## 7. 是否採用 (Adoption)

待執行。只有 `adopt: true`（評估起點涵蓋至少 7 個日曆日，且最佳候選在評估起點的整體 MAPE 低於基線）時才修改 `dynamic_horizon_forecast.toml`，在權重與開關旁加註解連回本報告，並將儀表板天氣欄位的語系字典改為「加權氣溫／加權濕度」（中英文）。否則 TOML 與前端不變，本報告作為探索報告保存。
