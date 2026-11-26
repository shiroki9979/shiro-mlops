# Rules of ML 對照：本專案的 ML 工程準則

> - Created: 2026-11-26
> - Last Updated: 2026-11-26
> - Related: [Rules of Machine Learning](https://developers.google.com/machine-learning/guides/rules-of-ml)、[ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)、[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)、[ADR-0018](../adr/0018-access-research-data-through-data-freezes-and-knowledge-time.md)

本文消化 Martin Zinkevich 的《Rules of Machine Learning: Best Practices for ML Engineering》（Google，共 43 條規則），保留原文的規則編號與英文標題，逐條說明要點，並對照本專案已經怎麼做、還缺什麼、哪些條目不適用。原文以搜尋排序、廣告與推薦系統為例；本專案是以時間為索引的電力負載預報，需要轉譯的地方會說明轉譯方式。

本文是設計與審查時的參考，不是契約。契約在 `docs/reference/`，決策在 `docs/adr/`；本文的對照與它們不一致時，以 reference 與 ADR 為準，並在同一個 PR 修正本文。用語依 [GLOSSARY](../../GLOSSARY.md)。

## 1. 讀法

### 1.1 對照標記

| 標記 | 意義 |
| :--- | :--- |
| 已落實 | 專案已有對應的做法，對照指出出處 |
| 部分落實 | 有做法，但只涵蓋規則的一部分 |
| 缺口 | 規則適用，目前沒有對應做法；可能已有 ADR 延後或 issue 追蹤 |
| 未到階段 | 規則針對 Phase III 的處境，本專案尚未到達；只記可預見的觸發條件 |
| 低適用 | 規則針對排序、廣告或使用者互動，本專案的情境不同；只記轉譯或理由 |

缺口不等於技術債。要處理缺口時依 [issue-tracker.md](../agents/issue-tracker.md) 開 issue；刻意延後且會持續產生成本的，才依 [tech-debt.md](../agents/tech-debt.md) 登記。

### 1.2 依變更類型查規則

| 變更 | 先看的規則 |
| :--- | :--- |
| 新增 ML 任務或任務類型 | 1、3、4、13、15、16、40 |
| 改特徵配方、氣象代表點或新增資料來源 | 2、7、11、17、20、21、22、26、41 |
| 改訓練 objective、評估指標或健康門檻 | 12、13、14、25、38 |
| 改滾動起點回測或採用判定 | 24、28、33、37、39 |
| 改訓練、serving 或回測的資料路徑 | 5、6、29、31、32、37 |
| 改監控、訓練排程或模型安裝 | 8、9、10 |

### 1.3 維護

對照描述的是本文最後更新時的現況。PR 改變了某條對照所描述的行為（例如補上一個缺口），同一個 PR 更新該條對照與第 5 節的缺口總表。

## 2. 核心主張

原文的總綱是："do machine learning like the great engineer you are, not like the great machine learning expert you aren't." 多數問題是工程問題；多數收益來自好的特徵，而不是好的演算法。基本路線依序是：

1. 確保整條管線端到端可靠。
2. 從合理的目標開始。
3. 以簡單的方式加入合乎常識的特徵。
4. 確保管線持續可靠。

簡單的手段用盡之前不要偏離這條路線；每增加一分複雜度，之後的每次推出都會變慢。

本專案的里程碑順序與這條路線一致：先以 M6 重建全台逐時實際負載、讓訓練與排程跑通，再以 M7 把任務抽象經三個實際任務驗證，加權天氣與放假日等新特徵（M3）要等滾動起點回測贏過基線才採用（[ROADMAP](../ROADMAP.md)）。

原文把系統的生命週期分為三期，第 4 節沿用這個分期：

- **Phase I（第一條管線）**：把訓練資料送進學習系統、接上關心的指標、建立 serving 基礎設施。
- **Phase II（特徵工程）**：端到端系統與單元、系統測試就緒後開始；大量加入直觀的特徵，各項指標應持續上升。
- **Phase III（成長趨緩）**：每月收益遞減、指標之間開始此消彼長，才需要更精巧的方法。

本專案處於 Phase I 尾段到 Phase II 初期：管線已端到端運作，第一批新特徵（M3）的採用研究尚未有結論。

## 3. 用語對照

| 原文 | 原文的意思 | 本專案對應 |
| :--- | :--- | :--- |
| Instance | 要預測的對象 | 動態視界預報為一個目標小時；高負載預警為一組（負載起點，提前時數）；用電型態異常偵測為一個時間窗 |
| Label | 預測任務的答案 | 動態視界預報為目標小時的全台逐時實際負載；高負載預警為目標小時是否超過高負載門檻；用電型態異常偵測沒有標籤 |
| Feature | 實例用於預測的屬性 | lag、rolling、日曆（含 `is_day_off`）與加權天氣欄位 |
| Feature column | 一組相關的特徵 | 特徵配方的一個項目，例如 `lags` 產生的一組 `load_mw_lag_{L}` |
| Example | 實例與它的特徵加上標籤 | 訓練表的一列 |
| Model | 預測任務的統計表示 | 任務類型訓練出的一個模型版本，以模型目錄的 SHA-256 識別；實際回答預測的是現役模型 |
| Metric | 在意的數字，不一定直接最佳化 | MAPE、RMSE、MAE、precision／recall／F1、預報實績 |
| Objective | 演算法試圖最佳化的指標 | 任務類型固定的訓練 objective，例如遞迴回歸的 LightGBM `regression`（平方誤差） |
| Pipeline | 圍繞演算法的基礎設施 | Dagster 的鏈路：擷取、推算全台逐時實際負載、`{task_id}__features`、`{task_id}__model`、`{task_id}__monitoring`，以及已發布預報、預報實績與預報檢視匯出 |

## 4. 逐條對照

### 4.1 開始 ML 之前（Rule 1–3）

#### Rule 1：不怕推出沒有 ML 的產品

原文：*Don't be afraid to launch a product without machine learning.*

- **要點**：ML 需要資料。沒有資料時，簡單的啟發式（heuristic）常能拿到 ML 一半的收益；除非產品非 ML 不可，否則先有資料再用 ML。
- **對照（缺口）**：有效逐時觀測達最低累積（動態視界預報為 672 小時）之前任務不訓練，這段期間系統只累積資料，符合「先有資料」。缺的是正式的啟發式比較基準：滾動起點回測的基線是任務設定 TOML 的現行參數，[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md) 把「季節性天真預報」等比較基準列為延後。沒有這條基準，就回答不了「LightGBM 比上週同小時的負載好多少」，Rule 39 的推出判斷也需要它。

#### Rule 2：先設計並實作指標

原文：*First, design and implement metrics.*

- **要點**：在定義 ML 系統要做什麼之前，就盡量記錄現行系統的一切：日後才擔心的問題，現在就有歷史資料；以指標為前提設計系統，比事後在 log 裡 grep 好；也能看出哪些指標會動、哪些不會。發現問題就加指標。原文也強調能分組彙整統計的實驗框架。
- **對照（已落實）**：本專案的資料多半無法回補，「現在就保存歷史」最為關鍵。全台逐時實際負載只能自開始累積時往後取得（[ADR-0008](../adr/0008-derive-hourly-actual-load-from-regional-snapshots.md)）；預報實績只能自開始發布後累積，所以 [ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md) 選擇盡早定時發布；擷取範圍獨立於任務設定，事後新增的任務才有歷史可用（[ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md) 候選方案 E）。原文的使用者分組實驗在此沒有對應；比較候選的機制是滾動起點回測（Rule 33）。

#### Rule 3：與其用複雜的啟發式，不如用 ML

原文：*Choose machine learning over a complex heuristic.*

- **要點**：簡單的啟發式能讓產品先推出，複雜的啟發式無法維護。有了資料、也大致知道目標之後，就改用 ML；ML 模型比層層堆疊的規則容易更新。
- **對照（已落實）**：專案中的啟發式都保持單層、說得清楚：降級預報的替代順序（測站前日同小時觀測、同月份同小時歷史平均）、高負載門檻（錨點前 28 日的 P90）。需要隨資料調整的判斷交給模型與任務設定參數，而不是增加規則分支。新增啟發式時，先看 Rule 7 的四種用法。

### 4.2 Phase I：第一條管線（Rule 4–7）

原文：第一條管線先專注於系統基礎設施；不先信任管線，就很難弄清楚發生了什麼。

#### Rule 4：第一個模型保持簡單，先把基礎設施做對

原文：*Keep the first model simple and get the infrastructure right.*

- **要點**：第一個模型帶來最大的提升，不需要花俏；真正花時間的是基礎設施：怎麼把樣本送進演算法、「好」與「壞」的初步定義、怎麼把模型接進應用（即時計算，或預先計算後存表）。簡單的特徵讓你容易確認特徵正確送達訓練與 serving、模型學到合理的權重。簡單模型也提供日後比較的基線。
- **對照（已落實）**：動態視界預報以單一 LightGBM 遞迴預報器為基線（[ADR-0003](../adr/0003-recursive-multi-step-forecasting.md)），特徵只有 lag、rolling、日曆與天氣。兩種接法都有：隨需 `/predict` 即時計算；已發布預報每小時預先計算並保存（[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)），預報檢視只呈現預先算好的結果（[ADR-0015](../adr/0015-publish-forecast-view-as-static-precomputed-output.md)）。

#### Rule 5：把基礎設施與 ML 分開測試

原文：*Test the infrastructure independently from the machine learning.*

- **要點**：把學習的部分封裝起來，周圍的一切都要可測。具體是兩端：資料進入演算法（該有值的特徵欄有值、在隱私許可下人工檢視輸入、與他處處理的同一份資料比對統計）；模型離開訓練（訓練環境與 serving 環境中的同一模型給出相同分數）。serving 也要能載入並使用一個固定的模型。
- **對照（已落實）**：`tests/` 全部離線、以 `tests/fixtures/` 為資料（[AGENTS.md](../../AGENTS.md)）；任務類型是不接觸 repository 的純計算 adapter，有公開介面層級的單元測試（[ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)）。資料進入端：預測輸入關卡在交給任務類型前檢查負載 lookback 與目標時段天氣完整（[ML 任務設定 §2](../reference/ml-tasks.md#2-任務類型介面taskstypes)）。模型離開端：訓練固定 seed，相同資料得到相同模型與相同的模型目錄雜湊；載入時比對模型的輸入配方與任務設定，不一致即拒絕（`ModelRecipeMismatchError`）；[test_recursive_regression.py](../../tests/unit/test_recursive_regression.py) 檢查以實際歷史預測一小時時，推論端的特徵等於該小時的訓練列。

#### Rule 6：複製管線時小心被丟掉的資料

原文：*Be careful about dropped data when copying pipelines.*

- **要點**：新管線常複製自舊管線，而舊管線為自己的目的丟掉的資料，正是新管線需要的。原文的例子包括只保留新貼文、只記錄使用者看過的內容（負樣本因此全被丟掉），以及混入來源不同、卻沒有特徵可以區分的樣本。
- **對照（部分落實）**：專案遇過同類問題並已收斂：特徵配方曾有三套不一致的 lag 設定，已收斂為任務設定單一來源（[ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)）；全台逐時實際負載的舊口徑列（`source IS NULL`）會阻擋訓練而不會混入（[ML 任務設定 §3](../reference/ml-tasks.md)）；隨需請求不記為已發布預報，避免樣本取決於誰在何時請求（[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md) 候選方案 D）。仍須留意的是 Feast 匯出：它自行計算特徵、不共用任何任務的特徵配方，也沒有正式讀取者（[資料契約 §4](../reference/data-contracts.md)）；有新用途要讀它時，先確認它的欄位與丟棄規則合乎新用途。

#### Rule 7：把啟發式轉為特徵，或在模型外處理

原文：*Turn heuristics into features, or handle them externally.*

- **要點**：要解決的問題多半已有現行規則，裡面藏著對系統的直覺，不要丟掉。四種用法：以啟發式做前處理（例如已列黑名單的寄件者直接擋下）、把啟發式的輸出直接當特徵、拆出啟發式的原始輸入分別餵給模型、以啟發式修改標籤。同時要留意增加的複雜度，想想有沒有更簡單的做法。
- **對照（已落實）**：高負載門檻同時定義標籤並作為特徵：標籤為目標小時負載是否超過錨點的門檻，`threshold_mw` 也是特徵（[ML 任務設定 §2](../reference/ml-tasks.md#2-任務類型介面taskstypes)）。政府辦公日曆以 `is_day_off` 特徵進入模型。天氣解析、預報版本回退與降級則在模型外處理，任務類型只收到完整的天氣值。

### 4.3 Phase I：監控（Rule 8–11）

原文：一般的告警衛生同樣適用：告警要能採取行動，並且要有儀表板。

#### Rule 8：了解系統的時效需求

原文：*Know the freshness requirements of your system.*

- **要點**：模型舊了一天、一週、一季，表現各降多少？答案決定監控的優先順序。時效需求也會隨特徵增減而改變。
- **對照（部分落實）**：輸入資料的時效有明確規則：負載起點落後超過 `stale_anchor_max_lag_hours`（現為 3 小時）時不產出預報；天氣欄位由七小時內發布的預報版本提供，才是正常預報；營運資料檢視器判定各資料集的資料新鮮度。模型本身的時效需求沒有量測：每日訓練一次是設定值，不是由「模型舊了多久會變差多少」推得。可在研究空間以固定的模型對之後的起點回測，量出誤差隨模型年齡的變化。

#### Rule 9：匯出模型前先偵測問題

原文：*Detect problems before exporting models.*

- **要點**：匯出到 serving 的模型出問題，就是使用者看得到的問題。匯出前做健全性檢查，例如確認保留資料上的表現合理；對資料仍有疑慮就不要匯出。未匯出模型的問題寄信即可，面對使用者的模型出問題可能要呼叫值班。
- **對照（缺口）**：`{task_id}__model` 訓練完成後即以 `save_model` 原子交換進模型目錄（[task_pipelines.py](../../src/shiro_mlops/pipelines/task_pipelines.py)），已發布預報每個 tick 重新載入模型，下一次發布就使用它；健康判定在之後的 `{task_id}__monitoring` 執行，`WARNING` 只回報、不阻擋安裝（[Dagster 排程](../reference/dagster-schedules.md)）。已有的防線是：輸入配方不符時拒絕載入，高負載預警的訓練標籤只有單一類別時拒絕訓練。

  補這個缺口時要與 [ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md) 區分。該 ADR 決定健康檢查為 `WARNING` 時照常發布，理由是暫停發布會讓預報實績避開表現差的期間。安裝關卡處理的是另一件事：新訓練的模型未通過檢查時，保留前一版繼續當現役模型，發布本身不中斷。

#### Rule 10：留意靜默失敗

原文：*Watch for silent failures.*

- **要點**：ML 系統比其他系統更容易靜默失敗：被 join 的表停止更新，系統仍會調適，表現緩慢衰退；特徵的涵蓋率可能因實作變更從 90% 掉到 60%。追蹤資料的統計並偶爾人工檢視資料，可以減少這類失敗。
- **對照（部分落實）**：專案把輸入不足設計成顯式拒絕，而不是帶著缺值推演：負載起點過舊、天氣無覆蓋、lookback 內的負載不足任務類型宣告的涵蓋，都拋出領域錯誤並對應 HTTP 503；資料庫錯誤不得轉為空資料而偽裝成資料缺口；驗證列為空時不回報指標（不以 `0.0` 佔位），缺少指標的健康判定一律為 `WARNING`（[ML 任務設定](../reference/ml-tasks.md)）。專案也實際遇過一次：lookback 內缺負載時，lag 以 NaN 交給 LightGBM，等於以 0 MW 遞迴推演，預報卻仍標為正常預報（[#226](https://github.com/shiroki9979/shiro-mlops/issues/226)，見 [2026-11-22 架構檢視](2026-11-22-architecture-review.md)候選 1），現由預測輸入關卡拒絕。

  缺的是特徵涵蓋率與分佈的持續追蹤。[GLOSSARY](../../GLOSSARY.md) 定義了特徵漂移與概念漂移，但 `{task_id}__monitoring` 只以訓練當時的驗證指標判定健康（[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md) §1），沒有比較近期輸入與基準分佈。訓練列因加權天氣嚴格缺值而減少多少，目前也只在研究時以 `training_row_count` 揭露（[研究空間](../reference/lab.md)）。

#### Rule 11：特徵欄要有負責人與文件

原文：*Give feature columns owners and documentation.*

- **要點**：系統大、特徵欄多時，要知道誰建立或維護每個特徵欄；除了描述性的名稱，還要寫下特徵是什麼、從哪裡來、預期怎麼幫助模型。
- **對照（已落實）**：特徵配方與模型超參數的唯一來源是任務設定 TOML 的 `[params]`，經 Pydantic 驗證；各任務類型產生哪些特徵、取自哪些欄位寫在 [ML 任務設定](../reference/ml-tasks.md)，入庫資料的來源與欄位寫在[資料契約](../reference/data-contracts.md)；模型的 `metadata.json` 記錄特徵名稱。研究採用的參數要在 TOML 參數旁以註解連回研究報告，保留「預期怎麼幫助」的證據（[研究空間 §5](../reference/lab.md)）。沒有逐特徵的負責人紀錄；責任以 GLOSSARY 的研究者與平台維護者兩個角色劃分。

### 4.4 Phase I：第一個目標（Rule 12–15）

原文先區分指標與目標：指標是系統回報的任何數字，不一定重要；目標是演算法「試圖」最佳化的那一個數字。

#### Rule 12：不要過度糾結於直接最佳化哪個目標

原文：*Don't overthink which objective you choose to directly optimize.*

- **要點**：早期最佳化任何一個合理的目標，其他指標通常都會一起上升，不必苦思如何平衡多個指標。但不要把目標當成系統的整體健康；直接最佳化的指標上升，卻決定不推出時，就該修訂目標。
- **對照（已落實）**：各任務類型固定自己的 objective，任務設定不能改：遞迴回歸以平方誤差訓練（LightGBM `regression`），健康判定看驗證期 MAPE，預報檢視的標題數字是提前 24 小時的 MAPE 與 MAE。三者不同但方向一致，目前不需要調整。若日後研究出現「訓練誤差下降、採用判定卻不採用」的情形，依本規則回頭檢視 objective。

#### Rule 13：第一個目標選簡單、可觀察、可歸因的指標

原文：*Choose a simple, observable and attributable metric for your first objective.*

- **要點**：真正的目標往往說不清，團隊也不一定有共識。ML 的目標應容易量測，作為「真正」目標的代理。最容易建模的是直接觀察到、可歸因於系統行為的事件；間接效果適合當指標，不適合當第一個目標；使用者是否滿意之類的問題不要交給 ML。可以在模型之上加一層簡單的 policy layer 處理最終決策。
- **對照（已落實）**：三個任務的目標都是直接觀察到的量：目標小時的全台逐時實際負載，或它是否超過門檻；用電型態異常偵測沒有標籤，以合成異常注入評估。電網調度好壞等間接效果不建模。policy layer 也已存在且保持簡單：正常預報、降級預報與無法產出的判定在 runner，高負載預警以 `probability >= 0.5` 判定 `is_high_load`，異常門檻取校準窗重建誤差的分位數。

#### Rule 14：從可解釋的模型開始，比較好除錯

原文：*Starting with an interpretable model makes debugging easier.*

- **要點**：線性、邏輯與 Poisson 迴歸的預測可解讀為機率或期望值，因此容易除錯：訓練時的機率與正式環境觀察到的機率有落差，就揭露了問題。這類模型在許多資料子集上是校準的（子集的平均預測等於平均標籤）。選模型時，決策品質比資料在模型下的概似（likelihood）重要。
- **對照（部分落實）**：專案從 LightGBM 開始，不是線性模型，但仍可借用這條規則的除錯方法：檢查各子集的平均誤差（偏差）是否接近 0。現行的 MAPE、RMSE、MAE 都是絕對誤差，看不出系統性高估或低估；可在預報實績或回測中依小時、放假日、提前時數檢視平均誤差。高負載預警以 0.5 為 `probability` 的界線，前提是機率大致校準，目前沒有檢查校準度。

#### Rule 15：在 policy layer 分開處理垃圾過濾與品質排序

原文：*Separate Spam Filtering and Quality Ranking in a Policy Layer.*

- **要點**：品質排序針對善意的內容；垃圾過濾是一場對抗，特徵一直在變，模型要頻繁更新。兩者分開建模，最後在 policy layer 整合；訓練品質分類器時，通常先從訓練資料移除垃圾。
- **對照（低適用）**：本專案沒有對抗性的輸入。可轉譯的是「異常與常態分開建模」：用電型態異常偵測是獨立的 ML 任務，不混入動態視界預報（[ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)）。原文「先移除垃圾」對應的問題是：颱風停班停課等用電型態異常的期間，是否該從預報模型的訓練資料排除。這是要以滾動起點回測判定的研究問題。

### 4.5 Phase II：特徵工程（Rule 16–22）

原文：端到端系統與單元、系統測試就緒後進入 Phase II。這一期有很多唾手可得的成果：盡量引入直觀的特徵、以直觀的方式組合，各項指標應持續上升。

#### Rule 16：規劃推出與迭代

原文：*Plan to launch and iterate.*

- **要點**：現在的模型不會是最後一個。推出新模型的理由有三：新特徵、調整正則化並以新方式組合舊特徵、調整目標。所以要想想這次增加的複雜度會不會拖慢之後的推出、特徵是否容易增減與重組、能否輕易建立一份新的管線並驗證正確、能否平行跑兩三份。
- **對照（已落實）**：調整參數只改任務設定 TOML、不改程式，新增同類型任務只需新增一份設定檔（[ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)）；研究空間的結論以 PR 修改 TOML 採用（[ADR-0011](../adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)）；每個任務有獨立的 Dagster 資產、MLflow experiment 與模型目錄，可平行運作。M11 的模型交付包與三層形狀契約，目的也是讓研究者頻繁交付時不必修改 `src/`（[模型交付包的三層形狀契約](three-layer-handoff-shape-contract.md)）。

#### Rule 17：先用直接觀察與回報的特徵，而非學習出來的特徵

原文：*Start with directly observed and reported features as opposed to learned features.*

- **要點**：學習出的特徵來自外部系統（例如非監督式分群）或學習器本身（例如因子模型、深度學習），不要放進第一個模型。外部系統有自己的目標，與你的目標可能只弱相關；取它的快照會過時，持續更新又可能改變意義。非凸模型每次訓練的結果不同，難以判斷一次變更的影響是真的還是隨機的。
- **對照（已落實）**：特徵都是直接觀察或發布的量：負載的 lag 與 rolling、日曆、測站觀測與氣象署預報。高負載預警刻意不串接動態視界預報的輸出（[ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md) 候選方案 G）。要留意的外部系統是氣象署預報：它是另一個系統的產出，氣象署改版預報作業或產品時，同名欄位的意義與誤差特性可能改變。serving 以預報天氣推論、訓練以觀測天氣建特徵的差異，見 Rule 37。

#### Rule 18：探索能跨情境泛化的內容特徵

原文：*Explore with features of content that generalize across contexts.*

- **要點**：ML 系統常只是大局的一小部分。內容在其他情境的統計（例如在別處的分享、觀看次數），能讓系統推廣它在目前情境還沒有資料的新內容。
- **對照（低適用）**：這條針對推薦新內容的冷啟動。本專案最接近的是加權天氣：以多個氣象代表點的天氣代表一個預測對象（[ADR-0012](../adr/0012-combine-weather-reference-points-into-weighted-weather.md)）。

#### Rule 19：能用非常具體的特徵時就用

原文：*Use very specific features when you can.*

- **要點**：資料量很大時，學習數百萬個簡單特徵比學習少數複雜特徵容易；每個特徵只涵蓋一小部分資料也無妨，以正則化剔除涵蓋太少的特徵。
- **對照（低適用）**：前提是海量資料。本專案的訓練資料以小時計（最低累積 672 小時），適用的是 Rule 21：特徵數要與資料量相稱。

#### Rule 20：以人能理解的方式組合與修改既有特徵

原文：*Combine and modify existing features to create new features in human-understandable ways.*

- **要點**：最標準的兩種做法是離散化與交叉。離散化把連續特徵切成區間，用基本的分位數即可，不必糾結邊界；交叉組合兩個以上的特徵欄，三四個以上的交叉需要極大量資料，產生的特徵太多會過擬合。
- **對照（已落實）**：日曆特徵都是人能理解的轉換：`hour`、`dayofweek`、`month`、`is_weekend`、小時的 sin／cos 編碼與 `is_day_off`。LightGBM 以樹的切分自行學習區間與交互作用，不需要手動交叉；要加入交互項時，依本規則保持可解讀，並照 Rule 21 衡量資料量。

#### Rule 21：線性模型可學習的特徵權重數，約與資料量成正比

原文：*The number of feature weights you can learn in a linear model is roughly proportional to the amount of data you have.*

- **要點**：模型的複雜度要隨資料量調整。原文的量級：一千個樣本配十來個高度人工設計的特徵；上千萬個樣本可以有約十萬個特徵；數十億個樣本才考慮千萬級的特徵。統計學習理論很少給出緊的界，但這是好的起點。
- **對照（已落實）**：本專案處於小資料區間：動態視界預報的最低累積為 672 小時，高負載預警為 1344 小時（[ML 任務設定 §1](../reference/ml-tasks.md)）。特徵維持十多個，研究時調整的也只是少數 lag 與 rolling 組合（[超參數研究](../../lab/2026-11-08-dhf-hyperparameter-search/README.md)）。值得在研究中檢查的例子：訓練資料只涵蓋數週時，`month` 在訓練列中只有一兩個值，模型學不到月份效應，換月後還會遇到訓練時沒見過的值。

#### Rule 22：清掉不再使用的特徵

原文：*Clean up features you are no longer using.*

- **要點**：未使用的特徵是技術債，會拖慢嘗試新特徵的速度；需要時隨時可以加回來。考慮特徵去留時看涵蓋率：只涵蓋少數樣本的特徵通常沒用，但涵蓋率低而判別力極強的特徵例外。
- **對照（部分落實）**：特徵配方收斂到任務設定後，從未進入訓練的 lag 3 已在 [ADR-0003](../adr/0003-recursive-multi-step-forecasting.md) 註記，舊版資產與排程已移除（[Dagster 排程](../reference/dagster-schedules.md)）。尚未收尾的是 Feast：它凍結為動態視界預報任務的專屬匯出，沒有正式讀取者，是否移除另案評估（[ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)、[#104](https://github.com/shiroki9979/shiro-mlops/issues/104)）。

### 4.6 Phase II：人工分析系統（Rule 23–28）

原文：進入 Phase III 前，要學會檢視既有的模型並改進它；這比較像藝術而非科學，但有幾個反模式可以避開。

#### Rule 23：你不是典型的使用者

原文：*You are not a typical end user.*

- **要點**：團隊太接近程式碼，也有確認偏誤，自己試用的感受不能代表使用者。接近正式的變更要以群眾外包評分或線上實驗驗證；想要使用者回饋，就用使用者經驗的方法（persona、可用性測試）。
- **對照（低適用）**：模型品質以預報與事後實際負載的對照判定，不靠人的觀感，這條在模型層面不適用。對公開的預報檢視仍有參考價值：版面與文案是否易懂，不能只由開發者自己判斷。

#### Rule 24：量測模型之間的差異

原文：*Measure the delta between models.*

- **要點**：在任何人看到新模型之前，最容易也最有用的量測是新結果與正式結果差多少。差異很小，不用實驗也知道變化不大；差異很大，就要確認變化是好的，並檢視差異最大的案例。同時要確認系統穩定：模型與自己比較，差異應該很低，理想上為零。
- **對照（缺口）**：平台模型每日重新訓練後直接取代前一版（Rule 9），沒有比較新舊模型對同一負載起點的預報差多少。已有的基礎：固定 seed 使相同資料得到相同模型，自我比較的差異為零；每份已發布預報都記下 `model_sha256`，事後可依模型版本切分預報實績（[資料契約](../reference/data-contracts.md)），但依版本的分析屬工程主控台，[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md) 列為延後。最小的做法是安裝前以新舊模型對最新的負載起點各推演 168 小時，記錄兩條曲線的差異。

#### Rule 25：選模型時，實用表現勝過預測力

原文：*When choosing models, utilitarian performance trumps predictive power.*

- **要點**：關鍵是拿預測去做什麼。用來排序就看排序品質，用門檻過濾就看放行內容的精確率。某個變更改善 log loss 卻讓系統表現變差時，就找別的特徵；這種情形變多時，就該重新檢視目標。
- **對照（已落實）**：各任務的評估都對準用途：高負載預警以判定門檻下的 precision／recall／F1 判定健康，而非 log loss；用電型態異常偵測看合成異常召回率與乾淨資料誤報率；預報檢視的標題數字取提前 24 小時，對應日前預測的用途（[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md) 候選方案 G）。要留意的是動態視界預報：健康判定的 MAPE 是驗證列上的單步誤差，營運上的用途卻是最多 168 小時的多步預報（見 Rule 37）。

#### Rule 26：從量測到的誤差中找模式，建立新特徵

原文：*Look for patterns in the measured errors, and create new features.*

- **要點**：模型「知道」自己錯的樣本，才會使用能修正它的特徵；針對系統不認為是錯誤的樣本做特徵，會被忽略。找出誤差中、目前特徵集以外的趨勢再加特徵；不要太具體，給模型一組特徵讓它自己決定怎麼用。
- **對照（部分落實）**：依提前時數分組的誤差已有（滾動起點回測的 `mape_by_horizon`、預報實績的提前時數曲線）；依小時、放假日等其他維度分組，要靠研究時自行分析。M3 的放假日特徵屬於這一類：舊的日曆特徵分不出國定假日與補假（[研究報告](../../lab/2026-11-17-dhf-weather-calendar/README.md)）。GLOSSARY 定義的預報實績回顧，即說明誤差在哪些時段偏大與可能原因的紀錄，是找模式的正式管道。

#### Rule 27：設法量化觀察到的不良行為

原文：*Try to quantify observed undesirable behavior.*

- **要點**：團隊對現有損失函數沒有涵蓋的系統行為不滿時，要把抱怨轉成具體的數字；可量測的問題才能變成特徵、目標或指標。原則是「先量測，再最佳化」（measure first, optimize second）。
- **對照（已落實）**：專案的判定都以數字為據：採用判定以 `candidate.beats(baseline)` 比較評估起點上的 MAPE（[研究空間 §2](../reference/lab.md#2-滾動起點回測labbacktestpy)），預報實績回顧的每項說法都要標明依據的證據（[GLOSSARY](../../GLOSSARY.md)）。遇到「尖峰時段好像總是低估」這類觀感，先在預報實績或回測中量出來，再決定改特徵或改目標。

#### Rule 28：短期行為相同，不代表長期行為相同

原文：*Be aware that identical short-term behavior does not imply identical long-term behavior.*

- **要點**：新系統在並排比較與 A/B 測試中與舊系統幾乎一樣，推出後仍可能出現長期才看得到的差異；原文的例子是只依各文件自身歷史排序的系統，永遠學不會展示新內容。要了解長期行為，只能讓它以上線後取得的資料訓練，這很困難。
- **對照（部分落實）**：本專案的長期風險來自季節與遞迴。訓練資料只涵蓋數週時，評估起點都落在同一季，夏季冷氣負載等型態要到季節轉換才看得到；遞迴預報的誤差隨步數累積，長視界的表現與前幾步不同（[ADR-0003](../adr/0003-recursive-multi-step-forecasting.md)）。已有的緩解是 M3 採用研究要求評估起點涵蓋至少 7 個日曆日（[ROADMAP](../ROADMAP.md)），以及依提前時數分組的 MAPE。季節轉換的影響只能靠持續累積的預報實績觀察。

### 4.7 Phase II：訓練與 serving 偏差（Rule 29–37）

原文定義 training-serving skew 為訓練時與 serving 時表現的差異，成因有三：訓練與 serving 管線處理資料的方式不同；訓練到 serving 之間資料改變；模型與演算法之間的回饋迴路。最好的解法是明確監控它，讓系統與資料的變更不會悄悄引入偏差。

本專案最主要的偏差來源是天氣：訓練一律以測站觀測天氣建特徵（`TrainingData.weather`），serving 以氣象署預報或降級來源推論（[ML 任務設定 §2](../reference/ml-tasks.md#2-任務類型介面taskstypes)）。遞迴預報另有一個結構性差異：訓練時的 lag 都是實際負載，推論時從第二步起，lag 開始包含模型自己的預測。

#### Rule 29：要確保訓練如同 serving，最好的方法是保存 serving 時的特徵，訓練時拿來用

原文：*The best way to make sure that you train like you serve is to save the set of features used at serving time, and then pipe those features to a log to use them at training time.*

- **要點**：即使無法對每個樣本都這樣做，也至少對一小部分做，才能驗證訓練與 serving 一致。原文提到改為在 serving 時記錄特徵的團隊，品質明顯改善，程式也變簡單。
- **對照（缺口）**：已發布預報只保存每步的 `predicted_load_mw`，不保存天氣值與天氣來源（[資料契約 §3](../reference/data-contracts.md)）；隨需 `/predict` 的回應帶有 `weather_sources`，但不保存。[ADR-0018](../adr/0018-access-research-data-through-data-freezes-and-knowledge-time.md) 把「已發布預報保存當時的輸入」與「研究者是否以預報天氣訓練」都列為延後。ADR-0018 的知悉時間是另一條路：以 `created_at <= T` 篩選，重建 T 時點已知的輸入，再以 serving 的解析規則推論。重建能否等於 serving 實際用到的值，取決於解析程式之後沒有改變、資料沒有被覆寫；保存 serving 時的值才能直接驗證。

#### Rule 30：抽樣的資料要做重要性加權，不要任意丟棄

原文：*Importance-weight sampled data, don't arbitrarily drop it!*

- **要點**：資料太多時，不要只取前幾個檔案而丟掉其餘。以機率 p 抽樣的樣本給予 1/p 的權重，Rule 14 的校準性質才會保留。
- **對照（低適用）**：本專案不抽樣，資料都用。相近的風險是缺值造成的丟棄：缺任一 lag 或天氣的訓練列會被剔除，加權天氣在任一代表點缺值的整點沒有加權值（[ML 任務設定 §3](../reference/ml-tasks.md)）。缺值若集中在特定時段（例如擷取中斷常發生在某些小時），剔除會讓訓練資料偏向其他時段。研究時以 `training_row_count` 揭露訓練列的損失，必要時檢視被剔除的列分布在哪裡。

#### Rule 31：訓練與 serving 時從表中 join 資料，表的內容可能已經改變

原文：*Beware that if you join data from a table at training and serving time, the data in the table may change.*

- **要點**：訓練到 serving 之間，join 進來的特徵值可能已被更新，同一筆樣本的預測因此不同。最簡單的解法是在 serving 時記錄特徵（Rule 29）；表變動緩慢時，也可以每小時或每天保存一份表的副本，但無法完全解決。
- **對照（部分落實）**：這正是 [ADR-0018](../adr/0018-access-research-data-through-data-freezes-and-knowledge-time.md)（`Proposed`）要處理的問題：現行的 point-in-time 參數只篩資料時間、不篩本系統何時取得資料，以過去的 T 回溯，會看到 T 之後才入庫的資料。ADR-0018 以知悉時間（`created_at <= T`）篩選預測輸入，並以凍結資料取代訓練表快照。在它實作之前，滾動起點回測的起點只在「資料時間不晚於起點」的意義上是 point-in-time。

#### Rule 32：盡可能在訓練與 serving 管線之間共用程式

原文：*Re-use code between your training pipeline and your serving pipeline whenever possible.*

- **要點**：批次與線上處理不同，但可以把查詢與 join 的結果存成人能讀、容易測試的物件，訓練與 serving 都經同一個方法轉成模型要的格式，消除一個偏差來源。訓練與 serving 不要用兩種程式語言。
- **對照（已落實）**：預測輸入關卡（`admit_prediction_inputs`）是 serving 與滾動起點回測共用的入口，兩者接受同一批起點（[ML 任務設定 §2](../reference/ml-tasks.md#2-任務類型介面taskstypes)）；研究空間直接呼叫 `src/` 的 runner 與任務類型，不另寫研究版的特徵轉換（[ADR-0011](../adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)）；日曆特徵在訓練與推論都由 `create_calendar_features` 產生。例外是遞迴回歸的 lag 與 rolling：訓練以 pandas 特徵管線計算，推論以逐步更新的歷史緩衝計算，兩份實作由 parity 測試約束（[test_recursive_regression.py](../../tests/unit/test_recursive_regression.py)）。修改任一邊的特徵計算時，parity 測試要涵蓋改動的部分。

#### Rule 33：以 1 月 5 日以前的資料訓練的模型，用 1 月 6 日以後的資料測試

原文：*If you produce a model based on the data until January 5th, test the model on the data from January 6th and after.*

- **要點**：以訓練資料之後蒐集的資料評估模型，較能反映正式表現。新資料上的表現會差一些，但不應差太多。
- **對照（已落實）**：依時間切分是共用元件：runner 以 `validation_fraction` 推導 `validation_start`，任務類型不得自行切分（[ML 任務設定 §2](../reference/ml-tasks.md#2-任務類型介面taskstypes)）。滾動起點回測在每個起點只用起點以前的資料訓練；超參數搜尋與採用判定分用兩組起點，評估起點全部晚於搜尋起點，且兩組的目標時段不重疊（[研究空間 §3](../reference/lab.md#3-搜尋起點與評估起點)）。GLOSSARY 也明列不以會打亂時間順序的交叉驗證代替滾動起點回測。

#### Rule 34：在過濾用的二元分類中，以短期表現換取非常乾淨的資料

原文：*In binary classification for filtering (such as spam detection or determining interesting emails), make small short-term sacrifices in performance for very clean data.*

- **要點**：被過濾掉的樣本使用者看不到，事後只從放行的樣本學習會有抽樣偏差。保留一小部分流量不過濾（例如 1%），作為乾淨的訓練資料；只要量測 serving 表現時，更小的樣本也夠。
- **對照（低適用）**：本專案的預測不會遮蔽任何觀測：不論預報或預警說什麼，全台逐時實際負載都照常入庫，標籤沒有因預測而產生的抽樣偏差。

#### Rule 35：留意排序問題固有的偏差

原文：*Beware of the inherent skew in ranking problems.*

- **要點**：大幅改變排序演算法，就改變了演算法日後會看到的資料。原文的對策包括對涵蓋多個查詢的特徵加強正則化、只允許正權重、不用只依文件本身的特徵。
- **對照（低適用）**：本系統的預報不回饋到電網調度，模型看到的資料不受自己的輸出影響。若日後預報被用於會影響負載的決策（例如需量反應），這條規則與 Rule 36 要重新檢視。

#### Rule 36：避免位置特徵造成的回饋迴路

原文：*Avoid feedback loops with positional features.*

- **要點**：內容的位置大幅影響使用者互動的機率。訓練時加入位置特徵，serving 時所有候選給同一個預設值；位置特徵要與其他特徵分開，例如讓模型成為兩者各自函數之和，不要與文件特徵交叉。
- **對照（低適用）**：沒有位置特徵。可借用的是「訓練與 serving 語意不對稱的特徵要隔離並量測」：遞迴預報的 lag 在訓練時是實際負載，在 serving 時多半是預測值，它的影響以多步評估量測（Rule 37）；高負載預警的 `lead_hours` 則訓練與 serving 同義。

#### Rule 37：量測訓練與 serving 的偏差

原文：*Measure Training/Serving Skew.*

- **要點**：偏差分三段：訓練資料與保留資料的表現差，一定存在，不一定是壞事；保留資料與「隔日」資料的表現差，也一定存在，正則化應以隔日表現為準調整，落差大表示有特徵對時間敏感；隔日資料與即時資料的表現差，同一樣本在訓練與 serving 應得到完全相同的結果，落差多半是工程錯誤。
- **對照（部分落實）**：三段在本專案的量測如下。原文的保留資料對應本專案依時間切分的驗證列。

| 原文的段 | 本專案的量測 | 現況 |
| :--- | :--- | :--- |
| 訓練與保留資料 | `{task_id}__model` 在驗證列上的指標，動態視界預報為單步 MAPE | 有，也是健康判定的依據 |
| 保留與隔日資料 | 滾動起點回測依提前時數分組的 MAPE | 有，但以觀測天氣推論，是「氣象已知」條件下的數字（[研究空間 §2](../reference/lab.md#2-滾動起點回測labbacktestpy)） |
| 隔日與即時資料 | 預報實績與同一時段、以 serving 規則重現的回測相比 | 缺：預報實績已在累積，但沒有以預報天氣重現 serving 的回測可比 |

因此目前分辨不出預報實績的誤差有多少來自氣象署預報本身、多少來自工程上的訓練與 serving 不一致。[ADR-0018](../adr/0018-access-research-data-through-data-freezes-and-knowledge-time.md) 的標準回測（每個起點是模擬的發布時刻，天氣照 serving 規則解析，提前時數從發布時刻起算）補上第三段；在那之前，回測的步數與預報實績的提前時數不可直接比較（[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)）。

### 4.8 Phase III：成長趨緩、精煉與複雜模型（Rule 38–43）

原文：每月收益遞減、指標之間開始此消彼長，就是 Phase II 接近尾聲的跡象。這一節的規則比前面更偏向展望，各團隊要找自己的路。

#### Rule 38：目標不一致才是問題時，不要在新特徵上浪費時間

原文：*Don't waste time on new features if unaligned objectives have become the issue.*

- **要點**：量測進入高原後，團隊會開始關注現行目標範圍以外的問題。產品目標不在演算法目標之內時，要改的是目標或產品目標，而不是加特徵。
- **對照（未到階段）**：可預見的不一致是：訓練以單步預測的平方誤差為 objective，採用判定看研究設定視界內的整體 MAPE，預報檢視的標題看提前 24 小時。若日後最在意的是尖峰時段或特定提前時數的準確度，而改特徵已無法改善，就依本規則調整 objective 或評估方式。

#### Rule 39：推出決策是長期產品目標的代理

原文：*Launch decisions are a proxy for long-term product goals.*

- **要點**：推出決策取決於多項標準，只有一部分能直接以 ML 最佳化；可量測的指標本身也只是長期目標的代理。唯一容易的推出決策，是所有指標都變好，或至少都沒有變差。若簡單的啟發式在所有指標上都勝過複雜的演算法，就選啟發式。個人傾向最佳化單一目標，團隊則要在各指標分別涵蓋的風險之間權衡。
- **對照（部分落實）**：採用判定已有明確規則：評估起點涵蓋足夠的日曆日，且最佳候選在評估起點的整體 MAPE 嚴格低於基線（`candidate.beats(baseline)`，[研究空間 §2](../reference/lab.md#2-滾動起點回測labbacktestpy)）。它只看單一指標。依本規則可補兩點：在研究報告中確認候選在各提前時數分組與其他指標（MAE、RMSE）上沒有變差，有變差時在結論段說明取捨；並把簡單的啟發式基準（Rule 1）列為候選之一。

#### Rule 40：讓 ensemble 保持簡單

原文：*Keep ensembles simple.*

- **要點**：直接吃原始特徵的單一模型最容易除錯。使用 ensemble 時，每個模型要嘛只吃其他模型的輸出，要嘛是吃特徵的基礎模型，不要兩者兼具；ensemble 本身用簡單模型，並保證基礎模型的分數上升時，ensemble 的分數不會下降。
- **對照（已落實）**：目前沒有 ensemble，每個 ML 任務一個模型；高負載預警刻意不以動態視界預報的輸出為輸入（[ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md) 候選方案 G），任務之間沒有串接。日後要串接任務或組合模型時，先依本規則決定每個模型的角色。

#### Rule 41：表現進入高原時，尋找性質不同的新資訊來源，而非精煉既有訊號

原文：*When performance plateaus, look for qualitatively new sources of information to add rather than refining existing signals.*

- **要點**：該加的都加了、正則化也調過，幾季都沒有超過 1% 的改善時，就該為性質截然不同的特徵建基礎設施，例如更長期的歷史或其他產品的資料；同時調整對投資報酬的預期，並權衡新特徵與增加的複雜度。
- **對照（未到階段）**：M3 是這個方向的早期例子：從單一臺北代表點擴充為多個氣象代表點的加權天氣，並加入以政府辦公日曆判定的放假日（[ADR-0012](../adr/0012-combine-weather-reference-points-into-weighted-weather.md)）。新的資訊來源要先有足夠的入庫歷史才能研究（Rule 2）；研究者自帶外部資料與新資料來源的擷取，[ADR-0018](../adr/0018-access-research-data-through-data-freezes-and-knowledge-time.md) 列為延後。

#### Rule 42：多樣性、個人化或相關性與熱門程度的相關，不如你想的高

原文：*Don't expect diversity, personalization, or relevance to be as correlated with popularity as you think they are.*

- **要點**：點擊、觀看等指標量測的是熱門程度；為多樣性或個人化加的特徵，權重常比預期低。可以用後處理提高多樣性或相關性，確認長期目標上升後，再考慮把它們納入目標。
- **對照（低適用）**：本專案沒有內容推薦或個人化。

#### Rule 43：你的朋友在不同產品間大致相同，你的興趣則不然

原文：*Your friends tend to be the same across different products. Your interests tend not to be.*

- **要點**：預測人際關係親疏的模型能跨產品沿用；個人化特徵跨產品則常常失效。有時有效的做法是以一個產品的原始資料預測另一個產品的行為。
- **對照（低適用）**：本專案沒有使用者層級或跨產品的資料。

## 5. 缺口總表

列出第 4 節標為缺口，或部分落實而缺的部分可以明確指出的規則。處理方式見第 1.1 節。

| Rule | 缺口 | 既有決策或追蹤 |
| :--- | :--- | :--- |
| 1、39 | 沒有啟發式比較基準（例如季節性天真預報），採用判定答不出比簡單做法好多少 | [ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md) 延後「比較基準」 |
| 8 | 沒有量測模型時效：模型舊了多久會變差多少 | 無 |
| 9 | 新訓練的模型不經檢查就成為現役模型 | 無；與 ADR-0013 的「照常發布」不衝突 |
| 10 | 沒有特徵涵蓋率與分佈的持續監控 | GLOSSARY 定義了特徵漂移與概念漂移 |
| 14 | 沒有偏差（平均誤差）與機率校準的檢查 | 無 |
| 24 | 沒有量測新舊模型的預報差異 | ADR-0013 延後依模型版本的分析 |
| 29 | 已發布預報不保存當時的輸入 | [ADR-0018](../adr/0018-access-research-data-through-data-freezes-and-knowledge-time.md) 延後 |
| 31 | point-in-time 只篩資料時間，不篩知悉時間 | ADR-0018（`Proposed`） |
| 37 | 回測只有「氣象已知」模式，無法與預報實績比較 | ADR-0018 的標準回測 |

## 6. 出處與授權

- **原文**：Martin Zinkevich，〈Rules of Machine Learning: Best Practices for ML Engineering〉，Google for Developers，<https://developers.google.com/machine-learning/guides/rules-of-ml>。本文依 2026-11-26 取得的版本整理，原文頁面標示的最後更新日為 2025-08-25（UTC）。
- **授權**：原文內容依 [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/) 授權。本文為摘要、翻譯與改寫，並加入本專案的對照；規則編號、英文標題與第 2 節的引句取自原文，其餘為改寫，不代表原作者或 Google 的立場。
- **案例**：原文以 Google Plus、Google Play、YouTube 的產品經驗為例；本文只在說明規則時簡述，不轉錄。
