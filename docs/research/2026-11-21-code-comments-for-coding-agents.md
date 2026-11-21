# Coding agent 時代的程式碼註解策略調查

- 建立日期：2026-11-21
- 最後更新：2026-11-21
- 對應：#181 Coding agent 時代的註解策略：研究報告與跨專案 guide
- 結論：**刪冗餘註解有據，「D 最好」卻證據不足。** 刪掉重述型註解、把 why 寫下來有證據支持；只留標頭與 why-not 的嚴格版本會少抓陷阱 bug，最大的風險是被奉為天條的註解過時。
- 延伸：可跨專案採用的原則見 [採用 coding agent 時代的註解策略](../how-to/adopt-agent-era-comment-policy.md)。

## 研究對象

一則貼文主張：coding agent 能讀大量程式碼，所以多份重複的說明（設計書、檔頭、內文註解、commit 訊息）大多不必保留，只要留下 package 與 class header，並把其中的不變條件當成永遠不能冒犯的「天條」。貼文附上的註解規則如下：

> 命名優先於註解（Names over comments）。名稱、型別、小型函式與測試應該清楚表達程式碼的用途與行為。凡是只是重述這些資訊的註解，都應刪除——例如重複函式簽章的文件說明、重複欄位名稱的欄位註解，或只是敘述下一行程式碼要做什麼的旁白。
>
> 註解只允許出現在兩種情境：
>
> 1. 模組或類別的標頭註解（Module/Class Header）：用一到三行說明其角色，以及所有修改都必須維持的不變條件（invariant）。也就是新呼叫端或新增函式可能破壞的核心規則。
> 2. 設計理由註解（Why-not）：放在那些表面上看起來不合理、多餘或任意，但實際上是刻意如此設計的程式碼旁邊。這類註解必須說明背後的限制條件、實際觀察到的失敗情況，或當時的決策依據。
>
> 這類註解必須明確指出它所保護的程式碼，讓日後修改相關程式碼時，仍能檢驗註解是否有效；當該段程式碼被移除時，註解也必須一併刪除。至於對執行期行為（runtime behaviour）的描述，仍須遵守前述規則。

實驗由 Opus 依不同規則改寫 3 個模組的註解，再讓 Sonnet 閱讀、修改並審查埋入的 bug。O 是現狀，N 是全刪，A 到 D 是不同嚴格度的規則；貼文沒有說明上述規則對應哪個版本。

| 指標 | O 現狀 | N 全刪 | A | B | C | D |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| 保留的註解字元（3 個模組） | 11,753 | 0 | 7,794 | 2,930 | 1,545 | 4,196 |
| 理解程式碼做什麼（what） | 94% | 97% | 92% | 86% | 83% | 92% |
| 理解為什麼這樣寫（why） | 94% | 60% | 96% | 96% | 81% | 98% |
| 審查時抓到的陷阱 bug | 10/14 | 3/14 | 10/14 | 6/14 | 5/14 | 6/14 |
| 審查時抓到的邏輯 bug | 12/12 | 12/12 | 12/12 | 11/12 | 12/12 | 12/12 |
| 修改時察覺設計衝突 | 6/6 | 3/6 | 6/6 | 6/6 | 4/6 | 6/6 |
| 停下來詢問而非直接實作 | 0/4 | 0/4 | 1/4 | 2/4 | 0/4 | 4/4 |
| 兩位改寫者的一致性（κ） | — | — | 0.77 | 0.54 | 0.82 | 0.81 |

## 摘要

這則貼文的方向大致站得住，結論卻說過頭了。「刪掉只重述名稱、簽章或下一行程式碼的註解，把 why 寫下來」同時得到已發表研究與貼文自身數據的支持：全刪的 N 版仍理解 97% 的 what，但 why 掉到 60%，陷阱 bug 也從 10/14 掉到 3/14。可是「D（模組／類別標頭加 why-not）最好」撐不住：D 漏掉了 O 與 A 都抓到的 10 個陷阱中的 4 個，而它唯一明顯的優勢「停下來詢問 4/4」只建立在 4 個任務上，若採配對分析，最小可達的精確 McNemar p 值是 **0.125**，無論結果多懸殊都不可能顯著；整張表也**沒有任何一項差異撐得過多重比較校正**。數據最直接支持的，其實是較溫和的 A：刪掉約三分之一的註解字元，所有指標都看不出損失。文獻最一致的發現是**錯誤或過時的註解造成的傷害遠大於沒有註解**，而且叫模型「忽略註解」並不管用；貼文只測了剛改寫、內容正確的註解，所以沒量到這條規則真正的風險：被奉為「天條」的少數註解一旦過時，agent 會拿它對抗程式碼。對 shiro-mlops 來說，`#` 註解層（`src/` 共 7,808 字元，多半已是理由與同步來源）其實已接近目標；這條規則真正會砍到的是 64,077 字元的 docstring，其中一部分由 FastAPI、Pydantic 與 argparse 在執行期讀取，直接刪除會改變 OpenAPI 文件，還會讓兩支 CLI 一啟動就崩潰。

## 文獻支持「刪重述、留 why」，最一致的警訊卻是過時註解

先說清楚證據的限度：這批文獻多為 2025–2026 年的預印本，研究團隊在本次調查中無法開啟 arXiv 全文，數字取自摘要與檢索結果頁，個別模型的細項尚未對照原文核實。即便如此，方向相當一致。在小型、自足函式的理解型任務上，拿掉註解幾乎沒有影響。MITRE 的 Macke 與 Doyle 讓 GPT-3.5 與 GPT-4 替 164 個 HumanEval 解答產生單元測試，結論是缺漏或不完整的文件「does not seem to significantly affect an LLM's ability to understand code」，錯誤文件卻「can greatly hinder code understanding」，隨機註解條件的成功率最低，**GPT-3.5 僅 22.1%、GPT-4 為 68.1%** ([Macke & Doyle, Findings of NAACL 2024](https://arxiv.org/abs/2404.03114))。NeurIPS 2025 的 CodeCrash 以 17 個模型、1,279 題輸出預測測試各種擾動，純結構擾動整體只造成 **1.63 個百分點** 的下降 ([CodeCrash](https://arxiv.org/html/2504.14119v3))。這與 N 版 97% 的 what 理解相符，但有個常被忽略的前提：這些研究都保留了識別字名稱。「When Names Disappear」把名稱混淆之後，模型的摘要就從意圖層級退回逐行描述 ([Le et al.](https://arxiv.org/pdf/2510.03178))。換句話說，扛起 what 的是名稱，不是註解；貼文規則中的「名稱優先」才是 N 版高分的真正機制。

