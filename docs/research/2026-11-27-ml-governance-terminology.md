# ML 治理與 MLOps 業界用語對照調查

> - Created: 2026-11-27
> - Last Updated: 2026-11-27
> - Status: Open
> - Related: [GitHub #408](https://github.com/shiroki9979/shiro-mlops/issues/408)、[GitHub #270](https://github.com/shiroki9979/shiro-mlops/issues/270)

本調查為 [#408](https://github.com/shiroki9979/shiro-mlops/issues/408) 盤點 repo 在 grilling 與 ADR 中自行命名的 ML 治理與生命週期用語，逐詞對照業界框架與工具的說法。這些詞在 repo 內定義清楚，但外部讀者不一定能對應到熟悉的概念，而 M11 的 ADR 與實作票即將把它們寫進資料表、設定鍵與規則代碼。

結論先講：

- **大多數用語保留**，只需補英文對照。業界詞只當對照，不取代繁中正式名稱。
- **建議改名四處**：
  - GLOSSARY 的「驗收」改為「可服務檢查 (Servability Check)」，「營運驗收」不動。這與 issue 的初步看法相反，理由見 [§4.1](#41-驗收與營運驗收撞名)。
  - #377 的「提交」改為「交付」，因為「提交」在 repo 已指 git commit 與交易 commit。
  - lineage 的三種寫法拆成兩個詞：Dagster 的依賴關係寫「資產依賴圖」，成品的來歷寫「出處」；「研究出處」成為 GLOSSARY 詞條（[§4.2](#42-lineage-的三種寫法)）。
  - `docs/research/` 的文件改稱「調查報告」，「研究報告」留給 `lab/` 研究主題的 README。
- **值得補進 M11 設計的業界概念有三項**：平台模型的退回、釘選模型的新舊與健康判定、健康判定規則歸輸出契約（[§6](#6-業界有repo-沒有的概念)）。
- **#376 的業界用語對照有兩處要修正**：MLflow `MetricThreshold` 只能表達「至少好多少」，表達不了平台重訓的 5% 容忍；Google 的 model validation 是部署前的整套離線檢查，同時包含效能對基準的比較與基礎設施相容性測試，不能單指「能不能服務」（[§4.3](#43-376-業界用語對照的查證)）。
- **來源限制**：NIST、SR 11-7、Google MLOps 文章、Model Cards 與 Datasheets 都已讀原文。EU AI Act（EUR-Lex 擋下自動讀取）、ML Test Score 的條目（PDF 所在主機未放行）、ISTQB、Nygard 與 Gama 等人的 survey 仍只有搜尋摘錄，ISO 標準的術語標為未查證（[§9](#9-限制)）。

## 1. 範圍與方法

### 1.1 盤點範圍

- **GLOSSARY §3、§4、§6 的全部詞條**，以 `origin/dev`（`11fa6a3`）為準，含 [#411](https://github.com/shiroki9979/shiro-mlops/issues/411) 新增的「退回」與「下架」。
- **#408 範圍表另列的詞**：知悉時間（GLOSSARY §1）、隨需請求、待定、成品、研究出處。
- **[#377](https://github.com/shiroki9979/shiro-mlops/issues/377) 的詞**：期望狀態、生效紀錄、reconciler、提交、既有模型接軌。
- **流程用語**：營運驗收、ADR、研究報告、重現紀錄。
- **技術用語**：lineage／血緣／世系、model store、任務類型、輸出契約。
- **不納入**：GLOSSARY §1（知悉時間除外）、§2、§5、§7。

### 1.2 命名原則

以下原則已在 #408 定案，本報告照著判定，不重新討論：

- **正式名稱**：繁中領域詞，括號附英文。業界詞只當對照，不取代正式名稱。
- **何時建議改名**：只有兩種情況。一是與業界同名詞的概念邊界衝突、外部讀者會誤解；二是 repo 內部有兩個概念撞名。
- **業界詞的處理**：邊界與 repo 用語不同的，列入 `_Avoid_`，例如現有的 champion/challenger。邊界相同的，寫進對照表，必要時當成 GLOSSARY 的英文對照。
- **禁詞**：`BANNED_TERMS` 只收 repo 自己淘汰的繁中舊詞，業界英文詞永遠不登記。

### 1.3 四種建議

- **保留**：名稱與定義都不動。
- **改名**：符合 §1.2 的兩種情況之一，給出新名稱。
- **補對照**：名稱不動，在 GLOSSARY 或 `docs/reference/` 補上業界詞作為英文對照，或修正定義的措辭。
- **列入 Avoid**：業界詞的邊界不同，寫進該詞條的 `_Avoid_`。

### 1.4 來源與標記

所有來源的讀取日期都是 2026-11-27，版本列在 [§10](#10-來源清單)。每項外部說法標明讀取方式：

- **原文**：直接讀到原文，或專案 GitHub 上的文件原始檔、原始碼。這仍算一手來源。
- **搜尋摘錄**：主機連不到，只讀到搜尋引擎對原頁的摘錄。來源仍是原頁，但措辭沒有逐字核對。ADR-0015 的 Notes 對 AWS 文件也用過同樣的標記。
- **未查證**：連摘錄都沒有讀到，或依規則只能標未查證（ISO 標準正文）。

repo 的事實取自 GLOSSARY、ADR、`docs/reference/`，以及 [#270](https://github.com/shiroki9979/shiro-mlops/issues/270)、[#276](https://github.com/shiroki9979/shiro-mlops/issues/276)、[#277](https://github.com/shiroki9979/shiro-mlops/issues/277)、[#376](https://github.com/shiroki9979/shiro-mlops/issues/376)、[#377](https://github.com/shiroki9979/shiro-mlops/issues/377)、[#388](https://github.com/shiroki9979/shiro-mlops/issues/388)、[#411](https://github.com/shiroki9979/shiro-mlops/issues/411) 的決議。

### 1.5 術語與流程分開

本專案是單人維護的 public repo，不屬於受監管產業，不導入任何框架的認證或合規流程。下表標明每個框架取用的部分：

| 框架 | 本報告取用 | 流程 |
| :--- | :--- | :--- |
| NIST AI RMF 1.0 | inventory、decommissioning、TEVV、AI actors 等用語 | 不採用 GOVERN／MAP／MEASURE／MANAGE 的整套流程 |
| ISO/IEC 42001、22989 | 只記錄標準的存在，術語內容未查證 | 不採用管理系統與認證 |
| EU AI Act | intended purpose、serious incident、substantial modification 等用語 | 不做適用性判斷，不採用任何義務 |
| SR 11-7 | effective challenge、outcomes analysis、back-testing、benchmarking 等用語 | 不採用模型風險管理的組織分工 |
| Google MLOps 文章、ML Test Score | 用語，加上兩項值得補進設計的概念（平台模型退回、模型新舊） | 不採用成熟度分級與評分 |
| Model Cards、Datasheets | 用語 | 不產出 model card 或 datasheet |
| MLflow、SageMaker、Vertex AI、TFX | 用語，加上一項設計輸入（健康判定依問題類型）與 #376 對照的修正 | 不導入任何 registry |
| W3C PROV、OpenLineage、Dagster | 用語 | 不導入 lineage 系統 |
| Kubernetes、OpenGitOps | 用語 | 已由 #377 採用宣告檔加 reconciler 的做法，本報告不另增流程 |

## 2. 各面向的業界用語與概念邊界

### 2.1 治理框架與角色責任

- **NIST 的 AI actors**：AI RMF 依生命週期把參與者分成 AI Design、AI Development、AI Deployment、Operation and Monitoring、TEVV 等任務類別，並主張執行 verification 與 validation 的人最好與執行 test 與 evaluation 的人不同（[NIST AI 100-1][nist-rmf]、[Appendix A][nist-actors]，原文）。研究者約略對應 AI Development，平台維護者對應 AI Deployment 與 Operation and Monitoring。repo 的角色依交付契約劃分，不依生命週期階段劃分，兩者沒有撞名。
- **SR 11-7 的 effective challenge**：由客觀、知情、具備適當誘因、能力與影響力的人，對模型與其結果做的批判性審查（[SR 11-7][sr117]，原文）。SR 11-7 把模型風險管理的角色分成 ownership、controls 與 compliance：業務單位的 model owner 對模型的使用與表現負最終責任；controls 一方負責風險衡量、限額與監控，並管理獨立驗證與審查流程（[SR 11-7][sr117]，原文）。
- **EU AI Act**：intended purpose 指 provider 預定的用途；serious incident 包括對關鍵基礎設施的管理或運轉造成嚴重且不可逆的中斷；Annex III 第 2 點把電力供應管理與運轉的安全元件列為高風險（[EU AI Act][eu-ai-act]，搜尋摘錄）。本 repo 不作為電網運轉的安全元件，也不在歐盟市場提供，本報告不做適用性判斷，只取用語。provider 與 deployer 的定義本次沒有讀到，標未查證。
- **ISO/IEC 42001 與 22989**：前者是 AI 管理系統的要求標準，後者是 AI 概念與術語標準（[42001][iso-42001]、[22989][iso-22989]，搜尋摘錄）。[ISO OBP][iso-obp] 連不到，所有術語條目標未查證。
- **營運驗收**：ISTQB 的 acceptance testing 是「著重判定是否接受系統的測試層級」，operational acceptance testing 是「判定維運或系統管理人員能否接受系統的驗收測試」（[ISTQB Glossary][istqb]，搜尋摘錄）。repo 的營運驗收以正式資料在運行環境證明一個里程碑（[issue-tracker.md][repo-issue-tracker]），和 OAT 同屬「由營運面接受」這一類。

### 2.2 模型登錄、版本與晉升

- **MLflow**：registered model 有唯一名稱，包含版本、alias 與 tag。alias 是「指向某個 model version 的可變具名參照」，文件以 `champion` 為例。stages 自 2.9.0 起棄用，改用 alias 與 tag；文件以 promote 指把版本推向 staging 或 production 環境，也以 `copy_model_version()` 在 registered model 之間推進版本（[registry][mlflow-registry]、[workflow][mlflow-workflow]、[client.py][mlflow-client]，原文）。
- **SageMaker**：Model Group 追蹤「為解決同一個問題而訓練的所有模型」，每次註冊成為一個 model version。`ModelApprovalStatus` 有 `PendingManualApproval`、`Approved`、`Rejected`；`Approved` 可觸發 CI/CD 部署；使用 SageMaker 提供的專案範本時，把已核准版本改為 `Rejected` 會重新部署最新一個 `Approved` 版本（[Model Registry][sm-registry]、[approval][sm-approve]，原文）。另有可自訂階段的 staging construct，並保留 lifecycle 事件的 audit trail（[staging construct][sm-staging]，原文）。
- **Vertex AI**：模型版本可用 version alias 參照。第一個版本自動得到 `default` alias，每個模型恰有一個 default version，未指定版本時取它（[model.proto][vertex-model]、[model_service.proto][vertex-service]，原文）。
- **TFX**：Pusher 依 Evaluator 與 InfraValidator 的 blessing 決定是否推送模型（[Pusher][tfx-pusher]，原文）。
- **Kubernetes 與 OpenGitOps**：controller 管理的物件以 spec 表示 desired state，controller 讓 current state 接近它（[controller][k8s-controller]，原文）。OpenGitOps 要求 desired state 是宣告式、有版本且不可變、自動拉取、持續 reconcile；reconciliation 是「確保實際狀態符合期望狀態」，實際狀態偏離期望狀態稱為 drift（[principles][gitops-principles]、[glossary][gitops-glossary]，原文）。

對照 repo 的結果：

- **ML 任務**相當於 registered model、Model Group 或 Vertex 的 Model，都是版本的容器。ML 任務另外帶有輸出契約與評估方式，範圍較大。
- **版本識別不同**：業界的版本號是遞增整數；repo 以模型目錄的 SHA-256 識別模型版本（[ml-tasks.md §4][repo-ml-tasks]），位元組相同就是同一版本。外部讀者需要被告知這一點。
- **釘選**相當於把 alias 指向某個版本，或核准某個版本。差別在於：釘選是 git 內的期望狀態（#377），必須引用通過的閘門判定，不會到期，平台訓練也不會覆蓋它。
- **repo 沒有單一的 model registry**：版本、判定與生效分散在模型存放、交付包存放區與 #377 的 append-only 資料表。`docs/reference/` 應明說這一點。
- **期望狀態與 reconciler** 與 Kubernetes、OpenGitOps 的邊界一致。但 GitOps 的 drift 指實際狀態偏離期望狀態，與 GLOSSARY 的特徵漂移、概念漂移無關；`src/shiro_mlops/pipelines/smoke_check.py` 的註解也已用 deployment drift 一詞。期望狀態沒有生效時，應寫「期望未生效」，不寫「漂移」。

### 2.3 驗證與上線閘門

- **TFX InfraValidator**：在實際的 serving 基礎設施中確認模型「mechanically fine」，模式有 `LOAD_ONLY` 與 `LOAD_AND_QUERY`，「不在乎預測對不對，只看請求是否成功」；Pusher 的說法是 InfraValidator 在模型「mechanically servable」時給 blessing（[InfraValidator][tfx-infra]、[Pusher][tfx-pusher]，原文）。這對應 repo 驗收的載入與試推論兩段；repo 另有一段靜態宣告檢查。
- **TFX Evaluator 與 TFMA**：Evaluator 拿新模型和 baseline（例如目前 serving 的模型）在同一份評估資料上比較，達到相對 baseline 的條件就判 blessed；沒有 baseline 的第一次執行會忽略 change threshold（[Evaluator][tfx-evaluator]，原文）。TFMA 分 value threshold（絕對上下界）與 change threshold（比較 `v_c - v_b` 或 `v_c / v_b`，並指定方向）；TFX 範例以 absolute `-1e-10` 表示「AUC 不低於基準」（[TFMA model validations][tfma-validations]、[Evaluator][tfx-evaluator]，原文）。
- **MLflow**：`MetricThreshold` 有 `threshold`、`min_absolute_change`、`min_relative_change`。後兩者是「候選模型通過與 baseline 比較所需的最小變化」：`min_absolute_change` 必須為正，`min_relative_change` 介於 0 與 1。`validate_evaluation_results(validation_thresholds, candidate_result, baseline_result)` 未通過時拋出例外，取代 `mlflow.evaluate` 中已棄用的 model validation（[validation.py][mlflow-validation]，原文）。
- **Google MLOps 文章**：model validation 指「確認模型適合部署，也就是預測表現優於某個基準」。CT 管線的 offline model validation 一步列了四件事：以測試資料產生評估指標；和目前的模型（例如 production model、baseline model）比較，確認新模型較好才晉升上線；確認各資料區段的表現一致；測試模型能否部署，包括基礎設施相容性與 prediction service API 的一致性。部署後另有以 canary 或 A/B 進行的 online model validation（[MLOps 文章][google-mlops]，原文）。
- **NIST**：validation 引 ISO 9000:2015 的定義，「以客觀證據確認特定預定用途或應用的需求已被滿足」（[NIST AI 100-1][nist-rmf]，原文）。
- **SR 11-7**：back-testing 是 outcomes analysis 的一種，比較實際結果與模型在未用於開發的期間所做的預測；benchmarking 把模型的輸入與輸出和其他資料或模型的估計比較（[SR 11-7][sr117]，原文）。滾動起點回測相當於模擬的 back-testing，#376 第 9 點的 naive 基準相當於 benchmarking。
- **scikit-learn**：`TimeSeriesSplit` 是 k-fold 的變體，後一個訓練集包含前一個；一般的交叉驗證假設樣本獨立同分佈，用在時間序列會高估表現（[cross_validation.rst][sklearn-cv]，原文）。

結論：業界的 validation 至少有三種邊界：NIST 與 ISO 的「需求已滿足」、Google 的部署前整套離線檢查（效能比較加上基礎設施相容性）、SR 11-7 的整套獨立審查。它不能當成驗收或評估閘門的英文名稱：Google 的用法同時涵蓋兩者，另外兩種又比兩者都廣。

### 2.4 資料版本、時點正確性與世系

- **W3C PROV-DM**：provenance 是「參與產生某份資料或某物的實體、活動與人的資訊，可用來評估其品質、可靠度或可信度」（[PROV-DM][prov-dm]，原文）。
- **OpenLineage**：核心 lineage 模型由 Run Event、Job（消耗與產出 dataset 的流程定義）、Dataset、Run 與 Facet 組成（[OpenLineage spec][openlineage]，原文）。lineage 描述的是 job 與 dataset 之間的流向。
- **Dagster**：以 `deps` 宣告的依賴「追蹤 lineage，但不把上游資產的資料傳給下游」，UI 的入口叫 View lineage（[asset dependencies][dagster-deps]、[tutorial][dagster-tutorial]，原文）。
- **MLflow 與 SageMaker 的 model lineage**：MLflow 把「哪個 experiment 與 run 產生了這個模型版本」稱為 lineage（[registry][mlflow-registry]，原文）；SageMaker ML Lineage Tracking 記錄訓練一個模型用到的資料集、job 與成品，用途是重現與稽核（[ML Lineage Tracking][sm-lineage]，原文）。這兩者的 lineage 實際上是 PROV 意義的 provenance。
- **Feast 的 point-in-time join**：以 event timestamp 判定，也就是「特徵被觀測或產生的事件時間」，entity row 的時間是可取用資料的上界（[feature retrieval][feast-retrieval]，原文）。這是 repo 的資料時間，不是知悉時間。
- **SageMaker 的重現前提**：只要能取得當時確切的資料集，就能重現模型（[ML Lineage Tracking][sm-lineage]，原文）。這和凍結資料的用途相同。
- **Datasheets**：每個資料集附一份 datasheet，記錄動機、組成、蒐集過程與建議用途；論文依 Motivation、Composition、Collection Process、Preprocessing/cleaning/labeling、Uses、Distribution、Maintenance 七節列出問題（[Datasheets for Datasets][datasheets]，原文）。

結論：英文的 lineage 同時涵蓋「job 或資產之間的資料流向圖」與「一個模型的來歷」兩個概念。repo 的中文要把這兩者分開，見 [§4.2](#42-lineage-的三種寫法)。

### 2.5 部署與服務

- **兩種推論形態**：SageMaker Model Monitor 把推論分成 real-time endpoint 與定期執行的 batch transform，模型品質監控也分 real-time 與 batch inference（[Model Monitor][sm-monitor]、[model quality][sm-quality]，原文）；Google 的文章以 online traffic 稱前者的流量（[MLOps 文章][google-mlops]，搜尋摘錄）。隨需請求對應前者，已發布預報對應後者，但已發布預報另有「發布後原樣保存」的約束。
- **MLflow flavor**：一種讓部署工具理解模型的保存慣例，一個模型目錄可以有多個 flavor（[MLflow Model][mlflow-model]，原文）。任務類型範圍較大：它還負責訓練、特徵解譯與輸出。
- **MLflow model signature 與 Vertex PredictSchemata**：signature「定義模型輸入、輸出與參數的格式，像一份契約」（[signatures][mlflow-signature]，原文）；Vertex 以 `PredictSchemata` 描述 instance 與 prediction 的 schema（[model.proto][vertex-model]，原文）。輸出契約範圍較大：還包含承諾的時程範圍、評分器、核心指標與標籤定義（#376 第 5 至 7 點、#279）。
- **預報運行狀態、正常預報、降級預報、無法產出、負載起點過舊**：本次讀過的來源中沒有對應的 ML 治理用語，屬於本 repo 的領域詞。

### 2.6 監控與事後評估

- **概念漂移**：Gama 等人的 survey 把 real concept drift 定義為 `p(y|X)` 的改變（[Gama et al.][gama]，搜尋摘錄）。GLOSSARY 的概念漂移（相同氣溫與日曆條件下負載模式改變）與此一致。
- **特徵漂移**：Vertex AI 把「訓練資料與預測資料之間的 skew」與「預測資料隨時間的 drift」分成兩種設定（[model_monitoring.proto][vertex-monitoring]，原文）；SageMaker 以訓練資料集建立 baseline，再把預測資料和 baseline 比較（[Model Monitor][sm-monitor]，原文）。GLOSSARY 的特徵漂移只寫「偏離基準分佈」，沒有說基準取自訓練資料還是先前期間，所以只部分對應。
- **模型品質監控**：SageMaker 把推論時擷取的預測與事後的 ground truth 合併比較，所用指標「取決於 ML 問題類型」（[model quality][sm-quality]，原文）。這和預報實績的做法一致：已發布預報與事後實際負載對照。
- **模型新舊**：ML Test Score 列有「測試模型是否過舊」與「上線前測試模型品質」（[ML Test Score][ml-test-score]：摘要頁為原文，只說明共 28 項測試與監控需求；條目內容為搜尋摘錄，PDF 所在的 `storage.googleapis.com` 未放行）。
- **誤差指標**：MAE、MSE、RMSE、MAPE 的定義見 scikit-learn 文件（[model_evaluation.rst][sklearn-metrics]，原文），與 GLOSSARY 一致。

### 2.7 文件與稽核紀錄

- **ADR**：Nygard 2011 年提出的格式含 Title、Context、Decision、Status、Consequences；被推翻的決定保留原檔並標為 superseded（[Documenting Architecture Decisions][nygard]，搜尋摘錄）。repo 的 ADR 與此一致。
- **Model Cards**：伴隨已訓練模型的短文件，提供在多種條件下的基準評估，是 Datasheets 的互補；論文提出的章節是 Model Details、Intended Use、Factors、Metrics、Evaluation Data、Training Data、Quantitative Analyses、Ethical Considerations、Caveats and Recommendations（[Model Cards][model-cards]，原文）。SageMaker Model Cards 的實作記錄 intended uses（用途、適用與不適用的情境、開發時的假設）、risk rating、訓練細節與評估結果（[SageMaker Model Cards][sm-cards]，原文）。
- **稽核軌跡**：SageMaker 的 staging construct 保留模型核准與階段轉換的歷史（[staging construct][sm-staging]，原文）；ML Lineage Tracking 的用途之一是稽核與合規查核（[ML Lineage Tracking][sm-lineage]，原文）。repo 以 #377 的 append-only 資料表與 git 歷史承擔同樣的功能。
- **repo 內兩種研究文件**：`lab/<YYYY-MM-DD>-<topic>/README.md` 是 [lab.md §5][repo-lab] 定義的研究報告，含重現紀錄欄位；`docs/research/` 下是調查類的紀錄文件，依 [markdown-metadata.md][repo-metadata] 以 `Status` 標示進行或結案。

## 3. 對照表

「一致」指概念邊界相同；「部分」指有重疊但範圍或規則不同；「不同」指沒有對應，或同名但邊界不同。

### 3.1 治理框架與角色責任

| repo 用語 | repo 的現行邊界 | 業界對應用語 | 來源 | 邊界 | 建議 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 研究者 (Researcher) | 在研究空間以凍結資料探索、訓練、評估，需要時交出模型交付包的角色 | AI Development actor；model developer | [NIST][nist-actors]、[SR 11-7][sr117] | 部分 | 保留：業界依生命週期劃分角色，repo 依交付契約劃分，沒有撞名。 |
| 平台維護者 (Platform Maintainer) | 負責擷取、平台訓練、serving 與監控，並「驗收模型交付包、決定釘選」 | AI Deployment、Operation and Monitoring actor；model owner | [NIST][nist-actors]、[SR 11-7][sr117] | 部分 | 保留，修定義：驗收已是 `src/` 的純函式、閘門判定不得人工推翻（#277、#376），人的責任是審查釘選變更的 PR，定義中的「驗收模型交付包」應改寫。 |
| 營運驗收 (Operational Acceptance) | `ops-acceptance` issue：以正式資料在運行環境證明一個里程碑，證據貼齊才關閉 | operational acceptance testing；acceptance testing | [ISTQB][istqb]（搜尋摘錄） | 部分 | 保留：與 OAT 同屬營運面的接受，撞名由模型層讓出，見 §4.1。 |

### 3.2 模型登錄、版本與晉升

| repo 用語 | repo 的現行邊界 | 業界對應用語 | 來源 | 邊界 | 建議 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| ML 任務 (ML Task) | 具名的 ML 問題設定，可歷經多個模型版本 | registered model；Model Group；Vertex Model | [MLflow][mlflow-registry]、[SageMaker][sm-registry]、[Vertex][vertex-model] | 部分 | 補對照：業界這一層只是版本的容器，ML 任務另含輸出契約與評估方式。 |
| 模型交付包 (Model Handoff Package) | 研究者交出的已訓練模型，連同宣告與研究出處，不帶評估證據 | model package；MLflow Model（目錄加 `MLmodel`） | [SageMaker][sm-registry]、[MLflow][mlflow-model] | 部分 | 補對照：SageMaker 的 model package 含指標與核准狀態，交付包不含；`_Avoid_` 已有 artifact。 |
| 成品 | 平台模型與交付包共用的檔案形式：一個目錄，含宣告檔與原生模型檔，以 SHA-256 識別 | model artifact；MLflow Model（含任意檔案的目錄加 `MLmodel`） | [SageMaker Model Cards][sm-cards]、[MLflow Model][mlflow-model] | 部分 | 補對照：英文寫 model artifact，不單寫 artifact，因為 [data-contracts.md §5][repo-data-contracts] 的 artifact 指 Dagster I/O 產物。 |
| 候選模型 (Candidate Model) | 等待評估閘門判定的模型版本 | candidate model | [MLflow][mlflow-validation]、[TFMA][tfma-validations] | 一致 | 補對照：candidate model 可作英文對照；challenger 留在 `_Avoid_`，因為對手依路徑不同（平台模型或現役模型）。 |
| 釘選 (Pin) | 指定通過閘門的交付包為現役模型，不到期，平台訓練不覆蓋 | alias 指派；`Approved`；version alias；promote | [MLflow][mlflow-workflow]、[SageMaker][sm-approve]、[Vertex][vertex-service] | 部分 | 保留：promote 留在 `_Avoid_`，MLflow 的 promote 指跨環境推進版本，範圍不同。 |
| 退回 (Rollback) | 改回同一任務先前曾生效的交付包，免過閘門，須重新通過驗收 | rollback | [SageMaker][sm-approve]、[Google][google-mlops] | 部分 | 保留：業界的 rollback 不限交付包；平台模型的退回列為值得補進設計，見 §6。 |
| 下架 (Retirement) | 停止提供某個 ML 任務，不刪除紀錄與交付包 | decommissioning and phasing out | [NIST GOVERN 1.7][nist-rmf] | 部分 | 補對照：decommissioning 可作英文對照。 |
| 平台模型 (Platform Model) | 最近一次通過評估閘門的平台訓練結果；有釘選時待命 | 無直接對應；continuous training 的產出 | [Google][google-mlops] | 不同 | 保留：業界沒有「待命中的平台模型」這一層。 |
| 現役模型 (Serving Model) | 目前回答隨需預測並產出已發布預報的模型版本 | production model；champion alias 指向的版本；default version | [MLflow][mlflow-registry]、[Vertex][vertex-service]、[Google][google-mlops] | 部分 | 補對照：production model 邊界一致（Google 的 MLOps 文章也以它稱目前服務中的模型），建議從 `_Avoid_` 移到英文對照；champion 留在 `_Avoid_`；Vertex 的 default version 是未指定版本時的預設，不是現役。 |
| 期望狀態 | 人決定、以 PR 修改的 `serving/<task_id>.toml`（釘選與自動訓練 flag） | desired state | [Kubernetes][k8s-controller]、[OpenGitOps][gitops-glossary] | 一致 | 補對照：desired state 可作英文對照；期望沒有生效時寫「期望未生效」，不寫 drift 或漂移。 |
| 生效紀錄 | reconciler 驗證期望狀態後寫入的 append-only 紀錄：哪個 SHA、依什麼判定、何時生效 | lifecycle audit trail；current state | [SageMaker][sm-staging]、[Kubernetes][k8s-controller] | 部分 | 保留：英文建議 activation record，不用 deployment 或 promotion，見 §8。 |
| reconciler | Dagster sensor，驗證期望狀態後才寫生效紀錄 | reconciliation；controller | [OpenGitOps][gitops-principles]、[Kubernetes][k8s-controller] | 一致 | 保留：英文技術詞，在 `docs/reference/` 補 OpenGitOps 對照。 |
| 提交 | 主機 CLI 的一步：檢查 `source_revision` 是 `origin/dev` 的祖先、複製進存放區、寫提交紀錄 | register a model version | [MLflow][mlflow-registry]、[SageMaker][sm-registry] | 部分 | 改名為「交付」：「提交」在 repo 已指 git commit 與交易 commit，#277 第 4 點的「未提交變更」就是 git 意義，見 §5。 |
| 既有模型接軌 | migration 後把已安裝的模型一次登記為平台模型，判定欄寫此值 | 本次來源未見對應詞 | — | 不同 | 保留：資料表中的值要和其他依據並列，見 §8。 |
| model store（模型存放） | `tasks/model_store.py`：每個任務只安裝一份模型目錄，以原子交換與共享鎖保護 | model registry（含版本、alias、核准） | [MLflow][mlflow-registry]、[SageMaker][sm-registry] | 不同 | 補對照：中文統一寫「模型存放」，「保存」留給 ADR-0010 的保存格式；`docs/reference/` 註明它不是 model registry。 |

### 3.3 驗證與上線閘門

| repo 用語 | repo 的現行邊界 | 業界對應用語 | 來源 | 邊界 | 建議 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 驗收 (Acceptance) | 平台確認一個模型版本能被服務：靜態檢查、載入、試推論；不比好壞 | infra validation；acceptance testing；model validation | [TFX][tfx-infra]、[ISTQB][istqb]（搜尋摘錄）、[Google][google-mlops] | 不同 | 改名為「可服務檢查 (Servability Check)」，驗收列入 `_Avoid_`，見 §4.1。 |
| 評估閘門 (Evaluation Gate) | 以核心指標在同一段資料上比較候選模型與對手，有拘束力；資料不足判待定 | Evaluator validation 與 blessing；`validate_evaluation_results`；model validation | [TFX][tfx-evaluator]、[MLflow][mlflow-validation]、[Google][google-mlops] | 部分 | 保留；`_Avoid_` 補 model validation（業界三種邊界都不同於本詞）。 |
| 核心指標 (Core Metric) | 評估閘門唯一的比較依據，由輸出契約定義 | validation threshold 所掛的 metric | [MLflow][mlflow-validation]、[TFMA][tfma-validations] | 部分 | 保留：業界允許多個指標同時設門檻，本詞刻意只有一個。 |
| 待定 | 評估窗不足時的判定，候選不取代對手，資料夠了自動重評 | 無對應；TFX 沒有 baseline 時忽略 change threshold | [TFX][tfx-evaluator] | 不同 | 保留：資料表中的值寫 `inconclusive`，不寫 `pending`，因為 SageMaker 的 `PendingManualApproval` 指等人核准。 |
| 滾動起點回測 (Rolling-Origin Backtest) | 多個起點、只用起點前已知的資料預報、依提前時數彙整誤差 | time series cross-validation；back-testing | [scikit-learn][sklearn-cv]、[SR 11-7][sr117] | 部分 | 補對照：`_Avoid_` 的「交叉驗證」理由改寫為「一般指打亂順序的 k-fold；時間序列交叉驗證不含知悉時間規則」。 |

### 3.4 資料版本、時點正確性與世系

| repo 用語 | repo 的現行邊界 | 業界對應用語 | 來源 | 邊界 | 建議 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 凍結資料 (Data Freeze) | 某凍結時刻，可作目標、輸入或比較對象的入庫資料所成的一致唯讀切面 | dataset snapshot；exact dataset | [SageMaker][sm-lineage] | 部分 | 保留：中文「快照」維持在 `_Avoid_`，它已專指台電快照。 |
| 知悉時間 (Knowledge Time) | 本系統首次保存某筆資料的時刻（GLOSSARY §1） | point-in-time join 的 event timestamp；transaction time | [Feast][feast-retrieval]；transaction time（未查證） | 不同 | 補對照：Feast 的 point-in-time 以資料時間判定，ADR-0018 寫 point-in-time 的地方要加註「以知悉時間判定」。 |
| 研究出處 | 交付包宣告的出處：凍結資料 SHA-256 與凍結時刻、commit、研究主題目錄 | provenance；model lineage | [PROV-DM][prov-dm]、[MLflow][mlflow-registry]、[SageMaker][sm-lineage] | 一致 | 補對照：新增 GLOSSARY 詞條，英文 Research Provenance，見 §4.2。 |
| lineage（`dagster-schedules.md`） | 以 `deps` 宣告、不傳資料的資產依賴 | asset lineage | [Dagster][dagster-deps]、[OpenLineage][openlineage] | 一致 | 改名：中文寫「資產依賴」，英文 lineage 只在指 Dagster UI 的 lineage 檢視時出現。 |
| 世系（ADR-0004） | Dagster UI 中從原始資料到漂移報告的依賴圖 | asset lineage | [Dagster][dagster-tutorial] | 一致 | 改名為「資產依賴圖」，世系登記為禁詞。 |
| 血緣（ADR-0015、#277） | ADR-0015 指 Dagster 依賴圖；#277 指交付包宣告的「出處與血緣」一節 | asset lineage；provenance | [Dagster][dagster-deps]、[PROV-DM][prov-dm] | 不同 | 改名：依語意改為「資產依賴圖」或「出處」，血緣登記為禁詞。 |

### 3.5 部署與服務

| repo 用語 | repo 的現行邊界 | 業界對應用語 | 來源 | 邊界 | 建議 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 已發布預報 (Issued Forecast) | 定時產出、發布後不再修改的預報，記下模型版本 | batch inference；batch transform | [SageMaker][sm-monitor] | 部分 | 保留：業界的 batch 推論沒有「原樣保存、以發布時刻為準」的約束。 |
| 隨需請求 | 請求當下產出的預報，不屬已發布預報 | real-time inference；real-time endpoint | [SageMaker][sm-monitor] | 部分 | 保留：GLOSSARY 同時寫「隨需請求」與「隨需預測」，建議擇一。 |
| 預報運行狀態 (Forecast Operating Mode) | 已產出預報依天氣輸入是否以觀測填補分兩級 | 本次來源未見對應詞 | — | 不同 | 保留：本 repo 的領域詞。 |
| 正常預報 (Normal Forecast) | 每個天氣值都來自七小時內的預報版本 | 本次來源未見對應詞 | — | 不同 | 保留。 |
| 降級預報 (Degraded Forecast) | 任一天氣值以觀測或歷史平均填補 | 本次來源未見對應詞 | — | 不同 | 保留。 |
| 無法產出 (No Forecast Produced) | 輸入不足時不產出任何預報，不是運行狀態 | 本次來源未見對應詞 | — | 不同 | 保留。 |
| 負載起點過舊 (Stale Load Anchor) | 最新負載距預報時刻超過容許落後，不產出預測 | model staleness（指模型，不指輸入） | [ML Test Score][ml-test-score]（搜尋摘錄） | 不同 | 保留：不要以 stale model 對照，兩者的對象不同。 |
| 任務類型 | 註冊單位：預測策略、估計器、特徵解譯與輸出 | MLflow flavor | [MLflow Model][mlflow-model] | 部分 | 保留：flavor 只涵蓋保存與載入的慣例；`TASK_TYPES` 的 registry 與 MLflow Model Registry 無關，`docs/reference/` 應註明。 |
| 輸出契約 | ML 任務對下游承諾的具名產出，含時程範圍、評分器與核心指標 | model signature；PredictSchemata | [MLflow][mlflow-signature]、[Vertex][vertex-model] | 部分 | 補對照：新增 GLOSSARY 詞條，`_Avoid_` 列 model signature（只描述 schema）。 |

### 3.6 監控與事後評估

| repo 用語 | repo 的現行邊界 | 業界對應用語 | 來源 | 邊界 | 建議 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| MAPE | 平均絕對百分比誤差 | mean absolute percentage error | [scikit-learn][sklearn-metrics] | 一致 | 保留。 |
| RMSE | 均方根誤差 | root mean squared error | [scikit-learn][sklearn-metrics] | 一致 | 保留。 |
| MAE | 平均絕對誤差 | mean absolute error | [scikit-learn][sklearn-metrics] | 一致 | 保留。 |
| 特徵漂移 (Feature Drift) | 近期實際氣溫或負載的分佈偏離基準分佈 | data drift；virtual drift；training-serving skew 與 prediction drift | [Vertex][vertex-monitoring]、[SageMaker][sm-monitor]；[Gama et al.][gama]（搜尋摘錄） | 部分 | 補對照：定義寫明基準分佈取自訓練資料（業界稱 skew）或先前期間（業界稱 drift）。 |
| 概念漂移 (Concept Drift) | 相同氣溫與日曆條件下，負載模式系統性轉變 | real concept drift | [Gama et al.][gama]（搜尋摘錄） | 一致 | 補對照：real concept drift 可作英文對照。 |
| 提前時數 (Lead Time) | 目標小時與發布時刻相差的小時數 | lead time；forecast horizon | 本次未另查一手來源 | 一致 | 保留：GLOSSARY 已有英文 Lead Time。 |
| 預報實績 (Forecast Track Record) | 已發布預報與事後實際負載對照的誤差紀錄，是營運紀錄 | model quality monitoring；outcomes analysis | [SageMaker][sm-quality]、[SR 11-7][sr117] | 部分 | 保留：`_Avoid_` 已排除回測，與 SR 11-7 把 back-testing 列為 outcomes analysis 之一的分法相容。 |
| 統計截至時刻 (Track Record Cutoff) | 一份預報實績涵蓋目標小時的終點 | 本次來源未見對應詞 | — | 不同 | 保留。 |
| 累積天數 (Accumulated Days)／累積不足 | 最近 30 天內有可比對小時的日數，滿 7 天才公開指標 | 本次來源未見對應詞 | — | 不同 | 保留。 |
| 預報實績回顧 (Forecast Track Record Review) | 對一段預報實績的文字解讀，每項說法附證據 | outcomes analysis 的分析部分 | [SR 11-7][sr117] | 部分 | 保留。 |

### 3.7 文件與稽核紀錄

| repo 用語 | repo 的現行邊界 | 業界對應用語 | 來源 | 邊界 | 建議 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| ADR | `docs/adr/`：難以反悔的決定與理由 | architecture decision record | [Nygard][nygard]（搜尋摘錄） | 一致 | 保留。 |
| 研究報告 | [lab.md §5][repo-lab] 的 `lab/<YYYY-MM-DD>-<topic>/README.md`；也被用來稱 `docs/research/` 與 `research/*` 分支上的文件 | experiment／run 紀錄；model card 的評估段 | [MLflow][mlflow-registry]、[SageMaker Model Cards][sm-cards] | 不同 | 改名（只改第二義）：`docs/research/` 的文件稱「調查報告」，「研究報告」專指 lab 研究主題的 README，見 §5。 |
| 重現紀錄 | lab.md §5 的欄位表：Git revision、資料、參數、起點、視界等 | reproducibility；model lineage | [SageMaker][sm-lineage]、[MLflow][mlflow-registry] | 部分 | 保留：研究出處是交付包帶走的指標，重現紀錄是研究報告裡較完整的欄位表，兩者不撞名。 |

## 4. 必修項目

### 4.1 「驗收」與「營運驗收」撞名

**結論：改模型層。** GLOSSARY 的「驗收 (Acceptance)」改為「可服務檢查 (Servability Check)」，「營運驗收」與 `ops-acceptance` 保留。這與 issue 的初步看法相反。

「驗收」在 repo 至少有四種用法：

| 用法 | 出處 | 意思 | 業界最接近的詞 |
| :--- | :--- | :--- | :--- |
| 模型層的驗收 | GLOSSARY §6、#277 | 平台確認一個模型版本能被服務：靜態檢查、載入、試推論 | infra validation（[TFX][tfx-infra]） |
| 營運驗收 | [issue-tracker.md][repo-issue-tracker]、ROADMAP、`ops-acceptance` | 以正式資料在運行環境證明一個里程碑 | operational acceptance testing（[ISTQB][istqb]） |
| 驗收標準、Acceptance Criteria | ROADMAP 的欄位、每張 issue 的段落 | 里程碑或工單的完成條件 | acceptance criteria |
| 測試意義的驗收 | ADR-0017 的「TimescaleDB opt-in 驗收」、`verify-data-explorer-pagination.md` | 對真實資料庫的 opt-in 測試 | acceptance testing（[ISTQB][istqb]） |

改模型層的理由：

1. **只改營運驗收解決不了撞名**。「驗收」在 repo 是通用詞，後三種用法都是業界 acceptance 的意思；模型層的窄義是唯一的例外。營運驗收改名後，模型層的驗收仍和「驗收標準」「Acceptance Criteria」並存。
2. **英文 Acceptance 與業界邊界不同**。業界的 acceptance testing 判定「是否接受整個系統」。外部讀者看到 accepted model，會讀成「已核准上線」，也就是 SageMaker 的 `Approved`。GLOSSARY 必須以「只問能不能服務，不比好壞」一句擋住這個讀法，表示名稱本身在誤導。TFX 對同一件事的說法是 mechanically servable（[Pusher][tfx-pusher]）。
3. **這個檢查不只用在交付**。平台訓練結果也要通過（#277 第 11 點），API 啟動、熱替換與平台升級後還要重跑（#277 第 12 點、#377 第 9、11 點）。「交付後驗收」的語感只涵蓋第一種用途。
4. **時機**。模型層的詞還沒進程式碼與資料表，現在改名只動 GLOSSARY 與議題決議的文字。issue 說「它即將進入程式與資料表」，這是要趁現在改的理由，不是保留的理由。營運驗收的改名代價確實較小，但它的英文 operational acceptance 與業界一致，改了反而失去對照。

新名稱的候選：

| 候選 | 判斷 |
| :--- | :--- |
| 可服務檢查 (Servability Check) | 採用：直接說出它問的問題；TFX 以 servable 描述同一件事；涵蓋交付、平台訓練與升級後重跑三種用途。 |
| 上線前檢查 | 不採用：涵蓋不了 API 啟動與平台升級後的重跑。 |
| 相容性檢查 | 不採用：與 #279「模型交付包輸入輸出形狀變更的相容性規則」撞名。 |
| 驗證、validation | 不採用：業界的 validation 有三種邊界（§2.3），repo 的「驗證窗」「驗證集」又已指 validation set。 |
| 就緒檢查、readiness | 不採用：與 `/tasks/{id}/ready`、`check_task_ready` 的就緒撞名。 |

改名後的 GLOSSARY 草稿：

- **可服務檢查 (Servability Check)**：平台確認一個模型版本能被現有平台服務的檢查：宣告是否完整，引用的特徵、輸入與產出是否都在平台支援的範圍內，能否載入並產出符合輸出契約的預測。模型交付包與平台訓練的結果都要通過，平台升級後對現役模型重新檢查；只問能不能服務，不比好壞。模型交付包未通過時，修正後可以重新交付，這不是終局判定。
  _Avoid_：驗收（與營運驗收、驗收標準撞名）、acceptance、model validation、評估閘門（比好壞）、核准、review、測試。

連帶要改的 GLOSSARY 詞條：模型交付包、候選模型、評估閘門、釘選、退回的「驗收」字樣，以及平台維護者定義中的「驗收模型交付包」。M11 的連帶名稱見 [§8](#8-建議的後續實作票)。

**備案**：如果維護者仍要保留模型層的「驗收」，改營運驗收為「營運實證 (Operational Proof)」，label 改 `ops-proof`，標題前綴改 `[營運實證]`，並在模型層驗收的 `_Avoid_` 加上「驗收標準（里程碑的完成條件）」。這個備案留下與「驗收標準」「Acceptance Criteria」的撞名。

### 4.2 lineage 的三種寫法

**結論：拆成兩個詞。** Dagster 資產之間的依賴寫「資產依賴圖」，屬技術詞，寫在 `docs/reference/`；成品的來歷寫「出處 (Provenance)」，交付包的出處稱「研究出處」，成為 GLOSSARY 詞條。「血緣」「世系」淘汰並登記為禁詞。

現況：

| 出處 | 寫法 | 指的是 |
| :--- | :--- | :--- |
| [ADR-0004][repo-adr-0004] 取捨分析 | 資料世系 (Lineage)、世系追蹤 | Dagster UI 中從原始資料到漂移報告的依賴圖 |
| [ADR-0015][repo-adr-0015] §2.3 | 血緣圖 | 匯出資產與其他資產在同一張 Dagster 依賴圖 |
| [dagster-schedules.md][repo-dagster] 第 1、6、7、8 項 | lineage 依賴 | 以 `deps` 宣告、不傳資料的資產依賴 |
| `task_pipelines.py`、`forecast_track_record.py` 的註解 | lineage | 同上 |
| #277 第 2、4 點 | 出處與血緣、血緣 | 宣告第 7 節：交付包的凍結資料、commit、研究主題目錄；平台模型的 `origin`、訓練 `as_of` 與映像 revision |
| GLOSSARY 的模型交付包 | 研究出處 | 同上，交付包的部分 |

業界的英文 lineage 同時用於兩個概念（§2.4）：Dagster 與 OpenLineage 的 lineage 是 job 或資產之間的資料流向；MLflow 與 SageMaker 的 model lineage 是一個模型的來歷，也就是 PROV-DM 的 provenance。repo 的「血緣」也同時被用在這兩處（ADR-0015 與 #277），所以這是一詞兩義，符合改名條件。

兩個詞的建議：

- **資產依賴圖**：Dagster 以 `deps` 或 input 宣告的資產依賴。[dagster-schedules.md][repo-dagster] 的「lineage 依賴 X，但不執行它們」改為「資產依賴（`deps`）X，但不執行它們」；ADR-0004 與 ADR-0015 的「世系」「血緣圖」改為「資產依賴圖」。英文 lineage 只在指 Dagster UI 的 lineage 檢視時出現，程式註解維持英文 lineage 不必改。
- **出處 (Provenance)**：一個成品由哪些資料、哪一版程式、經由誰產生的紀錄。宣告第 7 節由「出處與血緣」改名「出處」；其中的 `origin`（`platform`／`handoff`）中文稱「出處種類」，#377 生效紀錄裡的「出處」欄位同樣改稱出處種類。PROV-DM 的定義涵蓋實體、活動與人，所以出處種類、凍結資料、commit 與研究主題都在同一節之內。

**「研究出處」應成為 GLOSSARY 詞條。** 理由：

1. GLOSSARY 的模型交付包定義已經用到它，卻沒有定義。
2. 它承載業務規則：交付包帶研究出處而不帶評估證據（#277 第 3 點）；研究出處必須已在 `dev` 上，交付才算數（#277 第 5 點）。
3. 研究者與平台維護者在交付、審查與保留凍結資料時都要談到它。

平台模型的出處（訓練 `as_of`、映像 revision）屬實作細節，只寫進 `docs/reference/`。GLOSSARY 草稿：

- **研究出處 (Research Provenance)**：模型交付包記載的產生來歷：以哪一份凍結資料訓練、訓練程式是哪一個已合併的版本、對應哪個研究主題。用於重現、審查與保留，評估閘門不依它判定。
  _Avoid_：血緣、世系、lineage（Dagster 的資產依賴圖）、評估證據（交付包不帶）、重現紀錄（研究報告裡較完整的欄位表）。

「出處」在 repo 另有「文件引用來源」的一般用法，例如 [rules-of-ml.md][repo-rules-of-ml] 的「出處與授權」。這是同一類意思，不會誤讀；GLOSSARY 只收複合詞「研究出處」，不收單字「出處」。

### 4.3 #376 業界用語對照的查證

[#376](https://github.com/shiroki9979/shiro-mlops/issues/376) 決議的「業界用語對照」引用的 #272 研究檔已遺失。以下逐句重新查證，結論改指本報告：

| #376 的說法 | 查證結果 | 來源 |
| :--- | :--- | :--- |
| 能不能服務叫 model／infra validation（TFX InfraValidator），在本地圖是驗收 | infra validation 成立：它檢查模型在 serving 基礎設施中能否載入與查詢，不管預測對錯。model validation 不成立：Google 的 offline model validation 同時包含效能比較與基礎設施相容性測試，橫跨驗收與評估閘門，不能單指驗收。 | [TFX InfraValidator][tfx-infra]、[Google][google-mlops] |
| 夠不夠好叫 value threshold，在本 repo 是 `[health]` | 形式相同，角色不同：TFMA 的 value threshold 會擋下候選模型；`[health]` 依 #376 第 8 點只用於監控，不參與閘門。 | [TFMA][tfma-validations] |
| 誰比較好叫 champion/challenger，TFX Evaluator 對 baseline 判 blessing | Evaluator 的部分成立。但 InfraValidator 也輸出 blessing，所以 blessing 不專指評估閘門的判定，GLOSSARY 把它列入 `_Avoid_` 是對的。champion 在 MLflow 文件只是 alias 名稱的範例；champion/challenger 作為方法名的一手出處本次沒有查到。 | [TFX Evaluator][tfx-evaluator]、[InfraValidator][tfx-infra]、[MLflow][mlflow-registry] |
| MLflow 用 `MetricThreshold` 的 `min_absolute_change`／`min_relative_change` | 存在，但方向只有「至少好多少」：`min_absolute_change` 必須為正，`min_relative_change` 介於 0 與 1，設 0 等於「不比基準差」。平台重訓的「5% 容忍的不劣於」表達不了。TFMA 的 change threshold 可以設成允許候選略差（TFX 範例以 absolute `-1e-10` 表示「AUC 不低於基準」）。交付包的「嚴格優於」兩者都能表達。 | [MLflow validation.py][mlflow-validation]、[TFMA][tfma-validations]、[TFX Evaluator][tfx-evaluator] |
| 把勝出者換上去叫 promotion，在本地圖是釘選或平台模型更新 | 成立：MLflow 以 promote 指把版本推向 staging 或 production 環境，Google 以它指新模型通過驗證後晉升上線（promoted to production）。 | [MLflow workflow][mlflow-workflow]、[Google][google-mlops] |
| 來源見 #272 研究檔第 2.3 節與 3.10 節 | 研究檔已遺失，改指本報告 §2.2、§2.3 與本節。 | — |

## 5. 其他改名與統一寫法

- **提交改為交付**。#377 以「提交」稱交付包進入平台的那一步（提交紀錄、`handoff submit`），但「提交」在 repo 已有兩種意思：git commit（#277 第 4 點的「未提交變更」、`deploy-aws-infrastructure.md` 的「勿提交」）與交易 commit（ADR-0017 的「SQLite 執行 DDL 時即提交」）。GLOSSARY 與 #277 本來就以「交付」「重新交付」稱這個動作，所以改用「交付」，資料表稱交付紀錄；CLI 子命令維持英文 `submit` 即可。
- **`docs/research/` 改稱調查報告**。「研究報告」在 [lab.md §5][repo-lab]、ADR-0011 與 ADR-0018 指 lab 研究主題的 README，它會被研究出處引用，並保護凍結資料不被刪除（ADR-0018 §2.2）；ADR-0015 的 Notes 與 #408 又用它稱 `docs/research/` 的文件。兩者的契約不同，前者有固定段落與重現紀錄。`docs/research/` 既有的文件標題本來就寫「調查」（例如[台電全台逐時實際負載來源調查](2026-09-16-taipower-hourly-actual-load-source.md)），所以以「調查報告」稱它。
- **model store 的中文統一為「模型存放」**。[ml-tasks.md §4][repo-ml-tasks] 的標題寫「模型保存」，[dagster-schedules.md][repo-dagster] 寫「模型存放」。ADR-0010 的「保存」指保存格式，所以元件名稱統一為「模型存放」，#377 的 `DATA_DIR/handoffs/` 稱「交付包存放區」。兩者都不是 model registry。
- **隨需請求與隨需預測擇一**。GLOSSARY 的預報時刻與已發布預報寫「隨需請求」，現役模型寫「隨需預測」，指的是同一件事。
- **平台維護者的定義**。「驗收模型交付包、決定釘選」改為「審查釘選變更」之類的寫法：可服務檢查與評估閘門都由平台執行，判定不得人工推翻，人的決定只在期望狀態的 PR。

## 6. 業界有、repo 沒有的概念

| 概念 | 業界來源 | 結論 | 理由或影響 |
| :--- | :--- | :--- | :--- |
| 平台模型的退回 | [SageMaker][sm-approve]：使用專案範本時，把已核准版本改為 `Rejected` 會重新部署最新一個 `Approved` 版本；[Google][google-mlops]：ML metadata 要保留指向前一個訓練好的模型的指標，以便退回前一個模型版本 | 值得補進設計 | 影響 #270「平台模型本身的退回」。平台模型只留一份，又不能被釘選；通過閘門的平台模型上線後變差時，止損只能等下一次平台重訓勝出，或另交一份能贏過它的交付包。若變差的原因也影響重訓（例如上游資料錯誤），而該任務從未有交付包生效過，就沒有不靠研究者的止損路徑。建議保留前一份平台模型，並讓退回涵蓋它。 |
| 模型新舊（model staleness） | [ML Test Score][ml-test-score]：測試模型是否過舊（搜尋摘錄） | 值得補進設計 | 影響 #270「釘選模型的監控」。釘選不會到期，釘選期間監控評估的是平台模型（#274），交付包的訓練截止會無聲地變舊。建議監控報告列出現役模型的訓練截止距今多久，並以預報實績（已發布預報帶 `model_sha256`）計算現役模型本身的核心指標。 |
| 健康判定依問題類型 | [SageMaker][sm-quality]：模型品質監控的指標取決於 ML 問題類型 | 值得補進設計 | 影響 #270「`[health]` 的健康判定規則改歸輸出契約還是監控本身」。交付包的任務類型可以和平台模型不同（#376 第 5 點）；規則若留在任務類型的 `assess_health`，同一個 ML 任務換了模型就換了健康規則。建議歸輸出契約，和評分器、核心指標放在一起。 |
| Model card | [Model Cards][model-cards]、[SageMaker Model Cards][sm-cards] | 知悉但不採用 | 宣告（#277 的七節）、判定報告（#377 第 16 點）與輸出契約已涵蓋模型細節、訓練資料與評估；沒有要在多個模型之間挑選的外部使用者。 |
| Intended use、out-of-scope use | [SageMaker Model Cards][sm-cards]；[NIST MAP 1.1][nist-rmf]；[EU AI Act Art. 3(12)][eu-ai-act]（搜尋摘錄） | 知悉但不採用 | 用途由 ML 任務與輸出契約固定，不隨模型版本改變；交付包不能宣告契約以外的產出（#279）。 |
| 模型清冊（model inventory） | [NIST GOVERN 1.6][nist-rmf]；[SR 11-7][sr117]：由專人維護全公司的模型清冊 | 知悉但不採用 | `tasks/` 與 `serving/` 一對一（#388），加上生效紀錄，已列出每個 ML 任務與它的現役模型。 |
| 獨立驗證；V&V 與 T&E 分離 | [NIST Appendix A][nist-actors]；[SR 11-7][sr117]：獨立驗證與 effective challenge | 知悉但不採用 | 單人維護。以「判定一律由平台以成品重算、不採信交付包附上的證據」（#376 第 12 點）機械化代替。 |
| Effective challenge | [SR 11-7][sr117] | 知悉但不採用 | 需要另一位有影響力的審查者；本 repo 只有 PR review 與公開 repo 的讀者。 |
| Datasheet | [Datasheets for Datasets][datasheets] | 知悉但不採用 | 資料來源與 schema 已在 [data-contracts.md][repo-data-contracts]，凍結資料的清單記錄切面；沒有外部資料集使用者。 |
| 模型退役（decommissioning） | [NIST GOVERN 1.7][nist-rmf] | 知悉但不採用 | 已由下架與交付包的保留下限（#411）涵蓋，只補英文對照。 |
| 事件通報（serious incident、incident reporting） | [EU AI Act Art. 3(49)][eu-ai-act]（搜尋摘錄）；[NIST AI 600-1 MANAGE 4.3][nist-600] | 知悉但不採用 | 沒有須通報的使用者或主管機關；預報檢視的錯誤以 issue 處理，已發布預報原樣保存，可供事後追查。 |
| 線上驗證（canary、A/B、shadow） | [Google][google-mlops] | 知悉但不採用 | #376 已否決影子部署：以 `known_by` 事後回測等效；單機部署，沒有流量可分。 |
| 人工核准狀態（`PendingManualApproval`） | [SageMaker][sm-approve] | 知悉但不採用 | 閘門判定有拘束力，不得人工推翻（#376）；人的決定只在期望狀態的 PR。 |
| 人為推翻與申訴（appeal and override） | [NIST MANAGE 4.1][nist-rmf] | 知悉但不採用 | 理由同上；止損以解除釘選與退回達成。 |
| 風險分級（risk rating） | [SageMaker Model Cards][sm-cards]；[EU AI Act Annex III][eu-ai-act]（搜尋摘錄） | 知悉但不採用 | 單一領域的展示專案，不作為電網運轉的安全元件。 |
| 訓練與 serving 的偏差（training-serving skew） | [Vertex][vertex-monitoring] | 知悉但不採用 | 已是 #270「訓練與 serving 的特徵一致性」的未決項目；評估閘門以預報天氣評分，偏差的後果會反映在核心指標。只把 skew 記為該項目的英文對照。 |
| 推論輸入的擷取保存（data capture） | [SageMaker Model Monitor][sm-monitor] | 知悉但不採用 | 預測輸入可依知悉時間近似重建（ADR-0018）；是否保存仍由 #270「已發布預報記錄模型來源」的未決部分決定。 |
| 實質修改與預定變更（substantial modification） | [EU AI Act Art. 3(23)、Recital 128][eu-ai-act]（搜尋摘錄） | 知悉但不採用 | 只作理解：平台重訓在閘門內是預定的變更，改輸出契約才是實質變更；repo 已以「破壞性變更就開新的 ML 任務」處理（#279）。 |

## 7. 禁詞建議清單

只收 repo 自己淘汰的繁中舊詞。業界英文詞不登記，它們會以對照的身分合法出現在 GLOSSARY 與 `docs/reference/`。

| 舊詞 | 改用 | 目前出現處（tracked Markdown） | 備註 |
| :--- | :--- | :--- | :--- |
| 世系 | 資產依賴圖 | ADR-0004（2 處） | 先改 ADR 正文的用語 |
| 血緣 | 資產依賴圖或出處 | ADR-0015（1 處） | 同上；#277 的決議文字不在 repo 內 |
| 驗收關卡 | 可服務檢查 | 無 | 預防性；#277 的標題用過「平台端驗收關卡」 |
| 不可用預報 | 無法產出 | GLOSSARY §3 的 `_Avoid_` | |
| 模型家族 | 任務類型 | ADR-0009、ADR-0010、ADR-0011 | 條件式：ADR-0010 的用法指估計器種類，要等 M11 ADR 改寫 ADR-0009 與 ADR-0011 時一併決定改寫或豁免 |

不登記的詞：

- 「驗收」「提交」「快照」「研究報告」「出處」：它們在 repo 另有合法用法，子字串比對會誤中。
- 「上線模型」「預設模型」：兩者都是在新增現役模型與平台模型詞條的同一個 commit（`1b83e61`）裡直接寫進 `_Avoid_` 的，從來不是 repo 用過的詞，不屬於「repo 自己淘汰的舊詞」。「上線模型」另有子字串風險，例如「釘選上線模型交付包」這類句子會誤中。

**登記前要先改檢查。** `scripts/check_conventions.py` 的 `terms` 檢查以 `find_banned_terms` 對所有 tracked Markdown 逐行做子字串比對，沒有任何豁免，`lab/` 也在範圍內；`BANNED_TERMS` 目前只有一個詞。GLOSSARY 的 `_Avoid_` 行本來就要寫出舊詞，本報告也寫出了上表的每一個舊詞。所以要先讓 `_Avoid_` 行與 `docs/research/` 豁免，再登記禁詞，否則 CI 會在 GLOSSARY 與本報告上失敗。豁免機制由後續實作票決定。

## 8. 建議的後續實作票

### 8.1 GLOSSARY

一張票，遵守「GLOSSARY 不放實作細節」：

- 驗收改為可服務檢查（草稿見 §4.1），同步模型交付包、候選模型、評估閘門、釘選、退回的文字。
- 平台維護者的定義改寫（§5）。
- 新增研究出處（草稿見 §4.2）與輸出契約。輸出契約寫成業務語意：ML 任務對下游承諾的產出、時程範圍與評判好壞的方式；`_Avoid_` 列 model signature。
- 補英文對照：候選模型（candidate model）、現役模型（production model 從 `_Avoid_` 移出）、下架（decommissioning）、概念漂移（real concept drift）。
- 修定義或 `_Avoid_`：特徵漂移寫明基準分佈；評估閘門的 `_Avoid_` 加 model validation；滾動起點回測的「交叉驗證」理由改寫；隨需請求與隨需預測擇一。

### 8.2 營運驗收

建議保留，不開票。如果維護者否決 §4.1，改開一張票執行 §4.1 的備案，範圍是 `docs/agents/issue-tracker.md`、`docs/agents/triage-labels.md`、`docs/ROADMAP.md`、`docs/reference/terraform-state-and-deployment.md` 與 GitHub label。

### 8.3 `terms` 檢查

兩張票，有先後：

1. 讓 `_Avoid_` 行與 `docs/research/` 豁免，機制待定（例如依行首或依路徑判斷）。
2. 登記 §7 的清單，同時改 ADR-0004 與 ADR-0015 的用語。

### 8.4 `docs/reference/` 與 ADR 用語

一張票，只改用語，不改決定：

- [dagster-schedules.md][repo-dagster]：「lineage 依賴」改「資產依賴（`deps`）」。
- [ml-tasks.md][repo-ml-tasks]：§4 標題改「模型存放」；註明它不是 model registry；任務類型補 MLflow flavor 對照，並註明 `TASK_TYPES` 的 registry 與 MLflow Model Registry 無關。
- [data-contracts.md §5][repo-data-contracts]：註明 Dagster artifact 與成品（model artifact）不同。
- ADR-0004、ADR-0015：世系、血緣改為資產依賴圖。
- ADR-0018（`Proposed`）：point-in-time 處加註以知悉時間判定；「交付包的評估證據只認標準模式」與 #277「交付包不帶評估證據」不一致，定稿為 `Accepted` 時改寫成研究報告的回測。

### 8.5 文件類型的稱呼

一張小票：在 `docs/agents/` 或 [markdown-metadata.md][repo-metadata] 寫明 `docs/research/` 的文件稱「調查報告」，「研究報告」專指 lab 研究主題的 README。

### 8.6 影響 M11 契約的命名結論

不另開票，寫回 #270 的 Notes，作為 ADR 起草的輸入：

1. **可服務檢查**：函式（例如 `check_servability(directory, task) -> ServabilityReport`，取代 `accept_handoff` 與 `AcceptanceReport`）、報告資料表與 reconciler 的拒絕理由都改用此名。規則代碼前綴建議改為與檢查同名（例如 `servability-*`），不用 `handoff-*`，因為平台訓練結果也套用同一套規則（#277 第 11 點）。
2. **交付取代提交**：交付紀錄資料表；CLI 子命令可維持 `submit`。
3. **出處**：宣告第 7 節名稱為「出處」；`origin` 稱出處種類。
4. **待定**：閘門判定值寫 `inconclusive`，不寫 `pending`。
5. **生效紀錄**：英文用 activation（例如 `activation` 資料表），不用 deployment、promotion 或 registry。
6. **既有模型接軌**：依據欄的值要和閘門判定、退回並列，而且不暗示通過閘門；英文值可用 `grandfathered`。
7. **三項值得補進設計的概念**（§6）寫進對應的未決項目：平台模型本身的退回、釘選模型的監控、`[health]` 規則的歸屬。
8. **#376 的業界用語對照**改指本報告 §4.3，並修正 MLflow `MetricThreshold` 的方向。

### 8.7 議題留言

- #270、#376：依 #408 的 Acceptance Criteria 一定留言，內容見 §8.6。
- #277：「出處與血緣」改「出處」，驗收改可服務檢查。
- #377：提交改交付，驗收改可服務檢查，生效紀錄的「出處」欄改稱出處種類。
- #411：決議文字也用「驗收」，可在同一輪附註，非 Acceptance Criteria 要求。

## 9. 限制

### 9.1 連不到的主機

初次撰寫時，NIST、聯準會、EUR-Lex、ISO、arXiv 與 Google 的主機都被本環境的網路政策拒絕，相關說法只取自搜尋摘錄。之後 `nvlpubs.nist.gov`、`airc.nist.gov`、`www.federalreserve.gov`、`eur-lex.europa.eu`、`www.iso.org`、`arxiv.org`、`docs.cloud.google.com`、`research.google` 加進了允許清單，同日以 `curl` 重讀原文複核。WebFetch 對這些主機仍回報 `getaddrinfo ENOTFOUND`，所以複核只用 `curl`。

複核後仍讀不到的主機：

- `eur-lex.europa.eu`：回應 HTTP 202 且內容為空，是自動讀取的防護頁，不是網路政策。EU AI Act 維持搜尋摘錄。
- `www.iso.org`，含 [ISO OBP][iso-obp]：回應 HTTP 403。ISO/IEC 42001、22989 的術語維持未查證。
- `storage.googleapis.com`（未放行）：ML Test Score 的 PDF 放在這裡；`research.google` 的論文頁只有摘要。
- 未放行，改讀各專案 GitHub 上的文件原始檔或原始碼：`mlflow.org`、`www.tensorflow.org`、`docs.dagster.io`、`docs.feast.dev`、`openlineage.io`、`www.w3.org`、`kubernetes.io`、`opengitops.dev`。
- 未放行，維持搜尋摘錄：`glossary.istqb.org`、`cognitect.com`、`dl.acm.org`、`otexts.com`。

### 9.2 搜尋摘錄與未查證

- **以原文複核後改動的說法**：Google 的 offline model validation 除了效能比較，也包括「測試模型能否部署，含基礎設施相容性與 prediction service API 的一致性」。初稿依摘錄寫成「Google 的 model validation 只指效能優於基準」，已修正 §2.3、§3.3 與 §4.3；結論「model validation 不能當驗收或評估閘門的英文名稱」不變，理由改為它同時涵蓋兩者。其餘 NIST、SR 11-7、Model Cards、Datasheets 的說法與原文一致，只把標記改為原文。
- **以原文補上的項目**：SR 11-7 的角色分工（ownership、controls、compliance，model owner 負最終責任）與全公司模型清冊；Model Cards 與 Datasheets 的章節名稱。
- **搜尋摘錄**：EU AI Act、ML Test Score 的條目、ISTQB Glossary、Nygard 的 ADR 文章、Gama 等人的 survey。措辭沒有逐字核對，主機開放後應開原頁複核。
- **未查證**：
  - ISO/IEC 42001 與 22989 的全部術語內容。
  - EU AI Act 的 provider、deployer 定義，以及 Article 11、12、72、73 的條文。
  - ML Test Score 中 rollback、canary 與訓練可重現的條目。
  - 雙時間資料庫的 transaction time 定義，以及 champion/challenger 作為方法名的一手出處。
  - Hyndman 等人對 time series cross-validation 的說法（本報告改引 scikit-learn）。

### 9.3 判斷有疑義之處

1. **驗收改模型層**，與 issue 的初步看法相反（§4.1）。判斷依據是 repo 內「驗收」的通用用法與英文 Acceptance 的業界邊界；如果維護者更重視「交付」與「驗收」的中文配對，備案仍可解決撞名。
2. **研究報告與調查報告的切分**（§5）。撞名的影響較小，若維護者認為不值得，維持現狀也只是語意不夠精確。
3. **英文命名建議**：生效紀錄的 activation、既有模型接軌的 `grandfathered`、可服務檢查的規則代碼前綴，都沒有業界標準詞可依。
4. **把 production model 從 `_Avoid_` 移出**。邊界一致，Google 的 MLOps 文章也這樣用；但 production 在 repo 也可能被讀成 `main` 分支或正式環境。
5. **禁詞中的模型家族**：歷史 ADR 要改寫還是豁免，未定。

## 10. 來源清單

讀取日期一律為 2026-11-27。

| 來源 | 版本 | 讀取方式 |
| :--- | :--- | :--- |
| [MLflow Model Registry 文件][mlflow-registry]、[workflow][mlflow-workflow]、[MLflow Model][mlflow-model]、[signatures][mlflow-signature] | v3.16.1（與 `uv.lock` 相同） | 原文（GitHub 文件原始檔） |
| [MLflow `validation.py`][mlflow-validation]、[`client.py`][mlflow-client] | v3.16.1 | 原文（原始碼） |
| [TFX Evaluator][tfx-evaluator]、[InfraValidator][tfx-infra]、[Pusher][tfx-pusher] | v1.16.0 | 原文（GitHub 文件原始檔） |
| [TFMA model validations][tfma-validations] | v0.47.0 | 原文（GitHub 文件原始檔） |
| [SageMaker Model Registry][sm-registry]、[approval][sm-approve]、[staging construct][sm-staging]、[ML Lineage Tracking][sm-lineage]、[Model Monitor][sm-monitor]、[model quality][sm-quality]、[Model Cards][sm-cards] | 線上文件，無版本號 | 原文 |
| [Vertex AI `model.proto`][vertex-model]、[`model_service.proto`][vertex-service]、[`model_monitoring.proto`][vertex-monitoring] | `googleapis/googleapis` commit `fc38bc1`，API v1 | 原文（原始碼） |
| [Dagster asset dependencies][dagster-deps]、[tutorial][dagster-tutorial] | 1.13.19（與 `uv.lock` 相同） | 原文（GitHub 文件原始檔） |
| [Feast feature retrieval][feast-retrieval] | v0.66.0（與 `uv.lock` 相同） | 原文（GitHub 文件原始檔） |
| [scikit-learn cross validation][sklearn-cv]、[model evaluation][sklearn-metrics] | 1.9.0（與 `uv.lock` 相同） | 原文（GitHub 文件原始檔） |
| [OpenLineage spec][openlineage] | commit `b9cd9fd` | 原文（GitHub） |
| [W3C PROV-DM][prov-dm] | W3C Recommendation 2013-04-30，取自 `w3c/prov` commit `aa82bd7` | 原文（GitHub） |
| [Kubernetes controller][k8s-controller] | `kubernetes/website` commit `61712dd` | 原文（GitHub） |
| [OpenGitOps principles][gitops-principles]、[glossary][gitops-glossary] | `open-gitops/documents` commit `9752f1d` | 原文（GitHub） |
| [NIST AI 100-1][nist-rmf]、[Appendix A][nist-actors]、[NIST AI 600-1][nist-600] | AI RMF 1.0（2023-01）；AI 600-1（2024-07） | 原文（PDF；Appendix A 另見 AIRC 線上版） |
| [SR 11-7][sr117] | 2011-04-04 附件 | 原文（PDF） |
| [EU AI Act][eu-ai-act] | Regulation (EU) 2024/1689，含 2026-07-27 合併版 | 搜尋摘錄（EUR-Lex 擋下自動讀取） |
| [Google MLOps 文章][google-mlops] | 線上文件，Last reviewed 2024-08-28 | 原文 |
| [ML Test Score][ml-test-score] | Breck et al., IEEE Big Data 2017 | 摘要頁為原文；條目為搜尋摘錄 |
| [Model Cards for Model Reporting][model-cards] | arXiv 1810.03993v2 | 原文（PDF） |
| [Datasheets for Datasets][datasheets] | arXiv 1803.09010v8 | 原文（PDF） |
| [ISTQB Glossary][istqb] | v3.5 release notes 所載定義 | 搜尋摘錄 |
| [Documenting Architecture Decisions][nygard] | 2011-11-15 | 搜尋摘錄 |
| [A Survey on Concept Drift Adaptation][gama] | ACM Computing Surveys 46(4), 2014 | 搜尋摘錄 |
| [ISO/IEC 42001][iso-42001]、[ISO/IEC 22989][iso-22989]、[ISO OBP][iso-obp] | 42001:2023、22989:2022 | 標準頁為搜尋摘錄；術語條目未查證 |

[mlflow-registry]: https://github.com/mlflow/mlflow/blob/v3.16.1/docs/docs/classic-ml/model-registry/index.mdx
[mlflow-workflow]: https://github.com/mlflow/mlflow/blob/v3.16.1/docs/docs/classic-ml/model-registry/workflow.mdx
[mlflow-model]: https://github.com/mlflow/mlflow/blob/v3.16.1/docs/docs/classic-ml/model/index.mdx
[mlflow-signature]: https://github.com/mlflow/mlflow/blob/v3.16.1/docs/docs/classic-ml/model/signatures/index.mdx
[mlflow-validation]: https://github.com/mlflow/mlflow/blob/v3.16.1/mlflow/models/evaluation/validation.py
[mlflow-client]: https://github.com/mlflow/mlflow/blob/v3.16.1/mlflow/tracking/client.py
[tfx-evaluator]: https://github.com/tensorflow/tfx/blob/v1.16.0/docs/guide/evaluator.md
[tfx-infra]: https://github.com/tensorflow/tfx/blob/v1.16.0/docs/guide/infra_validator.md
[tfx-pusher]: https://github.com/tensorflow/tfx/blob/v1.16.0/docs/guide/pusher.md
[tfma-validations]: https://github.com/tensorflow/model-analysis/blob/v0.47.0/g3doc/model_validations.md
[sm-registry]: https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html
[sm-approve]: https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry-approve.html
[sm-staging]: https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry-staging-construct.html
[sm-lineage]: https://docs.aws.amazon.com/sagemaker/latest/dg/lineage-tracking.html
[sm-monitor]: https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor.html
[sm-quality]: https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor-model-quality.html
[sm-cards]: https://docs.aws.amazon.com/sagemaker/latest/dg/model-cards.html
[vertex-model]: https://github.com/googleapis/googleapis/blob/fc38bc195c0db21fbf363f2b6d824b191e7496d1/google/cloud/aiplatform/v1/model.proto
[vertex-service]: https://github.com/googleapis/googleapis/blob/fc38bc195c0db21fbf363f2b6d824b191e7496d1/google/cloud/aiplatform/v1/model_service.proto
[vertex-monitoring]: https://github.com/googleapis/googleapis/blob/fc38bc195c0db21fbf363f2b6d824b191e7496d1/google/cloud/aiplatform/v1/model_monitoring.proto
[dagster-deps]: https://github.com/dagster-io/dagster/blob/1.13.19/docs/docs/guides/build/assets/defining-assets-with-asset-dependencies.md
[dagster-tutorial]: https://github.com/dagster-io/dagster/blob/1.13.19/docs/docs/dagster-basics-tutorial/1-assets.md
[feast-retrieval]: https://github.com/feast-dev/feast/blob/v0.66.0/docs/getting-started/concepts/feature-retrieval.md
[sklearn-cv]: https://github.com/scikit-learn/scikit-learn/blob/1.9.0/doc/modules/cross_validation.rst
[sklearn-metrics]: https://github.com/scikit-learn/scikit-learn/blob/1.9.0/doc/modules/model_evaluation.rst
[openlineage]: https://github.com/OpenLineage/OpenLineage/blob/b9cd9fd9c323af31807d130eb2c7db23998d7f3c/spec/OpenLineage.md
[prov-dm]: https://github.com/w3c/prov/blob/aa82bd71b6bb1f7b735bf3f7f5b948fae87764f0/model/releases/REC-prov-dm-20130430/Overview.html
[k8s-controller]: https://github.com/kubernetes/website/blob/61712ddb619690242534e6e86bb5646c88f16c2e/content/en/docs/concepts/architecture/controller.md
[gitops-principles]: https://github.com/open-gitops/documents/blob/9752f1dec5ee20d9b124e3eb71c3b90d8a8e15c1/PRINCIPLES.md
[gitops-glossary]: https://github.com/open-gitops/documents/blob/9752f1dec5ee20d9b124e3eb71c3b90d8a8e15c1/GLOSSARY.md
[nist-rmf]: https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf
[nist-actors]: https://airc.nist.gov/airmf-resources/airmf/appendices/app-a-descriptions-of-ai-actor-tasks/
[nist-600]: https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
[sr117]: https://www.federalreserve.gov/boarddocs/srletters/2011/sr1107a1.pdf
[eu-ai-act]: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689
[google-mlops]: https://docs.cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning
[ml-test-score]: https://research.google/pubs/the-ml-test-score-a-rubric-for-ml-production-readiness-and-technical-debt-reduction/
[model-cards]: https://arxiv.org/abs/1810.03993
[datasheets]: https://arxiv.org/abs/1803.09010
[istqb]: https://glossary.istqb.org/
[nygard]: https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
[gama]: https://dl.acm.org/doi/10.1145/2523813
[iso-42001]: https://www.iso.org/standard/42001
[iso-22989]: https://www.iso.org/standard/74296.html
[iso-obp]: https://www.iso.org/obp
[repo-issue-tracker]: ../agents/issue-tracker.md
[repo-ml-tasks]: ../reference/ml-tasks.md#4-模型保存tasksmodel_storepy
[repo-lab]: ../reference/lab.md#5-研究報告labyyyy-mm-dd-topicreadmemd
[repo-metadata]: ../reference/markdown-metadata.md
[repo-data-contracts]: ../reference/data-contracts.md#5-dagster-artifact-序列化與信任邊界
[repo-dagster]: ../reference/dagster-schedules.md
[repo-rules-of-ml]: ../explanation/rules-of-ml.md
[repo-adr-0004]: ../adr/0004-dagster-asset-based-orchestration.md
[repo-adr-0015]: ../adr/0015-publish-forecast-view-as-static-precomputed-output.md
