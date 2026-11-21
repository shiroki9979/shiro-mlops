# Coding agent 註解精簡實驗評析（精簡版）

- 建立日期：2026-11-21
- 最後更新：2026-11-21

完整版見 [Coding agent 註解精簡實驗評析](<Coding agent 註解精簡實驗評析.md>)，引用來源與計算細節都在那裡。

## 一句話結論

方向對，結論說過頭。「刪掉重述型註解、留下 why」有文獻與數據支持；「D 最好」不成立。數據最支持的其實是溫和的 A：刪掉約三分之一的註解，看不出任何損失。

## 1. 文獻怎麼說

- **what 不靠註解，靠名稱**：缺漏文件對 GPT-4 理解程式碼沒有顯著影響（Macke & Doyle, NAACL Findings 2024），但這些研究都保留了識別字名稱；名稱被混淆後，模型表現大幅下滑。
- **why 從程式碼還原不出來**：LLM 從 commit 還原架構決策時，常漏掉背後的理由；AGENTS.md 研究也發現，儲存庫概覽沒有幫助，只有記載非標準慣例的內容有用。
- **最一致的警訊是過時註解**：錯誤註解的傷害遠大於沒有註解（隨機註解下 GPT-3.5 成功率只剩 22.1%）；過時註解會把生成的程式碼拉回舊實作；叫模型「忽略註解」沒有用。
- **停下來詢問要靠明確誘發**：agent 預設傾向自行假設，而最有效的誘發強度在 Sonnet 3.5 與 Sonnet 4 之間就已不同。
- **沒有同類研究**：找不到依註解類別刪減、再量測 agent 讀改審表現的研究。
- **限制**：研究環境無法開啟 arXiv 全文，數字取自摘要，且多為 2025–2026 年的預印本。

## 2. 實驗效度

| 對照 | 結果 | 統計判讀 |
| :--- | :--- | :--- |
| 陷阱 N 對 O | 3/14 對 10/14 | Fisher p = 0.021，多重比較校正後不顯著 |
| 陷阱 D 對 O | 6/14 對 10/14 | p = 0.252；14 個陷阱的檢定力只有 0.20 |
| 陷阱 A 對 O | 10/14 對 10/14 | 差值 95% 信賴區間 ±31 pp，不等於「一樣好」 |
| 詢問 D 對 O | 4/4 對 0/4 | 若為配對設計，最小可能 p 值是 0.125，永遠不會顯著 |
| why N 對 O | 60% 對 94% | 唯一可能穩健的效果（前提是約 48 題以上） |

- **沒有差異撐得過校正**：20 次檢定的 Bonferroni 門檻是 0.0025。若六個版本的真實偵測率其實相同，仍有 44–54% 的機率出現某版與 O 差 4 個陷阱以上，所以 D 的 6 對 10 跟擲硬幣差不多。
- **陷阱指標是循環的**：陷阱多半依註解中的約束設計，量到的其實是改寫保留了多少相關事實，不跑模型也數得出來。
- **同家族模型包辦太多角色**：Opus 改寫、Sonnet 閱讀，若出題與評分也出自同家族，就有自我偏好的風險。
- **「詢問 4/4」可能是措辭效應**：O 與 D 都察覺了 6/6 的設計衝突，只有 D 停手，可能是「天條」這種命令式措辭在起作用。實驗沒有「應該直接做」的對照任務，無法排除 D 讓 agent 什麼都問。
- **κ**：B 只有 0.54，兩位改寫者約每 4 個決定就有 1 個不同，代表規則太模糊。
- **值得肯定的地方**：O／N 兩端夾住變體、what 與 why 分開量、logic bug 當負對照、量了規則可重現性，而且連不利的 D 6/14 也公布了。

## 3. 傳統軟工對照