除錯與偵測任務的圖像就不同了。一篇 2026 年 1 月的預印本在兩個 LLM 家族上交叉比較訓練與推論時有無註解，發現註解讓 bug 修復準確率**最多提高三倍**，其中「describing method implementation」的註解特別有用 ([arXiv 2601.23059](https://arxiv.org/abs/2601.23059))；不過那是微調設定，模型可能較小，不能直接套到前沿 agent 上。Thornton 對 8 個前沿模型做了 9,366 次試驗，發現操弄性註解對偵測準確率只有「small, statistically non-significant effects」，但「comment stripping, the 'obvious' defense, actually degraded detection for weaker models」 ([Thornton 2026](https://arxiv.org/html/2602.16741v1))。以概念層級開關模型內「註解」表徵的 Inside Out 研究，量到的效果幅度從 **−90% 到 +67%** 都有，且「model-specific and task-dependent」 ([Imani et al.](https://arxiv.org/abs/2512.16790))。所以「註解不必要」只在特定任務、特定模型上成立。貼文中 logic bug 各版本都是 11–12/12，與 Thornton 的前沿模型結果一致；合理的解讀是模型越強，一般邏輯錯誤越不依賴註解，但這是推論，目前沒有研究在同一任務上跨模型規模直接驗證過。

why 則幾乎無法從程式碼還原。一篇以 4 個 LLM、30 個開發者撰寫的架構決策為樣本的研究發現，模型能「to a moderate extent」從 commit 還原架構資訊，但產出「often too implementation-focused and leave out the rationale behind the change」 ([arXiv 2609.03721](https://arxiv.org/abs/2609.03721))；另一項研究讓 5 個 LLM 以零樣本產生設計理由，平均 **F1 只有 0.381** ([arXiv 2504.20781](https://arxiv.org/abs/2504.20781))。ETH Zurich 對 AGENTS.md 的評估也是同樣形狀：LLM 生成的脈絡檔讓 SWE-bench Lite 解題率下降 0.5%、AGENTbench 下降 2%，推論成本卻增加**超過 20%**；開發者手寫的檔案在 AGENTbench 平均只帶來 4% 改善。檔案中的指令「are well followed」，儲存庫概覽卻「are not helpful」，真正有用之處在「specifying non-standard coding practices」 ([Gloaguen et al. 2026](https://arxiv.org/abs/2602.11988))。Anthropic 的提示指南也說，告訴 Claude 一條指令背後的動機，能讓回應更貼近目標 ([Claude prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices))。三個方向都指向同一件事：what 交給程式碼，why 與「必須」要寫下來。N 版 why 從 94% 掉到 60%，正是文獻預期的結果。

文獻中最一致、也最該影響規則設計的發現，是錯誤或過時的註解。ASE 2026 的「When Comments Mislead」指出，過時註解會把生成的程式碼拉向舊實作，結果整體看似合理，卻恰好在實作已改變之處失敗，作者稱註解是「strong but unreliable context signals」 ([Xia et al., ASE 2026](https://doi.org/10.1145/3832783.3834359))；脈絡中被註解掉的缺陷程式碼，會讓 GitHub Copilot 與 Cursor 產生缺陷程式碼的比率**最高達 58.17%** ([Comment Traps, ACM](https://dl.acm.org/doi/10.1145/3797102))。更關鍵的是，叫模型別理會註解並沒有用：CodeCrash 的「忽略註解」指示讓 Pass@1 幾乎不變 ([CodeCrash](https://arxiv.org/html/2504.14119v3))，ALIBI 也發現「even when explicitly told to treat comments as untrusted, LLMs often failed to do so」，並主張全刪註解不是可行的防禦 ([Wu & Nita-Rotaru 2026](https://arxiv.org/abs/2607.24964))。這對貼文是雙面刃。它支持刪掉重述型註解，因為那些最容易過時，對強模型又幾乎沒有加分；但它也意味著被留下、被奉為天條的少數註解，是模型會照單全收的高權威宣稱。**一條過時的不變條件，比一條過時的重述註解更危險**，因為 agent 會拿它替舊設計辯護。而貼文六個版本的註解全是剛改寫、內容正確的，實驗只量到註解的好處，完全沒量到它的腐化風險。

至於「停下來詢問」，文獻顯示 agent 預設傾向自行假設。Ambig-SWE 發現模型「consistently struggled to detect underspecification without explicit prompting」，一旦能與模擬使用者互動，效能最多提升 74%；而且 Claude Sonnet 3.5 在「中度鼓勵」下最能分辨需求是否完整，Sonnet 4 則在「強烈鼓勵」下表現最好 ([Vijayvargiya et al.](https://arxiv.org/html/2502.13069v3))。Findings of EMNLP 2026 的 UA-Multi 架構在資訊不足的 SWE-bench Verified 變體上拿到 69.40%，幾乎追平完整資訊的 70.80% ([Edwards et al.](https://arxiv.org/abs/2603.26233))。沒有任何研究把程式內註解和詢問行為連結起來。D 版 4/4 的一個合理機制，是命令式的「天條」措辭把隱性的設計衝突變成可偵測的缺口，進而觸發詢問；但既然最佳鼓勵程度在 Sonnet 版本之間就會改變，這種效果很可能無法跨版本延續。

截至本次調查，沒有找到任何複製貼文設計的研究，也就是依註解類別（標頭不變條件、why-not、重述）逐一刪減，再在多檔案模組上量測 agent 的讀、改、審。一篇實務綜述直言「nobody has actually proven it for the specific case of an AI agent exploring and editing a real codebase」 ([Terminal Wars](https://terminalwars.com/posts/should-you-comment-code-for-ai/))。下表把貼文各項發現對到最接近的證據。

| 貼文發現 | 最接近的證據 | 判讀 |
| :--- | :--- | :--- |
| N 版 what 理解 97% | 缺漏文件無顯著影響 ([Macke & Doyle](https://arxiv.org/abs/2404.03114))；結構擾動僅 1.63 pp ([CodeCrash](https://arxiv.org/html/2504.14119v3)) | 支持，但前提是名稱保留 ([When Names Disappear](https://arxiv.org/pdf/2510.03178)) |
| N 版 why 掉到 60% | 從 commit 還原的決策遺漏理由 ([2609.03721](https://arxiv.org/abs/2609.03721))；脈絡檔只在非標準慣例上有用 ([2602.11988](https://arxiv.org/abs/2602.11988)) | 間接支持 |
| N 版陷阱 3/14 | 註解讓 bug 修復最多提高三倍 ([2601.23059](https://arxiv.org/abs/2601.23059))；刪註解傷害較弱模型的偵測 ([Thornton](https://arxiv.org/html/2602.16741v1)) | 方向支持，但沒有針對不變條件的研究 |
| logic bug 各版 11–12/12 | 前沿模型的偵測不受註解操弄影響 ([Thornton](https://arxiv.org/html/2602.16741v1)) | 一致 |
| D 版 why 98%、詢問 4/4、陷阱 6/14 | 說明動機有助 Claude ([Anthropic](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices))；詢問需要明確誘發 ([Ambig-SWE](https://arxiv.org/html/2502.13069v3)) | 合理，但未經驗證 |
| 隱含主張：註解越少，腐化風險越低 | 錯誤註解傷害遠大於缺漏 ([Macke & Doyle](https://arxiv.org/abs/2404.03114)、[When Comments Mislead](https://doi.org/10.1145/3832783.3834359))；「忽略註解」指示無效 ([ALIBI](https://arxiv.org/abs/2607.24964)) | 支持刪減，但留下的天條若過時，影響最大 |

## 14 個陷阱、4 個任務：沒有任何差異撐過多重比較

貼文的表每格只有一個數字：百分比列沒有分母，沒說跑了幾次，也沒有誤差範圍。研究團隊以精確檢定重算（純 Python 實作，並與 scipy、statsmodels 交叉核對到小數點後四位），結果相當刺眼。陷阱 bug 的 Wilson 95% 信賴區間，O 與 A 的 10/14 是 [45.4%, 88.3%]，B 與 D 的 6/14 是 [21.4%, 67.4%]，**兩者大幅重疊**；D 的「詢問 4/4」與低至 51% 的真實詢問率相容，O 的 0/4 則與高達 49% 相容。小樣本該用 Wilson 而非教科書的 Wald 區間，Brown、Cai 與 DasGupta 早有定論 ([Statistical Science 2001](https://projecteuclid.org/euclid.ss/1009213286))；Miller 的評估統計論文也主張每個 eval 都該報告誤差範圍 ([Miller 2024](https://arxiv.org/abs/2411.00640)；[Anthropic](https://www.anthropic.com/research/statistical-approach-to-model-evals))。

把每個變體當作獨立樣本做 Fisher 精確檢定，只有兩項在名目上 p < 0.05：陷阱 N 對 O 的 **p = 0.021**，以及詢問 D 對 O 的 **p = 0.029**。但 5 個變體乘 4 個計數指標就是 20 次檢定，Bonferroni 門檻是 0.0025。Holm 校正後兩者分別變成 0.426 與 0.543；就算改用檢定力較高的 Boschloo 非條件檢定（0.0093 與 0.0078），Holm 校正後也只剩約 0.18 與 0.16，Benjamini-Hochberg 校正後則都是 0.286。作者沒有預先登記要比較哪些對照，誠實的檢定家族應是「所有可能被拿出來強調的對照」，校正只會更嚴，不會更鬆。

更根本的問題是，這個設計幾乎可以確定是配對的：同樣 14 個陷阱、同樣 4 個修改任務放進每個版本。這時正確的檢定是只看不一致配對的精確 McNemar，最小可達 p 值為 2 × 0.5^n，**n = 4 時是 0.125**。也就是說，詢問指標在配對分析下，結果再懸殊都不可能顯著；Fisher 的 0.029 只有在 D 與 O 用了不同、獨立抽樣的任務時才成立。Miller 也建議，同一題組下的條件比較應採配對差異，以抵銷題目難度的變異 ([Miller 2024](https://arxiv.org/abs/2411.00640))。下表列出關鍵對照；配對 p 值依貼文未公布的重疊程度，只能給出範圍。

| 對照 | 點估計差 | Fisher 雙尾 p | 配對 McNemar p 範圍 | Newcombe 95% CI |
| :--- | ---: | ---: | :--- | :--- |
| 陷阱 O − N（10 對 3，n = 14） | +50.0 pp | 0.021 | 0.0156–0.0923 | [+13.1, +71.8] |
| 陷阱 O − D（10 對 6，n = 14） | +28.6 pp | 0.252 | 0.125–0.388 | [−7.2, +55.9] |
| 陷阱 O − A（10 對 10，n = 14） | 0.0 pp | 1.000 | — | [−31.0, +31.0] |
| 設計衝突 O − N（6 對 3，n = 6） | +50.0 pp | 0.182 | 0.25 | [0.0, +81.2] |
| 詢問 D − O（4 對 0，n = 4） | +100 pp | 0.029 | 0.125 | [+30.7, +100] |

這張表也提醒另一面：「A 與 O 一樣好」同樣只是弱支持，差值的 95% 區間寬達正負 31 個百分點，沒有差異不等於等價。檢定力更說明問題所在。以觀察到的 71.4% 對 42.9%，14 個陷阱的檢定力只有 **0.20**，要達到 80% 檢定力，每組需要約 51 個陷阱。若六個版本的真實偵測率完全相同，在 20,000 次模擬中，「至少一個變體與 O 相差 4 個陷阱以上」的機率高達 **0.436 到 0.538**。拿來把 D 排在 O、A 之後的 10 比 6，在「沒有效果」的假設下等同擲硬幣。單次執行本身的抽樣也很寬：真實率 71.4% 時，14 題的 95% 中央範圍是 7 到 13 題；真實率 50% 時是 3 到 11 題，O 的 10 與 D 的 6 都落在其中。這還沒算上 agent 的非決定性：τ-bench 中 gpt-4o 在 τ-retail 的 pass^1 約為 61%，要求連續 8 次都成功的 pass^8 則掉到約 25% ([Yao et al., ICLR 2025](https://arxiv.org/abs/2406.12045))。何況每條規則的「D 版」本身也只是 Opus 的一次抽樣。

百分比列與 logic bug 列另有問題。若 what 與 why 列各來自一組二元計分的題目，能湊出所有報告整數百分比的最小分母，what 列是 36 題、why 列是 47 或 48 題，而 89 以內沒有任何單一 n 能同時符合兩列。所以要嘛題目真的很多但集中在 3 個模組（Miller 發現題目成群時，群集標準誤可比天真估計大 3 倍以上），要嘛是評分量表的平均分數（代表迴圈中有 judge 模型），要嘛合併了多次執行。在合理的分母範圍內，只有 **why 的 N 對 O（60% 對 94%）** 是穩健的：n = 50 時 p = 8.1×10⁻⁵，約在 n ≈ 50 時通過 30 次檢定的 Bonferroni 門檻。D「最好」的 98% 對上 O 的 94%，即使有 200 題，p 值也只有 0.071。logic bug 列五格 12/12 則撞到天花板，Wilson 下界 75.8% 代表最多 24 個百分點的傷害都看不見；它是有用的負對照，不是「沒有傷害」的證據。

κ 這一列反而是實驗少見的優點：它檢查同一條規則交給兩次獨立改寫，是否做出相同的保留與刪除決定，而非正式比較很少量測規則的可重現性。依 Landis 與 Koch 的分級，A 的 0.77 屬「substantial」，C 的 0.82 與 D 的 0.81 屬「almost perfect」，B 的 0.54 只是「moderate」；若採 McHugh 為醫學研究提出的較嚴標準，B 只算「weak」，而 Landis 與 Koch 的分級本身並無實證依據 ([McHugh 2012](https://pmc.ncbi.nlm.nih.gov/articles/PMC3900052/)；[Wikipedia: Cohen's kappa](https://en.wikipedia.org/wiki/Cohen%27s_kappa))。若機率一致率為 0.5，κ 0.54 代表原始一致率約 77%，**兩位改寫者每四個決定就有一個不同**，表示規則留下太多判斷空間。解讀時有三個限制。第一，貼文沒公布評分單位數，30 個單位時 B 的 95% 區間約為 [0.24, 0.84]，與 C、D 重疊。第二，κ 受刪除比例影響：原始一致率固定在 90% 時，刪 50% 得 κ 0.80，刪 85% 只剩 0.61，所以刪掉 87% 字元的 C 仍有 0.82，反而低估了 C 的一致性。第三，「兩位改寫者」多半是兩次 Opus 執行，量到的是模型加規則的再測信度，不是人類開發者之間的一致性。

## 陷阱 bug 量的是資訊保留率，「D 最好」是價值取捨而非發現

陷阱 bug 是整個實驗最貼近規則目的的指標，也是最循環的指標。陷阱最可能的形式，是局部看似合理、卻違反某條寫在註解裡的不變條件或刻意怪癖的修改。那麼 N 版的 3/14 就是「只靠程式碼、名稱與測試能推得」的基線，O 的 10/14 則代表連完整註解都漏了 4 個；任何改寫版本的偵測上限，就是它保留了多少與陷阱相關的事實。A 與 O 同為 10/14，暗示 A 全數保留；D 的 6/14 暗示 D 刪掉了約 4 條。這其實是一場**資訊保留稽核**，只要把每個陷阱對應到記載它的註解行，不必跑任何讀者模型就能確定性地算出來，讀者模型只是在可計數的量上再疊一層抽樣雜訊。若陷阱是看著 O 的註解挑出來的，O 就被設計成必勝、刪文字的規則被設計成必輸。這不算錯，因為那正是精簡的風險，但結論應表述為「多少已記載的約束在精簡後存活」，而不是「agent 的審查能力多好」。實驗也缺少關鍵對照：約束只寫在測試或名稱裡的陷阱，以及哪裡都沒寫的陷阱。Agentic Benchmark Checklist 把這類問題歸為任務效度與結果效度，十個熱門 agent 基準中各有七個違反 ([Zhu et al.](https://arxiv.org/abs/2507.02825))；NeurIPS 2025 一篇回顧 445 個 LLM 基準的研究也發現，現象定義、選題與計分的缺陷普遍削弱了基準的主張 ([Bean et al.](https://arxiv.org/abs/2511.04703))。

第二個混淆，是同一家族的模型包辦了太多角色。改寫者 Opus 與讀者 Sonnet 同屬 Anthropic，以 Claude 風格寫成的註解可能特別適合 Claude 讀，因而高估改寫版相對於人寫 O 版的價值。若陷阱、理解題或評分也出自 Opus 或同一個工作階段，自我偏好就成了風險：GPT-4 不經訓練就能以 **73.5%** 的準確率認出自己的輸出，微調後自我辨識能力與自我偏好強度呈線性相關 ([Panickssery et al., NeurIPS 2024](https://arxiv.org/abs/2404.13076))。LLM 評審也有位置、冗長與自我增強偏誤 ([Zheng et al., NeurIPS 2023](https://arxiv.org/abs/2306.05685))，CodeJudgeBench 更發現所有評審模型都對誤導性註解與變數命名敏感 ([CodeJudgeBench, ACL 2026](https://aclanthology.org/2026.acl-long.888/))。貼文沒有說明誰設計陷阱、誰出題、誰評分，所以這些是合理的風險，而非已證實的缺陷。

「停下來詢問」量的是行為策略，不是理解，而且什麼才算好結果並未定義。O 察覺了 6/6 的設計衝突卻 0/4 停手，D 同樣察覺 6/6 卻 4/4 停手：資訊在兩個版本裡都在，改變的是框架。把標頭稱為不可冒犯的「天條」是命令式語言，很可能透過指令遵循直接推動模型停手。Sclar 等人發現光是改變提示格式，就能造成**最高 76 個百分點**的準確率差距，而且這種效應在模型之間的相關性很弱 ([Sclar et al., ICLR 2024](https://arxiv.org/abs/2310.11324))。由於沒有「應該直接執行」的對照任務，4/4 無法與「D 讓 agent 什麼都問」區分。正確的量法是事先把任務標成應詢問或應執行，再報告詢問的精確率與召回率，並另外操弄標頭措辭（命令式對描述式），把框架效應與資訊內容拆開。

綜合來看，「D 最好」並不成立。貼文沒說明公布的規則對應哪個版本。若是最嚴格的 C（只留 13% 字元），它在 what（83%）、why（81%）、陷阱（5/14）、設計衝突（4/6）與詢問（0/4）上都是保留註解版本中最差的，結論與自身數據矛盾。若是 D，它在 why（98%，與 O 的 94% 無法區分）與詢問（4/4）上最好，陷阱卻只有 6/14，對上 O 與 A 的 10/14。下表把取捨攤開：

| 版本 | 字元相對 O | 陷阱相對 O | why 相對 O | 詢問 | κ | 直白解讀 |
| :--- | ---: | ---: | ---: | :---: | :---: | :--- |
| A | −34% | 0 | +2 pp | 1/4 | 0.77 | 各指標都看不出損失，文字少三分之一 |
| D | −64% | −4 個 | +4 pp | 4/4 | 0.81 | why 最好、最謹慎，但少抓 O 四成的陷阱 |
| B | −75% | −4 個 | +2 pp | 2/4 | 0.54 | 少抓陷阱，what 掉到 86%，規則最難重現 |
| C | −87% | −5 個 | −13 pp | 0/4 | 0.82 | 可重現，但各項理解指標損失最多 |
| N | −100% | −7 個 | −34 pp | 0/4 | — | 表中唯一明確的傷害 |

陷阱正是規則自稱要防的事：agent 弄壞不變條件。一條讓審查少抓 10 個中的 4 個、換來 4 個修改任務都停下來詢問的規則，是一種價值判斷，不是實驗發現。D 的 why 98% 與陷阱 43% 之所以分歧，一個解釋是 D 為保留下來的程式碼留了理由，卻整段刪掉某些約束陳述；理解題問的是保留的理由，陷阱打的是被刪的約束。這也呼應前述「描述實作的就地註解最有助於 bug 修復」的研究：知道全域的 why，不等於在違反點看得到護欄。數據能誠實支持的只有五件事：全刪註解明確傷害 why 理解（前提是 n 約 48 以上），也可能傷害陷阱偵測；名稱與程式碼足以支撐 what；約三分之一的現有註解（A 刪掉的部分）在此樣本中可刪而無可偵測的損失；更嚴格的規則可能降低陷阱偵測，但樣本太小無從判斷；命令式的天條措辭可能改變 agent 的停手行為，值得單獨測試。

實驗也有值得肯定之處，而且比多數非正式比較嚴謹。它用 O（現狀）與 N（全刪）兩端夾住變體，讓中間版本可以解讀；把 what 與 why、陷阱與 logic bug、理解與行動分開量；logic bug 是一個理應不受註解影響、結果也確實不受影響的負對照；埋入的 bug 提供客觀答案，而非主觀品質評分；它同時報告成本軸（保留字元）與可重現軸（κ）；最難得的是完整公布了不利於自家結論的數字，例如 D 的 6/14。在文獻中找不到同類研究的情況下，它是唯一依註解**類別**、在模組尺度上以 agent 任務量測的證據，作為假說產生器相當可信。要升級成證據，研究團隊建議預先登記主要指標與對照；由不同於改寫者的人或模型設計陷阱，並依約束記載位置（只在註解、只在測試、只在名稱與型別、哪裡都沒有）分層；先做確定性的資訊保留稽核；在 3 個以上儲存庫、20 到 30 個模組、兩種語言上放約 51 個陷阱，或採配對設計並以混合效應邏輯斯迴歸分析；每格至少 5 次讀者執行、每條規則至少 3 次獨立改寫；加入非 Anthropic 與較小的讀者模型；盲評；加入應執行的對照任務；最後重播真實 commit 歷史，量測哪些註解會過時，以及過時的天條是否比沒有註解更容易讓陷阱漏網。

## 傳統軟工同意刪冗餘，分歧集中在函式層級的介面語意

這條規則在精神上最接近 Robert C. Martin 的《Clean Code》。Martin 寫道「Comments are always failures」，也說「the only truly good comment is the comment you found a way not to write」 ([aposd-vs-clean-code](https://github.com/johnousterhout/aposd-vs-clean-code))；書中第 4 章的「壞註解」清單，包括重述、雜訊、日誌、署名、註解掉的程式碼、位置標記與函式標頭，幾乎就是規則要刪的東西。但規則比《Clean Code》更嚴。該章的八種「好註解」是 Legal、Informative、Explanation of Intent、Clarification、Warning of Consequences、TODO、Amplification 與 Javadocs in Public APIs ([Clean-Code-Notes](https://github.com/JuanCrg90/Clean-Code-Notes))，其中只有意圖說明、後果警告與強調能乾淨地對應到 why-not；授權標頭、TODO 與公開 API 文件在規則裡都沒有位置，嚴格套用甚至會刪掉 SPDX 授權標頭。Martin 說「the best comments tell me something surprising and verifiable about the code」，規則要求 why-not「點名所保護的程式碼」，正好把「可驗證」落實成可操作的要求。還有一個歷史對照值得注意：Martin 2008 年的論證是「組合語言與 FORTRAN 時代需要註解，現代語言與版本控制降低了需求」，和今天「agent 不知疲倦地讀程式碼，所以註解需求降低」是同一個形狀。

John Ousterhout 與 Martin 在 2024 年 9 月到 2025 年 2 月間的公開辯論，幾乎預演了這則貼文的爭議。Ousterhout 說「I would probably write 5-10x more lines of comments for a given piece of code than you would」，認為「it is not possible to define interfaces and create abstractions without a lot of comments」；簽章就包含使用所需全部資訊的情況「pretty rare」，而「unit tests are a poor form of documentation」 ([aposd-vs-clean-code](https://github.com/johnousterhout/aposd-vs-clean-code))。兩人唯一明確的共識是「implementation code only needs comments when the code is nonobvious」，這與規則對行內註解的節制一致。規則的兩半因此落在辯論的兩側：刪掉只重述簽章的 docstring，兩人都同意；不准寫函式層級的介面註解、只留模組與類別標頭，則站在 Martin「團隊內部看簽章就夠」那邊。Ousterhout 的反駁是，照 Martin 的做法，開發者會花大量時間「re-derive the interfaces, and probably making mistakes along the way」。這個反駁對 agent 更有力：agent 沒有跨工作階段的記憶，每次都是第一次讀這份程式碼的人。讀得便宜，降低的是重新推導的時間成本，不是推導出錯的風險，而 D 版少抓的陷阱，正是這種錯誤風險的具體樣貌。

主流風格指南在禁止「敘述程式碼」上與規則一致，在函式層級文件上則一致反對它。PEP 257 規定單行 docstring「should NOT be a 'signature' reiterating the function/method parameters」，幾乎就是規則原文；但它同時要求模組匯出的函式與類別都要有 docstring，並記載參數、回傳值、副作用、例外與呼叫限制 ([PEP 257](https://peps.python.org/pep-0257/))。Google Python Style Guide 規定公開 API、篇幅不小或邏輯不明顯的函式必須有 docstring，標準是「enough information to write a call to the function without reading the function's code」，同時要求「never describe the code」；它的「If you're going to have to explain it at the next code review, you should comment it now」也是 why-not 觸發條件很好用的操作定義 ([Google pyguide](https://google.github.io/styleguide/pyguide.html))。Linux kernel 的「NEVER try to explain HOW your code works in a comment」與「try to avoid putting comments inside a function body」最接近規則的精神，但它把註解放在每個函式開頭，說明做什麼「and possibly WHY」 ([kernel coding style](https://github.com/torvalds/linux/blob/master/Documentation/process/coding-style.rst))。Go 要求每個匯出名稱都有 doc comment，由 `go doc`、pkgsite 與 gopls 讀取 ([Go Doc Comments](https://go.dev/doc/comment))。PEP 8 那句「Comments that contradict the code are worse than no comments」 ([PEP 8](https://peps.python.org/pep-0008/)) 則與 LLM 文獻的腐化發現完全吻合。

ADR 可以承接去重，但無法取代就地的 why-not。Nygard 2011 年提出的格式包含 Context、Decision、Status 與 Consequences ([Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions))，Fowler 補充，決策改變時 ADR 不修改，而是由新決策取代 ([Fowler](https://www.martinfowler.com/bliki/ArchitectureDecisionRecord.html))；這讓 ADR 成為歷史紀錄，而非現行規格。站在程式碼現場的讀者，無論是人或 agent，除非想到去開 ADR 或跑 `git blame`，否則看不到它。Fluri 等人對 8 個系統的研究發現「API changes and comments do not co-evolve but get re-documented in a later revision」 ([Fluri et al. 2009](https://doi.org/10.1007/s11219-009-9075-x))，離改動點越遠的文件越容易落後。合理的分工是：ADR 承載架構層級的 why 與被否決的替代方案，reference 文件承載現行契約，commit 與 PR 承載單次改動的 why，程式內註解只留「改動當下必須看到才不會弄壞」的東西；why-not 也可以只指向 ADR 而不重述，用引用換取就地性。Chesterton's fence 是 why-not 最好的理由：在弄懂現狀的理由之前，不要改它 ([thoughtbot](https://thoughtbot.com/blog/chestertons-fence))。沒有告示牌的柵欄，最容易被一位不知疲倦、卻分不清刻意與意外的讀者拆掉。

最接近這條規則的既有慣例是 Rust 的 `// SAFETY:` 註解。clippy 的 `undocumented_unsafe_blocks` 要求每個 `unsafe` 區塊前一行要有說明為何安全的 `// SAFETY:` 註解，`unnecessary_safety_comment` 則在安全程式碼上出現 SAFETY 註解時報錯 ([clippy source](https://github.com/rust-lang/rust-clippy/blob/master/clippy_lints/src/undocumented_unsafe_blocks.rs))：一邊強制鄰接，一邊在被保護的結構消失時強制刪除，幾乎就是「why-not 必須點名所保護的程式碼，並隨之刪除」。但有三個差異很重要。其一，Rust 有編譯器看得見的錨點 `unsafe`，「看起來怪的程式碼」沒有，規則的「點名」條款只是人工替代品，沒有標記慣例就無法 lint。其二，Linux kernel 的 Rust 指南把 `# Safety`（給呼叫者的契約）與 `// SAFETY:`（就地理由）分開，契約放在**函式**層級，並提醒即使理由看似瑣碎，寫下來也能證明「there are no *extra* implicit constraints」 ([kernel Rust guidelines](https://github.com/torvalds/linux/blob/master/Documentation/rust/coding-guidelines.rst))。這是反對極簡主義的論點，因為 agent 無法從沉默推出「沒有其他約束」。其三，這兩個 lint 屬於 restriction 類別，預設不啟用，而且只檢查註解存在，不檢查內容為真。Design by Contract 的傳統偏好可執行的不變條件，Python 的 icontract 就提供 `invariant` 類別裝飾器 ([icontract](https://pypi.org/project/icontract/))。把散文不變條件稱為「天條」，提高了它的權威，卻沒有提高它的可驗證性。

人類讀者的實證研究也兩面都有。Woodfield 等人 1981 年讓 48 位有經驗的程式設計師讀 8 個版本的程式，有註解的版本理解分數較高 ([ICSE 1981](https://bibtex.github.io/ICSE-1981-WoodfieldDS.html))；Potdar 與 Shihab 發現自承技術債註解出現在 2.4% 到 31% 的檔案中，引入後只有 26.3% 到 63.5% 被移除 ([ICSME 2014](https://bibtex.github.io/ICSME-2014-PotdarS.html))，說明 TODO 是真實且長命的訊號，規則對它沉默就會丟失資訊。這些舊研究沒有區分 what 與 why，也沒測試現代命名與型別，所以既不能證實、也不能推翻「名稱與型別可取代 what 註解」。

| 面向 | 貼文規則 | Clean Code | Ousterhout | PEP 257／Google | Rust SAFETY |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 重述名稱或簽章的註解 | 刪 | 刪 | 刪，或縮短名稱 | 禁止重述簽章 | 不適用 |
| 函式層級介面語意 | 不允許 | 僅公開 API | 必要 | 公開 API 必要 | `# Safety` 在函式層級 |
| why 與意圖 | 僅限 why-not | 允許 | 必要 | 允許，難懂處必要 | `// SAFETY:` 必要 |
| 授權標頭、TODO | 未提及 | 允許 | — | Google 要求授權標頭，TODO 偏好附 bug 編號 | — |
| 可驗證性 | 點名受保護程式碼 | 「surprising and verifiable」 | — | — | clippy 強制鄰接與刪除 |

## shiro-mlops 的 `#` 註解已夠精簡，該動的是 docstring 與天條的執行

先釐清現況。repo 裡沒有任何文件寫著「名稱優先、只留標頭與 why-not」。[`CODING_STANDARDS.md`](../../CODING_STANDARDS.md) 只有「文件」「設定與基礎設施」「技術債」三節，與註解相關的只有第 14 行的「無法共用時，在重複處註明須同步的來源檔」，以及第 15 行的「非直觀設定附 Why 註解」，後者只涵蓋基礎設施設定。另有三處規定要求寫註解：[`docs/agents/tech-debt.md:25`](../../docs/agents/tech-debt.md) 的 `TODO(#123)` 格式、[`docs/reference/lab.md:83`](../../docs/reference/lab.md) 的「採用時在任務設定 TOML 參數旁註解連回報告」，以及只寫在 [`docs/adr/0010-persist-models-in-native-non-executable-formats.md:44`](../../docs/adr/0010-persist-models-in-native-non-executable-formats.md) 的 `np.load` 審查清單。貼文的實驗也沒有記錄在 repo 的任何地方；以 11,753 字元回推，`src/` 中有四組不同的三模組組合都落在正負 15 字元內，無法辨識是哪三個模組，甚至可能根本不是這個 repo。量測結果顯示，`#` 註解層已經接近規則的目標，冗餘主要在 docstring：

| 目錄 | 檔案數 | 行數 | `#` 註解字元 | docstring 字元 | 有模組 docstring |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `src/` | 75 | 12,072 | 7,808 | 64,077 | 75/75 |
| `tests/` | 84 | 16,416 | 4,856 | 32,702 | 84/84 |
| `lab/` | 12 | 2,722 | 3,673 | 8,215 | 10/12 |
| `scripts/` | 4 | 874 | 1,695 | 1,889 | 4/4 |

`src/` 的 docstring 約是 `#` 註解的 **8 倍**。151 行 `#` 註解中有 105 行是中文，多半已是 why-not 或同步來源：[`src/shiro_mlops/data/cwa_client.py:16-17`](../../src/shiro_mlops/data/cwa_client.py) 說明為何以 defusedxml 防範 billion laughs，[`src/shiro_mlops/pipelines/smoke_check.py:29`](../../src/shiro_mlops/pipelines/smoke_check.py) 解釋唯一一處依賴 `dagster._core` 私有路徑的原因，[`src/shiro_mlops/pipelines/assets.py:76-78`](../../src/shiro_mlops/pipelines/assets.py) 用算式證明重試仍早於下一個 10 分鐘 slot。575 個 docstring 中則只有 9 個含中文。所以這條規則若把 docstring 算進「註解」，落地時幾乎就是一場 docstring 刪減，規則文字必須先把這一點講清楚。

### 工具會讀的 docstring 是介面文字，不能當註解刪

至少三種工具在執行期讀取 docstring，直接刪除會改變對外輸出。以下行為都對照了 [`uv.lock`](../../uv.lock) 鎖定版本的套件原始碼確認。

| 工具（鎖定版本） | 讀取機制 | 本 repo 受影響位置 | 刪除後果 |
| :--- | :--- | :--- | :--- |
| FastAPI 0.141.1 | `route.description = description or inspect.cleandoc(route.endpoint.__doc__ or "")`（`fastapi/routing.py:1034`） | 沒有任何路由傳 `description=` 或 `summary=`；[`service/api.py`](../../src/shiro_mlops/service/api.py) 第 235、254、260、266、284 行，以及 [`data_explorer/router.py`](../../src/shiro_mlops/service/data_explorer/router.py) 第 69 至 129 行的九個處理函式 | `/docs` 與 OpenAPI 的 operation description 消失 |
| Pydantic 2.13.4 | 類別 `__doc__` 經 `inspect.cleandoc` 成為 JSON schema 的 `description`（`json_schema.py:1662-1665`；列舉在第 891 行） | [`data_explorer/schemas.py`](../../src/shiro_mlops/service/data_explorer/schemas.py) 第 17、44、51 行的類別；[`service/api.py:200`](../../src/shiro_mlops/service/api.py)；`create_model(..., __doc__=item.__doc__)` 刻意傳遞（[`service/api.py:178-181`](../../src/shiro_mlops/service/api.py) 與第 216 行），使 [`recursive_regression.py:69`](../../src/shiro_mlops/tasks/types/recursive_regression.py)、[`direct_classification.py:95`](../../src/shiro_mlops/tasks/types/direct_classification.py)、[`unsupervised_reconstruction.py:101`](../../src/shiro_mlops/tasks/types/unsupervised_reconstruction.py) 的預測項目 docstring 成為 API 文字 | OpenAPI schema 說明消失 |
| argparse | `ArgumentParser(description=__doc__.splitlines()[0])` | [`pipelines/smoke_check.py:241`](../../src/shiro_mlops/pipelines/smoke_check.py)、[`scripts/rederive_hourly_actual_load.py:76`](../../scripts/rederive_hourly_actual_load.py) | `__doc__` 變成 `None`，啟動即 `AttributeError` |
| argparse | `ArgumentParser(description=__doc__)` | [`scripts/smoke_nginx.py:249`](../../scripts/smoke_nginx.py)、[`lab/2026-11-17-dhf-weather-calendar/study.py:300`](../../lab/2026-11-17-dhf-weather-calendar/study.py) | `--help` 說明變空白 |
| Dagster 1.13.19 | 只在未傳 `description=` 時以 docstring 作為 op 或 asset 說明（`op_decorator.py:128`）；`@schedule` 完全不讀 docstring | 所有 `@asset` 都明示 `description=`（例如 [`pipelines/assets.py`](../../src/shiro_mlops/pipelines/assets.py) 第 89 行起）；[`pipelines/schedules.py`](../../src/shiro_mlops/pipelines/schedules.py) 第 131、158 行的 docstring 不會出現在 UI | 目前安全；未來漏寫 `description=` 的 asset 會悄悄改用 docstring |

Feast 以明示的 `description=` 參數設定說明（[`features/definitions.py:14`](../../src/shiro_mlops/features/definitions.py)），不讀 docstring；repo 也沒有設定 Sphinx、mkdocs 或 pdoc，ruff 只選 `E`、`F`、`I`、`N`、`W`、`UP`（[`pyproject.toml:54`](../../pyproject.toml)），沒有任何 `D` 規則要求或保護 docstring。最危險的是測試完全不會發現：[`tests/integration/test_api.py:650-654`](../../tests/integration/test_api.py) 只斷言 `Field(description=…)` 的內容，沒有任何測試斷言路由或模型的 docstring，一次「依規則清理」的 PR 可以在 CI 全綠的情況下改掉公開 API 文件，還弄壞兩支 CLI。建議在規則中明訂「被工具讀取的 docstring 屬於介面文字，不是註解」。更乾淨的做法是把這些文字搬到明示的 `summary=`、`description=` 與 `Field(description=…)`，沿用 [`service/api.py:142-152`](../../src/shiro_mlops/service/api.py) 請求模型已有的寫法，讓契約顯性且可測，再加一個針對 `app.openapi()` 關鍵說明的快照測試；argparse 的兩處 `__doc__.splitlines()[0]` 則改成明示字串，或至少改成 `__doc__` 為 `None` 時不會崩潰的寫法。

### 先做 A 級清理，別一步跳到 D 級的嚴格度

實驗數據支持的是「刪掉約三分之一，看不出損失」。對應到這個 repo，有一批幾乎沒有爭議的刪除對象：[`src/shiro_mlops/core/config.py`](../../src/shiro_mlops/core/config.py) 第 25、28、60、63、70、88 行的 `# Environment`、`# MLflow` 等分節標籤，就在不言自明的設定上方；[`src/shiro_mlops/features/definitions.py`](../../src/shiro_mlops/features/definitions.py) 第 10、19、44 行的編號標題；[`src/shiro_mlops/features/transformers.py:51`](../../src/shiro_mlops/features/transformers.py) 的 `# Cyclical hour encoding` 正好位於 `hour_sin` 計算上方，第 133、144 行亦然；[`src/shiro_mlops/data/cwa_client.py:566`](../../src/shiro_mlops/data/cwa_client.py) 與 [`src/shiro_mlops/core/database.py:202`](../../src/shiro_mlops/core/database.py) 只是重述下一行；[`src/shiro_mlops/tasks/runner.py`](../../src/shiro_mlops/tasks/runner.py) 第 131、226、252、525 行等共 11 處 `# --- Training ---` 式分隔線；[`src/shiro_mlops/data/repository.py:332-343`](../../src/shiro_mlops/data/repository.py) 這類重述簽章的 NumPy 式 `Parameters` 區塊（repository.py 有 4 個、database.py 有 5 個）；以及 [`repository.py`](../../src/shiro_mlops/data/repository.py) 第 56、93、324 行這種改寫函式或類別名稱的單行 docstring。這些多半在淺層 clone 的邊界（2026-09-28）之前就已存在，較新的 why 與同步註解則多在 11 月加入。啟發式統計顯示，297 個單行函式 docstring 中有 77 個以函式名的動詞開頭（5,086 字元），但這會高估冗餘，例如 [`core/io_managers.py:64`](../../src/shiro_mlops/core/io_managers.py) 的「reject legacy pickle files」就帶著不變條件，所以刪除應逐條審查，不宜批次處理。

刪除時要守住 Ousterhout 與 Google 的底線：型別與名稱承載不了的介面語意要留下。[`src/shiro_mlops/tasks/runner.py:1-8`](../../src/shiro_mlops/tasks/runner.py) 的模組 docstring 寫明 runner 掌管 I/O、任務類型只接收記憶體內資料、所有時間相依的決策都要明示台灣本地 naive 時間的 `as_of`。這些正是 agent 每次都得重新推導、也最容易推錯的東西，即使有 7 行、超過規則的 1 到 3 行，也不該砍。相對地，幾段長篇模組 docstring 是在敘述執行期行為，而且與 `docs/reference/` 重複：[`pipelines/issued_forecast.py:1`](../../src/shiro_mlops/pipelines/issued_forecast.py) 的「never floored to the hour」與「Only scheduled ticks issue」，幾乎就是 [`docs/reference/dagster-schedules.md`](../../docs/reference/dagster-schedules.md) 第 57、60 行；[`tasks/types/base.py:1`](../../src/shiro_mlops/tasks/types/base.py) 的「Task types never touch repositories」重述了 [`docs/reference/ml-tasks.md:48`](../../docs/reference/ml-tasks.md)；[`tasks/model_store.py:1`](../../src/shiro_mlops/tasks/model_store.py) 的「A legacy `model.joblib` is never loaded」重述了 ADR-0010 第 21 行。[`AGENTS.md:11`](../../AGENTS.md) 要求 reference 文件與程式碼在同一個 PR 修改，docstring 裡的副本卻沒有這道守門，這正是文獻警告的「過時天條」溫床。建議沿用 [`data/hourly_actual_load.py:1`](../../src/shiro_mlops/data/hourly_actual_load.py) 的寫法，只用兩行指向「ADR-0008 and docs/reference/data-contracts.md §1」，讓跨模組契約以連結取代重述，模組標頭只寫在本模組內成立的不變條件。[`pipelines/forecast_view_export.py:1`](../../src/shiro_mlops/pipelines/forecast_view_export.py)（953 字元、15 行）與 [`tasks/types/unsupervised_reconstruction.py:1`](../../src/shiro_mlops/tasks/types/unsupervised_reconstruction.py)（826 字元）是首選對象；[`pipelines/smoke_check.py:1-15`](../../src/shiro_mlops/pipelines/smoke_check.py) 雖然也長，但第一行餵給 argparse，還含使用說明，縮減時必須一併處理。

### 把天條變成會失敗的測試

既然模型會照單全收註解，叫它忽略也沒用，每條被奉為天條的不變條件都應盡量配一個違反時會失敗的檢查，並在標頭中點名那個檢查。這個 repo 已經有很好的範本：[`lab/tests/test_snapshot.py:357-358`](../../lab/tests/test_snapshot.py) 的 `test_src_never_imports_lab` 把 ADR-0011 的依賴方向變成測試；[`src/shiro_mlops/tasks/definition.py:98-127`](../../src/shiro_mlops/tasks/definition.py) 以 Pydantic validator 強制權重總和為 1；[`tests/unit/test_smoke_check.py:74`](../../tests/unit/test_smoke_check.py) 替 [`smoke_check.py:88-91`](../../src/shiro_mlops/pipelines/smoke_check.py) 那段「刻意重述排程名稱與 cron」的 why-not 撐腰；[`tests/integration/test_resiliency.py:364`](../../tests/integration/test_resiliency.py) 的 `test_serving_path_never_constructs_a_cwa_client` 則直接用測試名稱陳述不變條件。仍停在散文的有三條。第一，[`tasks/types/base.py:1`](../../src/shiro_mlops/tasks/types/base.py) 的「Task types never touch repositories」沒有任何測試或 lint 把關，ruff 也沒啟用 `flake8-tidy-imports` 或 banned-api；建議仿照 `test_src_never_imports_lab` 寫一個 AST 測試，禁止 `tasks/types/` 匯入 `shiro_mlops.data` 與 `sqlalchemy`。第二，ADR-0010 第 44 行要求 `np.load` 一律明示 `allow_pickle=False`，目前只是審查清單；`src/` 只有一個呼叫點（[`unsupervised_reconstruction.py:359`](../../src/shiro_mlops/tasks/types/unsupervised_reconstruction.py)），很適合做成 `check_conventions.py` 的檢查或一個測試。第三，[`tasks/types/base.py:59`](../../src/shiro_mlops/tasks/types/base.py) 的「各任務類型不得自行切分」是否有測試把關，本次調查尚未確認，值得補查。

### 規則寫進 CODING_STANDARDS.md，機械部分交給 check_conventions.py

[`CODING_STANDARDS.md:6`](../../CODING_STANDARDS.md) 已經劃好分工：審查者判斷的規則寫在這裡，可機械判定的交給 CI。建議新增「程式碼註解」一節，先定義「註解」是否包含 docstring，再列出允許的種類：模組與類別標頭（角色，加上本模組內成立的不變條件，跨模組契約以 ADR 或 reference 連結）、點名受保護程式碼的 why-not，以及 repo 已經強制要求、規則若不豁免就會自相矛盾的幾類，包括第 14 行的同步來源指標、第 15 行的基礎設施 Why 註解、`TODO(#n)` 技術債標記、附理由的 `noqa`（如 [`runner.py:63`](../../src/shiro_mlops/tasks/runner.py) 的「name fixed by the #66 interface design」）、lab 採用時的 TOML 註解，以及 [`docs/how-to/run-lab-study.md:174`](../../docs/how-to/run-lab-study.md) 規定的 Jupytext percent 格式儲存格（見 [`lab/2026-11-17-dhf-weather-calendar/study.py:1-26`](../../lab/2026-11-17-dhf-weather-calendar/study.py)）。同一節也可以寫下目前未成文的語言慣例：`#` 註解用中文，docstring 用英文。另外應比照 AGENTS.md 第 11 行補一條審查規則：改動標頭不變條件所描述的程式碼時，同一個 PR 必須更新或刪除那條不變條件。why-not 與 what 的區分是語意判斷，屬於審查者，不該硬塞進 CI。

能機械化的部分應放進 [`scripts/check_conventions.py`](../../scripts/check_conventions.py)，但要注意現有的 `debt-markers` 是逐行 regex（第 362 至 368 行），分不出註解與字串，新檢查應改用 `tokenize` 或 `ast`。值得做的有四項：同步指標的目標存在檢查，也就是註解中提到的 `docs/reference/…md` 或 `pipelines/…py` 路徑必須是被追蹤的檔案，便宜地抓出刪檔後過時的指標；仿照 clippy 那對 lint 的 why-not 標記慣例，例如以 `WHY-NOT(<symbol>)` 標出受保護的符號，檢查該符號仍存在於相鄰程式碼中，讓「隨受保護程式碼一起刪除」變得可驗證；檢查每個 Dagster asset 都有 `description=`；以及在 ruff 加入 `ERA001` 抓註解掉的程式碼。不要啟用 pydocstyle 的 `D` 規則，那會把 repo 推向更多 docstring，與規則方向相反。所有新檢查都要像 `DEBT_MARKER_EXEMPT`（第 56 至 62 行）一樣，豁免 Jupytext 檔與檢查本身的測試檔。最後，若團隊希望這條規則以實驗為依據，應把提示、各版本、評分方式與配對分析設計記錄在 `docs/research/`（已有 [`2026-09-16-taipower-hourly-actual-load-source.md`](../../docs/research/2026-09-16-taipower-hourly-actual-load-source.md) 的先例），再由 ADR 引用；`lab/` 的契約是為訓練快照與滾動起點回測設計的，不適合放這類研究。

## 結論

這場辯論真正的變數不是註解多寡，而是哪些宣稱可以驗證，以及它們是否放在讀者動手改的地方。貼文的數據其實已經暗示這一點：陷阱偵測幾乎完全取決於改寫是否保留了相關事實，而這不靠任何模型就能確定性地算出來。agent 時代只翻轉了舊辯論一半的成本結構：閱讀變便宜，重新推導介面的時間成本趨近於零，但推導出錯的風險沒有下降，留下的註解還會被當成指令執行。精簡規則最大的優點，也就是更少、更有份量的註解，因此也是它最大的失效模式：一條過時的天條，比十條過時的重述註解更危險。

對 shiro-mlops 而言，務實的順序是先做 A 級清理、豁免工具讀取的介面文字、把幾條散文天條換成會失敗的測試，之後再討論是否收緊到 D 級。要讓 D 級的嚴格度成為團隊標準，需要的不是更有說服力的貼文，而是一次預先登記、採配對設計、含過時註解組與應執行對照組的複製實驗；在那之前，「D 最好」只應被當成值得檢驗的假說，而不是規範。

## 參考文獻

有標註發表處的是會議或期刊論文，沒標註的多為 arXiv 預印本或網頁資料。本次調查無法開啟 arXiv 全文，所以 arXiv 文獻的數字取自摘要與檢索結果，未對照原文核實；正式引用前應先核對原文。repo 內的證據以內文的檔案與行號為準。

### LLM 與註解

1. Macke & Doyle，文件缺漏或錯誤對 LLM 理解程式碼的影響，Findings of NAACL 2024。[arXiv 2404.03114](https://arxiv.org/abs/2404.03114)
2. CodeCrash：17 個模型在程式碼擾動下的穩健性，NeurIPS 2025。[arXiv 2504.14119](https://arxiv.org/html/2504.14119v3)
3. Le et al.，When Names Disappear：識別字名稱混淆後的程式理解。[arXiv 2510.03178](https://arxiv.org/pdf/2510.03178)
4. 註解對 bug 修復準確率的影響（微調設定）。[arXiv 2601.23059](https://arxiv.org/abs/2601.23059)
5. Thornton：8 個前沿模型在註解操弄下的漏洞偵測。[arXiv 2602.16741](https://arxiv.org/html/2602.16741v1)
6. Imani et al.，Inside Out：開關模型內的「註解」表徵。[arXiv 2512.16790](https://arxiv.org/abs/2512.16790)
7. LLM 從 commit 還原架構決策。[arXiv 2609.03721](https://arxiv.org/abs/2609.03721)
8. LLM 零樣本產生設計理由。[arXiv 2504.20781](https://arxiv.org/abs/2504.20781)
9. Gloaguen et al.，AGENTS.md 等脈絡檔對 coding agent 的效果評估。[arXiv 2602.11988](https://arxiv.org/abs/2602.11988)
10. Xia et al.，When Comments Mislead：過時註解對程式碼生成的影響，ASE 2026。[DOI](https://doi.org/10.1145/3832783.3834359)
11. Comment Traps：被註解掉的缺陷程式碼對 Copilot 與 Cursor 的影響，ACM。[DOI](https://dl.acm.org/doi/10.1145/3797102)
12. Wu & Nita-Rotaru，ALIBI：LLM 無法照指示忽略不可信註解。[arXiv 2607.24964](https://arxiv.org/abs/2607.24964)
13. Vijayvargiya et al.，Ambig-SWE：agent 偵測需求不完整與詢問行為。[arXiv 2502.13069](https://arxiv.org/html/2502.13069v3)
14. Edwards et al.，Ask or Assume?，Findings of EMNLP 2026。[arXiv 2603.26233](https://arxiv.org/abs/2603.26233)
15. Anthropic，Claude prompting best practices。[文件](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices)
16. Terminal Wars，Should you comment code for AI?（實務綜述，部落格）。[連結](https://terminalwars.com/posts/should-you-comment-code-for-ai/)

### 實驗方法與統計

1. Miller，Adding Error Bars to Evals，2024。[arXiv 2411.00640](https://arxiv.org/abs/2411.00640)；Anthropic 摘要文章：[A statistical approach to model evaluations](https://www.anthropic.com/research/statistical-approach-to-model-evals)
2. Brown, Cai & DasGupta，二項比例的區間估計（Wilson 區間），Statistical Science 2001。[連結](https://projecteuclid.org/euclid.ss/1009213286)
3. McHugh，Interrater reliability: the kappa statistic，2012。[PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3900052/)
4. Cohen's kappa（含 Landis & Koch 分級）。[Wikipedia](https://en.wikipedia.org/wiki/Cohen%27s_kappa)
5. Yao et al.，τ-bench（pass^k 與 agent 執行變異），ICLR 2025。[arXiv 2406.12045](https://arxiv.org/abs/2406.12045)
6. Sclar et al.，提示格式敏感度，ICLR 2024。[arXiv 2310.11324](https://arxiv.org/abs/2310.11324)
7. Panickssery et al.，LLM 評審的自我偏好，NeurIPS 2024。[arXiv 2404.13076](https://arxiv.org/abs/2404.13076)
8. Zheng et al.，LLM-as-a-Judge 的偏誤，NeurIPS 2023。[arXiv 2306.05685](https://arxiv.org/abs/2306.05685)
9. CodeJudgeBench，ACL 2026。[ACL Anthology](https://aclanthology.org/2026.acl-long.888/)
10. Zhu et al.，Agentic Benchmark Checklist。[arXiv 2507.02825](https://arxiv.org/abs/2507.02825)
11. Bean et al.，445 個 LLM 基準的建構效度回顧，NeurIPS 2025。[arXiv 2511.04703](https://arxiv.org/abs/2511.04703)

### 傳統軟體工程

1. Ousterhout & Martin，A Philosophy of Software Design 與 Clean Code 的公開辯論，2024–2025。[GitHub](https://github.com/johnousterhout/aposd-vs-clean-code)
2. Clean Code 第 4 章筆記（二手整理）。[GitHub](https://github.com/JuanCrg90/Clean-Code-Notes)
3. PEP 257 Docstring Conventions。[連結](https://peps.python.org/pep-0257/)；PEP 8。[連結](https://peps.python.org/pep-0008/)
4. Google Python Style Guide。[連結](https://google.github.io/styleguide/pyguide.html)
5. Linux kernel coding style。[GitHub](https://github.com/torvalds/linux/blob/master/Documentation/process/coding-style.rst)；kernel Rust coding guidelines。[GitHub](https://github.com/torvalds/linux/blob/master/Documentation/rust/coding-guidelines.rst)
6. Go Doc Comments。[連結](https://go.dev/doc/comment)
7. clippy `undocumented_unsafe_blocks` 原始碼。[GitHub](https://github.com/rust-lang/rust-clippy/blob/master/clippy_lints/src/undocumented_unsafe_blocks.rs)
8. Nygard，Documenting Architecture Decisions，2011。[連結](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)；Fowler，Architecture Decision Record。[連結](https://www.martinfowler.com/bliki/ArchitectureDecisionRecord.html)
9. Fluri et al.，程式碼與註解的共同演化，2009。[DOI](https://doi.org/10.1007/s11219-009-9075-x)
10. Woodfield et al.，註解對程式理解的影響，ICSE 1981。[書目](https://bibtex.github.io/ICSE-1981-WoodfieldDS.html)
11. Potdar & Shihab，自承技術債，ICSME 2014。[書目](https://bibtex.github.io/ICSME-2014-PotdarS.html)
12. icontract（Python 的 Design by Contract 函式庫）。[PyPI](https://pypi.org/project/icontract/)
13. Chesterton's fence。[thoughtbot](https://thoughtbot.com/blog/chestertons-fence)
