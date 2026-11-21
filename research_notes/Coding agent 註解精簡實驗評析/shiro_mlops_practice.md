# shiro-mlops: current comment and documentation practice (evidence for a minimal-comment rule)

Scope: read-only investigation of the local checkout `/home/user/shiro-mlops` (branch `claude/modest-faraday-wfpb5g`, HEAD `ef67fdc`, 2026-11-21). All sources are repo-relative paths with line numbers. Measurements came from throwaway `ast`/`tokenize` scripts run outside the repo. Library behaviour was checked against the locked wheels (`uv.lock`: dagster 1.13.19, fastapi 0.141.1, pydantic 2.13.4, feast 0.66.0), downloaded to a scratch directory and grepped, never executed.

Caveat: the clone is shallow (`git rev-parse --is-shallow-repository` returns `true`). `git blame` assigns every line older than the boundary to boundary commit `3d7a461` (2026-09-28), so "added on" dates before 2026-09-28 cannot be trusted.

## Q1. Does CODING_STANDARDS.md or any other doc already contain this comment rule or a variant? When was it added?

### Takeaway

No repo doc contains the "names over comments / only header + why-not" rule. The nearest rules cover narrower cases. One says to add a Why comment on non-intuitive infrastructure settings. Another says to note the sync source wherever a config value is restated. A third requires a tech-debt marker to name its issue. Several docs go the other way and require comments in specific places (lab-adoption links in TOML, sync-source notes).

### Cited Findings

- CODING_STANDARDS.md has no general comment rule. It has three sections: 文件, 設定與基礎設施, 技術債. The only comment-specific rule is "**非直觀設定附 Why 註解**：行為取決於執行期機制的基礎設施設定，須在設定旁說明原因與所防範的失敗情境。例如 Nginx 以 `resolver` 加變數 upstream 延後 DNS 解析…" — [CODING_STANDARDS.md:15](CODING_STANDARDS.md). It covers only infrastructure settings, not application code.
- A second rule requires a comment wherever a value is duplicated: "**設定字面值單一來源**：…無法共用時，在重複處註明須同步的來源檔。" — [CODING_STANDARDS.md:14](CODING_STANDARDS.md). This is a "sync-source" comment type that the proposed two-case rule does not name explicitly.
- CODING_STANDARDS.md says mechanical rules live in CI and are not restated: "可機械判定的規則由 CI 執行（ruff、markdownlint、`scripts/check_conventions.py`），不在此重述。" — [CODING_STANDARDS.md:6](CODING_STANDARDS.md). AGENTS.md points reviewers to it: "apply CODING_STANDARDS.md for repo-specific judgement rules; mechanical rules run in CI." — [AGENTS.md:23](AGENTS.md).
- History of CODING_STANDARDS.md (`git log -- CODING_STANDARDS.md`):
  - Created in `e84391e` (2026-10-25, author `shiroki#9979`), "ci(docs): 新增慣例檢查與 docs job，並建立 CODING_STANDARDS.md". The body says: "新增 CODING_STANDARDS.md（審查者判斷規則），AGENTS.md 加入 code review 指標與本機檢查指令". Lines 14–17, including the Why-comment rule, all date from this commit (`git blame -L 14,17`). It was merged through PR #86 (`89c5b39`, branch `chore/agent-guardrails`). No issue number appears in the commit message.
  - Last changed in `d2ef162` (2026-11-16, author Claude), "docs(agents): add tech-debt guideline and enforce linked debt markers". This commit added the 技術債 section and the `debt-markers` check. It was merged through PR #100 (`ed52022`). Header: "最後更新：2026-11-16" — [CODING_STANDARDS.md:4](CODING_STANDARDS.md).
- Tech-debt marker rule: "a `TODO`, `FIXME`, `HACK`, or `XXX` comment must name its issue directly after the marker, as in `TODO(#123): ...`. CI enforces this with `scripts/check_conventions.py debt-markers`" — [docs/agents/tech-debt.md:25](docs/agents/tech-debt.md).
- Docs that require comments:
  - Lab adoption: "採用時在任務設定 TOML 參數旁註解連回報告。" — [docs/reference/lab.md:83](docs/reference/lab.md). The same step appears in [docs/how-to/run-lab-study.md:184](docs/how-to/run-lab-study.md) and in a study plan at [lab/2026-11-17-dhf-weather-calendar/README.md:76](lab/2026-11-17-dhf-weather-calendar/README.md).
  - A review-checklist rule stated only inside an ADR: "`np.load` 呼叫一律明示 `allow_pickle=False`，納入 Code Review 清單。" — [docs/adr/0010-persist-models-in-native-non-executable-formats.md:44](docs/adr/0010-persist-models-in-native-non-executable-formats.md). CODING_STANDARDS.md does not list it.
- Closest existing "names" guidance is about domain vocabulary, not comments: "When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`." — [docs/agents/domain.md:44-46](docs/agents/domain.md).
- Searches for "Names over comments", "why-not", "trap bug", "κ/kappa", "名稱優先" and "命名優先" across tracked `.md/.py/.toml/.yml/.ts/.tsx` returned nothing. "註解" appears only in CODING_STANDARDS.md:15 and the three lab-adoption passages above (`grep -rniE`).
- The repo has no CLAUDE.md. `.claude/` does not exist. `.cursor/` holds only `environment.json` and `install.sh`. None of them mention comments.

### Inferences

