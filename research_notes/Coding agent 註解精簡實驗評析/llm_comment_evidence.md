# Empirical evidence on how source-code comments affect LLMs and LLM coding agents

How to read these notes. arxiv.org and aclanthology.org could not be reached from this research session (DNS blocked), so no paper's full text was opened. Every finding below comes from search-engine result pages: abstracts, snippets and summaries from arXiv, ACM, NeurIPS proceedings, alphaXiv and similar mirrors. Exact numbers are reported only when a result page showed them, and each one is tagged with where it came from. Treat per-model breakdowns and table values as **not checked against the paper**. Rigor tags used: **[peer-reviewed]**, **[preprint]**, **[blog/anecdotal]**, **[vendor docs]**.

## Q1. Ablation and perturbation studies: what happens to LLM understanding, bug detection, repair and generation when comments are removed or corrupted?

### Takeaway
For comprehension-style tasks on small units of code (unit-test generation, multiple-choice QA, output prediction), removing comments has little effect, while wrong comments hurt a lot. That matches the post's finding that "what" survives without comments. The picture changes for bug fixing and security review. Comments, including ones that describe what the implementation does, raised bug-fix accuracy by up to 3×, and stripping comments lowered detection rates for weaker models. So "comments are unnecessary" holds per task and per model, not universally.

