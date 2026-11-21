# Methodological validity of the comment-pruning experiment (Opus rewrites, Sonnet reads)

Scope: what the posted 6-condition table (O = today's comments, N = none, A/B/C/D = rewrites under different rules) can and cannot support, with exact statistics and grounding in the LLM-evaluation literature.

Provenance of numbers: all p-values and intervals below were computed in this session with a pure-Python implementation (hypergeometric Fisher, Wilson, Clopper-Pearson, exact McNemar, Newcombe, Holm, Benjamini-Hochberg, exact power by enumeration, Monte Carlo null simulation with seed 20261121), cross-checked against `scipy.stats.fisher_exact`, `boschloo_exact`, `barnard_exact` and `statsmodels` (`proportion_confint`, `mcnemar`); the two agreed to 4 decimals. Script: `/tmp/claude-0/-home-user-shiro-mlops/e14dec42-ff1a-5a59-a447-00ef3cf9c6fb/scratchpad/stats.py` (scratchpad, may be cleared). Network note: arxiv.org and pmc.ncbi.nlm.nih.gov were blocked for full-text fetch in this session, so literature claims were verified against search-result extracts of the primary pages, not full PDFs.

Input table (as posted):

| Metric | O | N | A | B | C | D |
|---|---|---|---|---|---|---|
| Comment chars kept | 11,753 | 0 | 7,794 | 2,930 | 1,545 | 4,196 |
| Chars as % of O (computed) | 100% | 0% | 66.3% | 24.9% | 13.1% | 35.7% |
| Understood what | 94% | 97% | 92% | 86% | 83% | 92% |
| Understood why | 94% | 60% | 96% | 96% | 81% | 98% |
| Trap bugs found | 10/14 | 3/14 | 10/14 | 6/14 | 5/14 | 6/14 |
| Logic bugs found | 12/12 | 12/12 | 12/12 | 11/12 | 12/12 | 12/12 |
| Design conflict noticed | 6/6 | 3/6 | 6/6 | 6/6 | 4/6 | 6/6 |
| Stopped and asked | 0/4 | 0/4 | 1/4 | 2/4 | 0/4 | 4/4 |
| Inter-rewriter κ | — | — | 0.77 | 0.54 | 0.82 | 0.81 |

## Q1. Exact tests, confidence intervals, and multiple-comparison correction

### Takeaway
No single difference in the table survives any standard multiple-comparison correction; only two contrasts reach nominal p < 0.05 (trap bugs N vs O, p = 0.021; stopped-and-asked D vs O, p = 0.029), and if the design is paired (same traps/tasks in every arm, which is almost certain) the "stopped and asked" 4/4 vs 0/4 result cannot reach significance at all (minimum attainable exact McNemar p = 0.125). The only effect likely to be robust is "why"-understanding N 60% vs O 94%, and only if its denominator is ≥ ~48 independent items.

### Cited Findings
- For small n, Brown, Cai & DasGupta recommend the Wilson or equal-tailed Jeffreys interval (Agresti-Coull for larger n) because the textbook Wald interval has erratic coverage; for n > 40 Wilson, Jeffreys and Agresti-Coull are very similar — [Brown, Cai & DasGupta 2001, Statistical Science 16(2):101–133](https://projecteuclid.org/euclid.ss/1009213286)
- Miller recommends a paired-differences test when two conditions are run on the same question list, because pairing removes variance due to question difficulty; the higher the between-condition correlation, the smaller the standard error of the mean difference (he reports correlations of 0.3–0.7 between frontier models on popular evals) — [Miller 2024, "Adding Error Bars to Evals", arXiv:2411.00640](https://arxiv.org/abs/2411.00640); also summarized by Anthropic at [anthropic.com/research/statistical-approach-to-model-evals](https://www.anthropic.com/research/statistical-approach-to-model-evals)
- Miller recommends clustered standard errors when questions come in related groups (e.g. several questions per passage), and found clustered SEs can be more than 3x larger than naive SEs on popular evals — [Miller 2024, arXiv:2411.00640](https://arxiv.org/abs/2411.00640)

### Inferences

#### 1a. Wilson (and Clopper-Pearson) 95% CIs per cell (computed here)

| Metric | Cell | k/n | Point | Wilson 95% CI | Clopper-Pearson 95% CI |
|---|---|---|---|---|---|
| Trap | O, A | 10/14 | 71.4% | [45.4, 88.3] | [41.9, 91.6] |
| Trap | B, D | 6/14 | 42.9% | [21.4, 67.4] | [17.7, 71.1] |
| Trap | C | 5/14 | 35.7% | [16.3, 61.2] | [12.8, 64.9] |
| Trap | N | 3/14 | 21.4% | [7.6, 47.6] | [4.7, 50.8] |
| Logic | O, N, A, C, D | 12/12 | 100% | [75.8, 100] | [73.5, 100] |
| Logic | B | 11/12 | 91.7% | [64.6, 98.5] | [61.5, 99.8] |
| Design conflict | O, A, B, D | 6/6 | 100% | [61.0, 100] | [54.1, 100] |
| Design conflict | C | 4/6 | 66.7% | [30.0, 90.3] | [22.3, 95.7] |
| Design conflict | N | 3/6 | 50.0% | [18.8, 81.2] | [11.8, 88.2] |
| Stopped & asked | O, N, C | 0/4 | 0% | [0, 49.0] | [0, 60.2] |
| Stopped & asked | A | 1/4 | 25% | [4.6, 69.9] | [0.6, 80.6] |
| Stopped & asked | B | 2/4 | 50% | [15.0, 85.0] | [6.8, 93.2] |
| Stopped & asked | D | 4/4 | 100% | [51.0, 100] | [39.8, 100] |

Reading: every Wilson interval for trap bugs spans roughly 40–45 percentage points; the O/A interval [45, 88] overlaps the B/D interval [21, 67]. A 4/4 is compatible with a true asking rate as low as 51%; 0/4 is compatible with up to 49%.

#### 1b. Fisher's exact test, each variant vs O (treats arms as independent samples; computed here)

| Comparison | Fisher two-sided p | One-sided p | Boschloo (unconditional) p | Holm-adj. (20 tests) | BH-adj. (20 tests) |
|---|---|---|---|---|---|
| Trap N 3/14 vs O 10/14 | **0.0213** | 0.0107 | 0.0093 | 0.426 | 0.286 |
| Trap C 5/14 vs O 10/14 | 0.1283 | 0.0642 | — | 1.000 | 0.840 |
| Trap D 6/14 vs O 10/14 (same for B) | 0.2519 | 0.1259 | 0.1437 | 1.000 | 0.840 |
| Trap D 6/14 vs A 10/14 | 0.2519 | 0.1259 | — | — | — |
| Design N 3/6 vs O 6/6 | 0.1818 | 0.0909 | 0.0691 | 1.000 | 0.840 |
| Design C 4/6 vs O 6/6 | 0.4545 | 0.2273 | — | 1.000 | 1.000 |
| Asked D 4/4 vs O 0/4 | **0.0286** | 0.0143 | 0.0078 | 0.543 | 0.286 |
| Asked D 4/4 vs A 1/4 | 0.1429 | 0.0714 | — | — | — |
| Asked B 2/4 vs O 0/4 | 0.4286 | 0.2143 | — | 1.000 | 1.000 |
| Logic B 11/12 vs O 12/12 | 1.000 | 0.500 | — | 1.000 | 1.000 |

(Barnard's test gave 0.0102 for trap N vs O and 0.0078 for asked D vs O, matching Boschloo closely.)

#### 1c. Multiple-comparison thresholds

- 5 variants x 4 count metrics vs O = 20 tests -> Bonferroni alpha = 0.05/20 = 0.0025.
- 5 variants x 6 metrics vs O (adding the two % rows) = 30 tests -> 0.00167.
- All 6 variants x 7 metrics = 42 cells -> 0.00119; all pairwise variant contrasts on the 4 count metrics (15 x 4 = 60) -> 0.00083.
- Even with the more powerful unconditional tests, the smallest p-values (0.0078, 0.0093) are about 3x above the strictest relevant threshold for 20 tests; Holm-adjusted they become ~0.16 and ~0.18. With Benjamini-Hochberg (false discovery rate) both become 0.286. **Nothing survives correction.**
- Caveat: the author did not pre-register which contrasts mattered, so the honest family is "all contrasts one could have highlighted", which makes correction more, not less, necessary.

#### 1d. The design is almost certainly paired, which changes the right test

The same 14 traps, 12 logic bugs, 6 design-conflict items and 4 change tasks were presumably given in every condition. Then the correct test is exact McNemar on the discordant items (found in one condition, missed in the other), and the result depends on the unreported overlap. Computed over every overlap consistent with the marginals:

| Comparison | Possible overlaps (both found) | Exact McNemar p range |
|---|---|---|
| Trap O 10 vs N 3 (n = 14) | 0–3 | 0.0156 (N's 3 are a subset of O's 10) to 0.0923 |
| Trap O 10 vs C 5 | 1–5 | 0.0625 to 0.2668 |
| Trap O 10 vs D 6 | 2–6 | 0.125 (D's 6 subset of O's 10) to 0.388 |
| Design O 6 vs N 3 (n = 6) | 3 only | 0.25 |
| Asked D 4 vs O 0 (n = 4) | 0 only | 0.125 |

Minimum attainable exact McNemar p when all n discordant pairs go one way is 2 x 0.5^n: n = 3 -> 0.25; n = 4 -> 0.125; n = 6 -> 0.031; n = 7 -> 0.0156; n = 14 -> 0.00012. **With 4 tasks, "stopped and asked" can never be significant under a paired analysis, no matter the outcome.** The Fisher p = 0.029 for 4/4 vs 0/4 is only valid if the D and O runs used different, independently sampled tasks.

#### 1e. Effect sizes: what "not significant" does and does not mean (Newcombe hybrid-score 95% CIs, computed here)

| Difference | Point | 95% CI |
|---|---|---|
| Trap O − N | +50.0 pp | [+13.1, +71.8] |
| Trap O − C | +35.7 pp | [−0.8, +61.4] |
| Trap O − D (= A − D) | +28.6 pp | [−7.2, +55.9] |
| Trap O − A | 0.0 pp | [−31.0, +31.0] |
| Design O − N | +50.0 pp | [0.0, +81.2] |
| Asked D − O | +100 pp | [+30.7, +100] |
| Logic O − B | +8.3 pp | [−16.9, +35.4] |

So the data cannot rule out that D loses more than half of trap detections relative to O, nor that A is 31 pp worse (or better) than O. "A matches O" is also weakly supported: absence of a difference is not equivalence.

#### 1f. Power (exact, two-sided Fisher, alpha = 0.05, equal independent arms; computed here)

| True rates | Power at n = 14 | n per arm for 80% power |
|---|---|---|
| 71.4% vs 42.9% (O vs D traps) | 0.20 | 51 |
| 71.4% vs 21.4% (O vs N traps) | 0.64 | 18 |
| 94% vs 60% (why: O vs N) | 0.44 | 27 |
| 94% vs 86% (what: O vs B) | 0.016 | > 200 |

The experiment had about a 1-in-5 chance of detecting a real O-vs-D trap gap of the observed size.

#### 1g. Null simulation (20,000 replicates; computed here)

If O and all 5 variants had the **same** true trap-detection rate, the probability that at least one variant would differ from O by ≥ 4 of 14 traps purely by chance is 0.436 (true rate 71.4%), 0.523 (60%), 0.538 (50%). A 10-vs-6 gap of the kind used to rank D below O/A is therefore a coin-flip event under "no effect". (Probability that at least one of the 5 Fisher tests hits p < 0.05 under the null was 0.067–0.083; Fisher is conservative at this n.)

#### 1h. Percent rows under assumed denominators (Fisher two-sided p, computed here)

| Contrast | n = 10 | n = 20 | n = 30 | n = 50 | n = 100 | n = 200 |
|---|---|---|---|---|---|---|
| why O 94% vs N 60% | 0.303 | 0.0197 | 0.0048 | 8.1e-5 | 7.8e-9 | ~1e-16 |
| why O 94% vs C 81% | 1 | 0.342 | 0.254 | 0.071 | 0.0092 | 0.00012 |
| why O 94% vs D 98% | 1 | 1 | 1 | 0.617 | 0.279 | 0.071 |
| what O 94% vs C 83% | 1 | 0.605 | 0.424 | 0.200 | 0.025 | 0.00083 |
| what O 94% vs B 86% | 1 | 0.605 | 0.671 | 0.318 | 0.097 | 0.012 |
| what O 94% vs N 97% | 1 | 1 | 1 | 1 | 0.498 | 0.227 |

Only "why" N vs O is robust across plausible denominators; it clears the 30-test Bonferroni threshold (0.00167) at n ≈ 50 but not at n = 30. D's "best" 98% "why" score is indistinguishable from O's 94% unless there were hundreds of independent items.

### Gaps
- The post does not report the overlap of found traps across conditions, so the paired p-values can only be given as ranges.
- Whether any condition was run more than once is not stated; all tests above assume a single run per cell.
- Miller's paper also discusses within-question resampling and power analysis; those parts could not be re-verified against the full text in this session (arxiv.org blocked), so they are not cited above.

## Q2. What the percentages and counts likely mean: unknown denominators, single runs, sampling nondeterminism

### Takeaway
The table reports one number per cell with no denominators for the % rows, no run count and no error bars; LLM-agent outputs vary materially between identical runs, so a single run per cell measures one draw from a wide distribution, and with 14 traps a single run at a true 71% rate can land anywhere from 7 to 13.

### Cited Findings
- The LLM eval literature argues evals should be treated as experiments with standard errors computed from the question sample, and recommends reporting error bars — [Miller 2024, arXiv:2411.00640](https://arxiv.org/abs/2411.00640); [Anthropic, "A statistical approach to model evaluations"](https://www.anthropic.com/research/statistical-approach-to-model-evals)
- τ-bench introduced pass^k (probability an agent succeeds on all k independent trials of the same task) because agents are inconsistent across repeated trials: gpt-4o's pass^1 was ~61% on τ-retail and ~35% on τ-airline, and pass^8 on τ-retail fell to ~25% — [Yao, Shinn, Razavi & Narasimhan, τ-bench, arXiv:2406.12045 (ICLR 2025)](https://arxiv.org/abs/2406.12045)
- Formatting-only prompt changes produced accuracy spreads of up to 76 points (LLaMA-2-13B, few-shot); on GPT-3.5 the spread across 320 formats and 53 tasks was up to 56 points (median 6.4); format effects correlate only weakly across models, which undermines comparing conditions under one fixed prompt — [Sclar, Choi, Tsvetkov & Suhr, arXiv:2310.11324 (ICLR 2024)](https://arxiv.org/abs/2310.11324)
- The Agentic Benchmark Checklist found 80% of ten popular agentic benchmarks fail to acknowledge weaknesses in their design or implementation, and none met every reporting criterion — [Zhu et al., "Establishing Best Practices for Building Rigorous Agentic Benchmarks", arXiv:2507.02825](https://arxiv.org/abs/2507.02825)

### Inferences
- **Denominator forensics (computed here).** If each % row came from one shared set of binary-graded items, the smallest denominator consistent with every reported integer percentage is n = 36 for the "what" row (e.g. 34/36 = 94.4%, 35/36 = 97.2%, 33/36 = 91.7%, 31/36 = 86.1%, 30/36 = 83.3%) and n = 47 or 48 for the "why" row; no single n ≤ 89 fits both rows. So either (a) there were ≥ 36 "what" and ≥ 47 "why" questions (e.g. 3 modules x 12 or 16 questions), (b) the numbers are mean rubric/partial-credit scores, or (c) they pool several runs. Each reading changes the inference: under (a) the items are clustered in 3 modules, so the effective sample is much smaller than 36–48 (Miller: clustered SEs can exceed naive ones by >3x); under (b) a judge model is in the loop (see Q3); under (c) the counts rows (x/14 etc.) may also be pooled, which the post would need to say.
- **Single-run spread (computed here, binomial).** For one run on 14 traps, the central 95% range of found-trap counts is 7–13 at a true rate of 71.4%, 5–12 at 60%, 3–11 at 50%. O's 10 and D's 6 are both inside the 50% band; one draw per cell cannot rank them.
- **Sampling nondeterminism is a second variance source on top of item sampling.** Even with fixed traps, re-running Sonnet with the same prompt can change which traps it finds (the τ-bench pass^k decay is the canonical demonstration). Because the rewrites themselves were produced by sampling Opus, there is a third source: a different Opus draw of "variant D" might keep a different 4,196 characters. The κ row shows two rewriters did not fully agree, so the "D" a reader saw is one realization of the rule, not the rule.
- **Logic-bug row is a ceiling.** 12/12 in five of six cells means it cannot discriminate; with all-correct, the Wilson lower bound is 75.8%, so harms of up to ~24 pp in logic review would be invisible. It is still a useful negative control (comment removal did not obviously break local code reading), but not evidence of "no harm".

### Gaps
- No information on temperature, seeds, number of runs, or whether "found" was judged by exact match, test, or a model.
- I found no published run-to-run variance figures specifically for code-review or bug-finding tasks with Claude Sonnet; the τ-bench numbers are for a different model and task family and illustrate the phenomenon, not its magnitude here.

## Q3. Construct validity: trap bugs, who designed what, "stopped and asked", "understood why", and grading

### Takeaway
Several metrics are partly circular or confounded by construction: if trap bugs are violations of facts written in comments, deleting those comments makes the traps undetectable by definition, so the trap row largely measures "how many trap-relevant facts the rewrite retained", which could be checked without any reader model; the same model family wrote the comments, (likely) designed the traps, read the code and possibly graded it.

### Cited Findings
- Construct validity is whether a benchmark measures what it claims to; a systematic review of 445 LLM benchmarks by 29 expert reviewers found recurring problems in how benchmarks define the measured phenomenon, choose tasks and score results that undermine the validity of the claims, and issued eight recommendations plus an operational checklist — [Bean et al., "Measuring what Matters: Construct Validity in LLM Benchmarks", NeurIPS 2025 D&B, arXiv:2511.04703](https://arxiv.org/abs/2511.04703); [NeurIPS proceedings page](https://proceedings.neurips.cc/paper_files/paper/2025/hash/1967e0fc3aa6cbbace562f5cb8e3954e-Abstract-Datasets_and_Benchmarks_Track.html)
- The Agentic Benchmark Checklist defines **task validity** (a task should be solvable only if the agent has the target capability; e.g. a trivial agent passes 38% of τ-bench airline tasks) and **outcome validity** (the grading must correctly indicate success; e.g. incorrect SWE-bench-Verified patches can pass tests); 7 of 10 popular agentic benchmarks violated task validity and 7 violated outcome validity — [Zhu et al., arXiv:2507.02825](https://arxiv.org/abs/2507.02825); [ABC project page](https://uiuc-kang-lab.github.io/agentic-benchmarks)
- LLM evaluators recognize and favor their own generations: GPT-3.5 Turbo, GPT-4 and Llama 2 preferred their own summaries over other LLMs' and humans'; GPT-4 identified its own outputs with 73.5% accuracy out of the box; self-recognition ability correlated linearly with self-preference strength after fine-tuning — [Panickssery, Bowman & Feng, NeurIPS 2024, arXiv:2404.13076](https://arxiv.org/abs/2404.13076)
- LLM-as-a-judge exhibits position bias, verbosity bias and self-enhancement bias; GPT-4 as judge reached >80% agreement with human preferences (similar to human-human agreement), with self-enhancement described as present but modest — [Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", NeurIPS 2023, arXiv:2306.05685](https://arxiv.org/abs/2306.05685)
- Formatting/wording changes can swing LLM behaviour by large margins and the effect differs across models — [Sclar et al., arXiv:2310.11324](https://arxiv.org/abs/2310.11324)

### Inferences
- **Trap-bug circularity.** A "trap" in this setting is most plausibly a change that looks fine locally but violates an invariant or deliberate quirk that is stated in a comment. Then:
  - N (no comments) can only catch traps whose constraint is also inferable from code, names or tests: 3/14. That 3/14 is the "code-alone" baseline, and O's 10/14 means 4 traps were missed even with full comments.
  - For any rewrite, trap detection is bounded above by the number of trap-relevant facts the rewrite kept. A's 10/14 = O suggests A kept all of them; D's 6/14 suggests D dropped about four. This is an **information-retention audit**, measurable deterministically by mapping each trap to the comment lines that document it, before running any reader. The reader-model step adds sampling noise to a quantity that could be counted.
  - If the traps were chosen by looking at O's comments, O is favoured by construction, and rules that delete text are penalized by construction. That is not wrong (it is exactly the risk of pruning), but it should be stated as "what fraction of documented constraints survive", not as "how well agents review".
  - Missing control: traps whose constraint is documented **only** in tests or names, and traps documented nowhere. Without them the experiment cannot show that comments help beyond "contain the answer".
- **Same-family confounds.** Opus (rewriter) and Sonnet (reader) are the same vendor family; comments written in Claude's style may be easier for Claude to use, inflating the value of rewritten comments relative to human-written O. If Opus or the same session also designed the traps or graded the "understood" questions, the self-preference findings (Panickssery et al.) apply: the grader may reward answers echoing its own phrasing. Who designed traps, who wrote questions, and who graded is not stated.
- **"Understood why/what" measures agreement with an answer key, not understanding.** If the key was derived from O's comments, "why" scores are again partly circular (N's 60% shows the key's "why" content lives in comments, which is the expected and genuinely informative result). If an LLM judge scored free-text answers, verbosity and self-enhancement biases (Zheng et al.) could favour longer, comment-echoing answers. The "what" row (N 97%) is the cleanest finding: names, types and code alone sufficed for "what", which supports the rule's premise "names over comments".
- **"Stopped and asked" is a policy measure, not comprehension, and its desirability is undefined.** O noticed 6/6 design conflicts but stopped 0/4 times; D noticed 6/6 and stopped 4/4. The information was apparently available in both; what changed is the framing. Rule text that calls headers inviolable invariants ("天條", "every change must preserve") is imperative language that plausibly pushes the model to halt, i.e. an instruction-following effect of wording, which Sclar et al. show can be large and model-specific. Whether asking is good depends on whether each of the 4 tasks genuinely should have been escalated; with no "should-not-ask" control tasks, 4/4 cannot be distinguished from "D makes the agent ask about everything". A proper metric would report asking precision and recall over tasks labelled in advance as should-ask / should-proceed.
- **Outcome validity of "found".** Whether a review "found" a trap requires judging free-text review comments; partial or vague mentions need a pre-specified rubric. ABC's outcome-validity criterion applies directly.

### Gaps
- The post does not say who designed the traps, the 4 change tasks, or the comprehension questions, nor who graded; the circularity and self-preference concerns are therefore plausible risks, not confirmed defects.
- I found no published study that measures self-preference specifically between Claude Opus as author and Claude Sonnet as reader/grader; the cited evidence is for other model pairs.

## Q4. Interpreting the κ row (inter-rewriter agreement)

### Takeaway
κ measures whether two independent applications of the same rule produce the same keep/delete decisions; A (0.77), C (0.82) and D (0.81) are reproducible enough to be a team standard, while B (0.54) is "moderate" by Landis & Koch but only "weak" by McHugh, signalling an ambiguous rule; without the number of rated units, however, even the B-vs-others gap has wide uncertainty.

### Cited Findings
- Landis & Koch (1977, Biometrics 33:159–174) bands: 0–0.20 slight, 0.21–0.40 fair, 0.41–0.60 moderate, 0.61–0.80 substantial, 0.81–1.00 almost perfect — [Bland, "Assessing agreement using Cohen's kappa"](https://www-users.york.ac.uk/~mb55/intro/kappa4.htm); [Wikipedia: Cohen's kappa](https://en.wikipedia.org/wiki/Cohen%27s_kappa)
- These bands are not universally accepted; Landis & Koch supplied no evidence for them and based them on personal opinion — [Wikipedia: Cohen's kappa](https://en.wikipedia.org/wiki/Cohen%27s_kappa)
- McHugh's stricter table: 0–0.20 none (0–4% of data reliable), 0.21–0.39 minimal (4–15%), 0.40–0.59 weak (15–35%), 0.60–0.79 moderate (35–63%), 0.80–0.90 strong (64–81%), > 0.90 almost perfect (82–100%); the "% reliable" column is κ² (analogous to r²). McHugh argues Cohen's interpretation is too lenient for health research because it implies κ as low as 0.41 might be acceptable — [McHugh 2012, "Interrater reliability: the kappa statistic", Biochemia Medica 22(3):276–282](https://pmc.ncbi.nlm.nih.gov/articles/PMC3900052/); [table](https://pmc.ncbi.nlm.nih.gov/articles/PMC3900052/table/t3-biochem-med-22-3-276-4)
- Kappa paradoxes (Feinstein & Cicchetti 1990): high percent agreement can coexist with low κ when category prevalence is skewed, because chance agreement depends on the marginals; alternatives such as Gwet's AC1 have been proposed — [McCall, "Effect of prevalence on kappa"](https://www.acsu.buffalo.edu/~wdmccall/os512d/KappaBaseRate2.html); [Wikipedia: Cohen's kappa](https://en.wikipedia.org/wiki/Cohen%27s_kappa)

### Inferences
- **Labels per variant:**

| Variant | κ | Landis & Koch | McHugh | κ² ("% reliable", McHugh) |
|---|---|---|---|---|
| A | 0.77 | substantial | moderate | 59% |
| B | 0.54 | moderate | weak | 29% |
| C | 0.82 | almost perfect | strong | 67% |
| D | 0.81 | almost perfect | strong | 66% |

- **What 0.54 means in raw agreement (computed here):** κ = (p_o − p_e)/(1 − p_e). If chance agreement p_e = 0.5 (balanced keep/delete), κ 0.54 implies raw agreement p_o = 77%; if p_e = 0.7, p_o = 86%. So under rule B, two rewriters disagree on roughly 1 in 4 to 1 in 7 comment decisions, versus about 1 in 10 for C/D at the same p_e (κ 0.82 -> p_o 91% at p_e = 0.5).
- **Uncertainty depends on the unreported number of units (computed here, large-sample SE ≈ sqrt(p_o(1−p_o)/(n(1−p_e)²))):** at p_e = 0.5, κ 0.54 has 95% CI ≈ [0.24, 0.84] with 30 units, [0.33, 0.75] with 60, [0.39, 0.69] with 120; κ 0.82 has ≈ [0.62, 1.0], [0.68, 0.96], [0.72, 0.92]. With ~60+ units B is credibly lower than C/D; with ~30 the intervals overlap.
- **Prevalence matters for cross-variant comparison (computed here):** at a fixed 90% raw agreement, κ = 0.80 if 50% of comments are deleted, 0.76 at 70%, 0.61 at 85%, and −0.05 at 95%. C deletes ~87% of characters yet still scores κ 0.82, which, if anything, understates how consistent rule C is. Conversely, κ differences between variants with very different deletion rates partly reflect prevalence, not just rule clarity; reporting raw agreement and AC1 alongside κ would help.
- **Why B's 0.54 suggests an ambiguous rule:** two competent applications of the same text diverging on about a quarter of decisions means the rule leaves judgement calls under-specified (e.g. what counts as "restating the signature"). It also contaminates B's other metrics: B's 6/14 traps and 86% "what" may reflect which of many possible "B" rewrites happened to be sampled.
- **Why reproducibility matters for a team standard:** a comment policy is applied by many people and many agent sessions over time. A rule with κ ≈ 0.5 will produce inconsistent codebases and review disputes; a rule with κ ≈ 0.8 is closer to mechanically checkable. This is a genuine strength of the experiment: very few informal comparisons measure rule reproducibility at all.
- **What κ here probably is:** "two rewriters" are likely two Opus runs (test-retest reliability of model + rule), not two humans; reproducibility among human developers or across different agent models could be lower.

### Gaps
- Unit of analysis (per comment, per line, per character) and number of rated units are not reported, so κ CIs cannot be computed exactly.
- Whether the two rewriters were two Opus runs, two different models, or a human and a model is not stated.

## Q5. Does "D is best" follow? The trade-off the table actually shows

### Takeaway
No: the strict "header + why-not only" rule (whether it is C or D) loses 4–5 of the 10 traps O and A catch, and its one clear advantage ("stopped and asked" 4/4) rests on 4 tasks that cannot reach significance in a paired analysis; the table more directly supports "A is not detectably worse than O while cutting about a third of comment text", and "deleting all comments hurts 'why' understanding and trap detection".

### Cited Findings
- Evaluations that compare conditions should report the uncertainty of the difference, ideally paired, rather than ranking point estimates — [Miller 2024, arXiv:2411.00640](https://arxiv.org/abs/2411.00640)
- Benchmarks should define the phenomenon and justify that scoring reflects it before drawing claims; many published LLM benchmarks fail to — [Bean et al. 2025, arXiv:2511.04703](https://arxiv.org/abs/2511.04703)

### Inferences
- **Which variant is the posted rule?** Not stated. The rule allows only 1–3-line module/class headers plus why-not comments, which reads like the strictest variant. C (13% of chars) fits "strictest" best; D (36%) fits "D is the recommendation". Either way:
  - If C: worst of the comment-keeping variants on what (83%), why (81%), traps (5/14), design conflicts (4/6), asked (0/4). The conclusion would contradict its own data.
  - If D: best on why (98%, not distinguishable from O's 94%) and asked (4/4), but traps 6/14 vs 10/14 for O and A (−28.6 pp, 95% CI [−7.2, +55.9]).
- **Trade-off summary (relative to O):**

| Variant | Chars vs O | Trap vs O | Why vs O | Asked | κ | Plain reading |
|---|---|---|---|---|---|---|
| A | −34% | 0 | +2 pp | 1/4 | 0.77 | No detectable loss on any metric; one-third less text |
| D | −64% | −4 traps | +4 pp | 4/4 | 0.81 | Best "why" and most cautious, but loses ~40% of O's trap catches |
| B | −75% | −4 traps | +2 pp | 2/4 | 0.54 | Loses traps and "what" (86%); least reproducible rule |
| C | −87% | −5 traps | −13 pp | 0/4 | 0.82 | Reproducible but loses most on every comprehension metric |
| N | −100% | −7 traps | −34 pp | 0/4 | — | Only clear harm in the table (why, traps; design 3/6) |

- **Trap bugs are the metric closest to the stated purpose.** The rule's own rationale is to protect invariants and deliberate oddities so that agents do not break them. Trap bugs are exactly "agent breaks an invariant". A rule that loses 4 of 10 such catches while improving "asked" is a value judgement (prefer an agent that stops on 4 change tasks over one that catches 4 more planted invariant violations in review), not a finding.
- **The "why" row and the trap row disagree for D** (98% why, 43% traps). One reconciliation: D kept rationale for the code it kept, but deleted some constraint statements entirely; the questions asked about retained rationale, the traps targeted deleted constraints. That is consistent with the circularity in Q3: each metric measures overlap between what was kept and what that metric probes.
- **What the data can support, honestly stated:** (1) removing all comments clearly harms "why" understanding (if n ≥ ~48) and probably trap detection (p = 0.02 uncorrected); (2) names and code alone sufficed for "what" (N 97%); (3) about a third of current comment text (A's deletions) can be removed with no detectable change in this sample; (4) stricter rules may reduce trap detection, and the sample is too small to tell whether they do; (5) imperative "invariant" framing may change agent stopping behaviour, which deserves its own test.

### Gaps
- The content of rules A–D is not published, so it is unknown what A kept that D dropped; that diff is the most useful artifact for a team decision.
- No cost metric (tokens, latency) is reported, so the benefit side of pruning (smaller context) is not quantified.

## Q6. External validity and what a stronger design would look like

### Takeaway
Three modules from one codebase, one rewriter (Opus), one reader (Sonnet), probably one run per cell: results may not transfer to other repos, languages, models (especially non-Anthropic), human readers, or to comments that rot over time; a stronger design needs many more items and modules, repeated runs, multiple reader families, pre-registered and blinded trap definitions, paired/mixed-effects analysis, and a longitudinal comment-staleness measure.

### Cited Findings
- Prompt-format sensitivity correlates only weakly across models, so a comparison validated on one model may not hold on another — [Sclar et al., arXiv:2310.11324](https://arxiv.org/abs/2310.11324)
- Agents are inconsistent over repeated trials; pass^k (all k trials succeed) is a stricter, reliability-oriented metric — [Yao et al., τ-bench, arXiv:2406.12045](https://arxiv.org/abs/2406.12045)
- Clustered standard errors (questions grouped by shared context) can be >3x naive ones; paired differences reduce variance when conditions share items — [Miller 2024, arXiv:2411.00640](https://arxiv.org/abs/2411.00640)
- Agentic benchmarks should establish task validity and outcome validity and report limitations; ABC also recommends process-based metrics alongside outcome metrics — [Zhu et al., arXiv:2507.02825](https://arxiv.org/abs/2507.02825); [ABC project page](https://uiuc-kang-lab.github.io/agentic-benchmarks)
- Construct-validity checklist: define the phenomenon, justify task selection, justify scoring, report uncertainty — [Bean et al. 2025, arXiv:2511.04703](https://arxiv.org/abs/2511.04703)
- LLM judges should be validated against human labels; GPT-4's agreement with humans (>80%) was established by comparison to human-human agreement — [Zheng et al., arXiv:2306.05685](https://arxiv.org/abs/2306.05685)

### Inferences
Strengths worth crediting (the experiment is better than most informal comparisons):
- Bracketing baselines (O = status quo, N = no comments) make the variants interpretable.
- Multiple outcome types: comprehension (what vs why, separated), review (traps vs logic bugs), and action (design conflict noticed, stopped and asked).
- A logic-bug negative control that should not depend on comments, and does not.
- Planted bugs give ground truth rather than subjective quality ratings.
- A cost axis (characters kept) and a reproducibility axis (inter-rewriter κ) are both reported.
- Results are published in full, including those that do not favour the conclusion (D's 6/14).

Threats to external validity:
- 3 modules, 1 codebase, likely 1 language (the post's context suggests a Python repo), so items are clustered in 3 groups and cluster-robust inference is not feasible with so few clusters.
- 1 reader model (Sonnet) from the same vendor as the rewriter (Opus); 0 non-Anthropic readers; 0 human readers.
- Probably 1 run per cell; 1 sampled rewrite per rule.
- A static snapshot: the main argument against comments in practice is comment rot (comments drifting out of sync with code), which a one-shot experiment cannot observe; the rule's "name the code it protects so it can be re-validated" clause targets exactly that and is untested here.

A stronger design (concrete, sized):
1. **Pre-register** hypotheses, the primary metric (e.g. trap detection), the variant-vs-O contrasts, and the analysis (paired, with correction) before rewriting.
2. **Trap design blind to rewrites and to the rewriter model:** traps written by a different person/model from the comment rewriter, each labelled in advance by where its constraint is documented (comment only / test only / name-type only / nowhere). Report detection per stratum, which separates "comments contain the answer" from "comments help agents reason".
3. **Information-retention audit** first: for each variant, count how many trap-relevant facts survive (deterministic), then measure reader detection conditional on retention.
4. **Sample size:** for a 71% vs 43% difference, ~51 independent traps per arm give 80% power (computed in Q1); a paired design with correlated items needs fewer. Spread traps over ≥ 20–30 modules from ≥ 3 repositories and ≥ 2 languages; analyse with mixed-effects logistic regression (random effects for module and trap) or cluster-robust paired differences.
5. **Repeated runs:** ≥ 5 reader runs per (variant, task) and ≥ 3 independent rewrites per rule; report mean ± SE and pass^k-style consistency.
6. **Multiple reader models**, including at least one non-Anthropic model and one smaller model, to test whether gains are Claude-specific.
7. **Blinded grading:** graders (human or model) do not see which variant produced an answer; use deterministic checks where possible; if an LLM judge is used, use a different family from the rewriter and validate it against human labels on a subset.
8. **"Stop and ask" with controls:** include should-proceed tasks, label tasks in advance, report asking precision/recall; vary the wording of header comments (imperative "must" vs descriptive) to isolate framing effects.
9. **Rule reproducibility:** report units, raw agreement, κ with CI, and AC1; include human developers applying the rule.
10. **Longitudinal rot:** replay real commit history (or simulated edits) over each variant and measure how many comments become stale or misleading, and whether stale comments cause more trap misses than no comments.
11. **Cost:** report tokens and time per task, so the benefit of shorter context is weighed against detection loss.

### Gaps
- I did not find a published controlled study on how comment density or style affects LLM coding agents that could serve as an external replication; other researchers on this project may cover that literature.
- The exact repository and modules used are not identified, so representativeness cannot be assessed.

## Q7. Published methodology for using LLMs as experimental subjects

### Takeaway
There is a growing critique of using LLMs as stand-ins for human participants (validate against humans for every new application; small wording changes produce divergent responses; models differ sharply on novel items); here the LLM is the actual target user, so the "substitute for humans" critique applies only if conclusions are extended to human developers, while the benchmark-design and eval-statistics literatures (construct validity, ABC, error bars, pass^k, LLM-judge bias) apply directly.

### Cited Findings
- Schröder et al. argue LLMs do not simulate human psychology and should be treated as useful but fundamentally unreliable tools that must be validated against human responses for each new application; slight wording changes that correspond to large meaning changes produced notable LLM–human discrepancies, and different LLMs responded very differently to novel items — [Schröder et al. 2025, "Large Language Models Do Not Simulate Human Psychology", arXiv:2508.06950](https://arxiv.org/abs/2508.06950)
- A 2024 AI & Society commentary responding to Dillion et al. argues LLMs are unlikely to supplant human research participants in any significant way, in part because, as exemplary text processors, they do not reproduce how people misread or struggle with test items — [Harding et al. 2024, "AI language models cannot replace human research participants" (PhilArchive)](https://philarchive.org/archive/HARALM-4)
- Benchmark construct validity review and recommendations (445 benchmarks, 8 recommendations, checklist) — [Bean et al. 2025, arXiv:2511.04703](https://arxiv.org/abs/2511.04703)
- Agentic benchmark checklist (task validity, outcome validity, reporting) — [Zhu et al., arXiv:2507.02825](https://arxiv.org/abs/2507.02825)
- Statistical treatment of evals (CLT SEs, clustering, paired differences) — [Miller 2024, arXiv:2411.00640](https://arxiv.org/abs/2411.00640)
- LLM-as-judge bias and self-preference — [Zheng et al., arXiv:2306.05685](https://arxiv.org/abs/2306.05685); [Panickssery et al., arXiv:2404.13076](https://arxiv.org/abs/2404.13076)

### Inferences
- **Two different questions are mixed in the post.** (1) "What comment style helps Claude-based agents on this codebase?" — the LLM is the population of interest, and the right methodology is benchmark/eval design. (2) "What should the team's comment standard be?" — that also involves human maintainers, where the LLM-as-participant critique applies: an LLM reading comments is "an exemplary text processor" that may not skim, forget or misread the way people do, so a comment that is redundant for Sonnet may still help a human, and vice versa.
- **Wording sensitivity is the shared lesson.** Both the psychology critique (Schröder et al.) and the prompt-format literature (Sclar et al.) show that small wording changes can move LLM behaviour a lot. In this experiment the treatment is wording (comment text), so effects of *framing* (e.g. "inviolable" invariants) and effects of *information content* are confounded unless varied separately.
- **Applicable checklist for this experiment** (synthesizing the cited guidance): define the construct (e.g. "agent avoids breaking documented invariants"); justify that traps sample that construct and are not trivially solvable or unsolvable by construction (task validity); verify that "found" is graded correctly (outcome validity); pair conditions on the same items and report SEs/CIs with clustering; repeat runs; use independent, validated graders; report limitations.

### Gaps
- I found no methodology paper specifically on using LLM coding agents as subjects for software-engineering documentation experiments; the guidance above is transferred from general LLM benchmark and LLM-as-participant literatures.
- Full texts of the cited arXiv papers could not be fetched in this session (arxiv.org blocked); claims were limited to what search extracts of the primary pages confirmed.