| 觀點 | 與規則一致 | 與規則衝突 |
| :--- | :--- | :--- |
| Clean Code | 「壞註解」清單幾乎全部吻合 | 允許授權標頭、TODO、公開 API 文件 |
| Ousterhout | 實作碼只在不明顯時才註解 | 函式介面註解是必要的；「unit tests are a poor form of documentation」 |
| PEP 257／Google／Go | 禁止重述簽章，「never describe the code」 | 公開函式必須有 docstring |
| ADR | 承接架構層級的 why，可以去重 | 改動現場看不到，why-not 仍須寫在原地 |
| Rust `// SAFETY:` | 最接近：clippy 強制緊鄰、沒有 unsafe 時強制刪除 | Rust 有 `unsafe` 這個錨點可以 lint，規則說的「怪程式碼」沒有 |

agent 沒有跨工作階段的記憶，每次都要重新推導介面：讀得便宜，但推錯的風險沒有降低。把散文寫成「天條」提高了它的權威，卻沒有讓它變得可驗證。

## 4. 對 shiro-mlops 的建議

現況：`src/` 的 `#` 註解只有 7,808 字元，多半已是 why；docstring 有 64,077 字元，是註解的 8 倍。所以這條規則真正會砍的是 docstring。repo 裡目前沒有這條規則，也沒有實驗紀錄。

1. **先做 A 級清理**：刪掉 `core/config.py` 的分節標籤、只重述下一行的註解、`tasks/runner.py` 等處共 11 條分隔線，以及重述簽章的 NumPy `Parameters` 區塊。逐條審查，不要批次刪。
2. **工具會讀的 docstring 不能刪**（目前沒有任何測試會抓到，刪了 CI 照樣全綠）：
   - FastAPI 路由的 docstring 會變成 OpenAPI 說明（`service/api.py`、`service/data_explorer/router.py`）。
   - Pydantic 類別的 docstring 會變成 schema 說明，包括 `service/api.py:178-181` 刻意複製的部分。
   - argparse 讀取模組 docstring：刪掉後 `pipelines/smoke_check.py:241` 與 `scripts/rederive_hourly_actual_load.py:76` 一啟動就崩潰。
   - 建議把這些文字搬到明示的 `description=` 參數。
3. **長篇模組 docstring 改成指向文件**：`pipelines/issued_forecast.py`、`tasks/types/base.py` 的 docstring 重述了 `docs/reference/` 的內容，卻沒有「同 PR 更新」的守門，最容易變成過時的天條。像 `tasks/runner.py` 標頭那種只在本模組內成立的不變條件則要保留。
4. **把天條寫成測試**：「Task types never touch repositories」寫成 AST 匯入測試；ADR-0010 的 `np.load(..., allow_pickle=False)` 寫成檢查。
5. **規則寫進 `CODING_STANDARDS.md`**：
   - 明訂 docstring 算不算「註解」。
   - 豁免 repo 已經要求的幾類註解：同步來源註解、基礎設施 Why 註解、`TODO(#n)`、附理由的 `noqa`、lab 的 TOML 註解、Jupytext 儲存格。
   - 改到不變條件描述的程式碼時，必須在同一個 PR 更新那條不變條件。
6. **機械檢查放進 `scripts/check_conventions.py`**：
   - 註解中提到的檔案路徑必須存在。
   - `WHY-NOT(<symbol>)` 標記的符號必須存在。
   - Dagster asset 一律要寫 `description=`。
   - ruff 加開 `ERA001`。
   - 不要開 pydocstyle 的 `D` 規則。

## 結論

agent 讓「讀」變便宜，但沒有讓「推錯」變少，而且留下的註解會被當成指令執行。一條過時的天條，比十條過時的重述註解更危險。務實的順序是：先做 A 級清理、豁免介面文字、把天條轉成測試。若要收緊到 D 級，需要一次預先登記、採配對設計、含過時註解組的複製實驗。

## 參考文獻

有標註發表處的是會議或期刊論文，沒標註的多為 arXiv 預印本或網頁資料。研究環境無法開啟 arXiv 全文，所以 arXiv 文獻的數字取自摘要與檢索結果，未對照原文核實。第 4 節的 repo 證據來自 shiro-mlops 本身，逐行出處見完整版。

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