### Cited Findings
- **Macke & Doyle (MITRE), "Testing the Effect of Code Documentation on LLM Code Understanding"** [peer-reviewed, Findings of NAACL 2024; arXiv Apr 2024].
  - Setup: GPT-3.5 and GPT-4 generate unit tests for all 164 HumanEval ground-truth solutions. Documentation conditions varied: no docstring, original comments, partial, and incorrect/random.
  - Conclusion: "incorrect" documentation "can greatly hinder code understanding, while incomplete or missing documentation does not seem to significantly affect an LLM's ability to understand code". Having comments "did not significantly increase" understanding.
  - Numbers: the random-comment condition gave the lowest success rates, 22.1% for GPT-3.5 and 68.1% for GPT-4. The authors caution that results may depend on training data and may not transfer to non-OpenAI models.
  - Sources: [arXiv 2404.03114](https://arxiv.org/abs/2404.03114); [ACL Anthology PDF](https://aclanthology.org/2024.findings-naacl.66.pdf).
- **"Impact of Comments on LLM Comprehension of Legacy Code"** [preprint, Jun 2025; the authors call the findings "preliminary"].
  - Setup: multiple-choice QA on one IBM z/OS assembler module, varying how many comments there are and how accurate they are.
  - Results: "minor inaccuracies in comments have negligible effects on LLM comprehension, while major inaccuracies significantly degrade understanding". A search summary gives about 12% degradation.
  - The Pith third-party review says accurate comments raise comprehension, and it questions whether quiz scores measure real comprehension.
  - Sources: [arXiv 2506.11007](https://arxiv.org/abs/2506.11007); [Pith review](https://pith.science/paper/2506.11007).
- **"On the Impact of Code Comments for Automated Bug-Fixing: An Empirical Study"** [preprint, Jan 2026].
  - Setup: two LLM families, with comments present or absent in all training × inference combinations. Methods that lacked comments got LLM-generated ones.
  - Results:
    - Comments raised bug-fix accuracy "by up to threefold" when present in both training and testing.
    - Models trained without comments still improved when comments were added at inference.
    - Interpretability analysis: comments "describing method implementation" were especially useful.
    - Comments generated from the buggy code did not help and could mislead.
    - A supplementary experiment suggests the benefit holds on newer and larger LLMs.
  - Caveat: this is a fine-tuning setup on (likely) smaller models, not a frontier agent reading a repository.
  - Sources: [arXiv 2601.23059](https://arxiv.org/abs/2601.23059); [bytez summary](https://bytez.com/docs/arxiv/2601.23059/paper).
- **Thornton, "Can Adversarial Code Comments Fool AI Security Reviewers?" / "LLM Code Reviewers Are Harder to Fool Than You Think"** [preprint, Feb 2026].
  - Setup: 8 frontier models (5 commercial, 3 open), 9,366 trials, plus 4,646 defense trials.
  - Manipulative comments had "small, statistically non-significant effects on detection accuracy". Complex adversarial strategies did no better than simple ones.
  - "Comment stripping, the 'obvious' defense, actually degraded detection for weaker models" because it removed useful context.
  - SAST cross-referencing was the best defense, reaching 96.9% detection.
  - The same comment manipulation reaches 75–100% attack success in code *generation* contexts.
  - Sources: [arXiv 2602.16741](https://arxiv.org/html/2602.16741v1); [awesomepapers summary](https://awesomepapers.io/cybersecurity/papers/2602.16741).
- **CodeCrash** [peer-reviewed, NeurIPS 2025; arXiv Apr 2025].
  - Setup: 1,279 CRUXEval and LiveCodeBench output-prediction questions, 17 LLMs. Perturbations include comments that contradict the code and misleading print statements.
  - Misleading comment and statement perturbations reduce Pass@1 under direct inference. Chain-of-thought only partly mitigates this.
  - Telling models to ignore comments left Pass@1 close to the uninstructed result: "LLMs still incorporate NL cues into their inference".
  - Purely structural perturbations cost only 1.63 pp overall.
  - Plausible-but-wrong hints caused "Reasoning Collapse" in reasoning models, with 2–3× more tokens for QwQ-32B.
  - A blog claims a 23.2% average drop (13.8% with CoT). That figure is unverified against the paper's tables.
  - Sources: [NeurIPS paper](https://proceedings.neurips.cc/paper_files/paper/2025/file/aec5e2847c5ae90f939ab786774856cc-Paper-Conference.pdf); [arXiv 2504.14119](https://arxiv.org/html/2504.14119v3).
- **TREAT** [preprint, Oct 2025]: in its robustness component (which reuses CodeCrash-style perturbations), misleading comments caused the largest performance drop, 20.0%. — [arXiv 2510.17163](https://arxiv.org/pdf/2510.17163)
- **"How Accurately Do LLMs Understand Code?"** [preprint, Apr 2025]: misleading comments hurt fault localization more than misleading variable names. The search summary reports 24.55% average Phase II accuracy; the exact condition was not verified. — [arXiv 2504.04372](https://arxiv.org/html/2504.04372v2)
- **CodeJudgeBench** [peer-reviewed, ACL 2026]: every LLM-as-judge model was unstable and sensitive to response ordering, variable naming and misleading comments. This bears on any experiment that uses an LLM to grade another LLM's review. — [ACL Anthology](https://aclanthology.org/2026.acl-long.888/)
- **Imani et al., "Inside Out: Uncovering How Comment Internalization Steers LLMs for Better or Worse"** [preprint, Dec 2025].
  - Method: concept-level interpretability. The authors switch a "comment" concept on or off in the model's representation space.
  - Performance shifts ran from −90% to +67%, and were "model-specific and task-dependent". Code completion, translation and refinement were tested; translation sometimes improved with the comment concept suppressed.
  - Across 10 SE tasks, summarization activated comment concepts most strongly and completion least.
  - Sources: [arXiv 2512.16790](https://arxiv.org/abs/2512.16790); [X summary by Rohan Paul](https://x.com/rohanpaul_ai/status/2003252210679923028).
- **Related work cited by the legacy-code paper (citing text only):** "Imani et al. found that excluding comments enhanced the accuracy of LLM-generated code summaries", and "Nikiema et al. showed no statistically significant effect of comment inclusion". A separate 2025 result says that for "8 out of 13 LLMs tested", description accuracy was higher with comments. I could not retrieve the underlying Imani and Nikiema papers. — [search summary of 2506.11007 related work](https://arxiv.org/html/2506.11007); [search summary listing the 8/13 result](https://arxiv.org/html/2504.10557v1)
- **Le et al., "When Names Disappear"** [preprint, Oct 2025]. This study obfuscates identifier names rather than comments, which bears on how much "what" survives once the natural-language cues are gone.
  - Removing names hurt intent-level summarization. Without names, models fell back to line-by-line descriptions instead of intent-level ones.
  - Execution prediction also dropped, which the authors attribute to memorized name patterns.
  - A secondary blog reports GPT-4o's ClassEval class-summary score falling from 87.3% to 58.7%.
  - Sources: [arXiv 2510.03178](https://arxiv.org/pdf/2510.03178); [emergentmind summary](https://www.emergentmind.com/papers/2510.03178).
- **MANGO, "Comments as Natural Logic Pivots"** [peer-reviewed, Findings of ACL 2024].
  - This is about the model *generating* comments as a reasoning scaffold during code generation, not about existing comments in a repository.
  - On HumanEval/MBPP with StarCoder and WizardCoder (3B–7B), comment contrastive training plus logical-comment decoding improved pass rates. It was more robust than CoT, especially for small models.
  - Sources: [arXiv 2404.07549](https://arxiv.org/abs/2404.07549); [ACL Anthology](https://aclanthology.org/2024.findings-acl.420).

### Inferences
- The post's "N (no comments) still understands *what* at 97%" fits Macke & Doyle (missing docs: no significant effect) and CodeCrash (strong models are robust to non-NL perturbations). Note that both studies use small, self-contained functions with **intact identifier names**. "When Names Disappear" suggests that names, not comments, carry much of the "what". The post's rules keep names and delete comments that restate them, which is consistent with this.
- The post's "logic bugs found 11–12/12 in every variant" fits Thornton's frontier-model result: comment manipulation barely moved detection. It contrasts with the 2601.23059 bug-fixing study, where comments mattered a lot, but that study fine-tuned smaller models. The likely reconciliation is that comment dependence shrinks as model capability grows, at least for ordinary logic bugs. This is an inference; no study tests it directly across model scales on the same task.
- The 2601.23059 finding that **implementation-describing** comments help bug fixing most is a partial counterweight to "delete everything that restates the next line". At least for weaker or fine-tuned models, some "what" comments carry signal for repair. Whether a frontier model like Sonnet benefits is not established.
- "Inside Out" (task-dependent effects, from −90% to +67%) gives a mechanistic reason to expect the post's pattern, where different variants win on different metrics (D best on *why* and *ask*, O/A best on trap bugs). Comments do not have a single direction of effect.

### Gaps
- No study found that ablates **comment categories** (header/invariant vs. why-not vs. restating) one at a time and measures an agent on a multi-file repository. That is exactly the post's design.
- Per-model numbers for CodeCrash, TREAT, "When Comments Mislead" and 2601.23059 could not be verified (full texts unreachable). Whether 2601.23059 tested frontier models is unknown.
- The underlying Imani et al. (summarization) and Nikiema et al. papers could not be retrieved; they appear only as citations.
- ReCode (Wang et al., ACL 2023), a robustness benchmark with docstring perturbations, is recalled from prior knowledge but was **not verified** in this session, so no numbers are reported for it.

## Q2. Do wrong or outdated comments mislead LLMs more than correct comments help them? (the "comment rot" argument)

### Takeaway
Yes, and this is the most consistent finding in the literature. Across code understanding, output prediction, completion and vulnerability review, incorrect or stale comments cause large drops. Correct comments give small or non-significant gains on comprehension tasks. Telling the model to ignore or distrust comments does not reliably neutralize them. This supports cutting low-value comments to shrink the rot surface. It also means the few comments that remain ("天條" invariants, why-not notes) are high-leverage claims the model will believe even when the code says otherwise.

### Cited Findings
- **Incorrect vs. missing documentation:** for GPT-3.5 and GPT-4, missing or partial documentation made no significant difference, but random/incorrect documentation gave the lowest success rates (22.1% for GPT-3.5, 68.1% for GPT-4). — [Macke & Doyle, arXiv 2404.03114](https://arxiv.org/abs/2404.03114)
- **Legacy code:** minor inaccuracies were negligible, while major inaccuracies "significantly degrade understanding" (about 12% per search summary). — [arXiv 2506.11007](https://arxiv.org/abs/2506.11007)
- **Xia, Huang, Chen & Zheng (Sun Yat-sen University), "When Comments Mislead: An Empirical Study of Outdated Comments in LLM-Based Code Completion"** [peer-reviewed, ASE 2026, pp. 362–373].
  - Outdated comments bias generated code toward the **old implementation**. The output looks plausible overall but fails where the implementation has changed.
  - Severity depends on factors such as signature length and task complexity.
  - The authors call comments "strong but unreliable context signals".
  - Pass-rate numbers were not retrievable.
  - Sources: [DOI 10.1145/3832783.3834359](https://doi.org/10.1145/3832783.3834359); [ASE 2026 program](https://conf.researchr.org/details/ase-2026/ase-2026-research-track/29/When-Comments-Mislead-An-Empirical-Study-of-Outdated-Comments-in-LLM-Based-Code-Comp).
- **"Comment Traps: How Defective Commented-Out Code Augment Defects in AI-Assisted Code Generation"** [peer-reviewed, ACM journal]: defective commented-out code in context pushed GitHub Copilot and Cursor to generate defective code at rates up to 58.17%. — [ACM DOI 10.1145/3797102](https://dl.acm.org/doi/10.1145/3797102)
- **Instructions to ignore comments don't work:**
  - CodeCrash: an "ignore comments" prompt left Pass@1 close to the uninstructed result. — [arXiv 2504.14119](https://arxiv.org/html/2504.14119v3)
  - ALIBI: "even when explicitly told to treat comments as untrusted, LLMs often failed to do so". — [ALIBI, arXiv 2607.24964](https://arxiv.org/abs/2607.24964)
- **ALIBI (Wu & Nita-Rotaru), "Adaptive Agentic Attacks on LLM-Based Vulnerability Detectors via Adversarial Code Comments"** [preprint, Jul 2026].
  - LLM vulnerability detectors are "highly vulnerable to adaptive adversarial code comments".
  - The paper argues that removing all comments is **not** a viable defense, because prior work shows comments improve LLM-based vulnerability detection. It proposes filtering out comments that cannot be verified from the code.
  - Source: [arXiv 2607.24964](https://arxiv.org/html/2607.24964).
  - Contrast with Thornton (Feb 2026): simple manipulative comments had small, non-significant effects on 8 frontier models. The gap probably reflects attacker strength (adaptive vs. static). — [arXiv 2602.16741](https://arxiv.org/html/2602.16741v1)
- **"Words Speak Louder Than Code"** [preprint, Jun 2026].
  - Setup: code held fixed, surrounding natural-language context varied; 8 LLMs, 3 languages. This is context around the code rather than in-code comments.
  - Every model's verdicts shifted. Mean effects: framing 33.2%, anchoring 23.5%, halo 18.4%.
  - Bugs that need semantic reasoning were 1.3–2× more affected than pattern-detectable ones.
  - A black-box attack suppressed up to 97% of previously detected vulnerabilities.
  - Sources: [arXiv 2606.30587](https://arxiv.org/abs/2606.30587); [Pith review](https://pith.science/paper/2606.30587), which notes possible confounding with general prompt changes.
- **Comment rot is real in practice:**
  - A 2019 large-scale study documents that developers often fail to update comments when they change code. — [Wen et al. 2019, ICPC](https://www.inf.usi.ch/lanza/Downloads/Wen2019a.pdf)
  - An LLM plus program-analysis detector found 160 code–comment inconsistencies in 13 open-source projects, 23 of which developers confirmed and fixed. — [FSE 2024 companion, DOI 10.1145/3663529.3664458](https://dl.acm.org/doi/10.1145/3663529.3664458)
  - ReCite found 869 stale function references in Linux kernel v6.18-rc1 comments; 50 of 75 submitted patches were accepted. — [arXiv 2608.03734](https://arxiv.org/pdf/2608.03734)
  - LLM comment updaters themselves introduce inconsistencies through "erroneous updates or direct copies". — [LLMCup, arXiv 2507.08671](https://arxiv.org/pdf/2507.08671)
- **Practitioner synthesis** [blog/anecdotal]: "wrong comments are way worse than no comments", and the task-completion effect of comments was "basically a wash". — [Terminal Wars, "Should You Write Code Comments for Your AI?"](https://terminalwars.com/posts/should-you-comment-code-for-ai/)

### Inferences
- The harm asymmetry (wrong comments ≫ missing comments) supports the post's core move of deleting comments that restate names, signatures or the next line. Such comments add little for strong models and are the most likely to go stale as code changes.
- The same evidence cuts the other way for what is kept. The post keeps a small number of high-authority comments (invariants marked as never to be violated, why-not rationale). "When Comments Mislead" and CodeCrash show that models anchor on comments and won't detach even when told to. So a stale "天條" comment is likely **worse** than a stale restating comment: the model will defend the old invariant against the code. The post's approach needs a maintenance mechanism, such as review checks or tests that pin each documented invariant. Thornton's SAST cross-referencing and ALIBI's "filter comments not verifiable from code" are analogous verification ideas.
- The post's experiment used only correct, freshly rewritten comments in every variant. It therefore measured the *benefit* side of comments, not the *rot* side. A complete test of "fewer comments is safer" would need variants with deliberately stale comments.

### Gaps
- No study found that measures stale **design-rationale or invariant** comments specifically, as opposed to function-level docstrings or behavior comments, and their effect on agents.
- Effect sizes for "When Comments Mislead" (ASE 2026) and the 1.5× bug-introduction link sometimes attributed to code–comment inconsistency (arXiv 2409.10781, "Investigating the Impact of Code Comment Inconsistency on Bug Introducing") were not retrievable or verified. Only the title of the latter was seen.

## Q3. Can LLMs and agents infer design rationale, intent and invariants from code alone, or do they need documentation?

### Takeaway
The available evidence says LLMs recover structure and "what changed" reasonably well but are weak at recovering the "why". Rationale-extraction studies consistently find outputs that are implementation-focused and omit the rationale. Vendor guidance also says explaining the reason behind an instruction improves Claude's behavior. This supports the post's finding that the *why* score falls without comments (94% → 60%). No study was found that directly tests whether agents can detect **invariant violations** with and without invariant comments, which is the post's "trap bugs".

### Cited Findings
- **"Can LLMs Extract Architectural Design Decisions from Source Code Commits?"** [preprint, Sep 2026].
  - Setup: 4 LLMs, 30 developer-written architectural design decisions (ADDs).
  - LLMs recover architectural information from commits "to a moderate extent" (BERT-F1 > 0.81 for all four), and few-shot prompting helps.
  - But the generated ADDs are "often too implementation-focused and leave out the rationale behind the change".
  - The authors suggest combining issue trackers, code reviews and design documents to supply the missing context.
  - Sources: [arXiv 2609.03721](https://arxiv.org/abs/2609.03721); [Moonlight review](https://www.themoonlight.io/en/review/can-llms-extract-architectural-design-decisions-from-source-code-commits-a-preliminary-exploratory-study).
- **"Using LLMs in Generating Design Rationale for Software Architecture Decisions"** [preprint, Apr 2025].
  - Setup: 5 LLMs, 100 architecture items drawn from Stack Overflow, GitHub issues and discussions (text artifacts, not code).
  - Zero-shot design-rationale generation averaged precision 0.278, recall 0.627, F1 0.381.
  - Source: [arXiv 2504.20781](https://arxiv.org/abs/2504.20781).
- **Amalfitano et al., "Automated Software Architecture Design Recovery from Source Code Using LLMs"** [peer-reviewed, Springer LNCS 2026]: LLMs help identify structural and stylistic elements but "struggle with complex abstractions such as class relationships and fine-grained design patterns". — [Springer](https://link.springer.com/chapter/10.1007/978-3-032-02138-0_5)
- **Without names, intent collapses to line-by-line description:** when identifiers are removed, summaries fall back from intent-level to line-by-line. — ["When Names Disappear", arXiv 2510.03178](https://arxiv.org/pdf/2510.03178)
- **Anthropic prompting docs** [vendor docs]: giving Claude "context or motivation behind your instructions", such as why a behavior matters, "can help Claude better understand your goals and deliver more targeted responses". The docs' example contrasts a bare "NEVER use ellipses" with the reasoned version (output is read by a text-to-speech engine). I found no Anthropic benchmark that quantifies this. — [Claude prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices)
- **Evaluating AGENTS.md** (see Q4): context files are useful "for specifying non-standard coding practices", while repository overviews were not helpful. — [Gloaguen et al., arXiv 2602.11988](https://arxiv.org/abs/2602.11988)

### Inferences
- Results from three directions agree:
  - Rationale recovery from commits and code omits the *why*.
  - Agents ignore or don't benefit from overviews (*what*) but do benefit from non-standard conventions (*why* or *must*).
  - Vendor guidance says motivated instructions work better.

  Together these support the post's split: *what* comes from code, *why* must be written down. The post's N variant (why: 60%) is consistent with this literature.
- The post's D result (why 98% but trap bugs only 6/14) suggests that knowing the global *why* is not the same as catching a local violation. The "trap" probably needs a guard comment **at the site** where the invariant can be broken. This matches 2601.23059's finding (Q1) that comments located at and describing the implementation are the ones that help bug fixing. It is an inference, not tested in the literature.

### Gaps
- No study found that measures LLM or agent detection of violated *documented* invariants (or "Chesterton's fence" code) with and without the invariant comment.
- arXiv 2604.10345 ("Recovering Fine-Grained Code Change Rationale from Multiple Software Artifacts") looked directly relevant, but only its reference list was retrievable.
- No work found that compares, for the same codebase, rationale placed in in-code comments vs. ADRs vs. AGENTS.md for agent outcomes.

## Q4. Agent-era and industry evidence: context files (AGENTS.md/CLAUDE.md) and vendor guidance on what documentation agents need, including in-code comments

### Takeaway
The best 2026 evidence (ETH Zurich) finds that repository-level context files do **not** reliably improve SWE-bench-style success and add about 20% cost. LLM-generated files slightly hurt; developer-written files give a small gain on one benchmark. Instructions in these files are followed, overviews are not useful, and non-standard practices are where they help. An efficiency study finds AGENTS.md cuts runtime and output tokens with comparable completion. Vendor guidance converges on "document what can't be inferred from code". No first-party vendor guidance specifically on in-code comments *for agents* was found.

### Cited Findings
- **Gloaguen et al. (ETH Zurich SRI Lab), "Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?"** [preprint, Feb 2026].
  - LLM-generated context files cut average resolution by 0.5% on SWE-bench Lite and 2% on AGENTbench, and raised inference cost by more than 20%.
  - Developer-written files gave "marginal improvements (average 4% increase on AGENTBENCH)" but up to 19% more cost.
  - With context files, agents spent 14–22% more reasoning tokens and took 2–4 extra steps.
  - Instructions in context files "are well followed", but repository overviews "are not helpful"; the files are useful "for specifying non-standard coding practices".
  - Setup: the developer-context benchmark (called CTXBench in the arXiv version, AGENTbench in coverage) has 138 instances from 12 repositories.
  - One summary's GPT-4o example on SWE-bench Lite: 33.5% with no file, 32% with an LLM-generated file, 29.6% with a developer-written file. That example conflicts with other passages, so check the tables.
  - Sources: [arXiv 2602.11988](https://arxiv.org/abs/2602.11988); [ETH SRI page](https://www.sri.inf.ethz.ch/publications/gloaguen2026agentsmd); [DAIR.AI write-up](https://academy.dair.ai/blog/agents-md-evaluation).
- **Lulla et al., "On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents"** [preprint, Jan 2026].
  - Setup: 10 repositories, 124 PRs.
  - With AGENTS.md, median runtime dropped 28.64% and output tokens 16.58%, "while maintaining a comparable task completion behavior".
  - Sources: [arXiv 2601.20404](https://arxiv.org/abs/2601.20404); [CatalyzeX mirror](https://www.catalyzex.com/author/Jai%20Lal%20Lulla).
  - A practitioner case study reports 30–41% token reductions on 3 tasks [blog/anecdotal]. — [AAIF blog](https://aaif.io/blog/devex-for-your-agents-how-agents-md-cut-token-usage-and-cost)
- **Voria, Kashiwa, Catolino & Palomba, "Do They Do as They Are Told?"** [preprint, Nov 2026]: agents follow context-file guidance "more often than not", but adherence is bimodal. Some instructions are followed consistently and others never, and this varies by instruction category and by agent. — [arXiv 2611.13709](https://arxiv.org/abs/2611.13709)
- **"Do Coding Agents Follow AGENTS.md? The Effect of Policy Wording on Instruction Compliance"** [preprint, Nov 2026]: exists, but findings were not retrieved. — [arXiv 2611.04367](https://arxiv.org/pdf/2611.04367)
- **288-run context-file ablation with Codex CLI** [blog/anecdotal, Aug 2026]: reports that context-injection strategy "does not measurably move correctness" but affects efficiency. — [codex.danielvaughan.com](https://codex.danielvaughan.com/2026/08/06/do-context-files-help-coding-agents-agents-md-ablation-study-codex-cli-correctness-vs-efficiency/)
- **Unverified claim:** a blog attributes to Anthropic a +7.0 pp SWE-bench Verified gain from AGENTS.md files (54.3% → 61.3%). No primary Anthropic source was found; treat it as unverified. (Seen only in search-result summaries; no primary URL available.)
- **Anthropic Claude Code best practices** [vendor docs]: the official page states there is "no required format for CLAUDE.md files". — [Anthropic Engineering](https://www.anthropic.com/engineering/claude-code-best-practices)
- **Third-party restatements of Anthropic's CLAUDE.md guidance** [blog; attribution to Anthropic unverified]:
  - Include "architecture boundaries that are hard to infer from the code".
  - A test for whether a line belongs: "Lines whose absence the agent cannot notice."
  - "Comments only when the intent is genuinely non-obvious. The code should explain the what; comments explain the why."
  - "if your agent leaves too many comments throughout the code, mention it in the file."
  - Sources: [munderdiffl.in](https://munderdiffl.in/blog/claude-md-best-practices/); [max.nardit.com](https://max.nardit.com/articles/claude-md-best-practices); [Dometrain](https://dometrain.com/blog/creating-the-perfect-claudemd-for-claude-code/).
- **Anthropic prompting docs** [vendor docs]: explaining the motivation behind an instruction helps Claude target its behavior (see Q3). — [Claude prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices)

### Inferences
- The context-file literature has the same shape as the post's comment findings. Descriptive material (overviews = *what*) adds tokens without improving success, while non-inferable constraints (non-standard practices = *why* or *must*) help and are followed. That is indirect but consistent support for keeping only invariant and why-not comments.
- The ETH cost finding (14–22% more reasoning tokens, 2–4 more steps) suggests that more natural-language context is not free for agents. This weakly supports trimming restating comments for efficiency, though in-code comments were not tested.
- Adherence to context files is bimodal (Voria et al.), so "天條" rules may be honored inconsistently depending on wording and category. That argues for backing key invariants with tests or checks, not comments alone.

### Gaps
- No peer-reviewed or vendor study was found on the effect of **in-code comment density** (as opposed to AGENTS.md/CLAUDE.md) on agent success.
- No first-party OpenAI Codex, GitHub Copilot or Google guidance specifically about in-code comments for agents was retrieved.
- Recalled but not verified in this session: early-2025 Claude Code system prompts reportedly told the model not to add comments unless asked. No verifiable primary URL was found, so it is not cited.
- Two documentation-practice studies (arXiv 2608.20195 "From Agent Behaviour to Agent-Friendly Documentation"; arXiv 2611.02383 "Toward an Evidence-Based Template for Agent Instruction Files") surfaced only as titles or reference lists; their findings are unknown.

## Q5. Do agents stop and ask clarifying questions instead of proceeding, and what elicits it?

### Takeaway
By default, coding agents tend to assume rather than ask, and they are poor at telling well-specified tasks from underspecified ones unless prompted explicitly to consider asking. When they do ask, performance recovers substantially. Dedicated uncertainty-aware scaffolds come close to full-information performance. No study ties **in-code comments or documented constraints** to clarification behavior. The post's result (variant D "stopped and asked" 4/4, others 0–2/4) is novel but unreplicated.

### Cited Findings
- **Vijayvargiya et al., "Ambig-SWE: Interactive Agents to Overcome Underspecificity in Software Engineering"** [preprint Feb 2025; a secondary summary says ICLR 2026].
  - Models "consistently struggled to detect underspecification without explicit prompting".
  - Interacting with a simulated user recovered key information, with gains of up to 74% over non-interactive settings. This is a peak figure for Claude Sonnet 3.5 on synthetic underspecification; another summary says up to 80% of the lost performance was recovered.
  - Claude Sonnet 3.5 (v1) reached its best accuracy, 84%, at separating well-specified from underspecified tasks under "Moderate Encouragement". Claude Sonnet 4 (v3) did best under "Strong Encouragement".
  - Claude models asked about 3.80–4.03 questions after exploring the codebase first, reaching information gain comparable to DeepSeek and Qwen, which asked 4.57–6.02.
  - Sources: [arXiv 2502.13069](https://arxiv.org/html/2502.13069v3); [AgentPatterns summary](https://www.agentpatterns.ai/patterns/agent-design/interactive-clarification-underspecified-tasks/).
- **Edwards et al., "Ask or Assume? Uncertainty-Aware Clarification-Seeking in Coding Agents"** [peer-reviewed, Findings of EMNLP 2026; arXiv Mar 2026].
  - The multi-agent scaffold UA-Multi scored 69.40% on an underspecified SWE-bench Verified variant, vs. 70.80% with the full issue.
  - It is "well-calibrated": it asks more on harder tasks and refrains on easier ones. Detecting underspecification is separated from executing code.
  - Sources: [arXiv 2603.26233](https://arxiv.org/abs/2603.26233); [ACL Anthology](https://aclanthology.org/2026.findings-emnlp.15/); [GitHub](https://github.com/nedwards99/ask-or-assume).
- **Other work:** "Asking What Matters: Reward-Driven Clarification for SE Tasks" (arXiv 2604.14624) and ICAE-Bench (arXiv 2607.21217) extend clarification evaluation, to reward-trained questioning and to whole-repository builds respectively. Their findings were not retrieved. — [arXiv 2604.14624](https://arxiv.org/pdf/2604.14624); [arXiv 2607.21217](https://arxiv.org/pdf/2607.21217)

### Inferences
- The literature says asking is elicited mainly by **explicit permission or encouragement in the prompt** and by **detecting a gap between the task and what is known**. A plausible mechanism for the post's D result: D's comments state constraints explicitly and perhaps say when to escalate. That turns an implicit conflict ("this request violates a design decision") into a detectable gap, which then triggers asking. This is a hypothesis; the post's 4 scenarios are too few to separate the effect of the comment content from the wording of the D rules.
- Ambig-SWE shows the best encouragement level changed between Sonnet 3.5 and Sonnet 4. Elicitation is therefore model-version-sensitive, and a D-style effect measured on one Sonnet version may not carry over.

### Gaps
- No study found that manipulates code comments or in-repo documented constraints and measures whether agents halt or ask.
- No measured default "ask rate" for Claude Sonnet under a no-encouragement setup was found.

## Q6. Has anyone run experiments like the post's (comment density or rules vs. agent performance)? How does the evidence line up with the post's specific findings?

### Takeaway
No rigorous study replicating the post's design was found: multi-variant comment rewriting × agent read/modify/review × trap bugs, design conflicts and asking. The closest are comment-ablation studies on function-level benchmarks (Q1), context-file ablations (Q4) and blog syntheses. One practitioner synthesis states that "nobody has actually proven it for the specific case of an AI agent exploring and editing a real codebase". On direction, the literature mostly agrees with the post: *what* without comments is fine, *why* needs text, wrong comments are dangerous. It adds two caveats: comments can help bug fixing and detection, especially for weaker models, and the surviving comments become high-risk if they go stale.

### Cited Findings
- **Practitioner synthesis** [blog/anecdotal]:
  - Pretraining on commented code yields better models, but that "does not show that adding comments to your own project improves an already-trained agent's output".
  - For task completion, the effect was "basically a wash", and "wrong comments are way worse than no comments".
  - "nobody has actually proven it for the specific case of an AI agent exploring and editing a real codebase".
  - Source: [Terminal Wars](https://terminalwars.com/posts/should-you-comment-code-for-ai/).
- **Search for a matching experiment:** a targeted search for 2025–2026 blog posts or preprints measuring comment density vs. agent performance found none. Results were dominated by studies of PR review comments, which measure something different, e.g. comments per PR rising 38.6% after agent adoption. — [Forkast summary of Harvard working paper](https://forkast.news/ai-coding-agents-write-30-more-code-and-resolve-zero-additional-issues-harvard-study-finds/)
- **Grader sensitivity:** LLM judges are sensitive to misleading comments and variable naming. — [CodeJudgeBench, ACL 2026](https://aclanthology.org/2026.acl-long.888/)
- **Mapping each of the post's findings to the closest evidence:**

| Post finding | Closest evidence | Verdict |
|---|---|---|
| N: understands *what* 97% | Missing docs have no significant effect ([Macke & Doyle](https://arxiv.org/abs/2404.03114)); structural perturbations cost 1.63 pp ([CodeCrash](https://arxiv.org/html/2504.14119v3)) | Supports. Note these studies keep names, and names carry intent ([When Names Disappear](https://arxiv.org/pdf/2510.03178)) |
| N: *why* falls to 60% (vs. 94%) | Rationale omitted when recovered from code and commits ([2609.03721](https://arxiv.org/abs/2609.03721)); low design-rationale F1 ([2504.20781](https://arxiv.org/abs/2504.20781)); context files help with non-standard practices ([2602.11988](https://arxiv.org/abs/2602.11988)) | Supports (indirect) |
| N: trap bugs 3/14 (vs. 10/14) | Comments up to 3× bug-fix accuracy ([2601.23059](https://arxiv.org/abs/2601.23059)); stripping comments hurts weaker models' detection ([Thornton](https://arxiv.org/html/2602.16741v1)) | Supports direction; no invariant-specific study |
| Logic bugs 11–12/12 in all variants | Frontier detection robust to comment changes ([Thornton](https://arxiv.org/html/2602.16741v1)); reasoning models above 90% baseline ([CodeCrash](https://arxiv.org/html/2504.14119v3)) | Consistent |
| D: *why* 98%, conflicts 6/6, asked 4/4, but traps 6/14 | Motivated instructions help ([Anthropic docs](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices)); asking needs explicit elicitation ([Ambig-SWE](https://arxiv.org/html/2502.13069v3)); implementation-local comments help bug fixing most ([2601.23059](https://arxiv.org/abs/2601.23059)) | Plausible; trap drop fits "global why ≠ local guard" |
| Implicit claim: fewer comments means less rot risk | Wrong comments hurt far more than missing ones ([Macke & Doyle](https://arxiv.org/abs/2404.03114), [When Comments Mislead](https://doi.org/10.1145/3832783.3834359)); "ignore comments" instructions fail ([CodeCrash](https://arxiv.org/html/2504.14119v3), [ALIBI](https://arxiv.org/abs/2607.24964)) | Supports trimming; warns that the surviving "天條" comments are high-impact if stale |

### Inferences
- **Rigor of the post's experiment relative to the literature:**
  - Sample sizes are small: 14 traps, 6 conflicts, 4 ask scenarios, 12 logic bugs. Variance across runs is not reported.
  - One model family wrote the variants (Opus) and another read them (Sonnet). If Opus also designed the traps or graded the results, there is a risk of circularity and LLM-judge bias ([CodeJudgeBench](https://aclanthology.org/2026.acl-long.888/)).
  - Results like "4/4 vs. 0–2/4" are within the range expected from noise at that n.
  - Published studies (Macke & Doyle, CodeCrash, Thornton) use hundreds to thousands of items.
- **What the post adds beyond the literature:** it is the only evidence found that targets *categories* of comments (invariant/why-not vs. restating) at module scale with agent-style tasks (modify, review, design conflict, ask). Its direction aligns with the published evidence, so it is a credible **hypothesis generator**. It is not confirmation.
- **The strongest caution from the literature:** the post varied only correct comments. Its claim that comments can be cut safely is strongest for the deleted restating comments. The kept invariant comments are exactly where stale-comment harm (Q2) would bite hardest.

### Gaps
- No preprint, talk or blog post was found that replicates the post's comment-rule variants, or any similar multi-variant comment study on agents.
- No data on how results transfer across model versions (e.g., Sonnet 4.x vs. later) for comment-related effects. Most comment-ablation studies tested GPT-3.5/GPT-4-era or 3B–7B models.
