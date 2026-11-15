# Roadmap challenge, Missions 3 to 8 (strict paper reviewer)

Written 2026-11-15 by Fable, design only. It reads the whole plan through Mission 8 as a reviewer of the
workshop paper would: RQ1 to RQ5, the claims, the baselines, the threats to validity, and what would be rejected.
Read with: `docs/DESIGN.md` section 13 (the research questions), the plans in this folder, and `PROGRESS.md`.
Nothing here is built, and no data was read to write it: every statement about results quotes numbers already in
`PROGRESS.md` or `eval/results/`.

## 1. Goal and method
Goal: find, before more is built, what a strict reviewer would reject, rank it, and put each fix where it
belongs. Method: for each research question, ask (1) what exactly is claimed, (2) against which baseline, (3) on
which data and whether that data could fail the claim, (4) what the free tier and the laptop allow. A finding is
"real" if it changes a claim, a plan or the order of work.

## 2. Findings by severity
"Written into" names the file changed today. "Must change" names a plan that does not exist yet; its
requirement is section 4 of this file and a step in `.project-memory/PLAN.md`.

| # | Severity | Finding | Fix | Where |
|---|---|---|---|---|
| 1 | Critical | **The headline number describes runs that can hardly be buggy.** Real runs come from one template, so they can only carry config-level bugs, and the guard removes most of those. "The expected share of accepted findings that are buggy" will be near 0 by construction. Every non-trivial test of it uses planted bugs. A reviewer will say the quality control was built for a scientist that cannot make the errors it measures. | The paper's claim becomes: *a method for an AI scientist to measure its own reviewer continuously, validated on hidden-truth populations*, with the template limit in the abstract and the limitations. The hidden-truth populations of Mission 4.2 are named as the stand-in for an unconstrained scientist. LLM-written mutants (Mission 6.2) are the first step beyond the catalog and are needed for any wider wording. | must change: the report outline of Mission 8.3 (section 4); decision 1 |
| 2 | Critical | **The findings ledger may be almost empty.** Both real runs were inconclusive, with interval widths of about 0.10 and 0.16 against a `min_effect` of 0.005 (PROGRESS, Known issues). More seeds cannot fix this: under the Nadeau-Bengio correction the interval's half-width is proportional to `t x sqrt(1/n + n_test/n_train)`, and with a test share of 0.25 the second term is 1/3 whatever n is. From 5 to 10 seeds the interval narrows by about 27%, from 5 to 20 by about 36% (arithmetic from the verdict rule, to be confirmed by code). So only effects of several points become decisive. A gate that has nothing decisive to accept shows nothing. | (a) A local check, no reviewer data: the share of decisive verdicts among the clean runs already made, by dataset, metric and model family. (b) With it the student chooses the campaign's questions and grid (comparisons that have real effects, for example class weighting on the imbalanced datasets) and decides `seeds_per_arm`. **Both before pool 3 is built:** the number of seeds is visible in every `results.json`, so changing it later makes real runs differ from the bank's clones. | written into `mission_4_2_hidden_truth.md` (step 1b); new step in PLAN.md; decision 2 |
| 3 | Critical | **RQ3 as written cannot fail.** "Gate on against gate off" compares accepting what passed a filter with accepting everything. Contamination is lower with the gate, always; and a gate that accepts nothing scores best. | RQ3 gets real baselines and a second axis. Baselines: (i) accept everything; (ii) accept what the reviewer passes, with no trust statistics (what AI scientists do today); (iii) a gate on the pooled recall; (iv) Canary's gate (worst class plus leak). Axes: contamination of accepted runs **and** yield (how many true findings get through), over a range of tau. Conditions: a good reviewer, a weak reviewer (one of the local models from RQ1), a drifted one, an adverse bug mix. The gate earns its place only where (ii) fails and (iv) does not. All of it from re-splits of the reviewed bank, so it costs no review. | must change: Mission 5.4's plan (section 4) |
| 4 | Critical | **The tripwires, the guard and the saboteur come from the same heads.** Union recall near 1 on catalogued bugs is expected, not found. RQ2 and RQ3 would be reported before the first held-out shape exists (Mission 6.2 comes after 5.4). | RQ2 is reported in two labelled parts: "known shapes" (available after the bank) and "held-out shapes" (after 6.2). The paper's RQ2 table is not final until the second part exists; the abstract may not quote a union recall without the label. Already the rule of `mission_5_1_tripwires.md` section 7.3; the order of work now respects it. | section 4; PLAN.md |
| 5 | Major | **RQ4 never tests the configuration real campaigns use.** Its supports hold all 20 variants. Then the worst class is B09, its recall is near 0.2, and the worst-class bound sits near 1: it "holds" in every re-split because it says almost nothing. Real campaigns use a support without B09 and without B06 obvious. | A fourth kind of audited population, **D: guarded support** (canaries drawn from the supported variants only, the estimator given the real-run support). It costs no review. And for every kind the **median upper end** of the worst-class bound is reported beside how often it holds. | written into `mission_4_2_hidden_truth.md` (proposed addition); decision 3 |
| 6 | Major | **The bank cannot open the gate it is meant to open.** For real runs B06 counts through its subtle variant only (`mission_4_1_trust.md`, step 3). The bank has 10 canaries per variant, so 10 B06 canaries in the support, and the gate needs 12 per supported class. "Science can start with the gate already able to open" is not true as written. | A B06-subtle top-up of 10 canaries in the same extra batch as the B09 top-up (10 more reviews; the calendar stays at 7 sessions). Without it the first campaign block is a short calibration block, which is honest but must be said. | written into `mission_4_2_hidden_truth.md`, `mission_4_1_trust.md`, `mission_4_4_campaign.md`; decision 4 |
| 7 | Major | **No naive baseline for the estimate.** RQ4 shows Canary's interval against the truth, and nothing a reader could compare it with. | Beside every estimate: the raw flag rate read as prevalence, and "0 if the reviewer passed everything". Their error on the same re-splits is the baseline. | written into `mission_4_2_hidden_truth.md` (proposed addition) |
| 8 | Major | **One reviewer, one provider, one week.** Every Mission 4 number rests on one free-tier snapshot of one model. | (a) All claims carry model, settings and dates (already the rule). (b) RQ1's final table puts every reviewer (three local models, the cloud model, the tripwires, the union) on **one common padded batch**: the bank, after RQ4 is analysed, each local model's first audit under one locked plan; local models cost laptop time only. (c) If the efficiency search finds a second reviewer that clears the bar on its own fresh batch, RQ4 is repeated with it on the bank: a replication across reviewers. | must change: Mission 8.1's plan (section 4); decision 5 |
| 9 | Major | **The jury of Mission 5.2 is obsolete.** It pairs the Skeptic with `phi4-mini`, which RQ1 showed to be at chance. A union with a reviewer that flags almost everything flags almost everything. | Mission 5.2 is built only if a second reviewer has cleared the bar (efficiency search). Otherwise RQ2 compares LLM, tripwires and union, and the report says no second competent reviewer was available at no cost. | section 4; decision 6 |
| 10 | Major | **RQ5 may be a non-problem at this scale.** With 20 arms and blind spots as stark as B06 and B09 (0 of 6 and 1 of 6 on arm L), sampling evenly finds them in a handful of runs; Thompson sampling has little to win. Probing the union with known shapes is pointless (the tripwires are deterministic). Each hardening hint changes the reviewer's prompt, so by Mission 4.3 it starts a new epoch and a full calibration. | Mission 6 needs its own design pass before any build: probes aimed at the LLM alone and at mutants; a simulation first of "adaptive against even sampling" at the affordable number of reviews, with the rule written before it runs; the cost of a new epoch counted for every hint. If the simulated gain is small, RQ5 is reported as that. | must change: Mission 6's plan (section 4) |
| 11 | Major | **"Drift alarms" is more than the chart can do.** Simulated with assumed rates, a recall drop from 0.77 to 0.60 raises an alarm within a week in 0.11 to 0.16 of campaigns (`mission_4_3_drift.md`). CLAUDE.md's list of unique points says the chart watches for reviewer drift. | The claim is worded as that plan words it: identity checks, alarms for total and large changes, a rolling window for slow ones. CLAUDE.md section 3, point 4 is reworded when the student approves. | `mission_4_3_drift.md` section 8 (done); decision 7 |
| 12 | Major | **"Agent" for a nine-row rule table.** | Called a rule-based controller; compared in simulation with two simple controllers (`mission_4_4_campaign.md`). The paper says what is agentic (observe, decide, act on measured trust, replayable) and what is not (no learned policy). | done in that plan |
| 13 | Major | **Novelty has not been checked since the project began,** and the field moves monthly. | `/novelty` once now and again in Mission 8.4. A claim found in prior work is removed from CLAUDE.md's list, not argued around. | next actions; decision 8 |
| 14 | Moderate | **The ledger cannot show that its newest entries were removed** (Known issues). A reviewer of "tamper-evident" will find this in a minute. | A small command that writes the ledger's head hash into a tracked file at every commit, and `ledger verify` compares. One short sitting, before any campaign result is reported. | section 4; PLAN.md |
| 15 | Moderate | **Mutants are LLM-written code, and the sandbox guards against accidents only** (Known issues). | The Mission 6.2 plan starts with the sandbox: no network, a private working folder, a time and memory cap. | section 4 |
| 16 | Moderate | **Reproduction depends on a model that can vanish.** | Every reply is already in the call log. Mission 8 adds a script that rebuilds each table from logs and the ledger with no model call, and a release checklist (keys scrubbed, sealed table released only after the last locked test). | section 4 |
| 17 | Moderate | **DESIGN.md is out of date in sections 2 and 6 to 12,** and six plans each promise to rewrite a part of it. CLAUDE.md still names local Skeptics as the reviewers. | One "sync" sitting after tripwire sitting D rewrites DESIGN.md from the approved plans, and proposes the CLAUDE.md edits for the student's OK. The plans' own "rewrite DESIGN" steps then only check their section. | PLAN.md; decision 9 |
| 18 | Moderate | **The test suite has a 30 s limit and about 22 s used;** every plan adds tests. | Rule for every sitting: new simulations and replays are marked `slow`; a sitting that pushes the default suite over 26 s frees time first (the tripwire plan's rule, extended). | section 4 |
| 19 | Moderate | **Calendar.** The path through Mission 8 is about 35 to 40 sittings and three to four weeks of review days (section 5). | A shorter path to a presentable paper core is offered for the student's choice (section 5). | decision 10 |
| 20 | Minor | RQ7 (humans against the Skeptic) is small and descriptive. | Reported as such; no test. | Mission 7.2 |

## 3. Each research question: what a reviewer would reject, and what would stand
| RQ | Would be rejected as planned | Would stand after the fixes |
|---|---|---|
| RQ1 reviewers' reliability | a table that mixes batches with and without padding; any ranking of models that never saw the same runs | all reviewers on one common padded batch (finding 8); the trivial-feature baseline beside every model, as the ceiling check did |
| RQ2 defense in depth | union recall on catalogued bugs as evidence that tripwires "work"; a jury with a reviewer at chance | LLM, tripwires and union on the same runs, labelled "known shapes"; the held-out part after Mission 6.2; the 2x2 tables of who caught what (`mission_5_1_tripwires.md` section 8) |
| RQ3 the gate | gate on against gate off | four acceptance rules, contamination and yield, four conditions, from re-splits of the bank (finding 3) |
| RQ4 the estimate | cover of re-splits read as cover of campaigns; a bound that is always 1; no baseline | the pass marks from simulated banks (already planned), kind D, the bound's median upper end, the naive baselines (findings 5 and 7) |
| RQ5 probing and hardening | "adaptive finds blind spots faster" with 20 arms and two stark blind spots; a hint judged on canaries it was written from | a simulation-first design; mutants as arms; each hint judged on a fresh batch in a new epoch (finding 10) |

## 4. Requirements for missions that have no plan yet (binding when their plans are written)
- **Mission 5.2 (jury):** only with a second reviewer that cleared the ceiling bar on its own fresh batch. Never
  with a reviewer whose J is not clearly above 0.
- **Mission 5.3 (replication gate):** it tests whether a finding survives new seeds and a new split, not whether
  it is bug-free. Its seeds must be disjoint from run, guard and oracle seeds. Replication runs are local.
- **Mission 5.4 (RQ2, RQ3):** RQ2 in two labelled parts (finding 4), on `ceiling-ext` and `rq4-bank-1`, never on
  `tripwire-test-1` for any LLM. RQ3 as in finding 3, from re-splits of the bank under a locked plan whose pass
  marks come from simulated banks, as RQ4's do. No new review is needed for either.
- **Mission 6 (probes, mutants, hardening):** a design pass first (finding 10). The sandbox is hardened before
  the first LLM-written script runs (finding 15). Mutants enter by a behavioural oracle only (already decided).
  The tripwire version is hash-locked before the first mutant exists (already decided). A hint is a prompt
  change: new epoch, fresh batch, its own lock.
- **Mission 7.1 (Lab Monitor):** every "closed" reason of the gate, the epoch, the support, the worst class and
  the sentence "bugs of the catalogued kinds" are on the Overview page. The canary chart is labelled as a chain
  check, not an LLM chart (`mission_4_3_drift.md`).
- **Mission 8.1 (full evaluations):** RQ1 on the common batch (finding 8); every table rebuilt from logs and
  the ledger by one script with no model call (finding 16).
- **Mission 8.3 (report):** the claim of finding 1; a limitations section that names, at least: one template,
  catalogued bug kinds, one reviewer snapshot, clones of 17 or more bases, simulated detection probabilities for
  drift, rule-based control, what the guard does not cover.
- **Every sitting:** the suite rule of finding 18; no hand-typed number; lock checks before and after while any
  lock is open.
- **Ledger anchor (finding 14):** before the first campaign result is reported.

## 5. The order of work, and a shorter path
The full table is in `PROGRESS.md` (section "Design session 2026-11-15") and `.project-memory/PLAN.md`.
In one line: tripwires C and D; guard sitting 1 and the decisive-share check; trust arithmetic and drift
arithmetic; pool 3 and the bank; the review week (with the guard test, the gate, the campaign loop on a fake
provider and Missions 3.1 and 3.2 built meanwhile, all local); RQ4; the sentinel; the three-day real campaign;
then Missions 5.4, 6, 7, 8.

Where "35 to 40 sittings" comes from (a forecast, counted from the plans): tripwires 3, guard 2, Mission 4.1
2, RQ4 code and analysis 2, Mission 4.3 2, Mission 4.4 3, Missions 3.1 and 3.2 3, the DESIGN sync and the ledger
anchor 2: 19 sittings with a plan. Missions 5.2 to 5.4, 6, 7 and 8 have no plan; at the size of the planned ones
they are about 16 to 20 more. Review days: 7 for the bank, 3 for the campaign, then the efficiency search, RQ5's
reviews and any recalibration.

**A shorter path to a paper core** (finding 19), if time is short: tripwires, guard, Mission 4.1, the bank and
RQ4 with kind D, RQ2 "known shapes" and RQ3 from the bank's re-splits, RQ1 on the common batch, the Overview
page, the report. Missions 4.3 and 4.4 are then shown by their simulations, the fake-provider demo and the
three-day campaign; Missions 3.1, 3.2 and 6 become "further work" except the held-out mutants, without which RQ2
stays "known shapes". This path drops RQ5 and RQ6 from the paper.

## 6. What the project may and may not claim today (for the README and any talk)
**May:** the measured reviewer study (RQ1 and the ceiling check, with their limits); the design of the trust
statistics, the gate, the drift layers and the campaign loop, as designs; simulated operating characteristics,
labelled "assumed rates".
**May not, until measured:** any recall or specificity of the union; any contamination figure; that drift is
detected; that the gate reduces contamination; that the estimate is accurate; that tripwires catch bugs outside
the catalog.

## 7. Decisions (for the student; recommended default first)
1. **The paper's main claim** is the method and its validation on hidden-truth populations, with the template
   limit stated up front, not "how contaminated is our ledger": **yes.**
2. **Before pool 3:** run the local decisive-share check, then fix the campaign's questions and grid and
   `seeds_per_arm` (default: keep 5, because more seeds narrow the interval by about a quarter to a third at
   most; choose comparisons with real effects instead): **yes, check first.**
3. **RQ4 gets kind D (guarded support)** and reports the bound's median upper end: **yes.** Its pass marks are
   simulated before the lock, by the rule already used.
4. **A B06-subtle top-up of 10 canaries** beside the B09 top-up (10 more reviews, still 7 sessions): **yes.**
   Alternative: none, and the first campaign block calibrates B06.
5. **RQ1's final table on one common batch** (the bank, local reviewers under one locked plan, after RQ4):
   **yes.** A second RQ4 with a second reviewer only if the efficiency search finds one.
6. **Mission 5.2 (jury) only with a second competent reviewer;** otherwise dropped from the paper: **yes.**
7. **Reword CLAUDE.md section 3, point 4** (and the matching README line) from "drift alarms" to "identity
   checks, alarms for large changes, a rolling calibration window": **yes, after you approve the Mission 4.3
   plan.**
8. **Run `/novelty` now** (one short session with web search) and again in Mission 8.4: **yes.**
9. **One DESIGN.md sync sitting after tripwire sitting D,** with proposed CLAUDE.md edits for your OK (the
   reviewer is a cloud model plus tripwires; the baseline guard; the jury's status): **yes.**
10. **Path:** the full order, or the shorter paper core of section 5. **Default: the full order through the
    three-day campaign, then decide with `/priorities`,** because everything up to there is on both paths.