- The proposed rule would be new. The natural home is a new section in CODING_STANDARDS.md (for example `## 程式碼註解`), since that file holds judgement rules. Its mechanical parts would go into `check_conventions.py`, following the split stated at CODING_STANDARDS.md:6.
- The new rule must be reconciled with three existing comment mandates, or it will contradict them:
  1. Why comments on infrastructure settings (CODING_STANDARDS.md:15). These fit the "why-not" case.
  2. Sync-source comments on restated literals (CODING_STANDARDS.md:14). These are a third kind: pointers that name a duplicate, not a rationale.
  3. Lab-adoption comments in task TOML (lab.md:83). These fit "decision basis" if TOML counts as code under the rule.
- The rule should say whether `TODO(#n)` debt markers are allowed. They are neither a header nor a why-not comment.

### Gaps

- The clone is shallow and GitHub issue bodies were not read in full, so I cannot rule out discussion of comments in older issues (#1–#38) or in PR review threads. The 100 most recent issue titles (#39–#176) contain nothing about comments.

## Q2. Is the experiment (O/N/A/B/C/D variants, Opus rewrite, Sonnet read/modify/review) recorded anywhere in the repo?

### Takeaway

No. Nothing in the working tree, local history, remote branch heads, or recent GitHub issue titles records the experiment. The three modules cannot be identified from the reported 11,753-char total.

### Cited Findings

- `git log --all --oneline | grep -iE 'comment|註解|docstring|why'` returned nothing. All 260 commits reachable in the shallow clone were checked.
- `git log --all -i --grep=comment` matched only commits whose bodies mention comments in passing, none of them about an experiment:
  - `6b47c12` (2026-11-20): "Add Why comments for the whole-bucket lifecycle filter, the versioning depends_on, the multipart abort rule and the GREATER_THAN operator."
  - `ee3ba97`: "drop the Data Lake / Feast Registry / MLflow usage comments."
  - `9634c7b` (2026-11-09): "Keep the sys.path bootstrap with a Why-comment".
  - `7abe237` (2026-10-25): "保留「先啟動替代 API 再移除原容器」的順序與 Why 註解".
- Commits that added sync-source comments: `903f3a3` "chore(nginx): note where the /published/ cache header and mount are restated (#142)" and `8fc0135` "docs(frontend): name the sync source of every /console/ copy (#137)", both 2026-11-20.
- Branches:
  - Local branches are `claude/modest-faraday-wfpb5g` and `dev`.
  - `git ls-remote --heads origin` lists 17 heads. Head commits not present locally were read through the GitHub API: `aa42577` (#173 dev proxy), `4a54fc1` (glossary terms), `2ad4059` (#171 MSW fixture), `4dd2e26` (glossary issue time), `fa085f4` (#169 Cache-Control). None relate to comments.
  - Two `research/*` branches (`research/aws-hosting-cost`, `research/cloud-data-access`) are named for AWS topics. I did not inspect them.
- `reports/` is empty. `research_notes/` holds only this investigation's directory. `docs/research/` holds one unrelated file (`2026-09-16-taipower-hourly-actual-load-source.md`). `lab/` holds only forecasting studies (`2026-11-08-dhf-hyperparameter-search`, `2026-11-17-dhf-weather-calendar`).
- GitHub issues, listed by creation date (100 of 132 total): no title mentions comments, docstrings or an agent experiment.
- Identifying the three modules: I summed comment chars plus docstring chars over every 3-module combination in `src/`. Four different combinations land within ±15 chars of 11,753 when docstrings are counted raw, for example `tasks/runner.py + pipelines/smoke_check.py + core/database.py` and `tasks/runner.py + data/repository.py + data/issued_forecast.py`. None match when docstrings are counted after `cleandoc`. The total does not single out any modules, and the experiment may not have used this repo at all.

### Inferences

- The experiment is not reproducible from the repo. If the owner wants the rule to rest on it, the variants, prompts and scores could be stored as a `lab/<date>-comment-density/` study or under `docs/explanation/`, and an ADR could cite them. Only the rule text itself belongs in CODING_STANDARDS.md.

### Gaps

- I did not inspect the two `research/*` remote branches beyond their names, nor PR review comments.
- The experiment's module names and its counting method (whether docstrings count as "comments") are unknown. That method matters a great deal here: see Q3 on docstrings dominating.

## Q3. Current comment practice: volume, heaviest modules, and examples

### Takeaway

In `src/`, docstrings are about 8× the volume of `#` comments: 64,077 docstring chars against 7,808 comment chars across 75 files and 12,072 lines. Every file has a module docstring. `#` comments are sparse (151 lines), mostly Chinese, and already lean toward why, invariant and sync-source content. The redundant "what" material sits mainly in docstrings: NumPy-style `Parameters` blocks and one-liners that restate function names, plus some section-header `#` comments in older code.

### Cited Findings

Volume (comments are `tokenize.COMMENT` tokens; docstrings are module, class and function docstrings via `ast`):

| Tree | Files | Lines | `#` comment lines | Comment chars | Docstrings | Docstring chars | Files with module docstring |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `src/` | 75 | 12,072 | 151 | 7,808 | 575 | 64,077 | 75/75 |
| `tests/` | 84 | 16,416 | 124 | 4,856 | 469 | 32,702 | 84/84 |
| `lab/` | 12 | 2,722 | 117 | 3,673 | 74 | 8,215 | 10/12 |
| `scripts/` | 4 | 874 | 22 | 1,695 | 9 | 1,889 | 4/4 |

- Docstring coverage in `src/`: 248 of 342 public functions and 111 of 245 private functions have docstrings.
- Language split in `src/`: 105 of 151 `#` comments contain CJK, but only 9 of 575 docstrings do. Comments are mostly Traditional Chinese; docstrings are almost all English.
- `src/` also has 11 section-divider comments (`# --- Training ---`).
- Frontend: 116 tracked `.ts/.tsx` files, 6,589 lines, 95 `//` lines, no `/* */` blocks. No file has more than 6 comment lines; the largest is [frontend/packages/shared/src/i18n/format.ts](frontend/packages/shared/src/i18n/format.ts).
- Infrastructure comment lines: [infra/terraform/main.tf](infra/terraform/main.tf) 22, `docker/docker-compose.yml` 7, `docker/Dockerfile.api` 5, `docker/Dockerfile.dagster` 5.

Heaviest `src/` modules by comment plus docstring chars:

| Module | Docstring chars | Comment chars | Total |
| :--- | ---: | ---: | ---: |
| `data/repository.py` | 5,441 | 218 | 5,659 |
| `tasks/runner.py` | 5,036 | 425 | 5,461 |
| `tasks/types/unsupervised_reconstruction.py` | 3,159 | 598 | 3,757 |
| `core/database.py` | 3,113 | 210 | 3,323 |
| `pipelines/smoke_check.py` | 2,023 | 955 | 2,978 |
| `data/cwa_client.py` | 2,266 | 143 | 2,409 |
| `tasks/model_store.py` | 2,163 | 66 | 2,229 |

(a) Header and invariant comments, the kind the rule keeps:

- [src/shiro_mlops/tasks/runner.py:1-8](src/shiro_mlops/tasks/runner.py): module docstring "Task runner: the single entry point Dagster and the API use… The runner owns I/O and the shared components (ADR-0009)… Task types only ever receive in-memory frames. Every time-dependent decision takes an explicit `as_of` in Taiwan-local naive time." These are role plus invariants, but over 7 lines (412 chars), more than the 1–3 lines the rule allows.
- [src/shiro_mlops/tasks/types/base.py:1](src/shiro_mlops/tasks/types/base.py): "Task type seam: pure computation adapters… Task types never touch repositories."
- [src/shiro_mlops/tasks/types/base.py:59](src/shiro_mlops/tasks/types/base.py): "# 共用時間切分點：target 時間 >= 此值者為驗證列，各任務類型不得自行切分。" A field-level invariant.
- [src/shiro_mlops/tasks/model_store.py:1](src/shiro_mlops/tasks/model_store.py): "Only native, non-executable formats are written or read (ADR-0010). A legacy `model.joblib` is never loaded".
- [src/shiro_mlops/core/io_managers.py:16-18](src/shiro_mlops/core/io_managers.py): "A materialized asset whose artifact is gone still fails, so lost data is never mistaken for a fresh instance."
- [src/shiro_mlops/tasks/definition.py:51](src/shiro_mlops/tasks/definition.py): class docstring `TaskPolicies` "Shared-component parameters; task types must not reimplement these rules."
- Several module docstrings are long and narrate runtime behaviour rather than stating 1–3 lines of role plus invariants:
  - [src/shiro_mlops/pipelines/forecast_view_export.py:1](src/shiro_mlops/pipelines/forecast_view_export.py): 953 chars, 15 lines.
  - [src/shiro_mlops/tasks/types/unsupervised_reconstruction.py:1](src/shiro_mlops/tasks/types/unsupervised_reconstruction.py): 826 chars.
  - [src/shiro_mlops/pipelines/smoke_check.py:1](src/shiro_mlops/pipelines/smoke_check.py): 813 chars, including usage text.
  - `pipelines/forecast_track_record.py`: 676 chars. `pipelines/issued_forecast.py`: 660 chars.

(b) Why-not and rationale comments next to deliberately odd code, the kind the rule keeps:

- [src/shiro_mlops/data/cwa_client.py:16-17](src/shiro_mlops/data/cwa_client.py): "標準函式庫 ElementTree 不防範 entity expansion（billion laughs）等 XML 攻擊，故以 defusedxml 解析。"
- [src/shiro_mlops/pipelines/smoke_check.py:29](src/shiro_mlops/pipelines/smoke_check.py): "Dagster 未公開排程狀態型別；僅此處依賴內部路徑，升級時由離線測試揭露破壞。" It sits on a private `dagster._core` import.
- [src/shiro_mlops/pipelines/smoke_check.py:88-91](src/shiro_mlops/pipelines/smoke_check.py): "名稱與 cron 刻意重述而不引用 pipelines/issued_forecast.py，才能檢出部署漂移；變更時須同步 … docs/reference/dagster-schedules.md 第 6 項。" Deliberate duplication combined with a sync-source pointer. Blame: Claude, 2026-11-20 (`aa9c1fd`).
- [src/shiro_mlops/tasks/model_store.py:28](src/shiro_mlops/tasks/model_store.py): "核心沒有 renameat2（如 macOS）或檔案系統不支援 RENAME_EXCHANGE 時改以 rename 模擬交換。"
- [src/shiro_mlops/pipelines/tracking.py:62-63](src/shiro_mlops/pipelines/tracking.py): "MLflow 3 的 register_model 只接受 logged model，故直接以 artifact URI 建立 model version。"
- [src/shiro_mlops/pipelines/assets.py:76-78](src/shiro_mlops/pipelines/assets.py): the retry policy justified with arithmetic, "Dagster 指數退避等待 (2^n - 1) × delay，即 10、30、70 秒…仍早於下一個 10 分鐘 slot。"
- [src/shiro_mlops/tasks/types/unsupervised_reconstruction.py:57-58](src/shiro_mlops/tasks/types/unsupervised_reconstruction.py): the observed failure behind a design choice, "只以結束小時編碼星期時，這類常態轉換會被誤判為異常。"
- [src/shiro_mlops/data/repository.py:881-882](src/shiro_mlops/data/repository.py): "`# TODO(#160)`: 兩表在 SQLite 以不同字串形式保存 UTC…SQL join 只在 TimescaleDB 成立". The only debt marker in `src/`.
- [src/shiro_mlops/tasks/runner.py:63](src/shiro_mlops/tasks/runner.py): "`# noqa: N818 - name fixed by the #66 interface design`".
- [src/shiro_mlops/pipelines/task_pipelines.py:304](src/shiro_mlops/pipelines/task_pipelines.py): "`except Exception as error:  # MLflow 任何失敗都不應讓已保存的模型失效`".
- [frontend/nginx.conf:10-11](frontend/nginx.conf): the example cited by CODING_STANDARDS.md:15, "A variable upstream defers DNS to request time…".

Sync-source comments (CODING_STANDARDS.md:14 mandate):

- [src/shiro_mlops/data/forecast_view.py:21-22](src/shiro_mlops/data/forecast_view.py)
- [src/shiro_mlops/pipelines/issued_forecast.py:59-60](src/shiro_mlops/pipelines/issued_forecast.py)
- [src/shiro_mlops/pipelines/forecast_track_record.py:44-45](src/shiro_mlops/pipelines/forecast_track_record.py)
- [src/shiro_mlops/pipelines/forecast_view_export.py:51-52](src/shiro_mlops/pipelines/forecast_view_export.py)
- [src/shiro_mlops/core/config.py:56-57](src/shiro_mlops/core/config.py): "Keep the default in sync with that variable's default."

(c) Redundant "what" comments and docstrings the rule would delete:

- Section-label comments in [src/shiro_mlops/core/config.py](src/shiro_mlops/core/config.py), right above self-describing settings: `# Environment` (25), `# Storage paths` (28), `# MLflow` (60), `# Feast Feature Store` (63), `# External APIs` (70), `# API Serving` (88).
- [src/shiro_mlops/features/definitions.py:10,19,44](src/shiro_mlops/features/definitions.py): `# 1. Location Entity`, `# 2. Offline Parquet Sources`, `# 3. Feature Views`.
- [src/shiro_mlops/features/transformers.py:51](src/shiro_mlops/features/transformers.py): `# Cyclical hour encoding` above `df["hour_sin"] = np.sin(...)`. Also lines 133 (`# Keep weather columns`) and 144 (`# Deduplicate weather data on join keys before merge`, right before `drop_duplicates(subset=join_keys…)`).
- [src/shiro_mlops/data/cwa_client.py:566](src/shiro_mlops/data/cwa_client.py): `# Extract observation datetime` above `obs_time = st.get("ObsTime")…`.
- [src/shiro_mlops/core/database.py:202](src/shiro_mlops/core/database.py): `# Apply PostgreSQL to SQLite dialect conversions` above `re.sub(r"\bTIMESTAMPTZ\b", "TIMESTAMP", …)`.
- Section dividers `# --- Training ---` and similar: [src/shiro_mlops/tasks/runner.py:131,226,252,525](src/shiro_mlops/tasks/runner.py), plus `task_pipelines.py` and `unsupervised_reconstruction.py`. 11 in total.
- NumPy-style `Parameters` blocks that restate signatures:
  - [src/shiro_mlops/data/repository.py:332-343](src/shiro_mlops/data/repository.py): `__init__` with "engine : Engine | None — Optional pre-configured SQLAlchemy Engine."
  - `repository.py` has 4 such blocks in total (`fetch_load_range` at 665, `fetch_weather_range` at 770, 695 and 608 chars).
  - Elsewhere: `core/database.py` has 5, and each `taipower_*_repository.py` has 1.
- One-line docstrings that paraphrase the name:
  - [src/shiro_mlops/data/repository.py:56](src/shiro_mlops/data/repository.py) `_taiwan_instant_to_utc`: "Convert a Taiwan-local timestamp to a timezone-naive UTC datetime."
  - [src/shiro_mlops/data/repository.py:93](src/shiro_mlops/data/repository.py) `_build_time_filter`: "Construct SQL WHERE clause conditions and parameter mappings."
  - [src/shiro_mlops/data/repository.py:324](src/shiro_mlops/data/repository.py) `TimeSeriesRepository`: "Repository managing time-series persistence and queries for TimescaleDB."
  - `repository.py:822-858`: "Upsert … keyed by …" and "Fetch …".
  - Heuristic count: 77 of 297 one-line function docstrings in `src/` start with the function name's leading verb (5,086 chars). Some still carry an invariant, for example [src/shiro_mlops/core/io_managers.py:64](src/shiro_mlops/core/io_managers.py) "…reject legacy pickle files", so the heuristic overstates the redundancy.
- Age: `git blame` puts the redundant examples above (`transformers.py:51`, `config.py:25`, `definitions.py:10`, `cwa_client.py:566`, `repository.py:334`) at or before the shallow boundary (≤ 2026-09-28, author shiroki9979). The why and sync comments are newer, for example `smoke_check.py:90` by Claude on 2026-11-20.

`lab/` and `tests/`:

- The two lab study scripts carry the most comments, 64 and 46 lines: [lab/2026-11-17-dhf-weather-calendar/study.py:1-26](lab/2026-11-17-dhf-weather-calendar/study.py) and `lab/2026-11-08-dhf-hyperparameter-search/study.py`. These comments are functional. They are Jupytext `percent` headers (`# jupytext: formats: ipynb,py:percent`) and `# %% [markdown]` cells, required by [docs/how-to/run-lab-study.md:174](docs/how-to/run-lab-study.md).
- Every one of the 84 test files has a module docstring. Test docstrings often cite the spec, for example [tests/integration/test_api.py:658](tests/integration/test_api.py) "ADR-0012: each weather field lists the source behind every weather reference point." [lab/tests/test_snapshot.py:358](lab/tests/test_snapshot.py) "ADR-0011: dependency direction is strictly lab -> shiro_mlops; src/ never imports lab."

### Inferences

- If the experiment counted only `#` comments, this repo's `#` layer is already close to the target: about 7.8k chars across 75 files, most of it rationale. If it counted docstrings too, applying the rule mostly means cutting docstrings. That cut runs into the tooling issues in Q5. The rule text should say whether "comments" includes docstrings.
- "1–3 lines" would force several existing module docstrings (600–950 chars) to shrink. Much of their content is runtime narrative already in `docs/reference/` (see Q4), so it could move there or be cut.
- The language split (Chinese `#` comments, English docstrings) is undocumented. A rule could state the language expected for each kind.
- Any mechanical check has to exempt Jupytext percent-format files, or skip `lab/<date>-*/study.py`, since their comments are notebook structure.

### Gaps

- These counts measure volume, not the experiment's metrics (read, modify and review success, trap bugs, κ). Whether this repo's docstrings help or hurt Sonnet is untested.
- Redundancy was classified by heuristics and by hand on a sample, not over the whole corpus.

## Q4. How comments relate to the existing docs: duplication, ADR and issue references, and what `check_conventions.py` enforces

### Takeaway

Comments and docstrings cross-reference the docs heavily: 48 ADR references in 31 `src/` files, 12 `docs/reference/` paths and 5 GLOSSARY references. Many invariants in module docstrings are restated nearly word for word in `docs/reference/*.md` or the ADRs. `check_conventions.py` enforces nothing about comments except the debt-marker format. Its structure (a regex over tracked files, a scoped suffix list, an exempt set) would suit a few narrow mechanical checks that support the rule.

### Cited Findings

References from code:

- `grep -o 'ADR-[0-9]{4}'` over `src/**/*.py` gives 48 occurrences in 31 files. `docs/reference/<file>.md` paths appear 12 times and `GLOSSARY` 5 times.
- Issue references in `src/` comments are rare: `TODO(#160)` at [src/shiro_mlops/data/repository.py:881](src/shiro_mlops/data/repository.py), `(#112)` at [src/shiro_mlops/core/database.py:22](src/shiro_mlops/core/database.py), and `#66` at [src/shiro_mlops/tasks/runner.py:63](src/shiro_mlops/tasks/runner.py). `TODO(#160)` is the only debt marker in any tracked source file outside the checker's own exempt files.

Duplication between docstrings and specs:

- [src/shiro_mlops/pipelines/issued_forecast.py:1](src/shiro_mlops/pipelines/issued_forecast.py) says "It is never floored to the hour… Only scheduled ticks issue; a manual run without a tick fails and writes nothing". [docs/reference/dagster-schedules.md:57](docs/reference/dagster-schedules.md) says "發布時刻即排程 tick 時刻，也是預報的 `as_of`，不取整點" and [docs/reference/dagster-schedules.md:60](docs/reference/dagster-schedules.md) says "只有定時發布才算…手動 materialize…皆以 `Failure` 結束、不寫入".
- [src/shiro_mlops/tasks/types/base.py:1](src/shiro_mlops/tasks/types/base.py) says "Task types never touch repositories". [docs/reference/ml-tasks.md:48](docs/reference/ml-tasks.md) says "任務類型為純計算 adapter，不接觸 repository".
- [src/shiro_mlops/tasks/types/unsupervised_reconstruction.py:12](src/shiro_mlops/tasks/types/unsupervised_reconstruction.py) says "`.npz` arrays (`allow_pickle=False`)… numpy forward pass (ADR-0010)". The same statement appears at [docs/reference/ml-tasks.md:93](docs/reference/ml-tasks.md) and [docs/adr/0010-persist-models-in-native-non-executable-formats.md:20](docs/adr/0010-persist-models-in-native-non-executable-formats.md).
- [src/shiro_mlops/tasks/model_store.py:1](src/shiro_mlops/tasks/model_store.py) says "A legacy `model.joblib` is never loaded". [docs/adr/0010-persist-models-in-native-non-executable-formats.md:21](docs/adr/0010-persist-models-in-native-non-executable-formats.md) says "既有 `model.joblib` 不提供相容載入".
- Some docstrings point to the spec instead of restating it. [src/shiro_mlops/data/hourly_actual_load.py:1](src/shiro_mlops/data/hourly_actual_load.py): "See ADR-0008 and docs/reference/data-contracts.md §1 for the derivation contract." (2 lines). AGENTS.md requires specs to change with the code: "`docs/reference/` holds the current contracts…; edit them in the same PR as the code they describe." — [AGENTS.md:11](AGENTS.md).
- Task-config TOML comments restate domain rules next to keys:
  - [src/shiro_mlops/tasks/dynamic_horizon_forecast.toml:12](src/shiro_mlops/tasks/dynamic_horizon_forecast.toml): "推算序列無法回補；未滿 28 日（672 小時）不得訓練（ADR-0008）".
  - [src/shiro_mlops/tasks/dynamic_horizon_forecast.toml:19](src/shiro_mlops/tasks/dynamic_horizon_forecast.toml): "lag 3 從未進入訓練特徵", which is also in [docs/adr/0003-recursive-multi-step-forecasting.md:51](docs/adr/0003-recursive-multi-step-forecasting.md).
  - [src/shiro_mlops/tasks/dynamic_horizon_forecast.toml:33](src/shiro_mlops/tasks/dynamic_horizon_forecast.toml): "驗證期 MAPE（%）低於此值為 HEALTHY", a "what" description of a key.

What `check_conventions.py` enforces:

- It defines four checks: `python-uv`, `terms`, `doc-dates`, `debt-markers` — [scripts/check_conventions.py:3-10](scripts/check_conventions.py).
- The only comment-related one is `DEBT_MARKER = re.compile(r"\b(?P<marker>TODO|FIXME|HACK|XXX)\b(?!\(#\d+\))")` — [scripts/check_conventions.py:49](scripts/check_conventions.py). It scans suffixes `.py .ts .tsx .js .jsx .sh .sql .css .html .conf .toml .yml .yaml .tf` plus `Makefile*` and `Dockerfile*` — [scripts/check_conventions.py:50-54](scripts/check_conventions.py). An exempt set covers the checker and its tests — [scripts/check_conventions.py:56-62](scripts/check_conventions.py).
- The check runs line by line with `enumerate(text.splitlines())` — [scripts/check_conventions.py:362-368](scripts/check_conventions.py). It does not tokenize, so it cannot tell comments from strings.
- CI runs `python-uv debt-markers` in the lint-and-test job, and `terms` and `doc-dates` in the docs job — [.github/workflows/ci.yml:37](.github/workflows/ci.yml), [.github/workflows/ci.yml:120](.github/workflows/ci.yml), [.github/workflows/ci.yml:127](.github/workflows/ci.yml).
- It does not check for module docstrings or headers, comment length, or commented-out code.

### Inferences

- Duplicated invariants can drift: the spec gets edited in the same PR as the code, but the docstring copy has no such guard. The rule's "header = role + invariants" could be refined to "invariants that hold within this module". Cross-cutting contracts (schedule timing, file formats) would then be cited by link (`ADR-0010`, `dagster-schedules.md §6`), not restated, as `hourly_actual_load.py:1` already does.
- Mechanical checks that fit `check_conventions.py` (stdlib only, AST/tokenize based). All are inferences, none exist today:
  1. **header-present**: every `src/**/*.py` module has a docstring of at most N lines. Today 75/75 have one, but some run to 15 lines, so N needs choosing or a grace list.
  2. **sync-pointer target exists**: a comment that names a path (`docs/reference/…md`, `pipelines/…py`) must point at a tracked file. This is a cheap check for the rule's "must name the code they protect", and it catches stale pointers after deletions.
  3. **no section-label comments**: flag a `#` comment line of one to four words with no verb that precedes a block, or `# --- X ---` dividers. This is heuristic and would need an allowlist.
  4. **Jupytext and generated-file exemptions**, mirroring `DEBT_MARKER_EXEMPT`.
- Telling a "why-not" comment from a "what" comment is semantic. It belongs in CODING_STANDARDS.md as a reviewer judgement rule, consistent with CODING_STANDARDS.md:6.

### Gaps

- I did not measure how often docstring invariants have actually drifted from the specs, for example with `git log -S` on specific phrases. With a shallow clone that history is incomplete.

## Q5. Are docstrings consumed by tooling (OpenAPI, Dagster, Feast, CLI help, doc generators)?

### Takeaway

Yes, in four places where deleting a docstring changes runtime-visible output. (1) FastAPI route docstrings become OpenAPI operation descriptions. (2) Pydantic model and enum class docstrings become schema descriptions, and `service/api.py` deliberately copies item docstrings into the generated per-task models. (3) Module docstrings feed `argparse --help` in five CLIs. (4) Dagster uses a docstring as the asset or op description only when `description=` is missing; every asset here passes `description=` explicitly, and `@schedule` does not read docstrings at all. Feast uses explicit `description=` kwargs. No mkdocs, sphinx or pdoc is configured.

### Cited Findings

FastAPI (0.141.1):

- `route.description = description or inspect.cleandoc(route.endpoint.__doc__ or "")` (`fastapi/routing.py:1034` in the locked wheel).
- No route in the repo passes `description=` or `summary=`, so these handler docstrings are the OpenAPI operation descriptions shown at `/docs`:
  - [src/shiro_mlops/service/api.py](src/shiro_mlops/service/api.py): 235 `/health` "Check API and per-task model health status.", 254 `/ready`, 260 `/tasks/{task_id}/ready`, 266 `/predict`, 284 `/tasks/{task_id}/predict`.
  - [src/shiro_mlops/service/data_explorer/router.py](src/shiro_mlops/service/data_explorer/router.py): 69, 86, 93, 99, 105, 111, 117, 123, 129, for example "List CWA forecast release audit headers without raw payloads."

Pydantic (2.13.4):

- `json_schema.py:1662-1665` sets the JSON-schema `description` from `cls.__doc__` via `inspect.cleandoc`. Enum docstrings are handled the same way at `json_schema.py:891`.
- Schema models whose docstrings reach OpenAPI:
  - [src/shiro_mlops/service/data_explorer/schemas.py](src/shiro_mlops/service/data_explorer/schemas.py): `DatasetStatus` (17), `StatusResponse` (44), `ListEnvelope` (51).
  - [src/shiro_mlops/service/api.py:200](src/shiro_mlops/service/api.py): `TaskPredictionEnvelope`.
- The code deliberately propagates docstrings into dynamically built models:
  - `create_model(name, __base__=item, __doc__=item.__doc__, …)` — [src/shiro_mlops/service/api.py:178-181](src/shiro_mlops/service/api.py).
  - `__doc__=f"Prediction of task {task_id}; items follow its task type and weather fields."` — [src/shiro_mlops/service/api.py:216](src/shiro_mlops/service/api.py).
  - So the task-type item docstrings are API description text: [src/shiro_mlops/tasks/types/recursive_regression.py:69](src/shiro_mlops/tasks/types/recursive_regression.py) `RecursiveRegressionPrediction`, [src/shiro_mlops/tasks/types/direct_classification.py:95](src/shiro_mlops/tasks/types/direct_classification.py) `DirectClassificationPrediction`, [src/shiro_mlops/tasks/types/unsupervised_reconstruction.py:101](src/shiro_mlops/tasks/types/unsupervised_reconstruction.py) `UnsupervisedReconstructionPrediction`.
- The API request and response models in `service/api.py` (106–192) have no class docstrings. They describe fields with `Field(description=…)`, for example [src/shiro_mlops/service/api.py:142-152](src/shiro_mlops/service/api.py).
- Tests assert those field descriptions, not docstrings: [tests/integration/test_api.py:650-654](tests/integration/test_api.py) checks `"observed-weather tasks" in task_horizon` and `== "Forecast horizon in hours (1-168)"`. No test asserts a route or model docstring.
- `rest-api.md` defines the OpenAPI contract in terms of schema names, not descriptions — [docs/reference/rest-api.md:113](docs/reference/rest-api.md).

CLI help from module docstrings:

- `argparse.ArgumentParser(description=__doc__.splitlines()[0])` at [src/shiro_mlops/pipelines/smoke_check.py:241](src/shiro_mlops/pipelines/smoke_check.py) and [scripts/rederive_hourly_actual_load.py:76](scripts/rederive_hourly_actual_load.py).
- `description=__doc__` at [scripts/smoke_nginx.py:249](scripts/smoke_nginx.py) and [lab/2026-11-17-dhf-weather-calendar/study.py:300](lab/2026-11-17-dhf-weather-calendar/study.py).
- If those module docstrings were deleted, `__doc__` would be `None`. The `.splitlines()` call would raise `AttributeError` at startup in the first two. The other two would show empty help. `smoke_check.py`'s docstring also carries the usage line `python -m shiro_mlops.pipelines.smoke_check [--require-ready] [--task TASK_ID]` ([src/shiro_mlops/pipelines/smoke_check.py:1-15](src/shiro_mlops/pipelines/smoke_check.py)).

Dagster (1.13.19):

- The op decorator uses `description=self.description or format_docstring_for_description(fn)` (`op_decorator.py:128`). The asset description resolves as `spec.description or output_def_description or node_def_description` (`assets_definition.py:320`), and `@asset` passes its own `description` to the op as `op_description` (`decorator_assets_definition_builder.py:565`). So a docstring becomes the asset's description only when `description=` is omitted.
- Every `@asset` and `@multi_asset` here sets `description=`: [src/shiro_mlops/pipelines/assets.py](src/shiro_mlops/pipelines/assets.py) at 89, 108, 133, 154, 188, 239, 265 and 270; [src/shiro_mlops/pipelines/forecast_view_export.py:62](src/shiro_mlops/pipelines/forecast_view_export.py); [src/shiro_mlops/pipelines/issued_forecast.py:80](src/shiro_mlops/pipelines/issued_forecast.py); [src/shiro_mlops/pipelines/forecast_track_record.py:61](src/shiro_mlops/pipelines/forecast_track_record.py); [src/shiro_mlops/pipelines/task_pipelines.py](src/shiro_mlops/pipelines/task_pipelines.py) at 157, 198 and 263.
- `schedule_decorator.py` has no docstring fallback; it passes only the explicit `description` (line 209).
- Two schedules with no `description=` therefore have docstrings that are not surfaced in the Dagster UI: [src/shiro_mlops/pipelines/schedules.py:131](src/shiro_mlops/pipelines/schedules.py) ("每十分鐘 materialize 全部即時快照…") and [src/shiro_mlops/pipelines/schedules.py:158](src/shiro_mlops/pipelines/schedules.py).
- Some Dagster `description=` strings carry the rationale themselves: "Issue the hourly dynamic horizon forecast; no retries keep as_of honest" at [src/shiro_mlops/pipelines/issued_forecast.py:221](src/shiro_mlops/pipelines/issued_forecast.py), and "retries are safe because it overwrites" at [src/shiro_mlops/pipelines/forecast_view_export.py:109](src/shiro_mlops/pipelines/forecast_view_export.py).

Feast: `Entity(… description="Prediction subject (e.g. nationwide); name frozen by ADR-0009")` at [src/shiro_mlops/features/definitions.py:14](src/shiro_mlops/features/definitions.py). This is an explicit kwarg, not a docstring.

Doc generators: `pyproject.toml` and the repo contain no mkdocs, sphinx, pdoc, interrogate or pydocstyle configuration (grep over `*.toml/*.yml/*.cfg/Makefile`). `docs/` is hand-written Markdown.

### Inferences

- A blanket "delete docstrings" pass would visibly change three things: the OpenAPI document (route descriptions and four or more schema descriptions, including the deliberate `__doc__=` propagation), CLI `--help`, and possibly crash two CLIs. The rule needs a carve-out such as: "Docstrings consumed by tooling (FastAPI handlers, Pydantic schema models exposed in OpenAPI, modules whose `__doc__` feeds argparse) are interface text, not comments." Alternatively, move that text into explicit `description=` or `summary=` kwargs and `Field(description=…)`, the pattern `service/api.py` request models already use, which makes the contract explicit and testable.
- Dagster is safe today because every asset sets `description=`. A guard would help: a future asset without `description=` would silently start using its docstring as the UI description.

### Gaps

- I did not run the app, so I did not diff `app.openapi()` before and after removing docstrings. The behaviour above comes from reading library source at the locked versions, not from execution.

## Q6. Where could prose invariants become executable (validators, asserts, types, tests)?

### Takeaway

The repo already makes many invariants executable. There are Pydantic validators on task config, runtime checks, and tests named after the invariant they enforce, for example `test_src_never_imports_lab`. A few invariants still live only in prose: no test enforces "task types never touch repositories", and `allow_pickle=False` is only a review-checklist item. These are the best candidates for replacing prose with checks.

### Cited Findings

Already executable:

- Weight rules, with a comment explaining only the tolerance: [src/shiro_mlops/tasks/definition.py:98-127](src/shiro_mlops/tasks/definition.py), `_WeatherSection._weights_combine_into_one_value` raising "weights must sum to 1".
- The cron subset, with a comment giving the reason: [src/shiro_mlops/tasks/definition.py:36-37](src/shiro_mlops/tasks/definition.py), "為 Dagster 可解析之 cron 的嚴格子集，錯誤得以在載入任務設定時就失敗".
- A runtime guard against summing values from different hours: [src/shiro_mlops/tasks/weighted_weather.py:90](src/shiro_mlops/tasks/weighted_weather.py), "逐列相加前確認各點解析的是同一組小時".
- An import-direction test: [lab/tests/test_snapshot.py:357-358](lab/tests/test_snapshot.py), `test_src_never_imports_lab` (ADR-0011).
- Tests whose names state the invariant:
  - [tests/unit/test_forecast_track_record_definitions.py:20](tests/unit/test_forecast_track_record_definitions.py) `test_issuing_and_task_jobs_never_compile_the_track_record`
  - [tests/integration/test_resiliency.py:319](tests/integration/test_resiliency.py) `test_newer_legacy_rows_never_anchor_serving`
  - [tests/integration/test_resiliency.py:364](tests/integration/test_resiliency.py) `test_serving_path_never_constructs_a_cwa_client`
  - [tests/integration/test_task_runner.py:334](tests/integration/test_task_runner.py) `test_rows_persisted_after_as_of_never_anchor_the_forecast`
- A drift test backing the deliberately restated schedule names: [tests/unit/test_smoke_check.py:74](tests/unit/test_smoke_check.py) `test_schedule_cron_drift_and_missing_registration_fail`.
- Immutability through types: `ConfigDict(extra="forbid", frozen=True)` at [src/shiro_mlops/tasks/definition.py:105](src/shiro_mlops/tasks/definition.py), and `@dataclass(frozen=True)` on `TrainingData` and `InputRequirements` in [src/shiro_mlops/tasks/types/base.py](src/shiro_mlops/tasks/types/base.py).
- The frontend enforces workspace import boundaries with ESLint: commit `307dea1` "feat(frontend): forbid cross-app and shared-to-app imports with ESLint (#137)".

Prose only:

- "Task types never touch repositories" ([src/shiro_mlops/tasks/types/base.py:1](src/shiro_mlops/tasks/types/base.py); [docs/reference/ml-tasks.md:48](docs/reference/ml-tasks.md)). No test or lint checks `tasks/types/*` imports; a grep for an import-boundary test under `tests/` found none. Ruff does not enable `flake8-tidy-imports` or banned-API rules (`select = ["E","F","I","N","W","UP"]`, [pyproject.toml](pyproject.toml)).
- "`np.load` 呼叫一律明示 `allow_pickle=False`，納入 Code Review 清單" ([docs/adr/0010-persist-models-in-native-non-executable-formats.md:44](docs/adr/0010-persist-models-in-native-non-executable-formats.md)). Only one `np.load` call exists in `src/` ([src/shiro_mlops/tasks/types/unsupervised_reconstruction.py:359](src/shiro_mlops/tasks/types/unsupervised_reconstruction.py)). No check enforces the rule.
- "各任務類型不得自行切分" ([src/shiro_mlops/tasks/types/base.py:59](src/shiro_mlops/tasks/types/base.py)). The split is passed in as `validation_start`. Whether any test asserts that task types honour it, rather than re-splitting, was not verified.

### Inferences

- An AST test (or a ruff `banned-api` / `flake8-tidy-imports` rule) forbidding `shiro_mlops.data` and `sqlalchemy` imports in `tasks/types/` would replace the base.py header prose with an executable invariant. It would follow the `test_src_never_imports_lab` pattern.
- An `np.load` without `allow_pickle=False` check could join `check_conventions.py` or be a test. That would turn an ADR review-checklist line into CI.
- Invariant-named tests already work as executable documentation, which fits the rule's spirit ("names over comments"). The report can cite this as a local pattern to extend: a header comment names the invariant, and a test with the same wording enforces it.

### Gaps

- I did not audit every docstring invariant for a matching test. The examples are a sample.

## Q7. Does the ruff config have docstring (pydocstyle `D`) rules that would conflict with deleting docstrings?

### Takeaway

No. Ruff selects only `E, F, I, N, W, UP` and ignores `E501`, so no rule requires docstrings. No `ERA` rule (commented-out code) or other comment lint is enabled either.

### Cited Findings

- `[tool.ruff.lint] select = ["E", "F", "I", "N", "W", "UP"]`, `ignore = ["E501"]`, `line-length = 100`, `target-version = "py311"` — [pyproject.toml](pyproject.toml) (`[tool.ruff]` and `[tool.ruff.lint]` sections).
- CI runs `uv run ruff check .` and `uv run ruff format --check .` — [.github/workflows/ci.yml:31-34](.github/workflows/ci.yml).
- No `D` rules, no `pydocstyle` or `interrogate` config, and no docstring-coverage tool anywhere in the repo (grep over config files).
- The one active `noqa` in `src/` gives its reason inline: [src/shiro_mlops/tasks/runner.py:63](src/shiro_mlops/tasks/runner.py) `# noqa: N818 - name fixed by the #66 interface design`.

### Inferences

- Nothing in lint config blocks the rule, and nothing currently backs it. If the owner wants mechanical support, ruff's `ERA001` (commented-out code) is a low-risk addition. Selected `D` rules would push toward more docstrings, the opposite direction, so leaving `D` off fits the rule.
- `noqa` comments with a reason are a third comment type the rule should explicitly allow, or treat as why-not comments.

### Gaps

- I did not run ruff with `ERA001` or any `D` rule enabled, so the number of violations each would produce is unknown.
