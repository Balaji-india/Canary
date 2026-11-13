# Canary design details

Read this when working on a mission that touches the part described. `CLAUDE.md` has the overview.

## 1. The core idea: lab quality control for an AI scientist

A medical lab doesn't trust its blood analyser blindly. Every batch includes **positive controls** (samples known
to be abnormal), **negative controls** (samples known to be normal), and the lab plots the results on **control
charts** to spot drift. Canary applies the same discipline to an AI scientist's reviewer.

| Lab QC idea | Canary equivalent |
|---|---|
| Positive control | **Canary run**: an experiment with a known planted bug (one of 10 bug classes) |
| Negative control | **Control run**: an experiment from the verified gold template, known clean |
| Sham sample | **Sham run**: cosmetic change only (renamed variable, reordered imports), known clean. Catches a reviewer that flags "anything that looks different" |
| Blinding | The Skeptic never knows a run's type; all code is normalized the same way |
| Sensitivity / specificity | Per-class recall on canaries; specificity on control + sham runs |
| Prevalence estimate | Rogan–Gladen estimate of the real bug rate among the Scientist's own runs |
| Control chart + Westgard rules | Rolling recall chart with drift alarms that tighten the gate |

## 2. Run types inside a campaign

| Type | Share (default) | Ground truth | Used for |
|---|---|---|---|
| real | 50% | unknown | the actual research |
| canary-measure | 15% | buggy, class chosen uniformly | unbiased recall estimates |
| canary-probe | 15% | buggy, class chosen by the adaptive saboteur | finding blind spots (Mission 6) |
| control | 10% | clean (gold template) | specificity |
| sham | 10% | clean (cosmetic diff) | specificity against "diff-flagging" |

Canary, control and sham runs are **cloned from real Scientist hypotheses** (same kind of pre-registration, configs
and results schema) and then sabotaged, kept clean, or cosmetically changed. That way they look like real runs
in every respect except the planted difference. Order is shuffled. Run IDs are random UUIDs. The run type is stored in a separate sealed table that the Skeptic's
code path never reads. Until Mission 6 exists, canary-probe slots are filled as canary-measure.

## 3. Experiments: template-constrained, so they rarely crash

Sakana's AI Scientist had 42% of experiments fail from coding errors. Canary avoids this by design:
- The Scientist proposes a **hypothesis as a config diff**: `control_config` vs `treatment_config` (dataset, model,
  preprocessing, hyperparameters, metric, seeds), plus at most one small, optional code slot.
- `codegen.py` renders a complete Python script from `templates/experiment.py.tmpl` (stdlib `string.Template`).
- `sandbox.py` runs it in a subprocess (own working dir, 120 s timeout, kill on timeout), and the script writes
  `results.json` with a fixed schema: per-seed metrics for control and treatment, the metric name, class balance,
  split sizes, runtime.
- The crash rate is recorded and reported (an easy comparison with the 42% figure).

## 4. The 10 bug classes (`config/bug_classes.yaml`)

Each has an *obvious* and a *subtle* variant (difficulty tier). The Saboteur applies them as AST transforms or
template-variant snippets on the rendered script. Every class must have a unit test proving the bug is present
in the transformed code.

| id | Bug | Subtle variant example |
|---|---|---|
| B01 | Preprocessing leakage | scaler/imputer fitted on the full X before the split |
| B02 | Target leakage feature | adds a feature that is a noisy copy of the label |
| B03 | Evaluate on training data | metric computed on the train split |
| B04 | Tune on test | hyperparameter search or early stopping uses the test set |
| B05 | Seed cherry-picking | reports the best of k seeds instead of the mean |
| B06 | Metric misuse | accuracy only, on an imbalanced dataset |
| B07 | Duplicate rows across split | oversampling before the split, so copies land in both |
| B08 | Label misalignment | y_test shuffled or shifted relative to X_test |
| B09 | Weak baseline | control model given crippled hyperparameters |
| B10 | Easy test subset | hard or minority examples silently dropped from the test set |

LLM-generated mutants (Mission 6) add new variants; each must be validated by a **behavioural oracle only** (its
numbers differ from its clean twin on fixed seeds) before entering the mutant library, **never by a tripwire
firing**: a library selected by the tripwires would hold only tripwire-detectable bugs and could not measure them
(student, 2026-11-13; `docs/plans/mission_5_1_tripwires.md` section 7.3). The tripwire version is hash-locked
before the first mutant is generated. Benign rewrites (numbers equal to the twin's) are kept too, for held-out
specificity.

## 5. Blinding (`blinding.py`)

Before any reviewer sees a run: parse the script with `ast`, strip comments and docstrings, and emit it with
`ast.unparse` (standard library). This removes formatting and comment cues. Results JSON is passed with the same
key order for all runs. A unit test asserts that a control run and a sham run are indistinguishable by length
class and key set.

## 6. Reviewers

- **Skeptic** (single model): sees blinded code + results + the pre-registration. Returns JSON
  `{verdict: "pass"|"flag", bug_class: "B01".."B10"|null, evidence: str, confidence: 0-1}`.
- **Jury** (Mission 5): two Skeptics from different model families; flag if either flags (union) or by agreement
  (configurable). Report both rules.
- **Tripwires** (Mission 5, deterministic, no LLM): AST and data checks, e.g. fit/fit_transform called on X before
  the split (B01), single-feature AUC ≥ 0.99 (B02), metric computed on train variables (B03), test variables
  referenced in a search or early stopping (B04), reported metric equal to the max instead of the mean (B05),
  accuracy-only with class ratio > 3:1 (B06), row-hash overlap between splits (B07), near-chance metric with a
  strong model (B08 heuristic), test size smaller than declared (B10).
- **VRAM rule:** 6 GB fits one model at a time. Queue all audits for model A, run them, then switch to model B.
  Never alternate models per run.

## 7. Trust statistics (`trust.py`)

- Recall per class c: `Beta(1 + caught_c, 1 + missed_c)`, using **canary-measure runs only** (adaptive probe
  canaries would bias the estimate).
- Overall recall Se: the mean over classes (uniform class mix). Also report the worst-class recall.
- Specificity Sp: `Beta(1 + passed_clean, 1 + flagged_clean)` over control + sham runs. Report sham-only
  specificity separately.
- **Prevalence of real bugs (Rogan–Gladen):** with p = the Skeptic's flag rate on real runs,
  `π = (p + Sp − 1) / (Se + Sp − 1)`, clipped to [0, 1]; only valid when Se + Sp > 1 (else report "auditor
  uninformative"). Interval: Monte Carlo, drawing Se, Sp and p from their Beta posteriors (5,000 draws), taking
  the 5th-95th percentiles.
- **Contamination of accepted findings:** `P(bug | passed) = π(1 − Se) / (π(1 − Se) + (1 − π) Sp)`, with an
  interval from the same draws. A worst case uses the lowest class recall.
- Prior art to cite: Rogan & Gladen (1978); LLM-as-a-judge bias correction (arXiv 2511.21140). Canary's
  contribution is generating the calibration set *automatically and continuously* inside the research loop
  (canaries + controls) and using the result to gate what the AI scientist accepts.

## 8. Trust gate (`gate.py`)

A real run that the Skeptic passed is **accepted** only if the 90th percentile of P(bug | passed) ≤ τ (default
0.10). Otherwise it **escalates**: tripwires → replication → human review queue (shown in the dashboard). A
flagged real run goes to the graveyard with cause "flagged: <class>" unless a human overrides. Every decision is
written to the ledger with the trust numbers at that moment.

## 9. Control chart and drift (`trust.py`)

Windows of 20 canary-measure runs. p-chart: center p̄ (running recall), limits p̄ ± k·sqrt(p̄(1 − p̄)/n).
Alarms (Westgard-inspired): one window below the 3σ limit, or two consecutive windows below the 2σ limit. An alarm
tightens τ to 0.05 and makes the campaign agent spend its next runs on canaries until the chart recovers.

## 10. Adaptive saboteur and self-hardening (Mission 6)

- **Probing:** Thompson sampling over (class, tier) arms with `Beta(1 + misses, 1 + catches)`; picks the arm
  with the highest sampled miss rate. Probe canaries never feed the recall estimates in section 7.
- **Mutants:** the Scientist model writes a new variant of a class; it is kept only if the behavioural oracle
  (difference from its clean twin) confirms the bug, never because a tripwire fired (section 4).
- **Blind-spot map:** a heatmap of miss rate by class × tier × reviewer model.
- **Self-hardening:** for the worst blind spot, an LLM drafts one checklist line for the Skeptic prompt. It is
  evaluated on **held-out** canaries (mutants not used to write it) and on controls/shams. Keep the hint only if
  recall improves without specificity dropping by more than 2 points. Log before/after.
- Related prior work to cite: bandit-guided style attacks on LLM judges (BITE, arXiv 2605.26156) target
  *stylistic* bias; Canary probes *methodological* blind spots and uses them to harden the reviewer.

## 11. Scientist, pre-registration, ledger, graveyard, calibration

- **Pre-registration:** JSON `{hypothesis, control_config, treatment_config, metric, direction, min_effect,
  predicted_effect, confidence}`; canonical JSON → SHA-256; stored before the run. The verdict (supported /
  not supported / inconclusive) is computed by code from results vs the locked thresholds, never by an LLM.
- **Ledger:** append-only SQLite table; each entry stores `prev_hash` and its own hash over the canonical
  content (a hash chain). `canary ledger verify` recomputes the chain. Status flow:
  proposed → preregistered → ran → audited → (replicated) → accepted | graveyard | escalated.
- **Graveyard:** failed, null and flagged ideas with a cause of death. Before proposing, the Scientist receives the
  3 most similar graveyard entries (MiniLM embeddings, cosine ≥ 0.75) and must say how its idea differs.
- **Calibration:** Brier score and a reliability diagram over resolved predictions. From Mission 3 on, the Scientist
  sees its own recent calibration summary in the prompt; RQ6 tests whether its Brier score improves.
- **Replication gate (Mission 5):** accepted candidates are re-run with 5 new seeds and a different split (and a
  sibling dataset when the config allows). Status becomes replicated or fragile.

## 12. Campaign agent (`campaign.py`)

The orchestrator is a budgeted agent loop. Each step it observes the state (trust posteriors, drift alarm, open
escalations, the graveyard, the remaining budget) and decides what to do next, writing a one-line rationale to
the trace:
- do science (propose → preregister → run → audit → gate),
- **recalibrate** (spend runs on canaries/controls when the trust interval is too wide or a drift alarm fired),
- replicate a candidate finding,
- harden the Skeptic (Mission 6),
- stop (budget spent or question answered).
Rules decide; the LLMs do proposing and reviewing. The key agentic behaviour to demo: **the agent decides when to
stop doing science and re-check its own checker.**

## 13. Research questions (the evaluation)

| RQ | Question | Measured by |
|---|---|---|
| RQ1 | How reliable are small local LLM reviewers at catching realistic ML-experiment bugs? | recall per class and tier, specificity (controls vs shams), per model |
| RQ2 | Do tripwires and a cross-family jury improve detection? | recall/specificity: LLM only, tripwires only, jury, union |
| RQ3 | Does the trust gate reduce contamination of accepted findings? | campaigns with gate ON vs OFF, known truth via hidden-truth runs |
| RQ4 | Is the Rogan–Gladen estimate accurate? | hidden-truth campaign: secretly plant bugs in a known % of "real" runs; compare π estimate vs truth over several % levels |
| RQ5 | Does adaptive probing find blind spots faster, and does self-hardening help? | runs-to-discover vs uniform; held-out recall and specificity before/after |
| RQ6 | Does calibration feedback improve the Scientist's Brier score? | Brier over time, feedback ON vs OFF |
| RQ7 | Humans vs the Skeptic ("Beat the Skeptic") | small-n comparison, reported descriptively |

Every number in any report comes from `eval/results/*.json` produced by `eval/rq*.py`. Fix seeds, record model
tags and versions, and save raw per-run records so any table can be regenerated.
