# Canary progress log

Claude updates this at the end of every mission. If a mission stops early, write "stopped at: …" under it.

## Missions
**M1 Foundations**
- [x] 1.1 Setup and doctor
  - `python -m canary.cli doctor`: Doctor: all OK (Python 3.12.10 in venv, 11 packages, 3 role models, 9 datasets).
  - `pytest -q`: 15 passed. All 3 role models answered a real test prompt, fully on the GPU.
- [x] 1.2 Template, codegen, sandbox
  - `run-config baseline.yaml`: ok, valid results.json (control f1 0.9551, treatment f1 0.9447, 5 seeds). `run-config broken.yaml`: crash recorded (exit code 1, InvalidParameterError).
  - `pytest -q`: 64 passed. One-off smoke test: 19 of 19 runs ok across all 9 datasets, 7 models and 4 metrics.
- [x] 1.3 LLM wrapper (roles, JSON, cache, model queue)
  - `llm-smoke`: all OK. Valid JSON live from `qwen3:4b` (8.3 s), `gemma3:4b` (29.1 s) and `phi4-mini` (9.1 s), then all 3 repeats from the cache (0.0 s).
  - `pytest -q`: 118 passed. One-off real-sized review prompt (1324-1604 tokens): valid JSON and 100% GPU on all 3 models.
- [x] 1.4 Scientist, pre-registration, verdict, hash-chained ledger
  - `science --hypotheses 2`: 2 locked, run and verdicted (both inconclusive). `ledger verify`: OK (9 entries, including 3 from an earlier run that crashed).
  - After a manual verdict edit on a copy: `[FAIL] entry 3: content does not match its hash`, exit 1; real ledger still OK. `pytest -q`: 181 passed.
- [x] 1.5 Blinding and Skeptic
  - `audit`: 2 stored (both flag B01, both false alarms on clean scripts), 1 crashed run sent to the graveyard with no results to review, 0 failed. `ledger verify`: OK (12 entries).
  - `pytest -q`: 220 passed, including the test that fails if `skeptic.py` or `blinding.py` imports anything off their allowlist.

**M2 Controls and trust**
- [x] 2.1 Saboteur: 10 classes × 2 tiers
  - Each of the 20 variants has an oracle that watches the running script: false on the clean script, true on the sabotaged one.
  - `sabotage-check` on 6 real configs (6 datasets, 6 models, 4 metrics): 114 of 120 variants ran with 0 failures; 6 B06 variants were correctly refused as not applicable. After the realism pass: 95 harmful, 17 harmless, 2 unmeasured (see Saboteur effect sizes). `pytest -q`: 360 passed (includes the coach hook tests).
- [x] 2.2 Controls, shams, sealed run-type table
  - `controls-check` on `baseline.yaml` and `imbalanced.yaml`: all OK, 8 of 8 checks each. Sham numbers equal the control's; both scripts have 84 blinded lines (4753 vs 4836 characters on baseline); same result keys and run-folder files.
  - `pytest -q`: 434 passed in 28 s, including the import-chain test and a spy showing a real audit never opens the sealed file. `ledger verify`: OK (12 entries).
- [x] 2.3 Trust statistics
  - `trust --demo` (synthetic outcomes through the real join): 3 of 10 gives Beta(4, 8), mean 0.333; 8 of 10 gives Beta(9, 3), mean 0.750; specificity 0.833 controls, 0.667 shams, 0.773 combined. Real `trust`: no sealed table yet, so no real trust numbers exist until 2.4.
  - `pytest -q`: 464 passed in 28 s, with Beta values checked against hand-computed ones. `ledger verify`: OK (12 entries).
- [x] 2.4 Run mixer, calibrate command, RQ1
  - `calibrate --runs 180 --batch rq1-full`, `python -m eval.rq1 --batch rq1-full`: 180 reviewed, 0 failed audits, 0 crashes, 10 of 10 classes. Flagged 180 of 180, naming B01 every time: any-flag recall 100 of 100 (chance 1.00), right-type 10 of 100 (chance 0.10), specificity 0 of 80, Youden's J observed 0.000.
  - `pytest -q`: 500 passed in 30 s (at the limit). `ledger verify`: OK (852 entries). Results in `eval/results/rq1_skeptic_a.json`, figures in `eval/figures/`.

**M3 Memory and calibration**
- [ ] 3.1 Graveyard with similarity check
- [ ] 3.2 Brier, reliability diagram, calibration feedback
  - Both designed 2026-11-15 (`docs/plans/mission_3_1_3_2_memory_calibration.md`), not built. Local only; they
    block nothing in Mission 4.

**M4 How much should we trust our findings?**
- [ ] 4.1 Prevalence, contamination, trust gate
  - **Requirement (student, 2026-11-09):** real Scientist runs must get the same padding and decoy treatment as
    calibration runs (`canary/padding.py`, `canary/saboteur/decoys.py`, decoys in the canaries' proportions), or
    measured trust (recall, specificity, contamination) may not transfer to them. Check it with the length gate on
    real runs mixed with calibration runs before any gate decision uses calibration numbers.
  - Designed 2026-11-15 (`docs/plans/mission_4_1_trust.md`). **Sitting 1 built 2026-11-20** (steps 1-4, 6: estimate,
    support, union, `eval/rq4_power.py`); sitting 2 (gate, real-run padding, ledger decisions) not built. Needs the baseline guard
    (`docs/plans/b09_proposal_guard.md`; sitting 1 built and wired 2026-11-20, sitting 2 (the measurement) not done)
    before any real finding can be auto-accepted.
- [ ] 4.2 Hidden-truth validation (RQ4)
  - Designed 2026-11-15 (`docs/plans/mission_4_2_hidden_truth.md`), not built, not locked.
- [ ] 4.3 Control chart and drift alarms
  - Designed 2026-11-15 (`docs/plans/mission_4_3_drift.md`), not built.
- [ ] 4.4 Campaign agent loop
  - Designed 2026-11-15 (`docs/plans/mission_4_4_campaign.md`), not built.

**M5 Defense in depth**
- [x] 5.1 Tripwires (step 11, the wiring, remains as the plan's follow-up before Mission 4.1 uses tripwires)
  - **Step 10, 2026-11-19 (student's window), locked test PASSED** on `tripwire-test-1` (360 fresh runs, 17 pool-2
    bases, known shapes): chain-class fired recall 170/170 (Beta 90% lower bound 0.983, bar 0.90), specificity 159/160
    (lower bound 0.971, bar 0.95); the one flag a sham whose run timed out. B09 0/20, not covered (by design).
    `ceiling-ext` reported only. Result files committed `b28e722`; the freeze ended there. Plan section 11 items 1-5
    hold (item 2 from 2026-11-18: no code changed since, `git diff` against the tag empty).
  - Designed 2026-11-13 (`docs/plans/mission_5_1_tripwires.md`), decisions approved the same day.
  - **Sitting A built 2026-11-14 (plan steps 0-2):** test-suite room, `canary/probe.py` + `canary/replay.py` proven
    transparent (go), pair arithmetic in `canary/tripwires.py`.
  - **Sitting B built 2026-11-14 (plan steps 3-4):** checks S1, S2, K0, K1, K2, K5, `run_tripwires`,
    `python -m canary.tripwires`; guard tests.
  - **Sitting C built 2026-11-16 (plan steps 5-7):** K3, K4, K6, L1, the verdict with all ten checks, advisory A1,
    `python -m eval.tripwires_dev`. The dev loop on the three batches, the locked test (sitting D) and step 11 remain.
  - **Sitting D 2026-11-18 (plan steps 8-9):** step 8 dev loop on 3 batches (0 false alarms on 140 clean runs, 260/260
    replays reproduced, every miss a B09 canary, no fix). Step 9 **LOCKED**: `docs/plans/tripwire_test.md` +
    `.sha256` (6b07fe92...), commit `172bf95`, tag `tripwire-test-1-lock` (pushed 2026-11-18). Checks:
    `eval.tripwires_test --check` "Tripwire lock check: OK"; `--git-check` "Line endings: OK"; `eval.ceiling_lock
    --check` "Lock check: OK"; `pytest -q` 851 passed (19-20 s); `pytest -m slow` 264 passed, 3 skipped.
    Step 10 done 2026-11-19 (above). Step 11 (wiring) built 2026-11-19: part 1 `canary/tripwire_ledger.py`, part 2
    `canary.cli tripwires` after amendment 1 of both locked plans (lock checks at the lock tags). The real-ledger write
    was done 2026-11-20 in the student's window (440 records under `tripwire_v1`; ledger 3592 entries); the
    DESIGN.md text moves to the sync sitting (roadmap decision 9).
- [ ] 5.2 Skeptic B and jury
- [ ] 5.3 Replication gate
- [ ] 5.4 RQ2 and RQ3

**M6 Adaptive saboteur and self-hardening**
- [ ] 6.1 Thompson-sampling probes
- [ ] 6.2 LLM mutants with oracle validation
- [ ] 6.3 Blind-spot map
- [ ] 6.4 Self-hardening and RQ5

**M7 Lab Monitor and the game**
- [ ] 7.1 Dashboard pages
- [ ] 7.2 Beat the Skeptic

**M8 Results and write-up**
- [ ] 8.1 Full evaluation runs
- [ ] 8.2 Figures
- [ ] 8.3 Report, README, architecture, demo script, viva prep
- [ ] 8.4 Novelty re-check

**M9 Stretch:** novelty auditor · more domains · cloud Scientist · tree search

## In progress
**Current focus:** the build order's earliest open row: row 5, the decisive-share check (PLAN step 19), then row 6
(4.3 sitting 1) and row 8 (4.3 steps 4-5, before the RQ4 lock), then row 9 (RQ4 bank, pool 3 with the guard on).

**Stopped at:** Mission 4.1 sitting 1 is built (steps 1-4 and 6, 2026-11-20, Opus; entry below), with the guard
follow-ups. The gate itself (step 5), real runs with padding and decoys (step 7) and the ledger decisions (step 8) are
sitting 2. Nothing written to the real ledger (3592 entries); nothing pushed.

**Earlier the same day (Fable session 1, design only):** three build plans written, challenged and committed:
the baseline guard for B09 (`docs/plans/b09_proposal_guard.md`), Mission 4.1 with the union reviewer
(`docs/plans/mission_4_1_trust.md`) and Mission 4.2 / RQ4 (`docs/plans/mission_4_2_hidden_truth.md`). Each has a
build order, tests per step, "done when", traps, and a short list of decisions whose defaults apply unless the
student changes them. Section "Design session 2026-11-15" below has the summary and the build order across all
plans. No code in `canary/` or `eval/` changed; `pytest` was not run because nothing it covers changed. Mission 5.1
sittings A and B are done; sitting C is next. The ceiling files stay frozen until the tripwire test on
`ceiling-ext` is done. Mission 2.4 is the last mission complete.

## Design session 2, 2026-11-15 (Fable): Missions 4.3, 4.4, 3.1 and 3.2, roadmap challenge
Design only. Four simulations (`docs/plans/sims/drift_chart_sim.py`, `campaign_policy_sim.py`,
`scientist_test_sim.py`, JSON beside each) use **assumed** rates; each script was committed before its first run
with its rules in the docstring; Opus rebuilds each as tested code and re-runs it with measured rates.

**1. Mission 4.3, drift (`mission_4_3_drift.md`).** Three layers: identity checks on every call (server model,
tripwire and library versions, a cache key that carries the model identity); charts with exact Beta-binomial
limits at Westgard's sigma levels (rules R1, R2 and a cumulative R3); a rolling calibration window (the most recent
24 canaries per supported class and 120 clean runs). Everything belongs to a calibration epoch; epochs are never
pooled. The sentinel is a fixed set of already-reviewed runs asked again with the cache bypassed, chosen by code
from run type and class, never from replies.
- By the rule fixed before the simulation: **60 sentinel runs, 20 a day** (31% of a day's calls).
- Simulated: the LLM flagging everything is seen on day 1; passing everything within 2 review days in 0.97 to
  1.00 of campaigns; a recall drop from 0.77 to 0.60 within a week in only 0.11 to 0.16. **The charts see large
  changes, not moderate ones**; the rolling window covers the slow ones for the union.
- Under the lazy union the fresh canary chart cannot see the LLM lose recall; only the sentinel can.
- DESIGN section 9's normal-approximation limits alarm falsely about every 48 windows at recall 0.97.
- An alarm: pause auto-accept, hold the real runs accepted in the alarm's evidence window, recalibrate in a new
  epoch, re-open at tau 0.05 until 3 in-control slices.

**2. Mission 4.4, campaign loop (`mission_4_4_campaign.md`).** One block per review day in ten resumable phases;
a pure rule table decides the action (stop, wait, sentinel, recalibrate on drift, finish reviews, recalibrate when
calibration is thin or too uncertain, science). "Too uncertain" is the zero-flag test: would the gate open if 60
real runs were all passed? No LLM chooses an action. The daily-limit stop prints resume times in IST. Every
decision is a trace line whose hash is in the ledger, and `replay` re-derives it.
- Simulated: all five checks fixed before the run pass; from the bank about 30 real runs a day reach review; from
  a cold start two calibration blocks come first.
- The real proof: a 3-day cold-start campaign in the student's window (about 195 calls).

**3. Missions 3.1 and 3.2 (`mission_3_1_3_2_memory_calibration.md`).** Similarity by an exact idea key first, text
cosine second with a threshold set by a percentile rule and judged once on pool 3's pairs. Brier score with its
three parts, resolved for every finished real run. RQ6: 8 paired chains of 20 per arm (rule's choice). The
Scientist's narrow proposals: prompt v2 (shuffled lists, coverage table) judged on 72 fresh proposals per arm;
fallback is the focus grid. **Pool 3 is built before any Scientist prompt change;** every switch stays off in
campaigns until its test passed and RQ4 is analysed. All of it is local: no cloud call.

**4. Roadmap challenge (`roadmap_challenge_2026-11-15.md`).** 20 findings. The ones that change the order of work:
- The findings ledger may be almost empty: both real runs were inconclusive, and more seeds narrow the interval
  by about 27% at 10 seeds and 36% at 20 (never more than about 44%). **A local decisive-share check and the
  `seeds_per_arm` decision come before pool 3.**
- RQ3 as "gate on against off" cannot fail: it needs four acceptance rules, contamination and yield.
- RQ4 never tests the support real campaigns use: **kind D** proposed (no extra review).
- The bank has 10 B06-subtle canaries, the gate needs 12: **a top-up of 10** proposed (10 reviews).
- The jury with `phi4-mini` is obsolete; Mission 6 needs a design pass before any build.
- **Second read, 2026-11-16 (section 2a of that file, findings 21 to 29).** Every number and claim was checked
  against the plans and this file; nothing contradicts an approved decision. What changed: (1) RQ3 uses
  re-splits of the same bank as RQ4, so **its plan is locked before `python -m eval.rq4` runs** (new decision
  11; rows 16 and 18 below); (2) the second naive baseline is the Rogan-Gladen point formula, as the Mission 4.2
  plan says, and decision 3 now asks for the baselines; (3) the seeds figure above (it said "a quarter to a
  third at most"); (4) decision 2 keeps question q1 and the pool's grid by default, and another grid is an
  amendment to the Mission 4.2 plan before pool 3; (5) the decisive-share check covers at most 35 comparisons
  and reads pool-1 batches and real runs only until sitting D; (6) the ledger anchor checks that the anchored
  hash is still in the chain, and edits no frozen file; (7) the shorter path differs from the full one in row
  15 before the campaign; (8) decision 5 says that the common batch brings `llama3.1:8b` back as a measured row.

**Decisions waiting for the student (recommended defaults in each file's last section):** Mission 4.3: 9;
Mission 4.4: 6; Missions 3.1 and 3.2: 8; roadmap: 11 (34 in all). The ones that gate the next builds: roadmap 2
(check before pool 3), 3 (kind D), 4 (B06 top-up); Mission 4.3 decision 1 (sentinel size) and 8 (identity before
the RQ4 lock). None changes anything in Mission 5.1 sittings C or D.

## Design session 2026-11-15 (Fable): baseline guard, Mission 4.1, Mission 4.2
Design only. The simulations are design tools with **assumed** reviewer rates
(`docs/plans/sims/trust_design_sim.py`, `rq4_bank_sim.py`, JSON beside them); Opus rebuilds them as tested code
(`eval/rq4_power.py`) and re-runs them with the union's measured rates from sitting D before anything is locked.

**1. Baseline guard (B09 before the run).** Code asks two things of a proposal. In what do the arms differ
(library defaults read from scikit-learn at run time, no value table)? Is an arm worse than itself at library
defaults (one short reference run on seeds no real run can draw, read with the existing verdict code)?
- Reject and retry: accuracy above a 3:1 class ratio (G0); arms that differ in more than one factor (G1); in a
  two-model comparison, a control weaker than itself at defaults (G2); a reference run that crashes (G5).
- Human queue, never auto-accepted: one factor, and the control's value of it is weaker than the default (G3).
  It may be the honest point ("depth 1 against depth 8"), so a person decides.
- Warn only: both arms share a setting that is weaker than the default (G4).
- Fair measurement: G0 and G1 are rules and are never reported as recall (the saboteur's B09 fails G1 by
  definition). The measured rows are tested on fresh proposals and on mechanically generated handicaps, with a
  behavioural oracle on other seeds and pass marks fixed in advance; if a mark fails, those rows become advisory.
- Development fact: all 35 bases of pools 1 and 2 and the 3 real runs differ in exactly one factor.
- Needs no cloud call at all.

**2. Mission 4.1 with the union reviewer.**
- Each population gets a **support**: the bug variants it can carry, each exclusion backed by a named rule.
- **Pooled recall** (mean of the class recalls over the support) is the central estimate. **Worst-class recall**
  gives the bound, and the gate uses it: simulated, a pooled gate still opens in 81% to 100% of campaigns when the
  true contamination is 0.27 and every bug is of the worst class.
- **B09 cannot stay in the support.** Simulated with zero real bugs, the gate opens in 8% to 35% of campaigns
  (union) and 0% to 4% (LLM alone) when B09 is in it, and in 97% to 100% when it is out. So B09 leaves only
  through the tested guard, and what the guard lets through is added back as a measured leak term.
  **Until the guard passes its test, no real finding is auto-accepted.**
- Gate order: guard label, enough calibration (12 canaries per supported class, 60 clean runs), reviewer
  informative, then the 90th percentile of contamination plus leak against tau.
- Free tier: opening the gate from nothing costs about 228 reviews (3.5 sessions); starting from the RQ4 bank
  costs none. Proposed: in campaigns ask the LLM only when the tripwires pass (the union's verdict is the same).

**3. Mission 4.2 (RQ4).** One reviewed bank, many hidden-truth populations: `skeptic_d` reviews the 360 runs of
a new batch `rq4-bank-1` on a **fresh pool 3** (7 short sessions with the sentinel and the B09 top-up).
**Corrected the same day:** the first draft used `tripwire-test-1` (pool 2). The Mission 5.1 plan is right that
this batch is never reviewed by an LLM: that was the ground for approving it without a pool 3; `skeptic_d`'s
misses on pool 2's bases were already read when RQ4 was designed, so the B09-heavy test would not be out of
sample there; and the bank later calibrates real campaigns, so its bases must pass the guard. Cost: one local
build sitting (about 2 to 3 hours, no cloud call) and guard sitting 1 first. No extra review. Each level (0, 0.10, 0.30, 0.50 buggy) is
built by drawing 100 audited runs from the bank and calibrating on the rest (12 canaries per class, 60 clean), 2000
times; the estimator sees only flags. Three kinds: matched mix, other experiments (different bases), adverse mix
(B09-heavy, with a recommended top-up of 30 B09 canaries). 100 audited runs is what the bank allows; simulated
interval widths are 0.04 to 0.20. Pass marks come from simulated banks of the same size, because re-splits of
one bank cover more often than 90% even when all is well.

**Build order across all plans** (updated in design session 2; also in `.project-memory/PLAN.md`):
| # | Who | What | Plan | Needs |
|---|---|---|---|---|
| 1 | Opus | 5.1 sitting C: K3, K4, K6, L1, A1, dev runner | `mission_5_1_tripwires.md` steps 5-7 | nothing |
| 2 | Opus + student's window | 5.1 sitting D: lock, 360-run tripwire test, `ceiling-ext`; ceiling files unfreeze | steps 8-10 | 1 |
| 3 | Opus | 5.1 step 11: `canary.cli tripwires`, ledger role `tripwire_v1`; then one DESIGN.md sync sitting | step 11; roadmap finding 17 | 2 |
| 4 | Opus, any day, local only | Guard sitting 1: `canary/baseline_guard.py`, wired into the Scientist | `b09_proposal_guard.md` steps 1-4 | nothing |
| 5 | Opus, any day, local, short | Decisive-share check on the clean runs already made (no reviewer data; pool-1 batches and real runs only until row 2 is done); the student then fixes the campaign grid and `seeds_per_arm`; the ledger anchor (in `canary/ledger.py`, no frozen file) | roadmap findings 2, 14, 25 and 26 | nothing |
| 6 | Opus, any day, new files only | 4.3 sitting 1: `canary/drift.py` limits and rules, `eval/drift_power.py`, chart state | `mission_4_3_drift.md` steps 1-3 | nothing (the measured re-run needs 2) |
| 7 | Opus | 4.1 sitting 1: `eval/rq4_power.py`, prevalence, contamination, support, `trust.estimate`, union observations | `mission_4_1_trust.md` steps 1-4, 6 | 3 |
| 8 | Opus | 4.3 steps 4-5: identity in `canary/llm.py`, cache key, epochs; before the RQ4 lock | `mission_4_3_drift.md` steps 4-5 | 2 |
| 9 | Opus prepares, student's window runs | RQ4 bank, local: pool 3 (guard on), `rq4-bank-1` (360 runs), the top-ups, tripwire records; about 2 to 3 hours | `mission_4_2_hidden_truth.md` step 1b | 3, 4, 5 |
| 10 | Opus | RQ4 code and lock: `eval/rq4.py`, `eval/rq4_lock.py`, `docs/plans/rq4_hidden_truth.md` | steps 1-2 | 7, 9 (8 if in time) |
| 11 | Student's window | 7 review sessions on the bank and the top-ups (about 65 a day) | step 3 | 10 |
| 12 | Opus, local, in the review week | Guard sitting 2: oracle, generator, lock, test once | `b09_proposal_guard.md` steps 5-8 | 4 |
| 13 | Opus, in the review week | 4.1 sitting 2: `canary/gate.py`, real runs padded with decoys, ledger decisions | `mission_4_1_trust.md` steps 5, 7, 8 | 7 |
| 14 | Opus, in the review week | 4.3 steps 6-8 on fakes (sentinel runner, alarm, hold, regression check, drill); 4.4 sittings 1-2 (policy, block and trace on a fake provider) | `mission_4_3_drift.md`; `mission_4_4_campaign.md` steps 1-6 | 6, 8, 13 |
| 15 | Opus + student's window, local, in the review week | Missions 3.1 and 3.2: three sittings, then the variety test and RQ6 (about 4 to 8 laptop hours) | `mission_3_1_3_2_memory_calibration.md` | 2, or the new prompt file |
| 16 | Opus, then `/evaluate` | `python -m eval.rq4` once; RQ4 table and figure | `mission_4_2_hidden_truth.md` step 4 | 11; proposed: the RQ3 lock of row 18 first |
| 17 | Student's window | Sentinel drawn from the bank and its opening pass; then the real 3-day campaign (cold start) | `mission_4_3_drift.md` step 6; `mission_4_4_campaign.md` step 7 | 14, 16 |
| 18 | Fable or Opus | Plans for Mission 5.4 (RQ2 in two labelled parts, RQ3 with baselines, both from the bank), Mission 6 (design pass) and Mission 8.1 (RQ1 on one common batch); then `/priorities` | `roadmap_challenge_2026-11-15.md` section 4 | 16; proposed: the RQ3 part is written and locked in the review week, after 13 and before 16 |

Rows 12 to 15 fit into the review week of row 11: they make no cloud call and touch no file the RQ4 lock freezes.
Proposed in the second read (roadmap finding 21, decision 11): the RQ3 part of row 18 is locked in that week too,
before row 16 reads the bank's reviews.
No campaign makes a review call while the bank's reviews are open. `tripwire-test-1` (row 2) is tripwires-only for
good: no LLM ever reviews it. Rows 5 and 9 carry proposals that wait for the student (kind D, the B06-subtle top-up,
the decisive-share check): see design session 2 above.

**Decisions: all defaults approved by the student on 2026-11-15** (each plan's last section):
- Guard: one factor only; G3 to the human queue and G4 a warning; add G0; the pass marks.
- 4.1: gate on the worst class; no auto-accept until the guard is tested; lazy union in campaigns; minimum calibration.
- 4.2: review all 360 runs (not only tripwire-passed ones); the B09 top-up; levels and 100 audited runs; the
  bank on a fresh pool 3.

**What these designs may not be read as:** every simulated number rests on assumed rates; the union has not been
measured; contamination always means "bugs of the catalogued kinds"; the guard covers one definition of a weak
baseline (against library defaults) and says which ones it misses.

## Ceiling arm L: result and reading (2026-11-14, Fable): SOLVABLE for `openai/gpt-oss-120b`
**Outcome under the locked rule** (`docs/plans/cloud_ceiling_check.md` section 5; `eval.ceiling --arm L` ran once;
file `eval/results/ceiling/arm_L.json`): **SOLVABLE**. `skeptic_d` flagged 46 of
60 buggy runs and 0 of 60 clean runs, with 0
failed audits. Lock check OK before and after this session.

| Test (lower end of the 97.5% interval, 32 clusters) | Value | Interval | Bar | Passed |
|---|---|---|---|---|
| T1: J above 0 | +0.767 | [+0.643, +0.891] | 0 | True |
| T2: verdict AUC above 0.70 | 0.883 | [0.821, 0.946] | 0.7 | True |
| T3: gap over the strongest trivial feature above 0 | +0.358 | [+0.182, +0.381] | 0 | True |
| Sensitivity, 18 focus-level clusters (decides nothing) | J +0.767 | [+0.618, +0.911] | same tests | agrees: True |

Arm R is not needed (plan section 7, step 6). The plan was not changed and the analysis was not run again.

### Breakdown tables (exploratory; `python -m eval.ceiling_breakdown --arm L`)
New file `eval/ceiling_breakdown.py` (9 tests in `tests/test_ceiling_breakdown.py`). It reads the same rows as the
locked analysis, stops if the totals differ from `arm_L.json`, and only splits them. It writes
`eval/results/ceiling/arm_L_breakdown.json` and `.md` (counts and group labels only, no run ID). These splits were
not pre-registered, the groups are small, and the intervals (95% Jeffreys) ignore clustering. They decide nothing.
The tables below are copied from the generated file.

**1. Recall per bug class and tier (caught / planted)**

| Class | obvious | subtle | Both tiers | Planted class named, of caught |
|---|---|---|---|---|
| B01 | 3/3 | 3/3 | 6/6 (100%) [0.67, 1.00] | 6/6 (100%) [0.67, 1.00] |
| B02 | 3/3 | 2/3 | 5/6 (83%) [0.44, 0.98] | 5/5 (100%) [0.62, 1.00] |
| B03 | 3/3 | 3/3 | 6/6 (100%) [0.67, 1.00] | 6/6 (100%) [0.67, 1.00] |
| B04 | 3/3 | 2/3 | 5/6 (83%) [0.44, 0.98] | 5/5 (100%) [0.62, 1.00] |
| B05 | 3/3 | 2/3 | 5/6 (83%) [0.44, 0.98] | 5/5 (100%) [0.62, 1.00] |
| B06 | 0/3 | 0/3 | 0/6 (0%) [0.00, 0.33] | none caught |
| B07 | 3/3 | 3/3 | 6/6 (100%) [0.67, 1.00] | 6/6 (100%) [0.67, 1.00] |
| B08 | 3/3 | 3/3 | 6/6 (100%) [0.67, 1.00] | 6/6 (100%) [0.67, 1.00] |
| B09 | 1/3 | 0/3 | 1/6 (17%) [0.02, 0.56] | 1/1 (100%) [0.15, 1.00] |
| B10 | 3/3 | 3/3 | 6/6 (100%) [0.67, 1.00] | 0/6 (0%) [0.00, 0.33] |
| All | 25/30 (83%) [0.67, 0.93] | 21/30 (70%) [0.52, 0.84] | 46/60 (77%) [0.65, 0.86] | 40/46 (87%) [0.75, 0.94] |

**1b. The missed canaries: class, tier, dataset, metric**

| Missed | Runs |
|---|---|
| B02 subtle on breast_cancer, balanced_accuracy | 1 |
| B04 subtle on diabetes, f1 | 1 |
| B05 subtle on pc1, f1 | 1 |
| B06 obvious on ozone-level-8hr, roc_auc | 1 |
| B06 obvious on pc1, f1 | 2 |
| B06 subtle on diabetes, f1 | 1 |
| B06 subtle on pc1, f1 | 2 |
| B09 obvious on credit-g, accuracy | 1 |
| B09 obvious on diabetes, balanced_accuracy | 1 |
| B09 subtle on credit-g, balanced_accuracy | 1 |
| B09 subtle on pc1, f1 | 2 |

**1c. Caught, but another class named**

| Planted, named | Runs |
|---|---|
| B10 named B01 | 5 |
| B10 named B03 | 1 |

**2. Specificity.** No clean run was flagged in any group: controls 30 of 30 passed, shams
30 of 30, obvious decoys 30 of 30, subtle decoys
30 of 30, and 6 of 6 for the decoy of each of the
10 classes. Every clean run in these two batches carries a decoy
(60 of 60), so there is no "clean without a decoy" group here. The full
table is in the generated file.

**3. Repeat pass (same prompt asked again, days later)**

| Measure | Value |
|---|---|
| runs asked again | 20 (14 buggy, 6 clean) |
| same verdict | 19/20 (95%) [0.79, 0.99] |
| same bug class (a pass names none) | 18/20 (90%) [0.72, 0.98] |
| same bug class, runs flagged both times | 11/12 (92%) [0.67, 0.99] |
| wording differs (not a disagreement) | 16/20 |
| fields that changed | bug_class 2, confidence 6, evidence 16, verdict 1 |
| verdict changes | buggy run: pass then flag (1) |

**4a. SIDE COMPARISON, same runs: task-dev-2. the same 40 padded runs with decoys; the prompts differ (cloud: baseline, llama: checklist with a line check)**

| Reviewer | Model | Flagged buggy | Flagged clean | J | Verdict AUC |
|---|---|---|---|---|---|
| skeptic_d | openai/gpt-oss-120b | 17/20 (85%) [0.65, 0.96] | 0/20 (0%) [0.00, 0.12] | +0.850 | 0.925 |
| skeptic_c_checklist | llama3.1:8b | 0/20 (0%) [0.00, 0.12] | 0/20 (0%) [0.00, 0.12] | +0.000 | 0.500 |

**4b. SIDE COMPARISON, other runs (context only): task-dev-1. 40 different runs, no padding and no decoys, baseline prompt; the cloud model never saw them, so this is context only**

| Reviewer | Model | Flagged buggy | Flagged clean | J | Verdict AUC |
|---|---|---|---|---|---|
| skeptic_a | gemma3:4b | 20/20 (100%) [0.88, 1.00] | 20/20 (100%) [0.88, 1.00] | +0.000 | 0.500 |
| skeptic_b | phi4-mini:latest | 19/20 (95%) [0.79, 0.99] | 17/20 (85%) [0.65, 0.96] | +0.100 | 0.550 |
| skeptic_c | llama3.1:8b | 20/20 (100%) [0.88, 1.00] | 20/20 (100%) [0.88, 1.00] | +0.000 | 0.500 |

From the locked arm file (secondary): cloud verdict AUC minus skeptic_c_checklist's P(flag) AUC on the same 40 runs = +0.283 [+0.080, +0.505] (97.5%, base-level bootstrap).

Gemma and phi never reviewed task-dev-2, so they cannot be compared on the same runs. From the locked arm file
(secondary): cloud verdict AUC minus llama's P(flag) AUC on the same 40 runs = +0.283
[+0.080, +0.505].

### What the tables say
1. **The misses are not spread evenly.** 11 of the 14 missed canaries are in two classes:
   B06 metric misuse (0 of 6 caught) and B09 weak baseline (1 of 6). On the
   other 8 classes the reviewer caught 45 of 48; the misses there are all subtle tier (B02, B04, B05).
2. **The dataset and metric pattern is mostly the class pattern.** pc1 and f1 look weak in the generated file, but
   most of pc1's misses are B06 or B09 canaries (table 1b). Those classes sit on the imbalanced datasets by
   construction.
3. **B10 is caught for another reason.** All 6 easy-test-subset canaries were flagged, but none was
   named B10 (table 1c). The planted class was named in 40 of 46 caught canaries.
4. **Zero false alarms in every clean group**, including all 20 decoy variants.
5. **Verdicts repeat, wording does not.** 19 of 20 verdicts were the same when asked again; the
   one change was a buggy run that went from pass to flag. The wording differed in 16 of
   20 replies.

### `/challenge` of this reading (strict reviewer)
| # | Severity | Finding | What it means for the claim |
|---|---|---|---|
| 1 | Major | The overall recall is an average over the saboteur's uniform mix of 20 variants. It hides two classes near zero (B06, B09). With another mix of bugs the number would be different. | Report recall per class beside the overall number, and the worst class with every estimate. Never quote the overall recall as "the recall on real bugs". |
| 2 | Major | The class split is post hoc: 6 canaries per class, 3 per variant, wide intervals (table 1), clustering ignored. | Say "in this sample the misses concentrate in B06 and B09". Do not say "the model cannot detect B06". Why it misses them is a guess until tested: both bugs may need knowledge that is not in the script (the class ratio; what a fair baseline is). No reply was read to check this. |
| 3 | Major | Any fix chosen from these tables (a hint for B06, another prompt, a threshold) is tuning on seen data. Pool 2 is used up. | A change is judged only on a fresh batch from a new pool 3 under its own locked plan. These 120 runs are development data from now on. |
| 4 | Major | Specificity was measured only on template runs carrying decoys. 60 of 60 is a count, not "100%": with 32 clusters the true false-alarm rate could still be a few percent. Real Scientist runs and plain clean runs were not reviewed by this model. | Say "no false alarm in 60 clean runs". The Beta posterior, not the point value, goes into Mission 4. |
| 5 | Major | SOLVABLE covers known shapes only: 10 textbook bug classes on one template. A large model has seen these pitfalls in training. | "On Canary's canaries". Nothing about new bug shapes (Mission 6.2) or about bugs a real Scientist makes. |
| 6 | Moderate | A right verdict is not a right diagnosis (B10 never named). Recall by verdict overstates how well the reviewer explains a bug. | Trust statistics stay verdict-based, as registered. The graveyard cause "flagged: class" and the blind-spot map must not treat the named class as reliable for B10. |
| 7 | Moderate | The repeat pass (20 runs, days later) mixes sampling noise with a possible change at the provider. A verdict changed at temperature 0. | A single review is slightly noisy. The registered first reply stands. A campaign cannot assume a re-asked run gives the same verdict. |
| 8 | Moderate | The side comparison is weak evidence. Same runs: only llama, with another prompt (checklist), and its P(flag) cut-off was chosen on that batch. Other runs: gemma and phi on task-dev-1, which has no padding and no decoys. Model size, reasoning, strict JSON mode and provider all differ at once. | The plan allows "the local models are the weak link" because the paired lower bound is above 0. It does not allow "gpt-oss is better because of X", or any number for gemma and phi on this task. |
| 9 | Moderate | One model snapshot on a free tier, measured on 2026-11-13 and 14. The provider can change or retire it. | The claim carries the model name, settings and dates. A changed model means a new calibration; results are never mixed. |
| 10 | Minor | Pool 2 repeats pool 1's grid. | Covered: the 18-cluster sensitivity agrees. Recall by batch (task-dev-2 17 of 20, ceiling-ext 29 of 40) has overlapping intervals; no claim from it. |
| 11 | Minor | The agent that builds the tripwires has now seen class-level reviewer results that include ceiling-ext. | Only counts were printed, no run ID or reply. Tripwires never use reviewer output. Stated here so the tripwire test on ceiling-ext can cite it. |

**May claim:** for `openai/gpt-oss-120b`, at these settings, with the baseline prompt, on Canary's canaries, the review task is
solvable: J +0.767 [+0.643, +0.891], no false alarm in 60
clean runs, far above every trivial feature; the result holds under both cluster definitions; the local models, not
the task, were the weak link (paired lower bound above 0).

**May not claim:** that the task is solved; a recall for real bugs or new bug shapes; that any single class is
detected or undetectable (6 runs each); that specificity is 100%; a ranking of gemma, phi and the cloud model on the
same task; that the result holds for other prompts, settings, models or a later version of this model.

### Recommendation for Mission 4 (for the student to decide)
**Reviewer: the union of `openai/gpt-oss-120b` and the tripwires, each also logged alone.** A run is flagged if either flags it.
- **Why:** the LLM's misses sit in classes where reading code is not enough. The tripwire plan covers B06 with
  deterministic checks (L1, K4, K6: not built yet) and costs no API call. The two reviewers fail in different ways.
- **B09 stays uncovered by both** (the tripwire plan has no B09 check; the LLM caught 1 of 6). Handle it
  where the 5.1 plan proposes: prevent it at proposal time (Mission 4.1) and send doubtful baselines to the human
  queue. Show the worst-class recall with every contamination estimate.
- **Risk:** the union's false alarms are at least those of each part. The tripwires fail closed (an unverifiable
  run is flagged), and their false-alarm rate on fresh clean runs is not measured yet.
- **What would change it:** if the tripwire test (sitting D) shows false alarms or unverifiable runs on clean runs,
  use the tripwires as the first escalation step after the gate (`DESIGN.md` section 8) instead of in the union.
- **Until the tripwires are tested:** Mission 4.1's code takes the reviewer as a parameter (a role or a union) and
  is developed with `skeptic_d` alone. The union's trust numbers come from the tripwire test's own locked plan,
  never from re-splitting these 120 runs.
- **Why the worst class matters** (an illustration with these counts as Beta(1 + caught, 1 + missed) means; the
  prevalence values are assumptions, and Mission 4.1's code will compute the real numbers with intervals): mean
  class recall 0.700, worst class 0.125. If 20% of real runs were buggy, P(bug | passed) would be
  0.071 with the mean recall and 0.182 with the worst
  class, against a gate of 0.1. At 5% it is 0.016 and
  0.045.

**What the free-tier limit means** (arithmetic from `arm_L.json` and `config/campaign.yaml`; arm L used
2593 tokens per call over 143 calls):
- **About 65 reviews a day.** With the campaign mix that is about 32 real runs,
  10 measuring canaries, 10 probes and
  13 clean runs a day. The reviewer, not the laptop, sets the pace.
- **The control chart is slow and coarse.** A window of 20 measuring canaries fills in about
  2 days, so the "two windows in a row" alarm needs about
  4 days. At recall 0.77 the limits are 0.58 (2 sigma) and
  0.48 (3 sigma): one window alarms only at 9 or fewer catches
  of 20. It sees a collapse, not a slow drift.
- **Add a sentinel set for drift.** Re-ask the same 20 already reviewed runs on a schedule with the cache bypassed
  (the repeat-pass mechanism, `rescore --sample`). The prompts are the same, so a verdict change is the reviewer
  changing; the baseline is 1 change in 20. It costs 20
  calls, under a third of one day. The server-model check on every call stays.
- **The cache hides drift.** A cached reply is free but says nothing about today's model, so chart canaries must be
  new prompts or bypass the cache.
- **Long evaluations take days.** A 300-run hidden-truth campaign (Mission 4.2) is about 5 sessions.
  It must be resumable (a session already stops cleanly at the budget), and nobody analyses a part of it.
- **One provider is a single point of failure.** If Groq changes the limits or retires the model, Canary has no
  measured LLM reviewer, only the tripwires. The efficiency search (a local model that clears the same bar on a
  fresh batch) removes this; it can run after Mission 5.1 and does not block Mission 4.

## Mission 4.1 sitting 1 (2026-11-20, Opus): steps 1-4 and 6 built; design re-run with measured rates
- **Scope:** `docs/plans/mission_4_1_trust.md` steps 1-4 and 6. Local only: no cloud or Ollama call, no ledger write
  (`data/canary.db` and `data/sealed.db` SHA-256 unchanged across the re-run), nothing under `data/runs/`. Support
  as approved and confirmed today: B09 stays in the real-run support until the guard passes its test.
- **Step 2 (`dfb9555`):** `trust.prevalence_draws` (Rogan-Gladen; Se + Sp - 1 <= 0 gives 1, never dropped) and
  `trust.contamination_draws` (0 at prevalence 0, 1 when nothing can pass). Hand-computed tests: Se 0.8, Sp 0.9,
  p 0.3 -> prevalence 0.2857, contamination 0.0816 (0.05714 / 0.7); p below 1 - Sp clips to 0; den <= 0 gives 1;
  point posteriors reproduce the formulas to 3 decimals.
- **Step 3 (`28d19b8`):** `trust.support` in `config/campaign.yaml` (`real_guard_off`, `real_guard_untested` (today),
  `real_guard_tested`, `hidden_truth`), each left-out variant with its rule beside it (refused otherwise);
  `trust.support_variants`, `real_population`, `summarize(..., variants=...)` with `outside_support`. Tests: B06 in
  the real support comes from subtle canaries only; a class with no canaries is `untested`; worst = lowest posterior
  mean, ties by ID.
- **Step 4 (`b3848cf`):** `trust.estimate(observations, real_flags, support, leak, draws, seed)` and
  `estimate_from_posteriors`: pooled and worst-class recall, prevalence and contamination (mean, median, 5-95%,
  contamination p90), `p_informative`, the gate figure min(1, contamination_worst + leak / (1 - p)) at the 90th
  percentile, counts, support, leak, "bugs of the catalogued kinds only". No threshold applied (the gate is sitting
  2). Tests: signature and no database opened on the real-run side (sqlite3 and the sealed table spied); pooled ==
  worst with one class; hand values incl. the gate figure 0.096.
- **Step 6 (`0a36f72`):** `trust.union_observations` (flag if either; only runs both judged are scored, the rest
  counted) and `collect_union_observations` over two ledger roles. Tests: flag if either; a failed LLM audit with a
  passing tripwire is counted, not scored; per-run union differs from what rates could give (10 vs 5 of 10).
- **Step 1 (`d7fe7b9`; /challenge fixes `1a790b9`, `b2b47cb`; result `d4dc70c`):** `eval/rq4_power.py` runs the design
  simulation through `trust.estimate_from_posteriors` (tests: seeded and repeatable; a perfect reviewer recovers
  the planted prevalence to 3 decimals; the simulation calls the estimator). Measured counts are read through
  `trust` and each is checked against its locked result file before use (all 12 checks match: arm L per variant and
  specificity; tripwire-test-1 per class, B06 subtle and specificity; tripwire on ceiling-ext and task-dev-2 against
  their JSONs, same tripwire version). `python -m eval.rq4_power` -> `eval/results/rq4_power/design_rerun.json`
  (254 gate rows, 224 RQ4 rows, 434 s). "True" rate in a simulated campaign = posterior mean of the measured counts.
  **Design only: no threshold chosen on these numbers, nothing locked.**
- **Rates (B09 in = `real_guard_untested`; pooled always beside the worst class):** skeptic_d (arm L, 120 runs)
  pooled 0.708, worst B06 (subtle 0/3) 0.200, specificity 60/60 -> 0.984; tripwire_v1 (tripwire-test-1, 360 runs)
  pooled 0.860, worst B09 (0/20) 0.045, specificity 159/160 -> 0.988; union per run (ceiling-ext + task-dev-2, 120
  runs) pooled 0.805, worst B09 (1/6) 0.250, specificity 60/60 -> 0.984. B09 out: skeptic_d 0.758 / B06 0.200;
  tripwire_v1 0.950 / B06 0.917; union 0.867 / B06 0.800. Union on ceiling-ext alone (no tripwire development
  data): every non-B09 canary flagged, B09 0/4, 40/40 clean.
- **Re-run vs the design session (worst-class gate opens, zero real bugs, sizes 6/60/30 ... 40/120/120):**
  B09 in: design union (assumed) 0.08-0.35, rebuilt code with the same assumed rates 0.08-0.36, measured union
  0.17-0.64, skeptic_d 0.03-0.44, tripwire_v1 0.01-0.06. B09 out: design 0.97 then 1.00; measured union 0.80, 0.99,
  then 1.00; tripwire_v1 0.96 then 1.00; skeptic_d alone 0.10-0.51. At 30% buggy, uniform, B09 out: design union true
  contamination 0.013, gate opens 0.03-0.78; measured union 0.055, opens 0.00-0.02. All bugs in the worst class at
  30%: measured union true contamination 0.246, pooled gate opens 0.73-1.00, worst-class gate 0.01-0.02 (design
  0.266, 0.97-1.00 and 0.01-0.03). Leak (union B09 out, 20/120/60): 0 of 100 -> 0.996, 2 of 100 -> 0.969 (design
  1.000 both). RQ4 at 10 per class, truth 0.5: measured union pooled median 0.528-0.534 (design 0.532-0.535).
- **Own /challenge, fixed:** (1) **a real bug:** in the first re-run the assumed `union_B09_out` replaced the measured
  one (same dict key); assumed reviewers now carry `assumed_`, a collision raises, test added (`b2b47cb`); the
  committed JSON is the corrected run. (2) Tripwire B06 per tier is now checked against the locked headline.
  (3) Union counts are kept per batch, so ceiling-ext alone (no tripwire development data) is visible.
- **Own /challenge, stated:** (1) the union's rates rest on 6 canaries per class (3 per variant); its posterior means
  (6/6 -> 0.875) sit below tripwire_v1's alone (20/20 -> 0.955) although per run the union can only flag more, so
  the simulation understates the union; by the rule it cannot be patched from the halves' rates, only by more
  per-run data (the RQ4 bank). (2) task-dev-2 is tripwire development data (labelled; ceiling-ext alone shown).
  (3) Runs from one base are not independent (arm L: 120 runs on 32 bases): intervals too narrow (plan trap 5).
  (4) Specificity comes from clean runs with decoys; it transfers to real runs only after step 7. (5) The rebuilt
  code's "all bugs in the worst class" mix uses the class with the lowest true rate (for the assumed LLM: B06 0.05),
  where the design put them in B09 (0.17), so that one assumed row differs (0.294 vs 0.266 true contamination).
  (6) skeptic_d alone never opens the gate reliably, even without B09 (B06 subtle 0/3).
- **Checks (end of both parts):** `pytest -q` 1001 passed in 15.7 s and 15.5 s; `pytest -m slow` 269 passed, 3 skipped
  (200 s); `eval.ceiling_lock --check` "Lock check: OK, every hash matches"; `eval.tripwires_test --check` "Tripwire
  lock check: OK" (both OK at the start and after the `mixer.py` and `trust.py` changes); `ledger verify` OK (3592).

## Guard follow-ups (2026-11-20, Opus): the student's five answers to sitting 1
- Decisions recorded under Decisions (`e8a1151`). Code: G7 (arms identical after defaults -> human queue, label
  `no_difference`, `d095a96`; the sitting-1 test that expected `ok` now expects G7, renamed, not deleted); pool files
  store each base's guard record (`scientist.guard_record_of`, `mixer.build_pool`, `446ff2e`; both lock checks OK
  after the `mixer.py` change). Plan `docs/plans/b09_proposal_guard.md` (`5c5ffe2`): G7 row, trap 7 (two reference
  runs per attempt allowed), section 4 corrected (garbled first real run, G1), section 10 lists the decisions.

## B09 baseline guard, sitting 1 (2026-11-20, Opus): steps 1-4 built and wired; not measured
- **Scope:** `docs/plans/b09_proposal_guard.md` steps 1-4, rules exactly as approved 2026-11-15. Local only: no cloud or
  Ollama call, no ledger write, nothing under `data/runs/` (every reference run in a temporary folder). **Nothing here
  is recall**: G0 and G1 are rules; the measured rows (G2-G4) are tested in sitting 2.
- **Code:** `canary/baseline_guard.py` (new). Step 1 (`5199bbe`): `effective_params`, `factors`, `nondefault`,
  `unknown_params`; defaults from `get_params()` of the installed scikit-learn at run time; `random_state` ignored.
  Step 2 (`9bfc9a0`): G0, own constant `IMBALANCE_LINE` (a test checks it equals `classes.IMBALANCE_RATIO`). Step 3
  (`19647d6`): `reference_for` (G2 all control params at default, G3 the tested factor, G4 the shared settings;
  preprocessing default = no scaler), `reference_gap` (guard seeds 100001-100005, `sandbox.run_config` in a temporary
  folder, read with `prereg.compute_verdict`, direction increase, floor 0.005 and alpha 0.05 from `campaign.yaml`).
  Step 4 (`804aa39`): `check_config` / `check_proposal` -> `GuardRecord` (outcome, rule, label, feedback, factors,
  non-default names, `tuning_asymmetry`, gaps with scores, K, seeds, scikit-learn version, guard version);
  `scientist.proposal_problem(..., guard=True)` returns the reject sentence through the existing retry text (prompt
  unchanged); `run_locked` puts the record in the PROPOSED payload under `guard` (lock and hash unchanged; a lock
  that skipped `propose` is checked there, and a reject raises before any ledger write); every result appended to
  `data/guard/proposals.jsonl`; `science.baseline_guard: true`; `python -m canary.baseline_guard <config>` (prints,
  never logs). Not touched: `canary/cli.py`, `mixer.py`, `prompts.py`, `trust.py`.
- **Order of the rules (my reading of section 3):** G0, G1, then for two models G2; for one factor G3, then G4. G5 is
  any of those reference runs failing (reject). After a G3 finding (human queue) G4 is not measured.
- **Tests:** `tests/test_baseline_guard.py` (table rows from hand-made proposals, fake runners; 3 slow tests with real
  runs, one with a sealed table beside it and `sqlite3.connect` spied), `tests/test_baseline_guard_guards.py` (import
  allow-list and chain, no sealed/plans/twins/catalog words, no saboteur vocabulary, no hyperparameter name in the
  source, no dict or list of parameter values, estimator table equals the template's, reviewer code never reads the
  guard record), `tests/test_scientist_guard.py` (feedback, record in the ledger, the reviewer's blinded text
  identical with and without the guard, guard off = old behaviour exactly). `tests/conftest.py`: reference runs are
  neutral fakes and the log goes to `tmp_path` unless a test passes `run=sandbox.run_config`.
- **Done when:** `python -m canary.baseline_guard config/examples/baseline.yaml` -> `Baseline guard: ok (rule G6);
  factors: C`, one G4 reference run (shared `max_iter`), not weak (mean gap 0.0), 1.6 s; `data/runs/` count 740 before
  and after; no `data/guard/` written.
- **Development listing (not step 6, not a test; 35 bases of pools 1 and 2 + the first 3 ledger pre-registrations,
  real reference runs in temporary folders, 136 s):** pools: ok (G6) 32, warn (G4, `weak_regime`) 3, reject 0, human
  queue 0. Real runs: ok (G6) 2, reject (G1) 1. 36 reference runs (10 proposals needed two): G3 not weak 12,
  inconclusive 5; G4 weak 3, not weak 5, inconclusive 11. The three warnings: unscaled `svm` with `gamma` 1.0 or 0.1
  and `class_weight: balanced` on diabetes/f1 (mean gap 0.564 in both), and a linear `svm` with `gamma: 0.0` on
  phoneme/roc_auc (0.101; the reference is the default rbf kernel).
- **Own /challenge, fixed:** numeric equality now accepts numpy numbers (`6186644`); a test that the reviewer's code
  never reads the guard record or PROPOSED entries (below).
- **Own /challenge, stated (for the student):** (1) real runs now carry `guard` in their PROPOSED entry and clones do
  not (`mixer.py` writes theirs), so the ledger tells a real run from a clone; the reviewer never reads it (test), but
  the ledger was meant not to reveal run types. (2) Plan trap 7 says at most one reference run per attempt; G3 not
  weak followed by G4 needs two (10 of 38 above). (3) The plan's development fact "all 3 real runs differ in one
  factor" does not hold on effective params: the first real run's control has the garbled key `": "` instead of
  `class_weight`, so it differs in `": "`, `class_weight` and `preprocessing` (G1). That run crashed in Mission 1.4.
  (4) Arms identical after defaults are `ok` with a note (no row covers them). (5) `calibrate` pool building goes
  through `propose`, so it now runs the guard too (wanted for pool 3, plan trap 3); a pool file does not store the
  records (that needs `mixer.py`).
- **Checks (end of sitting):** `pytest -q` 964 passed in 15.3 s and 15.5 s (an earlier pair under machine load took
  28-29 s, the same with and without this sitting's changes); `pytest -m slow` 269 passed, 3 skipped (218 s);
  `eval.ceiling_lock --check` "Lock check: OK, every hash matches"; `eval.tripwires_test --check` "Tripwire lock
  check: OK" (both also OK at the start); `ledger verify` OK (3592 entries).

## Mission 5.1 step 11, part 2 (2026-11-19, Opus): amendment 1 of both locked plans, then `canary.cli tripwires`
- **Decisions (student):** option C for the lock checks, then the CLI in `canary/cli.py`; the three open
  design-session-2 decisions approved (Decisions section; commit `044186c`). The 4.3 plan now says the sentinel at 20
  calls a day catches a collapse, not a slow drift.
- **Before (the original checks, working copies):** `eval.ceiling_lock --check` "Lock check: OK, every hash matches"
  (24 files, manifest 120 runs, arm L 120 answered, call log 143 attempts, only `openai/gpt-oss-120b`);
  `eval.tripwires_test --check` "Tripwire lock check: OK"; `--git-check` "Line endings: OK".
- **The ceiling lock commit:** `2332136` (2026-11-12, the commit that added `cloud_ceiling_check.md.sha256`; new ID
  after the 2026-11-17 rewrite). The plan there hashes to the original `.sha256` and equals the working plan; all 18
  files of section 3 that git tracks hash, as `git show 2332136:<path>`, to their listed values; the 6 data files are
  not in git. Tagged **`ceiling-check-lock` -> 2332136** (local; the student pushes it). `tripwire-test-1-lock` ->
  `172bf95` as before.
- **Amendment 1** (appended as section 11 of `cloud_ceiling_check.md` and section 10 of `tripwire_test.md`; nothing
  above it changed, which the check now enforces): reason (freeze over, Mission 4.1 changes `cli.py` and `trust.py`),
  what changes (only how reproducibility is checked), what does not (locked analysis, bars, results, listed hashes).
  New `.sha256` by `--amend-lock` (refuses unless the plan at HEAD matches the old hash and the change only appends
  text with an amendment heading): ceiling **88cb6078cdbd6dff7926debde83e4e7a7cec5dfbcbc49f32fcb1b4b32682e8bc ->
  f328939322e1382760f9d28685b60d4e2661b7dde1da397f8d2b032c5a41cdc8**; tripwire
  **6b07fe92cc8acfe0db6838115a83e6090ddc57aa3168aa95bca3ac810ca501d5 ->
  6057e4a2b2821e36211beefcf416934bb7c012df4082fb25a6e8d258be7a1cf1**. Code: `eval/lock_git.py` (new),
  `eval/ceiling_lock.py`, `eval/tripwires_test.py` (`--check` at the tag by default, `--check --working-tree` the
  original, `--amend-lock`; `--git-check` compares listed hashes with the tag's blobs; `--batch` still requires the
  original strict check). Each plan names its tag and original hash in one line the code reads. Commit `3d5b96d`.
- **After (the new way):** both checks OK; information lines: `eval/ceiling_lock.py` and `canary/cli.py` (ceiling),
  `eval/tripwires_test.py` (tripwire) differ from their locked versions. `--git-check` "Line endings: OK". The original
  ceiling check now fails on those two files, as expected.
- **CLI (`canary.cli tripwires`, commit `98adf11`):** `inspect <run folder or ID>` (= `python -m canary.tripwires`,
  replay in a temporary copy), `record --batch B [--write]` (dry run by default; uses the locked test's stored records
  first; the run IDs come from the sealed table here, never in the ledger writer), `verify` (record files against the
  hashes in the ledger). Tests `tests/test_cli_tripwires.py` (9) and `tests/test_lock_git.py` (12, 3 of them slow).
- **Done when, on temporary copies only** (scratch script; real `data/canary.db` and `data/sealed.db` SHA-256
  unchanged before and after; real ledger 3152 entries): copy verify OK (3152); `record --batch tripwire-test-1` dry
  run 360 ready (flag 181, pass 179); `--write` 360 written, 0 made; repeat 360 already recorded; `ceiling-ext --write`
  80 written (flag 36, pass 44); `verify` OK (440 entries); `trust --role tripwire_v1 --batch tripwire-test-1`: B01-B08
  and B10 20 of 20, B09 0 of 20, controls 80 of 80, shams 79 of 80, combined 159 of 160 (90% [0.971, 0.998]): **the
  same as `test_tripwire-test-1.json`** (any-flag per class and specificity; the bar's chain-class fired recall 170/170
  is in the JSON only). `ceiling-ext`: per class 4 of 4, B09 0 of 4, specificity 40 of 40: **same as its JSON**. Copy
  verify after: OK (3592 entries).
- **Own /challenge, fixed (commit `4d4d8a0`):** (1) **a bare `canary.cli audit` would have had `skeptic_a` review all
  360 runs of `tripwire-test-1`** (and ceiling-ext's 80): they wait for the default role. `audit` now leaves out every
  batch planned `--no-audit` plus `tripwire-test-1`, and `reaudit` / `rescore` refuse `tripwire-test-1` by name, before
  any model. (2) `trust` said crashed runs "count in no figure above", but a tripwire record of a timed-out run (the
  sham) is counted; `trust` now prints a note naming such runs. **Stated, not changed:** the new check code is not
  itself frozen (its info line shows it differs from the locked version; tests pin its behaviour); the ceiling manifest
  rebuild and the tripwire dry plan still use the working code, so a later change to `skeptic.py`, `blinding.py`,
  `review_tasks.py`, `prompts.py` or `mixer.py` will make a check fail although the locked bytes exist at the tag
  (then run that part in a clone at the tag); `record --write` on a batch without stored records replays serially in
  the foreground.
- **Checks:** `pytest -q` 883 passed (15.1 s and 14.7 s; wall 17.0 s and 16.5 s); `pytest -m slow` 267 passed, 3
  skipped; `ledger verify` OK (3152 entries).
- **Real-ledger write (the student's commands, not run):**
  `.venv\Scripts\python.exe -m canary.cli ledger verify`;
  `Copy-Item data\canary.db "$HOME\canary-backups\canary-2026-11-19-before-tripwire-records.db"`;
  `.venv\Scripts\python.exe -m canary.cli tripwires record --batch tripwire-test-1` (dry run: 360 ready, flag 181,
  pass 179); `... tripwires record --batch tripwire-test-1 --write`; `... tripwires record --batch ceiling-ext --write`;
  `... tripwires verify`; `... trust --role tripwire_v1 --batch tripwire-test-1`; `... ledger verify` (3592 entries).
- **Real-ledger write done (2026-11-20, student's window):** `tripwire-test-1` 360 written (flag 181, pass 179);
  `ceiling-ext` 80 written (flag 36, pass 44); `tripwires verify` OK (440 entries under `tripwire_v1`); `trust --role
  tripwire_v1 --batch tripwire-test-1` matches the locked test (combined specificity 159/160, B09 0/20); `ledger verify`
  OK (3592 entries). Backups: `$HOME\canary-backups\canary-2026-11-20-before-tripwire-records.db` and
  `canary-2026-11-20-after-tripwire-records.db`. Tag `ceiling-check-lock` pushed 2026-11-19 (origin has it at 2332136).

## Mission 5.1 step 11, part 1 (2026-11-19, Opus): tripwire records in the ledger; CLI part waits for the student
- **Scope (roadmap decision 9, approved):** CLI and ledger wiring only; the `DESIGN.md` rewrite of sections 4, 6 and 10
  moves to the DESIGN.md sync sitting. Lock checks OK at the start; no cloud or Ollama call; nothing replayed; no
  write in `data/runs/`, `data/tripwires/` or the real ledger.
- **Built: `canary/tripwire_ledger.py`** (new file, in neither lock's list). `record_runs(run_ids, ledger, write=...)`
  attaches each run's tripwire record as an `audited` entry under role `tripwire_v1`: `audit` (verdict, suspected
  class, evidence: the shape `trust.collect_observations` reads), each check's status (fired and unverifiable stay
  apart), the replay status, the full tripwire version and the SHA-256 of the whole record. Rules: **dry run unless
  `write`**; the first record of a run stands (a repeat adds nothing); a stored record of the current version is
  reused (the locked test's records in `data/tripwires/test/<batch>/`), otherwise one is made only when writing (replay
  in a temporary copy) and stored in `data/tripwires/v1/`; only replay-tier records; **one version per role** (if
  `tripwire_v1` holds records of another code version every write is refused, so `trust` can never pool two
  versions); runs not in the ledger or already closed (accepted, escalated, graveyard) are reported, never forced.
  `verify_records` checks the record files against the hashes in the ledger. The module opens no sealed table, sealed
  plan or twin and reads no reviewer's opinion; choosing the runs is the caller's job.
- **Tests (`tests/test_tripwire_ledger.py`, 15, fast):** payload shape; static-tier and wrong-run records refused or
  passed over; dry run writes nothing; write and repeat; not-in-ledger, closed and no-record runs reported; another
  version not used and blocks every write; a record made only when writing, nothing written in the run folder;
  `verify_records` finds an edited and a lost file; a tripwire record does not stop the LLM from reviewing the run
  (`skeptic._waiting`), as the union needs; **the trust join from the ledger equals `eval.tripwires_dev.score` on the
  same records** (per class, pooled, specificity combined, controls and shams; hand counts beside); guards (imports,
  no import chain to the sealed table, the saboteur or a reviewer; no sealed or twin names in the code).
- **Done-when evidence, on temporary copies only** (scratch script; `data/canary.db` and the sealed table copied, the
  copy written, the real files' SHA-256 unchanged before and after): `tripwire-test-1` 360 written (flag 181, pass 179),
  0 made, chain OK, record files match their hashes; the trust join printed per class B01-B08 and B10 20 of 20, B09 0
  of 20, controls 80 of 80, shams 79 of 80, combined 159 of 160 (90% [0.971, 0.998]); **parity with
  `test_tripwire-test-1.json`: SAME**. `ceiling-ext`: 80 written (flag 36, pass 44), **parity SAME**. The real
  done-when (`python -m canary.cli trust --role tripwire_v1 --batch tripwire-test-1`) needs the records in the real
  ledger: the student's command, after the CLI part.
- **Checks:** `pytest -q` 865 passed (14.7 s and 14.7 s; wall 16.5 s each); `pytest -m slow` 264 passed, 3 skipped
  (before the last small fix, which touched only the new module and its tests); lock checks OK at the end;
  `ledger verify` OK (3152 entries).
- **Own /challenge, fixed:** a stored static-tier record would have raised in the middle of a batch after earlier
  writes; static records are now passed over when searching (`no_record`), with a test. **Stated, not changed:** a
  record file is trusted when it is first read (its hash goes into the ledger, so later edits are found); the parity
  run is that check for the two test batches. A run accepted before its tripwire record cannot get one (the flow
  allows no review after acceptance), so Mission 4 must record tripwires before the gate.
- **Decision needed (the student):** `canary/cli.py` is hashed by the ceiling lock, and `canary/trust.py` by the
  tripwire lock, so the CLI part of step 11 (and later Mission 4.1, which changes `trust.py` and `cli.py`) cannot be
  built while both checks must stay exactly OK. Options are in this session's printout; recommended: keep the
  working-tree checks for this step by putting the commands in a new module (`python -m canary.tripwire_cli`), and
  decide before Mission 4.1 how the two checks verify against the locked commits instead of the working tree.

## Mission 5.1 step 10 (2026-11-19, student's window; recorded by Opus): tripwire test PASSED
- **What the student ran** (plan `docs/plans/tripwire_test.md` section 6), as the student reported it: pre-checks OK
  (`git diff` against the tag empty; "Lock check: OK"; "Tripwire lock check: OK"; "Line endings: OK"); `calibrate`
  built 360 runs, 0 skipped, nothing audited, length gate PASSED; `--check` OK on the built slot list; backup
  `data-2026-11-18-tripwire-test.zip` written; `--batch tripwire-test-1` "TEST PASSED"; `--batch ceiling-ext`
  reported; final checks after both tests "Lock check: OK", "Tripwire lock check: OK", "Ledger verify OK (3152
  entries)". No LLM reviewed `tripwire-test-1`; no cloud or Ollama call.
- **Recorded (Opus, this session):** both lock checks OK at the start and the end; no code changed, so `pytest` was not
  run. The test wrote two files under `eval/results/tripwires/`, both committed in `b28e722` "Mission 5.1 step 10:
  tripwire test result (tripwire-test-1 passed; ceiling-ext reported)": `test_tripwire-test-1.json` and
  `test_ceiling-ext.json` (no other file there was new).
- **Both files:** tripwire version `v1:765b9cc1ae237180...`, plan SHA-256 `6b07fe92...`; label "known shapes, fresh
  bases"; held-out shapes "not measured (Mission 6.2)"; B09 "not covered: no tripwire (plan section 5); B09 canaries
  count as misses in the headline". Not-built slots 0, superseded runs 0, missing records 0. **The bars ignore
  clustering; base-level intervals beside** (17 clusters, 5000 draws; all-pass counts collapse to one value).

**Bars (numbers from the `bars` block of each file):**

| | `tripwire-test-1` (decides) | `ceiling-ext` (reported only) |
|---|---|---|
| Chain-class fired recall (all but B09 and B06 obvious) | 170/170, Beta 90% 0.983-1.000, bar 0.90: met | 34/34, Beta 90% 0.918-0.999, bar 0.90: met |
| Specificity (controls + shams) | 159/160, Beta 90% 0.971-0.998, bar 0.95: met | 40/40, Beta 90% 0.930-0.999, bar 0.95: not met |
| Base-level 90% beside (recall; specificity) | 1.00-1.00; 0.982-1.00 | 1.00-1.00; 1.00-1.00 |
| Outcome | **PASSED** | reported only |

**Development-style table (from `headline`, `any_flag`, `per_class` and the other blocks; deciding nothing):**

| | `tripwire-test-1` | `ceiling-ext` |
|---|---|---|
| Runs / canaries / clean | 360 / 200 / 160 | 80 / 40 / 40 |
| Headline fired recall (B09 in, B06 obvious out) | 170/190, Beta 90% 0.851-0.925; base-level 0.868-0.921 | 34/38, Beta 90% 0.780-0.948; base-level 0.829-0.967 |
| Controls / shams | 80/80 (0.964-0.999) / 79/80 (0.943-0.996) | 20/20 (0.867-0.998) / 20/20 (0.867-0.998) |
| Specificity by decoy class | every class 8/8 except B04 obvious 7/8 | every class 2/2 |
| Youden's J (observed; 90%; base-level) | 0.888; 0.838-0.915; 0.857-0.918 | 0.895; 0.748-0.932; 0.829-0.967 |
| Any flag (fired or unverifiable) | 180/200, unverifiable only 0 | 36/40, unverifiable only 0 |
| By tier (fired, headline) | obvious 80/90, subtle 90/100 | obvious 16/18, subtle 18/20 |
| By impact (fired, headline) | harmful 147/167, harmless 23/23 | harmful 28/32, harmless 6/6 |
| Right class named | 170/190 | 34/38 |
| Per class (fired) | B01-B05, B07, B08, B10 20/20 each; B06 20/20 (subtle 10/10 headline, obvious 10/10 by the L1 rule); **B09 0/20** (Beta 90% 0.002-0.133) | each of those 4/4; B06 4/4 (L1 rule 2/2); **B09 0/4** |
| B06 obvious, L1 rule (outside the headline) | 10/10 (plants and detects the same thing: not evidence) | 2/2 |
| Gold-twin reference recall | 180/190 (0.913-0.967); tripwires only 10, reference only 20 | 35/38 (0.813-0.964); tripwires only 3, reference only 4 |
| Replays reproducing the stored numbers | 359/360; seconds mean 6.6, max 120.1 | 80/80; seconds mean 5.7, max 49.5 |
| Misses / unverifiable canaries / false alarms / no-op canaries | 20 (all B09: 10 obvious, 10 subtle) / 0 / 1 / 10 (all B01, all flagged) | 4 (all B09) / 0 / 0 / 3 (B01 2, B04 1, all flagged) |
| A1 advisory, AUC of "low margin picks B09" | 0.555 (20 B09, 159 clean) | 0.80 (4 B09, 40 clean) |
| Wall time of the scoring | 834 s | 141 s |

- **The one false alarm, explained (counted as the plan says, never excluded):** sham
  `e5c9f79c-910b-4aa0-b126-f21045946a4e`, decoy B04 obvious (grid search, the slowest script type). Its record: S1
  and S2 "unverifiable: results.json has no readable split_sizes / class_balance"; K0 "unverifiable: replay status
  timeout: killed after 120 s"; K1-K6 "no trustworthy replay (see K0)". So its build run timed out at the 120 s
  sandbox limit (the student's account; the record shows no readable results.json) and its replay was killed at
  120 s too: the tripwires could not verify the run and failed closed, which the plan counts as a false alarm
  (`unverifiable` is a flag). It is the 1 of 360 replays that did not reproduce, and the 7/8 of decoy class B04
  obvious. Nothing was re-run or dropped.
- **`ceiling-ext` "specificity not met" explained:** with 40 clean runs even 40/40 gives a Beta(41, 1) lower bound of
  0.930, below 0.95, so this bar cannot be met on that batch whatever happens. It is the secondary batch and decides
  nothing (`decides: false`); it is kept so Mission 5.4 can compare tripwires, LLM and union on the same runs.
- **B09: 0 caught, not covered, by design** (no tripwire, plan section 5). Every miss in both batches is a B09 canary
  whose numbers changed. **A1 is too weak to stand in for a B09 check:** AUC 0.555 on the 20 B09 canaries of
  `tripwire-test-1` is close to chance; the 0.80 on `ceiling-ext` rests on 4 canaries. B09 needs the proposal-time
  guard (`docs/plans/b09_proposal_guard.md`).
- **What may be claimed:** on a fresh, locked batch of 360 runs on 17 pool-2 bases, the frozen tripwires fired on all
  170 chain-class canaries (Beta 90% lower bound 0.98) and passed 159 of 160 clean runs (lower bound 0.97); the one
  flag was a clean run that timed out. **Not claimed:** anything about B09; anything about new bug shapes (Mission
  6.2); 100% specificity; that the Beta bounds account for clustering on 17 bases (they do not; base-level intervals
  are beside). The union reviewer's numbers come from its own locked measurement, never from combining these with the
  LLM's.
- **Freeze ended** with commit `b28e722` (plan section 3): the tripwire plan's frozen files (`canary/probe.py`,
  `replay.py`, `tripwires.py`, `trust.py`, `eval/tripwires_test.py`, `tripwires_dev.py`, `ceiling.py`,
  `config/bug_classes.yaml`, `pool-2.json`) are unfrozen, and so are the ceiling plan's 24 frozen files (including
  `canary/cli.py` and `canary/mixer.py`), as the build order (row 2) says after the test on `ceiling-ext`.
  `eval.ceiling_lock --check` and `eval.tripwires_test --check` stay as reproducibility checks: once a listed file
  changes they will report a mismatch, which is expected and no longer a stop; to reproduce a result, check out
  `b28e722` (or the tag for the plan).
- **Mission 5.1 ticked:** plan section 11 items 1-5 hold (1: `tripwires_dev` on task-dev-2, sittings C and D; 2:
  `pytest -q` 851 in 19-20 s and `pytest -m slow` passed on 2026-11-18, no code changed since; 3: run once on
  `tripwire-test-1` under its lock; 4: ceiling lock OK and `ledger verify` OK; 5: this entry). Step 11 (wiring) is the
  follow-up that must be done before Mission 4.1 uses tripwires; its precondition holds (ceiling arms closed: arm L
  SOLVABLE, arm R not needed; `canary/cli.py` no longer frozen).

## Mission 5.1 sitting D, part 3 (2026-11-18, Opus): step 9 LOCKED
- **Student's answers** (recorded in the plan's section 9, commit `c105763`): the freeze ends when both result files
  exist and are committed; the latest sealed run of a slot counts and every earlier one is listed with its reason
  (checked in the code: `calibrate --resume` rebuilds only slots without a ledger `RAN` entry, and every run gets one
  whatever its status, so no outcome triggers a rebuild); the backup keeps the name
  `data-2026-11-18-tripwire-test.zip` whatever day the build runs. Code: `superseded_runs` entries now carry slot,
  sealed time, status, reason, replacing run and why; section 3 hash of `eval/tripwires_test.py` updated.
- **Step 9 as the plan's section 6 lists it.** 1-2: lock checks OK, no tracked change. 3: six `-text` lines in
  `.gitattributes`. 4: `--sync-lf` rewrote `canary/probe.py` and `canary/replay.py` with their HEAD bytes (CRLF on
  disk, LF in git, same text). 5-6: **first pass stopped**: `git add --renormalize .` also staged
  `docs/plans/review_task_screen.md` (already `-text`; CRLF working copy of an LF blob; git status had not re-read it
  because its stat data had not changed). With the student's OK it was unstaged and restored from git (unchanged in
  git); a scan of all 49 `-text` files found no other. Re-run: only `.gitattributes` staged. 6: "Line endings: OK".
  7: commit `002de41`. 8: title and Status without DRAFT (LF; section 3 unchanged). 9: `--lock` wrote
  `6b07fe92cc8acfe0db6838115a83e6090ddc57aa3168aa95bca3ac810ca501d5`; `--check` "Tripwire lock check: OK"; ceiling
  lock OK. 10: commit `172bf95` (plan + `.sha256`), working tree clean, `--git-check` OK. 11: `git tag
  tripwire-test-1-lock` on `172bf95`; the student pushed it the same day (`git push origin tripwire-test-1-lock`).
- Nothing built, replayed or analysed; no write in `data/`, no ledger write, no Ollama or cloud call.

## Mission 5.1 sitting D, part 2 (2026-11-18, Opus): step 9 draft amended, still NOT locked
- **Student's points, built into `docs/plans/tripwire_test.md` (DRAFT):**
  1. Line endings: section 3 has a table of each frozen file (in git?, `-text` now?). Six need `-text` (probe, replay,
     tripwires, trust, tripwires_test, tripwires_dev); `eval/ceiling.py` and `config/bug_classes.yaml` have it;
     `pool-2.json` is outside git. Found: the working copies of `canary/probe.py` and `canary/replay.py` are CRLF while
     their blobs are LF (content identical). Step 9 now: `.gitattributes` lines, then `eval.tripwires_test --sync-lf`
     (working copy := HEAD blob when only line endings differ; refuses a content difference, writing nothing), then
     `git add --renormalize .`, `git diff --cached` only `.gitattributes`, `--git-check` "Line endings: OK".
  2. `pool-2.json` is gitignored: stated; its LF hash kept, and the ceiling plan's raw-bytes hash (the file is CRLF on
     disk) named beside it; step 10 backs up `data/` with `Compress-Archive` after the build.
  3. Freeze until both step 10 result files exist and are committed; `git tag tripwire-test-1-lock` after the lock
     commit (the student pushes it); Mission 4.1 sitting 1 (changes `canary/trust.py`) only after step 10.
  4. Exact batch: slot-list lock (SHA-256 of the plan's seed, runs, split, padding, decoys, bases, slots):
     `tripwire-test-1` cf348112... (dry plan), `ceiling-ext` 39ffcae8... (stored plan; `mixer.plan_batch` today
     reproduces it exactly). Every planned slot is scored: the latest sealed run of the slot, or a stand-in with no
     record for a slot never built; a sandbox crash gives `unverifiable` (checked on a copy); both count against.
     Resume command `calibrate --batch tripwire-test-1 --resume --no-audit`; stored role `skeptic_a` (length gate's
     context size only); no LLM ever audits the batch (`no_audit` required by the script).
  5. Write-once: already tested for the primary; the test is now parametrized over both batches and checks the file is
     unchanged after the refused second call.
  6. Section 9 records the answers (a)-(d).
- **Own /challenge, fixed:** the old exact-count check would have refused a batch where a crash left two sealed runs
  in one slot (361 rows) and would have stopped on any skipped slot; `--check` now re-plans the batch so a change in
  the planning code shows before an hour of building; the building code (controls, saboteur, padding, sandbox) was not
  pinned, so step 10 starts with `git diff --stat tripwire-test-1-lock -- canary eval config`; the claim states that
  the Beta bars ignore clustering; reproduction recipe and commit of the result files (deleting one to rerun would
  show in git); the stored role's context fits pool-2 prompts.
- **Code:** `eval/tripwires_test.py` (slot lock, `slot_truths`, `--git-check`, `--sync-lf`; refusals: no stored plan,
  slot mismatch, planned with audits, build unfinished, length gate failed, wrong type in a slot, stray run);
  `tests/test_tripwires_locked.py` 16 -> 22 (5 new, 1 parametrized; none deleted; two existing tests adapted to the
  new refusals).
- **End checks:** `pytest -q` 851 passed in 19.9 s and 18.7 s; `pytest -m slow` 264 passed, 3 skipped in 224 s;
  `eval.tripwires_test --check` "hashes OK, plan NOT LOCKED (draft)"; `eval.ceiling_lock --check` "Lock check: OK" at
  start and end. No frozen file edited, no write in `data/`, no ledger write, no Ollama or cloud call.

## Mission 5.1 sitting D, part 1 (2026-11-18, Opus): step 8 done; step 9 drafted, NOT locked
- **Step 0:** `eval.ceiling_lock --check` "Lock check: OK, every hash matches". Decisions of 2026-11-16 and the history
  rewrite note recorded under Decisions (own commit).
- **Step 8, development loop (known shapes, development), tripwire version `v1:765b9cc1ae237180`, unchanged since
  sitting C.** Each batch reported alone (rq1-full and task-dev-1 have no padding and no decoys). Lines copied from
  `python -m eval.tripwires_dev --batch <b>`; JSON in `eval/results/tripwires/dev_<b>.json`.
  - **rq1-full** (180 replays, 4 workers, 4 min 40 s by `data/tripwires/dev.log`): "headline recall (fired): 85/95
    (Beta 90% 0.83-0.93), base-level 90% 0.85-0.94 (18 clusters)"; "specificity: 80/80 (Beta 90% 0.96-1.00); controls
    40/40 (Beta 90% 0.93-1.00); shams 40/40 (Beta 90% 0.93-1.00)"; "Youden's J: +0.895, base-level 90% +0.853 to
    +0.935"; "any flag (fired or unverifiable): 90/100 (Beta 90% 0.84-0.94), unverifiable only: 0"; "B06 obvious (L1
    rule, outside the headline): 5/5"; "gold-twin reference recall: 89/95 (Beta 90% 0.88-0.97) (tripwires only 6,
    reference only 10; specificity not measured)"; "replays reproducing the stored numbers: 180/180; seconds per
    replay mean 5.7, max 62.2"; "misses 10, unverifiable-only canaries 0, false alarms 0, no-op canaries 6"; right
    class named 85/95; every class except B09 10/10 fired. "A1 (advisory): ... AUC 0.583 (10 B09, 80 clean)".
  - **task-dev-1** (40 replays, 74 s): "headline recall (fired): 17/19 (Beta 90% 0.72-0.96), base-level 90% 0.79-1.00
    (17 clusters)"; "specificity: 20/20 (Beta 90% 0.87-1.00); controls 10/10 ...; shams 10/10 ..."; "Youden's J:
    +0.895, base-level 90% +0.789 to +1.000"; unverifiable only 0; "B06 obvious (L1 rule, outside the headline): 1/1";
    "gold-twin reference recall: 18/19 (Beta 90% 0.78-0.98) (tripwires only 1, reference only 2 ...)"; "replays
    reproducing the stored numbers: 40/40; seconds per replay mean 5.3, max 51.9"; "misses 2, unverifiable-only
    canaries 0, false alarms 0, no-op canaries 1"; A1 AUC 0.550 (2 B09, 20 clean).
  - **task-dev-2 again at the end**: same tripwire version as sitting C, so the runner reused its 40 records
    ("made=0 reused=40") and printed the same table as sitting C (17/19 fired, 20/20 clean, every decoy class 1/1, J
    +0.895, base-level +0.750 to +1.000, 0 unverifiable, 40/40 replays, misses = the 2 B09). As a check that today's
    machine gives the same answers, all 40 were also replayed afresh into a scratch folder (not `data/`): 0 differences
    in verdict, named class or any check's status. The JSON changed only in `generated_at` and `wall_seconds`.
  - **Every miss explained:** 14 misses in all (10 + 2 + 2), every one a B09 canary whose numbers changed (B09 has no
    tripwire, plan section 5). **0 false alarms, 0 unverifiable** on 140 clean runs, **260/260 replays reproduced**.
    The 7 no-op canaries (rq1-full: B01 obvious 2, B01 subtle 3, B04 subtle 1; task-dev-1: 1) were all fired by a
    tripwire: the broken link is in the run even though the numbers equal the twin's; they are the "tripwires only"
    count of the reference row. "Reference only" = the B09 canaries.
  - **Fixes: none.** No bug was found, so nothing changed in `probe.py`, `replay.py` or `tripwires.py`; no rule or
    threshold moved. Stated, not changed: rq1-full and task-dev-1 have no decoys, so their specificity says nothing
    about decoys (task-dev-2 does); development numbers are close to guaranteed by construction (plan section 7.3).
- **Step 9, DRAFT only (not locked; no `.sha256`; `tripwire-test-1` not created; nothing run on `ceiling-ext`):**
  - `docs/plans/tripwire_test.md` (DRAFT, LF): question and claim label "known shapes, fresh bases"; frozen version
    `v1:765b9cc1ae237180`; section 3 lists LF SHA-256 of the plan's four files (`probe.py`, `replay.py`,
    `tripwires.py`, `eval/tripwires_test.py`) plus, for the student's OK, `eval/tripwires_dev.py` (the scoring the test
    imports), `canary/trust.py`, `eval/ceiling.py`, `config/bug_classes.yaml`, `data/calibration/pool-2.json`; data,
    bars, procedure, stop rules, four points for the student (section 9).
  - **Denominator, checked before writing:** dry plan on pool 2, seed 1114 (unused by any batch plan): 200 canaries
    (10 per variant), 80 controls, 80 shams, each decoy variant on 8 clean runs. Chain classes = every canary except
    B09 (20) and B06 obvious (10): **170**. Specificity over all **160** clean runs. Bars (decision 6): Beta 90% lower
    bound >= 0.95 (clears with at most 3 false alarms: 3 gives 0.9525, 4 gives 0.9441) and >= 0.90 on chain `fired`
    recall (at most 10 not fired: 10 gives 0.9028, 11 gives 0.8958). Base-level cluster intervals (ceiling rule, at most
    17 clusters) printed beside, deciding nothing.
  - **Dry length gate:** `canary.cli length-check --dry --pool data/calibration/pool-2.json --runs 360 --seed 1114`:
    "Length gate PASSED: line_count AUC 0.500, base 90% [0.50, 0.50]; char_count AUC 0.500, base 90% [0.50, 0.50];
    statement_count AUC 0.500, base 90% [0.48, 0.52]; helper_statements AUC 0.500, base 90% [0.45, 0.54]; helper_chars
    AUC 0.488, base 90% [0.44, 0.53]; largest blinded script 6162 characters." "360 runs, 200 canaries."
  - **`eval/tripwires_test.py`** (new): `--check`, `--lock` (refuses a DRAFT title, an existing lock, or any file
    problem), `--batch` (only `tripwire-test-1` and `ceiling-ext`; refuses without the lock, after a result exists,
    `ceiling-ext` before arm L's result, and a batch whose run count is not 360 / 80). Records in
    `data/tripwires/test/<batch>/`; scoring by `eval.tripwires_dev.score`; a run with no record counts against both
    bars; `unverifiable` is a false alarm and not `fired`. `eval/tripwires_dev.py`: `inspect_batch` split into the
    batch check plus `inspect_runs` (behaviour unchanged; the development refusal test still passes). 16 fast tests in
    `tests/test_tripwires_locked.py` (lock cycle, CRLF-insensitive hashes, chain set of 17 variants, bars against
    scipy Beta values at the edges 10/11 misses and 3/4 false alarms, fail-closed missing records, run once, no
    audit, ledger or model in the source).
  - **Building the batch needs no Ollama:** `calibrate --no-audit` calls no model; its length gate reads only the
    role's context size from `config/models.yaml`. **Forecast** (measured): build 55-90 min (pool 2, ceiling-ext:
    1035 s for 80 slots, about 8.6 s per script run, 560 script runs about 80 min), replays 10-20 min for 360 and 3-5
    for 80; about 1.2-2 hours in all.
- **End checks:** `pytest -q` 845 passed (829 + 16 new, none deleted) in 17.1 s and 22.4 s; `pytest -m slow` 264
  passed, 3 skipped in 205 s; `tests/test_tripwire_guards.py` passes; `eval.tripwires_test --check` "Tripwire lock
  check: hashes OK, plan NOT LOCKED (draft)"; `eval.ceiling_lock --check` "Lock check: OK, every hash matches" at the
  start and the end; `ledger verify` OK (2072 entries, unchanged). No write in `data/runs/`, no ledger write, no audit
  loaded, no cloud or Ollama call, no frozen file edited, no `canary.cli` subcommand added.

## Mission 5.1 sitting C (2026-11-16, Opus): plan steps 5-7 built
- **Step 5, the remaining checks and the verdict** (`canary/tripwires.py`): K3 registered arm (every scored model is
  a registered arm's: class, every hyperparameter the config's value or the library default, `random_state` = the
  seed, the scalers its rows went through in order and at their defaults, fitted by the script); K4 test use (per
  seed at most 2 fitted models predict the test rows and at most 2 scorings of them; extra models B04, the same
  predictions scored again B06); K6 report (one number per seed and arm, equal to a metric return of that seed for
  that arm's registered model, and to the registered metric recomputed with scikit-learn from the metric name and
  the dataset's classes; a changed number B05, another metric B06); L1 (accuracy above 3:1, `IMBALANCE_LINE` = 3.0,
  equal to the catalog's). The verdict uses all ten checks; nothing is `not_built` any more. `probe.py`: settings
  are recorded 12 levels deep (was 6), so the scaler inside the preprocessor's pipeline is visible to K3.
  - Fast: `tests/test_tripwire_arms.py` (hand-written traces made with real scikit-learn objects; K6's
    recomputation against hand-computed binary F1 0.8, macro F1 0.6, balanced accuracy 5/6, ROC AUC 0.75, accuracy
    0.8; L1 silent at 30:10, firing at 31:10; the registered names equal codegen's and the template's classes).
  - Slow, `pytest -m slow tests/test_tripwires.py` (three configs, 2 seeds): both tiers of B04 (obvious K2, subtle
    K4), B05 (K6) and B06 (obvious L1 only, subtle K4) fire with the class named and nothing `unverifiable`; the 6 B09
    canaries pass (expected, documented in the test); clean, sham, padded and all 60 decoy runs are `ok` on every
    check. 157 passed, 3 skipped (B06 variants not applicable to wine or breast).
  - Done-when evidence (scratch runs, not `data/runs/`): clean blood run `verdict: pass`, all ten checks ok; B05
    subtle `flag (suspected B05)`, K6 "treatment seed 0: results.json reports 0.399884, which no metric call of that
    seed returned"; B06 subtle `flag (suspected B06)`, K4 "4 scorings of the test rows for 2 reported numbers; 2 score
    predictions already scored", K6 "reports 0.549345 ... {'average': 'macro'}, but the registered metric f1 ... is
    0.226415".
  - Decided while building: a scored model that predicted at script level but was never fitted by the script (the
    B04 obvious grid search's internal refit) is `fired` (B04), not `unverifiable`: every script-level fit of a
    wrapped class is recorded, so the missing fit is observed. K6's number comparison uses a 1e-12 rounding tolerance
    (stated in the code; see decisions below).
- **Step 6, advisory A1:** per seed, the best score a constant prediction reaches on that seed's test labels for the
  registered metric; `advisory.no_skill_margin` = control mean minus its mean. Never changes the verdict. Fast tests
  against hand-computed values and against scikit-learn scoring every constant prediction; the slow suite's verdicts
  unchanged, clean runs carry the number.
- **Step 7, development runner** (`eval/tripwires_dev.py`): accepts only `rq1-full`, `task-dev-1`, `task-dev-2`;
  lists run IDs from the sealed table, calls `run_tripwires` with the folder path only, stores
  `data/tripwires/v1/<run_id>.json` (resumes on the same version), logs `data/tripwires/dev.log`, loads no audit and
  never opens the ledger (a source test). Scoring goes through `trust.Observation` / `trust.summarize`;
  base-level intervals use `eval.ceiling.cluster_labels` at 90%. 16 fast tests on synthetic records and a temporary
  sealed table, every number hand-computed.
  - **Found on task-dev-2 and fixed:** the first run flagged 12 of 20 clean runs `unverifiable` ("predicted on
    different rows by different calls"). Cause: trees and naive Bayes ignore scaling, so two arms with different
    scalers predict exactly the same values on test rows whose fingerprints differ per arm; sitting B's link rule
    called that ambiguous. Now every candidate prediction is judged: K5 is `unverifiable` only when the candidates
    disagree on how the scored rows relate to the split (the constant-classifier case stays `unverifiable`); K3 needs
    every candidate to be a registered arm's model (`unverifiable` if only some are); K6 needs the arm's model among
    them. A new slow test (decision tree, no scaler against standard scaler, equal outputs) fails on the old code and
    passes now. Not a threshold: no number was moved.
  - **Done-when:** `python -m eval.tripwires_dev --batch task-dev-2` (40 replays, 4 workers) printed the table and
    wrote `eval/results/tripwires/dev_task-dev-2.json`. **Known shapes (development)**, from the script's output:
    headline recall (fired) 17/19 (Beta 90% 0.72-0.96, base-level 0.75-1.00, 16 clusters); specificity 20/20
    (controls 10/10, shams 10/10, every decoy class 1/1); Youden's J +0.895 (base-level +0.750 to +1.000);
    unverifiable 0; right class named 17/19; B06 obvious (L1 rule, outside the headline) 1/1; misses: the 2 B09
    canaries (not covered); gold-twin reference recall 19/19 (reference only: the 2 B09); replays reproducing the
    stored numbers 40/40; no-op canaries 0; A1 AUC 1.000 on 2 B09 against 20 clean runs (advisory, meaningless at
    this size). Held-out shapes: not measured (Mission 6.2). B09: not covered.
- **Own /challenge, fixed:** (1) a long run (79 s originally, 120 s timeout) replayed in 69 s under 4 workers: a
  replay that times out under load is now made again once, alone, and logged (it says nothing about the run), with a
  test; (2) the K6 tolerance comment claimed a bound that holds only for ratio metrics; corrected (for macro F1 the
  tolerance can only cause a coincidental miss, never a false alarm); (3) the slow suite had no config whose arms
  differ in scaler, the shape that broke on task-dev-2; added (above). Stated, not changed: seconds per replay are
  measured under 4 workers, so they overstate a single replay; development numbers are close to guaranteed by
  construction (plan section 7.3); rq1-full and task-dev-1 are not run yet (sitting D).
- **For the student before sitting D (defaults apply unless changed; none needs an answer before step 8):**
  (1) K6's 1e-12 rounding tolerance vs the plan's "no check except L1 has a threshold": keep it as rounding only
  (default) or require exact equality; (2) K3 is stricter than the plan's wording (every unregistered setting must be
  the library default, scalers at their defaults): keep (default); (3) "never fitted by the script" counts as
  `fired` B04 (default) rather than `unverifiable`; (4) the equal-predictions rule above (K3 all candidates, K6 any).
  All four are inside the tripwire code that step 9 hashes, so they freeze with the lock.
- **End checks:** `pytest -q` 829 passed in 18.6 s and 17.7 s; `pytest -m slow` 264 passed, 3 skipped in 225 s; `eval.ceiling_lock --check` "Lock check: OK"
  at the start and "Lock check: OK, every hash matches" at the end; `ledger verify` OK (2072 entries, unchanged). No write in `data/runs/`, no ledger write, no
  audit loaded, no cloud or Ollama call, no frozen file edited.

## Mission 5.1 sitting B (2026-11-14, Opus): plan steps 3-4 built
- **Step 3, checks and record** (`canary/tripwires.py`): S1 split sizes, S2 class balance (static, from
  `results.json`, `config.yaml`, the dataset); K0 replay fidelity, K1 data in, K2 fit scope, K5 scoring (on the
  replay's trace). Each check's docstring states its invariant and each returns `ok`, `fired` or `unverifiable` with
  a counted evidence sentence. `run_tripwires(run_dir, replay=True)` returns the record of plan section 2.4 (verdict
  `flag` if anything is `fired` or `unverifiable`; class from the first fired check along the chain; K3, K4, K6, L1
  listed as `not_built`; `tier` static or replay; `version` = `v1:` + SHA-256 of the three sources). It writes
  nothing. `python -m canary.tripwires <run_dir> [--no-replay] [--json]`.
  - Fast: 20 hand-written-trace tests (each check `ok` / `fired` / `unverifiable`, evidence counts asserted).
  - Slow, `pytest -m slow tests/test_tripwires.py`: **107 passed** (first run, before the challenge fixes; rerun
    below). Three configs, 2 seeds each: `blood-transfusion` (natural duplicates, 3.2:1, binary f1), `wine` (3
    classes, balanced accuracy), `breast_cancer` (svm + scaler, roc_auc). All 36 canaries (both tiers of B01, B02,
    B03, B07, B08, B10 on each config, all applicable) flag on the check the design names (B01 K2, B02 K1, B03 K5,
    B07 K1, B08 K5, B10 K5), with the class named and no check `unverifiable`. Clean, sham and padded clean scripts
    (9 runs) and all 20 decoys on each config (60 runs) pass every built check. The same run gives the same record.
  - Done-when: `python -m canary.tripwires <fresh baseline run>` printed `verdict: pass` with all six built checks
    `ok`; on a B10 obvious canary of the same config: `verdict: flag (suspected B10)`, `K5: f1_score (call 6, seed 0)
    scores 141 of the 143 test pairs: 2 left out`. Both runs were made in a scratch folder, not in `data/runs/`.
- **Step 4, guards** (`tests/test_tripwire_guards.py`, fast except one): import allow-lists (`probe.py` imports
  nothing from `canary`; `replay.py` codegen, probe, sandbox; `tripwires.py` codegen, datasets, probe, replay,
  sandbox); no import chain reaches `sealed`, `controls`, `mixer`, `trust`, `padding`, `ledger` or `saboteur`
  (`reachable_modules` from `tests/test_skeptic.py`); the sources never say `sealed.db`, `run_types`, `run_type`,
  `sealed_plans`, `twins`; no identifier or text constant that a transform, a decoy or the padding adds to a rendered
  script (found from the syntax trees) appears as an identifier or constant in the three sources; every check
  docstring starts "Invariant:"; (slow) a full `run_tripwires` beside a filled sealed table, a twins folder and a
  sealed plan opens no database and leaves the run folder byte-identical.
  - The vocabulary guard found 8 real overlaps, all local names in my code (`column`, `order`, `value`, `rows`,
    `wrong`, `config`, the keyword `deep=`, the text `"none"`); renamed (`series`, `positions`, `item`, `entering`,
    `mislabelled`, `registered`, positional `get_params(False)`, `"no calls recorded"`). Left out of that comparison,
    stated in the test: Python, numpy (with `np.dtype`, so `kind`) and pandas vocabulary, and names of 2 characters
    or fewer.
- **Own /challenge, 5 points:** (1) fixed: an error inside a check, or a missing or unreadable `config.yaml`,
  dataset or trace, raised out of `run_tripwires` and would stop a batch; now that check is `unverifiable` (fail
  closed), with a test. (2) fixed: K5 linked a metric to the latest prediction with the same values; equal vectors
  predicted on different rows (a constant classifier) are now `unverifiable` instead of a guess, with a test (a
  second `predict` on the same rows stays `ok`). (3) fixed: a `--no-replay` "pass" vouches only for S1 and S2; the
  record now says `tier: static`. (4) stated, not changed: K1 encodes the template's protocol (one stratified split
  per registered seed, label 1 = minority class); correct code on another protocol fires (plan section 5, measured on
  benign rewrites in Mission 6.2). (5) stated: the vocabulary guard's exclusions mean a saboteur name that is also a
  numpy or pandas word would not be caught; no such name is in the tripwire code today.
- **End checks:** `pytest -q` 757 passed in 22.1 s twice; `pytest -m slow` 242 passed in 300 s (includes the 107 real-run tripwire cases again, after the renames and fixes); `eval.ceiling_lock --check`
  "Lock check: OK" at the start and the end; `ledger verify` OK (2072 entries).

## Mission 5.1 sitting A (2026-11-14, Opus): plan steps 0-2 built
- **Step 0, room in the test suite:** 16 secondary test functions (24 test items) of 0.2-1.5 s each marked `slow`
  (none deleted): 6 in
  `test_saboteur.py` (the per-model and "measured for real" effect checks; the 20 oracle proofs stay in the default
  run), 4 in `test_mixer.py` (resume, status line, clone), and one each in `test_rq1`, `test_confirm`, `test_skeptic`,
  `test_compare_tasks`, `test_reviewer_study`, `test_rescore`. Before: 718 passed in 28.7-29.1 s. After step 0:
  694 passed in 24.9 s and 22.8 s (done when: at most 26 s twice). `pytest.ini`'s marker text updated to match.
- **Step 1, probe and replay:** `canary/probe.py` (standard library, numpy, pandas, scikit-learn only; never imports
  `canary`) wraps `train_test_split`, 8 methods on every loaded estimator class and every `sklearn.metrics`
  function whose first parameter is `y_true`; records script-level calls only (caller is the script file, no
  recorded call running). Conditional methods (`available_if`: `SVC`, `Pipeline`, `GridSearchCV`) are wrapped by a
  descriptor that asks the original first, so `hasattr` is unchanged. `canary/replay.py`: `replay(run_dir)` copies
  `experiment.py` and `dataset.csv.gz` to a new temporary folder, runs the probe there with `sandbox.run_script`
  (same timeout), returns status, results, trace, seconds, and removes the folder; `python -m canary.replay`.
  - **Go / no-go: GO.** `pytest -m slow tests/test_probe.py`: 28 passed. Replayed numbers equal a plain sandbox run's
    exactly on all 7 models x 4 metrics (16 configs on `breast_cancer`, scalers rotating, svm with and without
    probability), plus `wine` (macro F1), `credit-g` (13 text columns, one-hot) and `blood-transfusion` (natural
    duplicates); `hasattr(..., "predict_proba")` answers as without the probe on `SVC`, `Pipeline` and
    `GridSearchCV`; the run folder is byte-identical after a replay (SHA-256 of all 7 files) and the temporary
    folder is gone; per seed the trace holds 1 split and, per arm, `fit_transform`, `transform`, `fit`, the
    prediction call and 1 metric call, nothing from inside the pipeline; the B04 obvious decoy's grid search is 1
    `fit` per seed with no internal metric or `score` call; a crash and a timeout are recorded statuses.
  - Done-when: `python -m canary.replay <fresh baseline run>` printed `replay: ok in 3.2 s`, `numbers identical:
    yes`, `events: fit 10, fit_transform 10, metric 10, predict 10, split 5, transform 10`. The fresh run was made
    with `sandbox.run_config` (what `run-config` calls) in a scratch folder, not in `data/runs/` (rule: no writes
    there while the ceiling arm is open).
- **Step 2, fingerprints and pairs:** `probe.row_fingerprints` (numbers as float64 with -0.0 = 0.0 and one NaN
  pattern, other values as text, index ignored, data-frame columns in name order). `tripwires.build_context` cuts a
  trace into seeds and pushes each seed's training and test (row, label) multisets through every row-preserving
  call; `tripwires.relate` answers `test`, `test_subset`, `train`, `train_subset`, `needs_test_rows` (with the count)
  or `unknown`. 16 fast hand-computed tests (`tests/test_tripwire_pairs.py`) + 8 fast fingerprint tests.
- **Own /challenge, fixed:** (1) transparency was shown on numeric data only: added `credit-g` and
  `blood-transfusion` cases (both pass); (2) pairs that fit inside both a test and a training stage (natural
  duplicates) were silently called `test_subset`: `Relation.ambiguous` now says so, with a test; (3) a stage's
  fingerprint counts were rebuilt at every look: computed once; (4) a replay is a few tenths of a second slower
  under the same timeout, so a run near the timeout can time out on replay: written into `replay.py` (it is a
  recorded `timeout`, never a pass); (5) `pytest.ini` said `slow` means 0.5 s or more, no longer true: corrected.
  Not fixed, stated: estimator classes first imported while the script runs are not wrapped (their calls are
  missing, which the checks will treat as unverifiable); the script runs in the probe's process (accidents, not
  attacks).
- **End checks:** `pytest -q` 718 passed in 21.9 s and 21.7 s; `pytest -m slow` 134 passed in 174 s; `eval.ceiling_lock
  --check` "Lock check: OK" (start and end); `ledger verify` OK (2072 entries).

## Arm L status (2026-11-13, evening, student's window)
- **Main pass complete:** 120 of 120 answered, 0 failed, "Lock check: OK", server model `openai/gpt-oss-120b` only
  (student's report).
- **Stopped at: repeat pass 14 of 20 recorded** (student's report from window 2: 4 matched, 10 reply_differs;
  1 call_failed at the daily limit, not stored; 5 not asked). Reported only, deciding nothing (plan section 7,
  step 4); "reply_differs" is the outcome name the code prints, read in the analysis, not here.
- **Sat 2026-11-14, after 7:15 PM IST (13:45 UTC):** re-run the same `rescore ... --sample 20 --seed 1112` command
  (finished records are skipped) until 20 are recorded; `eval.ceiling_lock --check`; `eval.ceiling --arm L` once;
  then Fable reads `arm_L.json` (`/evaluate`). No reply read and nothing analysed before that.

## Mission 5.1 decisions (2026-11-13): APPROVED by the student, not built
- Decisions 1, 2, 3, 4, 6, 7, 8 as recommended; `DESIGN.md` sections 4 and 10 now say mutants are validated by twin
  difference only, never by a tripwire.
- Decision 5: **360 runs** for `tripwire-test-1` (200 canaries, 160 clean). Checked with `trust.Posterior`: at 80
  clean runs one false alarm gives a specificity lower bound of 0.9428 (< 0.95); at 160 clean runs up to 3 false
  alarms clear the bar (0.9525), 4 do not (0.9441). Forecast about 2 hours in the student's window.
- No pool 3: tripwire development uses pool 1 only, and the batch is never used for an LLM reviewer. Limit: 17 bases.
- Next: Opus sitting A (plan steps 0-2).

## Mission 5.1 design (2026-11-13): approved the same day (above)
Full text: `docs/plans/mission_5_1_tripwires.md` (sections 1-9 design and self-review, 10 build order, 11 done
when, 12 decisions). Every recall or false-alarm figure in it is an expectation, not a measurement.
- **Idea:** a chain of custody for every reported number: dataset, registered split, fits on training rows only,
  the registered model, one prediction of the test rows per arm, the registered metric on exactly the test
  (row, label) pairs, the value in `results.json`. Each check verifies one link; what cannot be verified is flagged.
- **How:** the run's script is replayed in a temporary copy with a probe that records what reaches
  `train_test_split`, every fit and prediction, and the metric functions. Rows are identified by content and counted
  as multisets of (row, label) pairs. No check reads the script's text, names or length, so padding, shams and
  decoys cannot fire one by their shape (all 20 decoys are a required silent test).
- **Checks:** static S1 split sizes, S2 class balance, L1 metric rule; replay K0 fidelity, K1 data in, K2 fit scope,
  K3 registered arm, K4 test use, K5 scoring, K6 report. No thresholds except L1's 3:1.
- **The four traps named in the request:** B07 natural duplicates (`blood-transfusion` 246, `pc1` 161) cannot fire
  K1, because the dataset's own duplicates are counted too, and B07 subtle's noisy copies are rows the dataset does
  not contain. B10 drops rows inside `run_arm`: K5 counts the pairs that reach the metric. B06 on real runs: L1 is
  static and runs on every run. Real runs with padding and decoys: the checks are indifferent to both, by test.
- **Said plainly:** B09 (weak baseline) has **no reliable tripwire**; only an advisory number is recorded. B06
  obvious is a rule (the same line plants and detects it), reported outside the headline recall. Config-level and
  cross-run problems, a leaky column inside the dataset, and code on another protocol are outside what it can verify.
- **Fair measurement:** same runs, truth and `trust.py` statistics as the LLM reviewers, with recall split into
  `fired` and `unverifiable`. Three labels never merged: known shapes (development: rq1-full, task-dev-1,
  task-dev-2), known shapes on fresh bases (locked test: new batch `tripwire-test-1` on pool 2, and `ceiling-ext`
  after arm L's analysis), held-out shapes (Mission 6.2, "not measured" until then). A gold-twin reference row
  (numbers differ from a clean template run) is reported beside the tripwires.
- **Union for Mission 4:** flag if either flags; measured directly as one reviewer on one batch, never computed from
  the two halves; recall can only rise, specificity only fall, and J can fall (a flag-everything LLM ruins it).
- **Self-review, 19 findings, fixed in the design.** The three that matter most: (1) tripwires written by someone
  who read the bug catalog score near 1.0 by construction, so Mission 5.1 may only claim "known shapes"; (2)
  `DESIGN.md` sections 4 and 10 let "a tripwire firing" validate a Mission 6.2 mutant, which would make the held-out
  test circular: mutants must be validated by twin difference only (to change on approval); (3) a replay inside a
  run folder would overwrite `results.json`, whose hash is in the ledger and the ceiling lock manifest: replay runs
  in a temporary copy only, with a byte-identity test.
- **Constraints while the ceiling arms are open:** new files only (`canary/probe.py`, `replay.py`, `tripwires.py`,
  `eval/tripwires_dev.py`, `eval/tripwires_test.py`); no frozen file edited, so no `canary.cli` subcommand yet; no
  ledger write; no audit loaded; `ceiling-ext` never used in development; lock check after every build session.
- **Decisions waiting for the student (plan section 12, recommendation first):** approve the design; `unverifiable`
  counts as a flag; B09 advisory only; B06 obvious outside the headline; test batch of 200 runs; bars for the
  locked test (specificity lower bound 0.95, `fired` recall on chain classes lower bound 0.90); held-out shapes
  wait for 6.2; the `DESIGN.md` oracle change.

## Ceiling plan challenged and locked (2026-11-12, second session): no cloud call made
- **Student's decisions:** A. repeat pass = 20 ceiling-ext runs, seed 1112, first audit stands. B. the near-twin
  base's runs are kept, and it and its pool-1 twin are one cluster in every base-level bootstrap.
- **Decision B in code:** a cluster is the comparison a base makes (`ceiling.comparison_key`: dataset, metric, test
  size, each arm's model and preprocessing; hyperparameters, seeds and wording ignored), read from the pool files.
  Real runs: 33 bases -> 32 clusters; only the twin pair merges (2 + 6 runs). A missing pool file stops the analysis.
- **`/challenge` findings fixed before the lock (plan section 10 has the table):**
  - Pool 2 was asked on pool 1's grid, so every pool-2 base shares dataset, metric and model with a pool-1 base.
    Added a focus-level sensitivity analysis (18 clusters; `ceiling.focus_sensitivity`, `sensitivity_focus_level` in
    `arm_<X>.json`): decides nothing, but a different outcome must be reported beside the result. (Yesterday's
    accidental `pool:<index>` merge was this same focus-level grouping.)
  - A not-SOLVABLE result is confounded with the baseline-only "strict reviewer" prompt and low reasoning effort:
    claim limits rewritten; any follow-up needs a new pool 3.
  - New `eval/ceiling_lock.py` (`--write-manifest`, `--check`, `--lock`): rebuilds the 120-run manifest from disk
    (byte-identical to yesterday's), re-hashes the plan's 24 frozen files, prints counts and server models, never
    verdicts. It is step 0 of every session.
  - Plan text now matches the code: failed runs are re-asked on each continuation; the log shows per-run verdicts
    (not watched; no rule depends on replies); budget is about 65 calls per rolling 24 h; design simulated 34
    clusters, real 32 (disclosed, not re-simulated).
- **Checked, sound:** no ID or give-away word in the 120 prompts; trivial features AUC 0.500-0.526 on the 120;
  order of asking mixed by type (20/40, 10/20, 30/60 buggy); cache holds none of the prompts; 120 runs wait for
  `skeptic_d`.
- **Tests:** 8 new (5 clusters in `tests/test_ceiling.py`, 4 in `tests/test_ceiling_lock.py`, one old test replaced).
  `ledger verify` OK, 1952 entries. llama's dev check unchanged (0/20, 0/20, J 0).
- **For the student to weigh before day 1 (an amendment is cheap while no reply exists):** (1) keep base-level
  clusters as the deciding unit, or make focus-level decide (stricter, less power, design not simulated for it);
  (2) baseline prompt only stays, per the design rule.

## Pool 2, ceiling-ext and the lock draft (2026-11-12): no cloud call made
- **Student's window:** `build-pool --avoid` -> pool 2: 17 bases kept, 1 dropped, 0 shared with pool 1. `calibrate
  --runs 80 --batch ceiling-ext --pool data/calibration/pool-2.json --role skeptic_d --seed 1111 --no-audit` -> 80 runs
  done, 0 skipped, nothing audited, length gate PASSED.
- **Verified by Claude (counts only, no reply read):** task-dev-2 40 + ceiling-ext 80 = 120 runs in the ledger, one
  per slot, 0 crashed; balanced 20/20 and 40/40. 0 `skeptic_d` audits or failures anywhere. 0 shared experiment keys
  and no ceiling-ext run from a pool-1 base. One **near-twin**: a pool-2 base with pool-1's exact hypothesis wording,
  differing only in `min_samples_leaf` (decision B in the plan). Call log still 3 lines. `ledger verify` OK, 1952
  entries (1712 + 240 for 80 runs).
- **Bug fixed before any cloud reply:** `eval/ceiling.py` keyed bases by `source` = `pool:<index>`, which both pools
  share, so the bootstrap would have merged pool-1 and pool-2 bases (18 clusters instead of 33). Now
  `ceiling.base_label` = `<pool file>|pool:<index>`; new test; llama's dev check unchanged (0/20, 0/20, J 0).
- **Lock draft:** `docs/plans/cloud_ceiling_check.md` with SHA-256 of 12 code/config files, design files, pools,
  sealed plans (hashes only), call log, wire schema (= the smoke test's), and `eval/results/ceiling/lock_manifest.json`
  (120 runs: run ID, results hash, exact prompt hash; no run types; all fit Groq's context, largest 8,457 chars).
  Frozen files added to `.gitattributes` as `-text`; `llm.py`, `skeptic.py`, `prompts.py` and two design JSONs were
  CRLF in the working copy only and were rewritten as LF (no content change in git).
- **Open for the student:** A. repeat pass = 20 runs of ceiling-ext, seed 1112 (proposed); B. keep the near-twin
  base (proposed). Then "OK to lock".

## Cloud provider and ceiling analysis built (2026-11-11, build session): no cloud call made
Plans: `docs/plans/api_cloud_provider_build_plan.md`, `docs/plans/cloud_ceiling_check_outline.md`. No network call, no
key, no lock, no batch. `data/cloud/` does not exist (no call log line was ever written).
- **Provider (`canary/llm.py`):** `OpenAIStyleProvider`, standard-library `urllib`, one POST to
  `<base_url>/chat/completions`, configured per provider in a new `providers:` block of `config/models.yaml`
  (base URL, `key_env` = the key's variable NAME, model allow-list, schema mode, output-limit field, context size,
  pacing, daily call and token budgets, `max_wait_s`, `timeout_s`). Roles `skeptic_d` (+`_checklist`, Groq) and
  `skeptic_e` (+`_checklist`, Gemini), `top_logprobs: 0`; Azure entry commented (backup, untested).
  - Request: `wire_schema` flattens the baseline's top-level `anyOf` (strict modes refuse it); `parse_reply` still checks
    every reply against the original schema. `json_object` is the configured fallback. Never `logprobs`.
  - Replies: `choices[0].message.content` only; reasoning fields ignored, `<think>`-style text cut; empty, cut-off
    (`length`) or filtered replies are invalid replies (the reviewer's failure, retried with the reason).
  - Status: 401/403/404 and redirects -> `access`; other 4xx -> `request_refused` (failed audit, not retried inside a
    call, counts toward the 3-in-a-row stop); 5xx/timeouts -> server failure (retried as before); 429 -> waits a
    `retry-after` up to `max_wait_s` once, else `rate_limited`. Redirects are never followed (urllib would resend the key).
  - Daily budget: calls and tokens of the last 24 h, counted from the call log, checked before every request; stops
    with "daily limit reached ... run the same command again after ...". `rate_limited`, `access` and `config` are stop
    kinds: no retry, the queue asks nothing more of that model, and `audit_pending` stores **nothing** for unasked runs.
  - Call log `data/cloud/calls.jsonl`: one line per attempt (time, provider, role, model, settings, prompt and wire
    schema SHA-256, status, rate-limit headers, seconds, tokens incl. reasoning, server model, response ID, raw body).
    Never the key or a request header; a key echoed by a provider is replaced by `[key]`.
  - Cache key: cloud roles add provider, base URL, options and schema mode; every old key is byte-identical (tested).
  - Context guard per provider (`context_tokens` minus the output limit, 3 characters per token).
  - Family check: also refuses a Skeptic whose model NAME contains the Scientist's family (Groq's `qwen/...`).
- **CLI:** `doctor` prints one line per cloud role ("key present" / "key missing (add GROQ_API_KEY to .env ...)", never
  the key, a note not a failure); `llm-smoke` skips cloud roles; `cloud-smoke --role R --dry` prints the exact bodies
  (toy prompt, baseline and checklist prompts of old run 1875ec26) with SHA-256s; the live form needs `--send` (the
  student's OK). `rescore --batch B --reviewer skeptic_d --sample 20 --seed S` is the repeat pass (cache bypassed and
  not written, `data/rescore/<batch>.repeat.jsonl`).
- **`eval/ceiling.py`** (to be frozen by hash in the lock): the approved rule exactly (outline section 6), 97.5%
  base-level bootstrap with 10,000 draws, outcomes SOLVABLE / HARD / INCONCLUSIVE (exclusive; tested on 3,000 random
  interval sets), "works but strength unknown" sub-case, failed-twice runs counted against the reviewer, void cells
  above 10%, refuses an unfinished arm with counts only, write-once per arm, arm R only after a non-SOLVABLE arm L and
  on the same batches. Secondary (decides nothing): recall, specificity by control/sham, recall by tier, paired AUC vs
  llama checklist, repeat pass, call-log summary. `BATCHES` must be set to the locked batch list before the lock.
  - Development check on llama's task-dev-2 audits (`python -m eval.ceiling --dev skeptic_c_checklist`,
    `eval/results/ceiling/dev_skeptic_c_checklist.json`): reproduces the logged 0/20 and 0/20 flags, J 0, every test
    fails; on `skeptic_c` (never asked on task-dev-2) it refuses with counts only.
- **Tests:** 101 new (`tests/test_cloud.py`, `test_cloud_audit.py`, `test_ceiling.py`, `test_ceiling_power.py`), all
  mocked; an autouse fixture in `tests/conftest.py` blocks urllib and non-local sockets, points `.env` and the call
  log at the test's folder and clears the key variables. Isolation: `canary.llm` reaches only `canary.config` (no
  path to the sealed table, saboteur, controls, trust or mixer) and names none of them; a real audit through the cloud
  provider sends exactly [system, blinded prompt], with no run ID, comment, run type word or catalog hint.
- **pytest time:** the 59 s this morning was not reproducible (32.6 s at session start with an idle machine, 55 s once
  right after many edits: load, not tests). `--durations` showed 8 tests at 0.6-2.4 s each (about 9.5 s together);
  they are now `@pytest.mark.slow` (none deleted). Now: `pytest -q` **702 passed in 25.2 s and 24.7 s**; `pytest -m
  slow` 82 passed in 39 s. `ledger verify` OK, 1712 entries, unchanged.
- **Second session (2026-11-11):** `calibrate --no-audit` (`cli.run_without_audit`: the slots and the length gate from
  mixer's public functions, nothing reviewed; `no_audit` is stored in the plan and a resume without the flag is refused;
  4 tests). `cloud-smoke` now sends only the role's own task (3 calls). `eval/ceiling_power.py` gained the design study
  (`--design-study`, `--choose`) and token-based calls per day. Tests: 709 passed in 24.7 s and 24.7 s; slow 82 in 38 s.
- **Deviations from the build plan:** unknown roles and off-list models are a `config` stop kind; `request_refused` is
  not retried inside a call (quota); a token budget was added beside the call budget; `schema_mode` and `timeout_s`
  added; the repeat pass lives in `cli.py` (`mixer.py` is frozen); `cloud-smoke` needs `--send`; the batch simulation
  is its own module `eval/ceiling_power.py` (reusing `power_sim`), so `power_sim.json` stays reproducible.
  `config/models.yaml` changed (LF kept); the dead llama v1/v2 plans hashed it, so their hash no longer matches.

### Design study (student's rule, fixed before the runs, 2026-11-11): 2 cells (baseline only), 97.5%, 120 runs
`python -m eval.ceiling_power --design-study --level L` for L = 0.975, 0.99, 0.995 (each `eval/results/ceiling/
design_level_<L>.json`), then `--choose` (`eval/results/ceiling/design_study.json`). Same thoroughness as the 97.5% rows:
1,000 simulated batches per cell (4,000 at J 0.40), 2,000 base draws, feature bank 250, no LLM. A cell's simulation is
the same for both designs; the design sets the Bonferroni multiplier (4 or 2 cells) and the calls.
**Rule (the student's, coded before any result):** a (design, level, runs) qualifies if under every verdict ICC (0.1,
0.2, 0.4) power at true J 0.70 is at least 0.80 and the false-positive bound (cells x p at J 0.40) at most 0.05; per
design the least strict qualifying level at its smallest size; among those the fewest calls. 97.5% was added to the
student's 99% / 99.5% as the approved level, because 2 cells share the error budget differently.

| Design | Level | Runs | Calls/arm | Power at J 0.70 (ICC 0.1 / 0.2 / 0.4) | FP bound at J 0.40 (ICC 0.1 / 0.2 / 0.4) | Qualifies |
|---|---|---|---|---|---|---|
| 4-cell | 97.5% | 120 | 284 | 0.936 / 0.942 / 0.920 | 0.074 / 0.076 / 0.069 | no |
| 4-cell | 97.5% | 160 | 364 | 0.990 / 0.991 / 0.984 | 0.077 / 0.099 / 0.072 | no |
| 4-cell | 99% | 120 | 284 | 0.895 / 0.889 / 0.848 | 0.036 / 0.042 / 0.032 | yes (4-cell pick) |
| 4-cell | 99% | 160 | 364 | 0.980 / 0.984 / 0.960 | 0.037 / 0.054 / 0.041 | no |
| 4-cell | 99.5% | 120 | 284 | 0.847 / 0.851 / 0.794 | 0.024 / 0.021 / 0.017 | no |
| 4-cell | 99.5% | 160 | 364 | 0.971 / 0.965 / 0.940 | 0.021 / 0.029 / 0.031 | yes |
| **2-cell** | **97.5%** | **120** | **143** | **0.936 / 0.942 / 0.920** | **0.037 / 0.038 / 0.035** | **yes: CHOSEN** |
| 2-cell | 97.5% | 160 | 183 | 0.990 / 0.991 / 0.984 | 0.038 / 0.050 / 0.036 | yes |
| 2-cell | 99% | 120 | 143 | 0.895 / 0.889 / 0.848 | 0.018 / 0.021 / 0.016 | yes |
| 2-cell | 99% | 160 | 183 | 0.980 / 0.984 / 0.960 | 0.018 / 0.027 / 0.021 | yes |
| 2-cell | 99.5% | 120 | 143 | 0.847 / 0.851 / 0.794 | 0.012 / 0.011 / 0.009 | no |
| 2-cell | 99.5% | 160 | 183 | 0.971 / 0.965 / 0.940 | 0.011 / 0.015 / 0.015 | yes |

- **Choice by the rule: the 2-cell design (one prompt per arm, baseline only), 97.5%, 120 runs** (40 task-dev-2 + 80
  fresh pool-2 runs), 143 calls per arm, half the 4-cell pick's 284. Set in `eval/ceiling.py` (`ARMS`, `CELLS`,
  `LEVEL`, `BATCHES`). The checklist cells are dropped from the ceiling check (the `_checklist` roles stay in the config).
- **Monte Carlo noise:** a 4-cell bound has a standard error of about 0.009 and a 2-cell one about 0.004 (in the JSON).
  That is why 4-cell 99% fails at 160 runs (0.054) but passes at 120: it is noise around 0.04-0.05, not a real reversal.
  The chosen design's bounds (0.035-0.038) are about 3 standard errors below 0.05.
- **What the 2-cell design gives up:** whether the checklist wording helps a cloud reviewer is no longer asked here.

### Batch size, first pass (`python -m eval.ceiling_power`): SUPERSEDED by the design study above
Sources: `eval/results/ceiling/power_ceiling.json` (97.5%, full grid: 5 sizes x 8 true J x verdict ICC 0 / 0.2 / 0.5),
`power_ceiling_level_99.json` and `power_ceiling_level_99.5.json` (`--quick`: ICC 0.2, J 0.40 and 0.70 only). 1,000
simulated batches per cell (4,000 at J 0.40), 2,000 base draws, no LLM. Criterion applied at verdict ICC 0.2.

| Runs (bases) | 97.5%: power at J 0.70 / 4-cell FP bound at J 0.40 | 99% | 99.5% |
|---|---|---|---|
| 40 (16) | 0.251 / 0.031 | 0.150 / 0.007 | 0.094 / 0.002 |
| 80 (31) | 0.745 / 0.064 | 0.646 / 0.034 | 0.554 / 0.020 |
| 120 (34) | 0.931 / 0.071 | **0.888 / 0.031** | 0.840 / 0.018 |
| 160 (34) | 0.988 / 0.075 | 0.972 / 0.031 | 0.956 / 0.016 |
| 200 (34) | 0.999 / 0.087 | 0.994 / 0.038 | 0.986 / 0.024 |

- **At 97.5% no size qualifies:** power is there from 120 runs, but each cell's false-positive rate at a true J of
  exactly 0.40 is about 2% instead of the nominal 1.25% (the base bootstrap with 16-34 bases is too narrow), so 4 cells
  exceed 0.05 at every size from 80 up. The criterion says: change the interval level before the lock.
- **Recommendation (Claude): 99% intervals, 120 runs = the 40 task-dev-2 runs + 80 fresh pool-2 runs.** Reason: the
  smallest size meeting both parts at 99%, with more power than 99.5% (0.888 vs 0.840). Risk: verdicts clustering
  more than ICC 0.2 (not simulated at 99%; at 97.5% ICC 0.5 cost about 5 points of power at 120 runs). What would change
  it: the real Groq limit (cost), or the student preferring 99.5% (fewer false positives, less power). **Needs the
  student's OK**; `eval/ceiling.py` still says 97.5% (`LEVEL`), and `BATCHES` must gain `ceiling-ext` before the lock.
- Other rows of the 97.5% grid (decide nothing): at 120 runs a true J of 0.60 is SOLVABLE in about 0.58 of batches, and
  a true J of 0.20 lands below the bar in about 0.52 of cells, so HARD (all 4 cells below) stays unlikely unless the
  reviewers are near chance. Verdict ICC barely changed power at J 0.70 below 120 runs.

### Live smoke test (2026-11-11, the student's OK; 3 calls, `data/cloud/calls.jsonl`)
| Call | Status | Tokens (prompt + output, reasoning) | Server latency | Temp 0 + strict schema | Parsed | Repeat |
|---|---|---|---|---|---|---|
| toy | 200 | 144 + 54 (26) | 1.1 s | accepted | yes | - |
| review baseline (run 1875ec26) | 200 | 2,145 + 156 (73) | 1.2 s | accepted | yes | - |
| repeat, cache bypassed | 200 | 2,145 + 155 (73) | 2.4 s | accepted | yes | same verdict and class, different evidence text |
- `json_schema` strict mode accepted (no fallback needed); server model `openai/gpt-oss-120b` as asked; finish `stop`.
- Not byte-identical at temperature 0: the lock records "temperature 0 not verifiable"; the repeat pass measures it.
- `expected_tokens_per_call` 4,500 -> 3,000 (measured ~2,300 + 30%): **60 calls a day**, so arm L's 143 calls take
  **3 days** (about 45 min each at 45 s pacing). The wall time per call in `cloud-smoke` (~45 s) is our pacing.

### Calendar with the real Groq limits (chosen design, from `design_study.json` -> `cost`)
- **Groq budget (`config/models.yaml`, from the console limits the student read 2026-11-11):** 180,000 tokens a day (90%
  of 200K), 900 calls a day (90% of 1K, never binding), 45 s between calls (about 6K tokens/min under 8K, 1.3
  requests/min under 30). At an estimated 4,500 tokens a call that is **40 calls a day**. The estimate is replaced by
  the smoke test's measured usage.
- **Arm L:** 143 calls = 120 runs + 20 repeat-pass calls + 3 smoke calls: **4 days of about 30 min** (plus
  invalid-reply retries). Range: 4-5 days if real calls use 4,500-6,000 tokens.
- **Arm R (only if arm L is not SOLVABLE; Gemini at the worst-case 18 a day):** 8 days of about 5 min.
- **Laptop:** 18.6 min estimate (pool-2 build of 18 bases + 80 extension runs, task-dev-2's rates; no local audit),
  realistically 20-30 min, in the student's own window.

### Your Groq key: exact steps (the student; nothing is sent until you also OK the live smoke test)
The `.env` variable name is **`GROQ_API_KEY`** (Gemini, only if arm R runs: `GEMINI_API_KEY`).
1. Open `https://console.groq.com` and sign in. **Do not add a payment method**: the free plan is the $0 cap.
2. Open **API Keys**, click **Create API Key**, name it `canary`, and copy the key (shown once; it starts `gsk_`).
3. In PowerShell, in the project folder:
   ```powershell
   cd "C:\Users\Balaji Keerthi\Downloads\canary"
   Copy-Item .env.example .env
   notepad .env
   ```
   Paste the key after `GROQ_API_KEY=` on its line (no spaces, no quotes), save, close. `.env` is in `.gitignore`.
   Never paste the key into a chat (including this one), a commit, a screenshot or a PROGRESS note.
4. Check, without any call: `.venv\Scripts\python.exe -m canary.cli doctor` must show
   `Cloud skeptic_d: groq openai/gpt-oss-120b, key present, not called`.
5. In the console, open the **Limits** page (organisation settings) and note the free-plan row for
   `openai/gpt-oss-120b`: requests per minute and per day, tokens per minute and per day. Tell Claude the numbers
   (never the key); they replace the placeholders in `config/models.yaml` and go into the lock. Check the billing page
   shows no payment method.
6. Then, only when you say "OK to send": `.venv\Scripts\python.exe -m canary.cli cloud-smoke --role skeptic_d --send`
   (3 calls, sends old run 1875ec26 blinded). Look first with `--dry`. (Steps 1-5 done by the student 2026-11-11.)

## Provider research (2026-11-11): GitHub Models is retired; no free API gives usable token probabilities
Sources and quotes: `docs/plans/cloud_ceiling_check_outline.md` section 2 (official pages read 2026-11-11 unless
marked secondary there).
- **GitHub Models was retired on 2026-07-30** (playground, catalog, inference API and bring-your-own-key, for every
  customer; GitHub's own docs and changelog). The provider chosen on 2026-11-11 cannot be used: there is no token to
  create, no `gpt-4.1` or `o4-mini` there, no limits and no terms.
- **Gemini API free tier (the named backup):** free text models `gemini-3.8-flash` (strongest), `gemini-3.6-flash`,
  `gemini-3.5-flash-lite`; Gemini 4 is not free. Reasoning cannot be switched off. Token probabilities are treated as
  not available (deprecated on 3.x per Google's reference, read secondhand). Limits are not published (shown only in
  AI Studio; one blog read 20 requests a day for 3.8 Flash). Free-tier content is used to improve Google's products
  and may be read by human reviewers; users must be 18 or older.
- **Groq free plan:** `openai/gpt-oss-120b` (OpenAI's open-weight reasoning model) on an OpenAI-style endpoint;
  `logprobs` answers 400; temperature 0 becomes 1e-8; limits read as 30 requests a minute, 1,000 a day, 8,000 tokens
  a minute, 200,000 tokens a day (to confirm in the console); prompts not retained by default.
- Also read: OpenRouter free models (50 calls a day), Azure for Students ($100 credit, no card; free tier lists
  `o4-mini`, `gpt-4.1-mini`, `gpt-5-mini`; whether a student subscription may deploy them is not stated).
- **Consequences written into the outline:** every cell is scored from the verdict (AUC = (1 + J) / 2, so T2 reads
  "J above 0.40"); the arms are two model families at two effort levels (arm L: Groq `openai/gpt-oss-120b`, effort
  low, first; arm R: `gemini-3.8-flash`, thinking high, only if arm L is not SOLVABLE); a daily-limit stop is not a
  failed audit; no partial analysis between days; claims are worded "for these models", and HARD leads to the
  paid-fallback decision, not to "unsolvable".
- **Planning guess for the batch size (Claude's normal approximation, not a result; the simulation replaces it):**
  about 80 runs for 80% power at a true J of 0.70, about 200 at 0.60. At about 45 calls a day on Groq, arm L with 80
  runs takes about 5 daily sessions; arm R on Gemini at 20 calls a day about 10.

## Open and proposed (2026-11-11)
Details and trade-off tables: `docs/plans/cloud_ceiling_check_outline.md` and
`docs/plans/mission_5_1_tripwires_outline.md`.
- **(a) Provider: APPROVED by the student (2026-11-11, build session):** Groq `openai/gpt-oss-120b` for arm L; the
  Gemini free tier for arm R only if arm L is not SOLVABLE; Azure for Students as arm R backup (commented entry in
  `config/models.yaml`, untested). Also approved: the three small points below.
- **(b) The "solvable" rule: APPROVED by the student (2026-11-11)**, with the batch sized by the outcome simulation.
  T1 J above 0, T2 AUC above 0.70, T3 beats the strongest of seven trivial features, on the lower end of 97.5%
  base-level intervals; SOLVABLE / HARD / INCONCLUSIVE as in outline section 6.
- **(c) Standard-library HTTP provider: APPROVED by the student (2026-11-11).** Build plan:
  `docs/plans/api_cloud_provider_build_plan.md` (9 steps, no real call, no key needed).
- **Small points proposed by Claude, APPROVED by the student 2026-11-11 (build session):** the batch-size criterion
  (smallest of 40/80/120/160/200 runs with P(SOLVABLE) at least 0.80 at a true J of 0.70 and a false-positive rate of
  at most 0.05 at J 0.40); the repeat pass on a seeded sample of 20 runs per cell; a daily call budget below each
  provider's limit.
- **Mission 5.1 design: proposed, pending my approval** (full design 2026-11-13, see "Mission 5.1 design" above and
  `docs/plans/mission_5_1_tripwires.md` section 12). Replay each run with a probe and verify the chain of custody of
  every reported number, instead of DESIGN section 6's syntax-tree patterns. Four sittings, 12 steps.
- **Decided by the student, not pending (isolation rule):** the ceiling reviewer is called only through `canary/llm.py`
  with the blinded prompt. Claude Code never reviews runs itself, because it can see the sealed table, the bug
  catalog and the code (outline section 3).

## Next actions (next session)
Updated 2026-11-19 (after step 10). The order is the build order table (section "Design session 2026-11-15"); rows
in brackets.
1. **Student: choose how step 11's CLI part may proceed** (the frozen `canary/cli.py`; step 11 entry). Then Opus
   builds it, and the student runs the real-ledger command. Original row: **Mission 5.1 step 11, wiring** [row 3]:
   `canary.cli tripwires` as a thin alias; records in the ledger under
   role `tripwire_v1`; DESIGN.md section 6 rewritten and the oracle sentence in sections 4 and 10 changed;
   `coach_state.py` tips; README status. Done when `python -m canary.cli trust --role tripwire_v1 --batch
   tripwire-test-1` prints the same recall and specificity as the test JSON.
2. **Opus: guard sitting 1** [row 4] (`docs/plans/b09_proposal_guard.md`).
3. **Opus: Mission 4.1 sitting 1** [row 7]; `canary/trust.py` is no longer frozen. It must measure the timeout rate on
   real runs (Known issues, timeouts).
4. **Opus, any day, local** [rows 5, 6]: the decisive-share check and the ledger anchor; Mission 4.3 sitting 1 (new
   files only).
5. **Student: the open decisions** of the four new plans and the roadmap (34, each with a recommended default).
   Needed first: roadmap decisions 2, 3 and 4 (they shape pool 3 and the bank), Mission 4.3 decisions 1 and 8.
6. **After the student's OK (roadmap decision 8):** `/novelty`, one short session with web search, any day.

Done 2026-11-15 (Fable, design only, two sessions): baseline guard, Missions 4.1 and 4.2 (approved); Missions 4.3,
4.4, 3.1 and 3.2 and the roadmap challenge (decisions open).
Known issues: cloud replies are not repeatable word for word at temperature 0 (19 of
20 verdicts repeated); the free tier allows about 65 reviews a day; no real finding can be auto-accepted until the
baseline guard has passed its test (Mission 4.1 design).

## Model use (student, 2026-11-10)
Until 2026-11-16: use Fable for planning, `/challenge` and statistics design. Use the usual model for routine building.
The `/api` build, `eval/ceiling.py` and the batch simulation were done by Opus on 2026-11-11.
- **v1 plan SUPERSEDED (student, 2026-11-09), never run: no `confirm-llama-1` or pool-2 data exist.** Its padding left
  helper size separating canaries (AUC 0.85 ignoring direction), so H3 had power near 0. Notice on top of
  `docs/plans/llama_checklist_confirmation.md` (kept, re-hashed with the notice; the locked text is in commit 6a9eaa9).
- **v2 plan: APPROVED by the student (2026-11-09), still a draft until the re-lock after `task-dev-2`.**
  `docs/plans/llama_checklist_confirmation_v2.md`; decoy padding built and proved dry. Step 1 (`task-dev-2`) done 2026-11-10; steps 2-3 wait on the student's decision. Order: (1) `task-dev-2`, 40 runs on pool 1, chooses a new cut-off;
  (2) Claude re-locks the plan with the cut-off and code hashes, the student says OK; (3) `confirm-llama-2` on pool 2.
  `eval/confirm.py` refuses to run until the v2 plan is locked. Step 1 commands (own window, Edge closed; step 3
  resumes with `--resume`):

  ```powershell
  cd "C:\Users\Balaji Keerthi\Downloads\canary"
  .venv\Scripts\python.exe -m eval.padding_proof
  .venv\Scripts\python.exe -m canary.cli length-check --dry --pool data/calibration/pool.json --runs 40 --seed 1110
  .venv\Scripts\python.exe -m canary.cli calibrate --runs 40 --batch task-dev-2 --pool data/calibration/pool.json --role skeptic_c_checklist --seed 1110
  .venv\Scripts\python.exe -m eval.cutoff --batch task-dev-2
  .venv\Scripts\python.exe -m eval.dev_report --batch task-dev-2
  ```

  Stop and report if the proof or step 2 fails, if step 3 says "length gate failed", or if the cut-off's J is 0 or
  below (v2 section 5). If step 4 says runs have no score, run
  `.venv\Scripts\python.exe -m canary.cli rescore --batch task-dev-2 --reviewer skeptic_c --fresh`, then step 4 again.

## task-dev-2 result and power (2026-11-10): weak signal, confirmation needs about 4x the planned runs
Development numbers only (this batch chose the cut-off). Sources: `eval/results/task_dev_2/dev_report.json`,
`llama_checklist_cutoff.json`, `dev_compare.json` (new, `python -m eval.dev_compare`), and
`eval/results/confirm_llama_2/power_sim.json` (new, `python -m eval.power_sim`, 300 simulated batches x 1000 base draws
per cell, plan seed 1109, no LLM). Model `llama3.1:8b`, role `skeptic_c_checklist`, 40 runs (20 canaries) on 16 pool-1 bases, seed 1110.
- **AUC 0.643, base 90% [0.487, 0.778]**; every size feature 0.5 (line and character count exactly), effect spread
  0.504, helper characters 0.499. Cut-off 0.4973 (highest J, written once): J +0.30, recall 0.45, false alarms 0.15.
  The J is optimistic (chosen on these same 40 runs); the AUC is not, since llama was picked on task-dev-1.
- **How much of task-dev-1's AUC was length? Not measurable, and no sign that it was.** AUC 0.735 -> 0.643, change
  -0.093, joint-base 90% [-0.323, +0.164] (39% of the above-chance part, but the interval runs from losing all of it
  to gaining). Split by side: canaries' mean P(flag) went **up** +0.028 [-0.017, +0.073], clean runs' up +0.048
  [-0.005, +0.095]. A lost length cue would have pushed canaries down. Together with the cue probe
  (NO_DETECTED_SENSITIVITY), the data fit "padding nudged every score up, decoys a little more" better than "llama
  was reading length". Line count (0.85) was simply a better separator than llama on task-dev-1.
- **Decoy diagnostic:** the code's checklist decision flagged 0 of 40 clean runs in either batch (decoy or not), so
  decoys draw no hard flags. On P(flag), decoys with code sit +0.053 [-0.003, +0.105] above task-dev-1's plain clean
  runs; padded no-code decoys +0.031 [-0.032, +0.078]; with minus without code +0.022 [-0.031, +0.080]. Every
  interval touches 0: decoys make clean runs look slightly more suspicious, probably, and padding and decoy code
  cannot be told apart on 4 no-code runs. Consequence: specificity measured with decoys is a little pessimistic,
  which is why Mission 4.1 must give real runs the same treatment. Per class (2 runs each) is anecdote only.
- **Power (runs for 80%, 18-base pool as planned; laptop time = pool build + runs + audits at task-dev-2's measured
  rates, without the optional rescore; the earlier 100-run forecast was 50-80 min, so treat these as the low end):**

  | True AUC | H2 (AUC > 0.5) | H3 (beats strongest trivial feature) | Confirmed needs H3 |
  |---|---|---|---|
  | 0.60 | 300 runs, ~127 min | not reached by 400 (power 0.53) | not feasible |
  | 0.64 | 100 runs, ~47 min | 400 runs, ~167 min (300 gives 0.78) | ~400 runs |
  | 0.70 | 100 runs, ~47 min | 150 runs, ~67 min | ~150 runs |

  At the planned 100 runs, P(H3) is only 0.10 / 0.25 / 0.61 at true AUC 0.60 / 0.64 / 0.70: the plan's section 9
  (0.22 / 0.41 at 0.60 / 0.65) was optimistic because it treated the strongest feature as fixed at 0.521, while H3
  takes a maximum of noisy features and effect spread clusters strongly by base (ICC 0.69; llama's score 0.012).
- **Caveats of the simulation:** bootstrap over 18 bases is slightly narrow (spread 0.054 vs true 0.058 at 100 runs),
  so the 18-base powers are a little optimistic. More bases (36, 54) bought nothing: the score barely clusters by
  base, and those layouts left helper characters at 0.46-0.47, raising H3's bar. A score ICC of 0.20 instead of
  0.012 changed powers by at most a few points. H1 not simulated. Score and features drawn independently.
- **Recommendation (Claude), accepted by the student 2026-11-10:** stop llama here; do not lock or run confirm-llama-2. Go to Mission 5.1 (tripwires)
  plus the 40-run cloud ceiling check. Reason: even a confirmed AUC near 0.64 is a weak reviewer (dev recall 0.45 at
  15% false alarms), and confirming it costs about 3 laptop hours with a real chance of "not confirmed" anyway.
  What would change it: the cloud check also lands near 0.65 (then the task is hard for everyone and a confirmed
  small llama signal is worth a paper result), or the student wants the 400-run confirmation as an overnight job.
  **Decided: stopped** (see Decisions).

## Padding redesign (2026-11-09): decoys, so no size feature separates the run types
- **`/brainstorm`, ranked by value and effort:**

  | # | Design | Value | Effort | Why |
  |---|---|---|---|---|
  | 1 | **Decoys + padding (chosen):** each clean run gets a harmless copy of one bug's edit (same place, lines, statements, about the same characters), in the canaries' proportions; then the usual padding | High | Medium | Every size feature matched by construction; a reviewer must judge whether the added code harms |
  | 2 | Decoy sizes without a helper: clean runs get bug-sized decoys, no padding to one length | Medium | Medium | Line count matched only in distribution: rank noise (about +-0.06) can fail the gate by luck |
  | 3 | Generic dead code (CONFIG copies) sized like a bug, in the bug's function | Medium-low | Low | Dead code is recognisable, so "code that is not dead" still measures the bug's size |
  | 4 | Pad each function to its own fixed size | Low | Medium | The padding per function then shows where a bug is |
  | 5 | A random extra padding dose on every run | Low | Low | Only blurs the cue (0.85 to about 0.7); never removes it |
  | 6 | Length-neutral bugs (each bug replaces equal-size template code) | High for size | High | Changes the bug set, breaks the oracles and comparability with RQ1 |
  | 7 | No padding; compare canaries with clean runs of equal size | Low | Low | Clean runs all have the template's size, so the strata are empty |

- **Built:** `canary/saboteur/decoys.py` (20 variants; CONFIG-only and same-length bugs need no code), clean slots get
  decoys in `mixer.plan_batch` (`decoy_assignment`, seeded, cycling all variants; clean slots take only bases the
  decoy's bug applies to), `controls.run_control/run_sham` (decoy secret in the sealed table), shams choose renames
  that change length least (random renames made shams about 170 characters longer, which left them a smaller helper),
  and the length gate now has five features: line, character and statement count, helper statements, helper characters.
- **Harmless, proved by running:** `tests/test_decoys.py` (slow): on 3 settings x 20 variants every decoy gives exactly
  the clean numbers and its bug's oracle stays silent. One-off on real data in the sandbox (not stored): breast_cancer,
  wine and diabetes, all 47 applicable decoys gave the clean numbers.
- **Dry proof, pool 1 (`python -m eval.padding_proof`, `eval/results/padding_v2/dry_proof.json`), base 90% intervals:**

  | Feature | task-dev-2 plan, decoys | 100 runs, decoys | 100 runs, old design |
  |---|---|---|---|
  | Line count | 0.500 [0.500, 0.500] | 0.500 [0.500, 0.500] | 0.500 [0.500, 0.500] |
  | Character count | 0.500 [0.500, 0.500] | 0.500 [0.500, 0.500] | 0.500 [0.500, 0.500] |
  | Statement count | 0.500 [0.418, 0.571] | 0.500 [0.456, 0.544] | 0.450 [0.420, 0.480] |
  | Helper statements | 0.500 [0.381, 0.643] | 0.500 [0.444, 0.558] | 0.150 [0.096, 0.205] |
  | Helper characters | 0.499 [0.369, 0.633] | 0.482 [0.410, 0.558] | 0.134 [0.084, 0.185] |
  | Effect spread (existing 220 pool-1 runs) | 0.521 [0.469, 0.567] | same | same |

  Every interval with decoys contains 0.5. Diagnostics on the existing runs: effect size 0.541 [0.498, 0.579]; **best
  arm's score 0.591 [0.541, 0.650] separates**: bugs really inflate scores, which no padding can hide (v2 limit).
- **Power (`eval/results/confirm_llama_2/power.json`):** H3's strongest feature is now effect spread (0.521). P(H3
  passes) at true AUC 0.60 / 0.65 / 0.70 / 0.75: 0.22 / 0.41 / 0.65 / 0.85 (was 0.00 at 0.75). H2 unchanged. H1 waits
  for the new cut-off.
- **Other code:** `eval/cutoff.py --batch` (refuses confirmation batches; the task-dev-1 cut-off stays, superseded),
  `eval/confirm.py` points at v2, refuses `confirm-llama-1` and dev batches, H3 has six features;
  `compare_tasks.run_features` adds statement count and helper characters. Test bootstrap draws 400 -> 300 to stay
  under 30 s.
- **Forecast, from measured numbers** (task-dev-1: 40 runs in 7.8 min; llama-checklist 14.4 s median per audit, max
  25 s; padded probe prompts 14.1 s median; pool-1 build 6.4 min):
  - Step 1, `task-dev-2`: proof and dry check under 1 min, runs 7-12 min, 40 audits 10-14 min with model load, cut-off
    seconds: **about 20-27 min**.
  - Step 3, `confirm-llama-2`: build-pool 6-10 min, runs 22-35 min (160 script runs incl. canary twins, plus 3 B09
    subtle slots that measure, about 2 min each), 100 audits 24-33 min, rescore 22-26 min: **about 75-105 min**
    (50-80 min without the optional rescore).

## Amendment 1 of the confirmation plan (2026-11-09): helper-size cue
- **`/analyze`:** length matching keeps total length constant, so a canary's bug lines take the place of helper lines.
  On the pool-1 dry plan (100 runs, seed 1109) every clean run gets 21 helper statements; canaries get 6 (B10 subtle)
  to 22 (B06 subtle), and 12 of 60 get 21 (B03 obvious, B06 obvious, B09). Helper-size AUC 0.15 (0.85 inverted). The
  cue moved from "how long is the script" to "how much settings-copying code does it have". As a non-monotone rule
  ("helper differs from 21") it would separate even better, but a stateless reviewer does not know 21 is the clean size.
- **H3 amended:** llama's AUC minus the direction-free AUC of the strongest of line count, character count, helper size
  and effect spread, re-picked in every base-level draw (`separation.strongest_feature_gap`, used by `eval/confirm.py`).
  The old H3 used line count alone, which is constant under length matching. Effect size and best arm's score stay as
  diagnostics (the student's list had four features).
- **Consequence, computed before any data (`eval/results/confirm_llama_1/power.json`):** with helper size at 0.85,
  P(H3 passes) is 0.00 / 0.05 / 0.23 / 0.66 at true llama AUC 0.75 / 0.85 / 0.90 / 0.95. llama's task-dev-1 AUC was
  0.735. **So with this padding, "not confirmed" is close to certain whatever the probe says.** A padding redesign
  that removes the cue (decoy code in clean runs, so helper size has the same distribution for every type) is
  probably needed anyway; the student decides after the probe.
- **Cue-sensitivity probe (`eval/cue_probe.py`, plan section 4a):** 20 pool-1 controls from rq1-full/task-dev-1 on 18
  bases. Each is padded with 6 and with 21 statements (97 vs 112 blinded lines) and scored by llama-checklist with the
  cache bypassed. Nothing goes to the ledger, the sealed table or the cache. Rule: mean P(flag | small) - P(flag | large),
  base-level 90% interval; excludes 0 in either direction -> CUE_LIVE (stop); fewer than 15 pairs or a prompt too large
  -> INCONCLUSIVE (stop); else NO_DETECTED_SENSITIVITY. Dry run: 40 prompts built, 0 too large for `num_ctx` 4096.
  Limit: the small version is also 15 lines shorter, so size and length effects cannot be told apart. Either one stops.
- **Forecast for the probe:** 40 llama calls. Past llama-checklist calls on unpadded 84-line scripts: median 14.4 s,
  mean 14.7 s, max 25.2 s (40 ledger audits); rescore median 14.1 s. Padded scripts are 13-28 lines longer (97 and 112 vs 84), so assume
  14-19 s per call, plus a cold load of 30-110 s. Expect **10-15 min** (likely about 12).
- **Also fixed:** six frozen files had been hashed as CRLF working copies while git stores LF (`-text`), so their
  hashes could not be reproduced from a checkout. They were restored to the git bytes (content checked identical) and
  re-hashed. `mixer.dry_length_check` was split into `dry_rows` + the check (same output), so the probe can read
  helper sizes. Tests: `tests/test_cue_probe.py` (8), H3 tests in `tests/test_confirm.py`, and a hand-computed gap test.

## Cue probe result (2026-11-09): no detected reaction to helper size
From `eval/results/confirm_llama_1/cue_probe.json` (40 records in `cue_probe.jsonl`; re-analysing the records gives the
same answer). 20 controls on 18 bases, all 40 versions scored by llama3.1:8b, 0 prompts too large, 0 unscored.
- **Mean P(flag): small helper (6 statements) 0.402, large (21) 0.429.** Difference -0.027, base 90% [-0.055, +0.002]:
  the interval contains 0, so the rule says NO_DETECTED_SENSITIVITY. Small scored higher on 7 controls, large on 13.
  No code verdict changed (all 40 were "pass").
- **Honest reading:** borderline, not a clean zero. The upper bound is only just above 0, and the lean is toward
  *larger* helpers (longer scripts) scoring higher. In the batch, canaries carry the smaller helpers, so a reaction of
  this kind would lower llama's AUC, not inflate it: it biases against confirming, not for it. 20 controls cannot
  rule out a small reaction.
- **Diagnostic, decides nothing:** at the locked cut-off (0.3845), 14 of 20 small and 17 of 20 large clean versions
  score at or above it. False alarms on padded clean runs may be far above task-dev-1's 0.45, so H1 may fail; H2 does
  not use the cut-off.
- **Time:** 570 s of model time (median 14.1 s per call, max 24.8 s), inside the 10-15 min forecast.

## Finding (2026-11-08): a trivial line-count baseline beat every LLM reviewer
**The trivial line-count baseline (AUC 0.85) beat every LLM reviewer, exposing a length cue in the canaries.** On
task-dev-1, blinded line count alone gave AUC 0.850, base 90% [0.75, 0.94]; character count 0.709 [0.59, 0.86]; the
best reviewer, llama3.1:8b with every run scored, 0.718 / 0.690 / 0.735 (baseline / grounded / checklist). All numbers:
`eval/results/task_dev_1/compare_tasks.json`.
- **Why (`/analyze`):** the template gives every clean script 84 blinded lines; a bug is code, so planting it adds
  code. Measured on all 18 pool-1 bases: B10 subtle +15 lines (a helper plus 9 lines in `run_arm`), B04 subtle +8,
  B07 subtle +7, B10 obvious +7, B01 subtle / B04 obvious / B07 obvious +4, B05 subtle / B08 subtle +3, B01 obvious /
  B02 / B03 subtle / B05 obvious / B08 obvious +1. Only bugs that change a value or swap a statement keep the length:
  B03 obvious and B09 (0), B06 obvious (0, config only) and B06 subtle (-1). Shams and controls stay at 84 by design.
  The 2.2 indistinguishability test compared shams with controls only, never canaries with clean runs.
- **Consequence:** any reviewer that tends to flag longer code looks discriminating. rq1-full used the same template
  and saboteur, so it likely has the same cue (not re-measured; its result was no discrimination anyway).

## Length matching and the confirmation plan (2026-11-08)
- **`canary/padding.py`:** every calibration run gets one never-used helper, `describe_settings`, sized so every
  blinded script in a batch has the same line count and character count (one target per batch, from the pool's
  clean scripts: lines = longest + 28, characters = median + 28 x 49). A first version drew a random target per run;
  it was type-blind too, but its rank noise (about +-0.06 AUC) could fail the gate by luck, so it was replaced.
  Constants tuned on all 18 pool-1 bases: every variant, clean run and sham (1,140 scripts) hit the target exactly.
  A padded run gives identical numbers (slow test).
- **Dry gate on pool 1 (100-run plan, seed 1109):** unpadded, line-count AUC 0.850 [0.80, 0.90] and characters 0.742
  [0.67, 0.81]: FAILED. Padded: both 0.500 [0.50, 0.50]: passed. Same on seeds 1 and 2.
- **New cue, measured, not gating:** helper size. A canary's bug lines replace helper lines, so canaries get smaller
  helpers: helper-size AUC 0.15 on the pool-1 dry run (two long statements are needed mostly by B10 subtle). A
  reviewer would have to react to how much settings-copying code a script has. Reported in every gate and result.
- **Gate in the pipeline:** `plan_batch` pads new plans by default (`length_match`, old plans resume unpadded);
  `run_batch` runs `batch_length_check` after the experiments and audits nothing if it fails (also if a prompt is too
  large for the role). `length-check --dry` checks a plan without running. `run_batch` now audits only its own
  batch, with the plan's `role` (a new role would otherwise have picked up every old run).
- **Pool-2:** `build-pool --avoid` asks the same fixed grid again, shows the Scientist the old pool's hypotheses on
  the same dataset and refuses duplicates. Without the avoid list the same focused prompt would hit the LLM cache and
  return pool 1 word for word.
- **Cut-off (`eval/cutoff.py`, locked, write-once):** 0.38452 on task-dev-1 fresh scores, J +0.40 (recall 0.85, false
  alarms 0.45), 2 tied candidates, lowest taken. Its file records that it was chosen on length-confounded data.
- **Plan locked:** `docs/plans/llama_checklist_confirmation.md` with the student's changes A-E; `eval/confirm.py`
  computes H1-H3 and refuses to run if the plan or cut-off changed. Two consequences are written in the plan: H1 or H2
  allows up to about 10% false positives; with constant length, line count's AUC is exactly 0.5, so H3 reduces to H2
  and H1 alone cannot confirm. Power (`eval/results/confirm_llama_1/power.json`, design effect 1.27): H2 0.46 / 0.78 /
  0.96 at true AUC 0.60 / 0.65 / 0.70.
- **Fixes on the way:** bootstrap intervals depended on Python's set order (they moved by 0.01 between processes);
  runs are now sorted before resampling. `.gitattributes` keeps locked files byte-exact (`core.autocrlf` is on).
  The AUC and bootstrap helpers moved to `canary/separation.py` (the gate needs them inside `canary/`).
- **Tests:** 582 passed, 11 deselected in 28.8 s (bootstrap draws lowered to 400 in tests by `tests/conftest.py`);
  `pytest -m slow` 11 passed.

## Review-task screen (2026-11-08): can another way of asking give J clearly above 0?
Plan and decision rule, committed before the batch ran: `docs/plans/review_task_screen.md`. Fresh batch `task-dev-1`
(40 runs: 20 canaries, 10 controls, 10 shams, seed 1108, same 18-base pool). rq1-full is not touched; baseline
result and figure hashes are in `eval/results/task_dev_1/baseline_sha256_before.txt`.
- **Built:** `canary/review_tasks.py` with 3 tasks. `baseline` is the original prompt, unchanged. `grounded` (V1) uses
  neutral wording and puts the offending line first, checked by code. `checklist` (V2) asks one yes/no plus line per
  class. Code turns each reply into the verdict (`decision` in the audit). Token-probability scores give P(flag) and
  AUC (`score`). The wrapper gained a per-role `num_ctx` and `top_logprobs`. Roles `skeptic_c` (llama3.1:8b) and 6
  task aliases added. `eval/rq1.py` now writes batches other than rq1-full to their own folder.
  `eval/compare_tasks.py` builds the 9-cell table.
- **Rule (fixed):** a cell passes if the lower end of its 90% J interval is above 0. AUC, raw-verdict J and paired
  delta J are reported but decide nothing. A pass must be confirmed on an 80-100 run batch built from a NEW pool of
  fresh Scientist proposals. Prompts are not changed after seeing these results.
- **Checks before the batch:** Ollama returns token probabilities, but from before the schema constrains each token, so
  the score renormalises over the two allowed words. llama3.1:8b at num_ctx 4096 loads at 5.25 GiB, 75% on the GPU
  (accepted). Prompts are about 2,000 of its tokens, so the checklist fits and the llama3.2:3b fallback was not needed.
  The format was checked on old real run `1875ec26` (not in any batch) with direct calls, and nothing was stored.
- **Tests:** `pytest -q` 554 passed, 10 deselected in 24.9 s; `pytest -m slow` 10 passed.
- **Result: no cell passes the fixed rule** (`eval/results/task_dev_1/compare_tasks.json`). 9 cells x 40 audits, 0 failed;
  every 90% J interval includes 0. Baseline hashes unchanged; `ledger verify` OK (1552 entries).

  | Role | Model | Flagged buggy | Flagged clean | J (90%) | Passes | delta J vs own baseline (90%) |
  |---|---|---|---|---|---|---|
  | skeptic_a | gemma3:4b | 20/20 | 20/20 | +0.001 [-0.102, +0.105] | no | - |
  | skeptic_a_grounded | gemma3:4b | 17/20 | 19/20 | -0.092 [-0.257, +0.066] | no | -0.100 [-0.250, +0.050] |
  | skeptic_a_checklist | gemma3:4b | 14/20 | 16/20 | -0.088 [-0.295, +0.124] | no | -0.100 [-0.350, +0.100] |
  | skeptic_b | phi4-mini | 19/20 | 17/20 | +0.088 [-0.069, +0.257] | no | - |
  | skeptic_b_grounded | phi4-mini | 15/20 | 18/20 | -0.135 [-0.326, +0.055] | no | -0.250 [-0.450, -0.050] |
  | skeptic_b_checklist | phi4-mini | 5/20 | 3/20 | +0.089 [-0.107, +0.289] | no | +0.000 [-0.250, +0.250] |
  | skeptic_c | llama3.1:8b | 20/20 | 20/20 | +0.001 [-0.102, +0.105] | no | - |
  | skeptic_c_grounded | llama3.1:8b | 19/20 | 20/20 | -0.046 [-0.173, +0.066] | no | -0.050 [-0.150, +0.000] |
  | skeptic_c_checklist | llama3.1:8b | 0/20 | 0/20 | -0.001 [-0.103, +0.102] | no | +0.000 [+0.000, +0.000] |

  - **The wording changes how often a reviewer flags, not whether it can tell buggy from clean.** The checklist took
    flag rates from about 100% down to 75% (gemma), 20% (phi) and 0% (llama), with J still near 0. On this fresh
    batch the baselines repeat rq1-full: gemma and llama flag 40/40.
  - **The line check did not help.** Reviewers quoted real lines (verified 0.90 gemma, 0.82 phi, 0.97 llama), so the
    check only removed flags, slightly more often on buggy runs. phi's grounded J fell against its baseline: delta
    -0.25 [-0.45, -0.05]. This is a secondary measure and decides nothing. The plan predicted it: a quote check
    catches made-up evidence, not a real, correct line misread as a bug.
  - **Right class:** the truth was among the checklist "yes" classes for 4/20 (gemma), 2/20 (phi) and 0/20 (llama)
    canaries. llama's raw checklist answers (before the line check) had J +0.135 [-0.005, +0.290]. That is not the rule,
    and on 3 "yes" answers in 40 runs it is no evidence.
  - **Limits:** 20 buggy and 20 clean runs detect only J of about 0.35 or more, so a small real gain could be missed.
    One pool of 18 bases, temperature 0, class names without definitions.
  - **AUC is missing (bug, fixed afterwards):** all 360 audits stored `score: null`. The ollama client (0.6.3) drops
    each token's `bytes`, and the scorer read the empty list as zero bytes. A second gap: the chosen token was not
    counted when it was outside the model's own top 20. Both fixed with tests. Through the wrapper, real review prompts
    now give scores for all 3 tasks. The stored audits cannot be rescored without new model calls.
  - **Rescore (built 2026-11-08, `719b40a`):** `canary.cli rescore --batch B --reviewer R` rebuilds each audit's prompt
    (all 360 rebuilt prompts hash-match the stored `prompt_sha256`), asks the same model again at temperature 0 with
    token probabilities, and keeps a score only if the new reply equals the stored one. Records go to
    `data/rescore/<batch>.jsonl`, each tied to its audit's ledger hash. The ledger, the verdicts and the LLM cache are
    not written (`ledger verify` still 1552 entries). From `812fd32`, a differing reply also records whether its
    verdict changed. Tests: 563 passed, 10 deselected in 27.1 s; slow 10 passed.
  - **AUC results (rescore complete, 2026-11-08).** `eval.compare_tasks --batch task-dev-1` re-run with all 360
    records; only the `auc` fields of `compare_tasks.json` changed (checked field by field against the previous file),
    so J, passes and verdicts are as above. Baseline hashes OK; `ledger verify` OK (1552 entries). AUC uses only runs
    whose reply repeated exactly; "bounds" put every unscored run at the worst and then the best rank (from a
    read-only scratch script, not stored in results). AUC decides nothing.

    | Role | Model | Matched / 40 | Scored bug+clean | AUC (90%) | Bounds if unscored runs fell either way |
    |---|---|---|---|---|---|
    | skeptic_a | gemma3:4b | 40 | 20+20 | 0.565 [0.41, 0.71] | - |
    | skeptic_a_grounded | gemma3:4b | 40 | 20+20 | 0.470 [0.32, 0.63] | - |
    | skeptic_a_checklist | gemma3:4b | 38 | 19+19 | 0.449 [0.30, 0.61] | [0.41, 0.50] |
    | skeptic_b | phi4-mini | 24 | 12+12 | 0.583 [0.36, 0.78] | [0.21, 0.85] |
    | skeptic_b_grounded | phi4-mini | 23 | 11+12 | 0.477 [0.27, 0.70] | [0.16, 0.83] |
    | skeptic_b_checklist | phi4-mini | 28 | 13+15 | 0.559 [0.37, 0.73] | [0.27, 0.79] |
    | skeptic_c | llama3.1:8b | 26 | 12+14 | 0.792 [0.62, 0.92] | [0.33, 0.91] |
    | skeptic_c_grounded | llama3.1:8b | 30 | 14+16 | 0.728 [0.57, 0.88] | [0.41, 0.85] |
    | skeptic_c_checklist | llama3.1:8b | 38 | 18+20 | 0.706 [0.57, 0.84] | [0.64, 0.73] |

    - **Only llama ranks buggy above clean, and only weakly.** Its three 90% AUC intervals sit above 0.5, while gemma's
      and phi's all include it. With a 9-cell correction (98.9% intervals, scratch diagnostic) all three llama cells
      touch 0.5 or nearly do: [0.52, 0.96], [0.47, 0.93], [0.46, 0.89]. Its verdicts still do not separate (J about 0):
      the signal lives in the probability, not in where the code's threshold cuts it.
    - **llama3.1:8b is not repeatable either:** 94/120 matched (26, 30, 38). Every one of its 26 differing replies kept
      the stored verdict (`verdict_changed` false); what changed was wording or evidence. phi's 45 and gemma's 2
      mismatches predate `812fd32`, so their verdict change is unknown.
    - **gemma's baseline and grounded scores are saturated:** all 80 have p_flag above 0.999, so their AUC ranks
      differences in the far tail of a probability and means little. llama's baseline scores spread from about 0.90 to
      0.99 and are usable.
    - **llama checklist is the most robust number:** 38 of 40 scored, bounds [0.64, 0.73], though it flagged 0 of 40.
      Its raw J was +0.135 [-0.005, +0.290]. A pointer, not a pass: it is one of 9 cells seen after the fact.
  - **Fresh pass and baselines (2026-11-08, later).** `rescore --fresh` asks again only for runs whose reply differed
    and keeps the new reply's score, in `data/rescore/task-dev-1.fresh.jsonl` (the first file is only read).
    `compare_tasks` now also reports, all deciding nothing: base-level 90% intervals (resampling the 17 bases, since
    clones of a base are not independent), fresh AUC on all 40 runs, trivial-feature AUCs (blinded line count,
    per-seed effect spread, effect size, best arm's score), the same features on each cell's matched-only runs, and
    Spearman rho of score vs line count within buggy and within clean runs. All numbers: `compare_tasks.json`.
    - gemma (2 runs) and phi (45 runs) done in the background, 183 s of calls. phi's third reply matched its stored
      one only 17 of 45 times. llama's 26 not run yet (command under "In progress").
    - **phi with every run scored:** baseline 0.640, grounded 0.545, checklist 0.583; every base-level interval
      includes 0.5. The matched-only numbers did not hide a signal.
    - **Major finding: script length gives canaries away.** All 20 clean runs (controls and shams) have exactly 84
      blinded lines; canaries have 83-99, and only B03 (one), B09 (both) and none of the others sit at 84. Line count
      alone has AUC 0.850, base 90% [0.75, 0.94], higher than every reviewer cell. The 2.2 indistinguishability test
      compared shams with controls only, never canaries with clean runs. A reviewer cannot use this without knowing
      the template's length, but any score that rises with code size would look discriminating: llama checklist's
      score rises with length within buggy runs (rho +0.46, p 0.05, n 18). Within clean runs rho cannot be computed
      (no variation). So llama's AUC may partly be a length effect. The confirmation must control for it.
    - Tests: 567 passed, 10 deselected in 27.1 s (32 s while phi ran in the background).
  - **Finding: phi4-mini is not fully repeatable at temperature 0.** It gave its stored reply again only 75 of 120 times
    (baseline 24/40, grounded 23/40, checklist 28/40). gemma3:4b repeated 118 of 120 (40, 40, 38). phi's mismatches hit
    buggy and clean runs about equally (24/60 and 21/60), but that does not make them random. AUC for phi will rest on
    a subset chosen by the model's own instability, likely its least certain cases, so it may look more decided than
    it is. The 45 phi mismatches were scored before `812fd32`, so whether their verdicts changed is unknown without a
    third call. **The LLM cache hides this:** every normal call with the same prompt returns the stored reply, so a
    reviewer looks perfectly repeatable unless it is asked again with the cache bypassed.

## Reviewer study (2026-11-05): Skeptic B RQ1, gemma position diagnostic, comparison
Re-audits of the existing `rq1-full` runs; no experiment was re-run (215 run folders, 213 sealed rows and 213 `ran` entries before
and after). Plan: `~\.claude\plans\run-rq1-for-skeptic-b-twinkling-shell.md`. Data backed up first to
`~\canary-backups\data-2026-11-05.zip`.
- Commands: `canary.cli reaudit --batch rq1-full --role skeptic_b` (180 audits, 0 failed, 7.5 min, median 2.3 s per audit), then
  `reaudit ... --role skeptic_a_shuffled --position-sample` (40 audits, 0 failed, 2.3 min), `eval.rq1 --role skeptic_b`,
  `eval.position_bias`, `eval.compare_reviewers`. Results: `eval/results/rq1_skeptic_b.json`, `position_bias_skeptic_a.json`,
  `rq1_comparison.json`; Skeptic B figures in `eval/figures/skeptic_b/`.
- **Skeptic B (`phi4-mini`) cannot discriminate either:** flags 172/180, Youden's J +0.034, 90% [-0.020, +0.093]. Like gemma it
  names B01 on almost every flag. Paired with A on the same 180 runs: kappa 0; the 8 disagreements are all B passing where A flags.
- **Position diagnostic, reading fixed before the run: "prefers B01 itself, not its position".** With the class list shuffled
  per run (prompt and schema), gemma still flags 40/40 and names B01 27/40 (90% [0.54, 0.78], chance 0.10). There is also a
  smaller pull to the first-listed class: 13/40 (90% [0.22, 0.46]). 9 of its 13 non-B01 names were the first-listed class,
  mostly when B01 sat late in the list. So order is not why it flags everything, and only partly why it names B01.
- `/compare` verdict: no reviewer switch, no gate built on either. Both families flag almost everything and name B01, so the
  review task (prompt and reply format) is the likely cause; change it next and measure it with RQ1. The jury stays Mission 5.2.
- Baseline untouched: SHA-256 of `rq1_skeptic_a.json`, `rq1_recall.png`, `rq1_specificity.png` identical before and after;
  `build_results` for skeptic_a reproduces the file except `generated_at` and `excluded` (`other_role` 0 -> 220).
- Code: status flow now allows `audited -> audited | audit_failed` (a second reviewer role). `skeptic._waiting` is role-aware;
  `audit_pending` takes `run_ids` and `class_order`; `skeptic_prompt` takes an optional order (default prompt byte-identical,
  tested by hash); alias role `skeptic_a_shuffled`; `config.family_clashes` skips aliases (it raised KeyError on them);
  `mixer.reaudit`, `position_sample`, `shuffled_order`; `eval/rq1.py` writes other roles' figures to `eval/figures/<role>/`.
  `position_sample` also takes the ledger, so a crashed run is never sampled (a gap is reported, not skipped).
- Tests: `pytest -q` 517 passed, 10 deselected in 24.9 s; `pytest -m slow` 10 passed in 15.6 s. The suite was already at
  36.8 s before this work, so the 10 slowest tests are marked `slow` in `pytest.ini` (deselected by default, not deleted).

## Running or interrupted campaigns
- **2026-11-20 (4.1 sitting 1):** none running or interrupted; no model called; `eval.rq4_power` is a local simulation.
- **2026-11-20 (guard sitting 1):** none running or interrupted; no model called; reference runs only in temporary
  folders.
- **2026-11-20:** none running or interrupted. The tripwire records were written to the real ledger in the
  student's window (3592 entries).
- **2026-11-19 (step 11 part 2):** none running or interrupted; nothing replayed, no model called.
- **2026-11-19:** none running or interrupted. `tripwire-test-1` built (360 runs) and both tripwire tests ran once in
  the student's window; nothing to resume. `tripwire-test-1` is never reviewed by an LLM.
- **2026-11-18:** none running or interrupted. `tripwire-test-1` is not built (step 10, student's window); nothing has
  run on `ceiling-ext` for the tripwire test. If the step 10 build stops part way, resume it with
  `.venv\Scripts\python.exe -m canary.cli calibrate --batch tripwire-test-1 --resume --no-audit` (never `--runs` again).
- None running. `task-dev-1` finished 2026-11-08 at 05:59 UTC after two stops (a batch log bug and low RAM; see the
  review-task screen above). The last part ran from the student's own PowerShell window.
- The task-dev-1 rescore is complete (360 of 360 records; llama passes took 566 s for the checklist alone, from the
  student's own window), and so is its fresh pass (73 records).
- The cue probe finished 2026-11-09 13:38 UTC (40 records, `eval/results/confirm_llama_1/cue_probe.jsonl`).
- `confirm-llama-1` never started and is superseded (no pool-2, no runs, no audits); the name is refused.
- `task-dev-2` (v2 step 1) finished 2026-11-10 in the student's own window: 40 runs in 357 s (length gate passed on
  the run folders), 40 audits in 602 s, 0 failed; cut-off written once (`eval/results/task_dev_2/llama_checklist_cutoff.json`).
- `confirm-llama-2` will not run (llama stopped, 2026-11-10); no pool-2 data exist; the v2 plan stays unlocked.
- Cloud: 3-call Groq smoke test (2026-11-11). **Arm L (`skeptic_d`) is open:** day 1 done 2026-11-12, 67 of 120
  answered (task-dev-2 40 of 40, ceiling-ext 27 of 80), 0 failed; resume from 2026-11-13 13:11 UTC with
  `reaudit --batch ceiling-ext --role skeptic_d`. No partial analysis while it is open.
- **Arm L is finished (2026-11-14); the line above is the 2026-11-12 state.** Main pass 120 of 120 answered, repeat
  pass 20 of 20, `eval.ceiling --arm L` ran once (SOLVABLE). Nothing is running or interrupted.

## Decisions
- **Mission 4.1 gate (student, 2026-11-20):** (1) the gate gets an explicit row "baseline guard not tested -> gate
  closed (no finding auto-accepted)", built in 4.1 sitting 2 (`canary/gate.py`); the gate table of
  `docs/plans/mission_4_1_trust.md` is amended now (section 9). Reason: with the measured union and B09 in the support,
  the worst-class gate opened in 17-64% of zero-bug simulated campaigns, so "no auto-accept until the guard is
  tested" cannot rely on noise. (2) No change to the fixed minimums (12 canaries per class, 60 clean runs).
- **Guard follow-ups from sitting 1 (student, 2026-11-20):** (1) the guard record stays in the PROPOSED ledger
  entry of real runs only: the ledger already differs between real runs and clones (a clone's lock comes after its
  run, accepted in Mission 2.4) because the reviewer never sees the ledger, and a test enforces that reviewer code
  never reads the guard key; copying a base's record onto clones would be false for B09 canaries, and a separate file
  would lose the ledger's tamper evidence. (2) Two reference runs per attempt are allowed (G3, then G4 when G3 finds
  nothing); trap 7 of `docs/plans/b09_proposal_guard.md` amended (`5c5ffe2`). (3) The plan's development fact does not
  hold for the garbled first real run: after defaults its arms differ in three factors and G1 rejects it (plan
  section 4 corrected). (4) Arms identical after defaults go to the human queue as new rule G7 (label
  `no_difference`), never auto-accepted (`d095a96`). (5) Pool files store each base's guard record (`446ff2e`), so
  pool 3 is built with the records.
- **Mission 4.1 support (student, 2026-11-20, asked again and confirmed):** the plan as approved: until the guard has
  passed its test, B09 stays IN the real-run support (the gate stays closed); it leaves only after, with the leak term.
- **The three open decisions, approved as explained (student, 2026-11-19, step 11 session):**
  (1) **Mission 4.3 decision 1:** keep the sentinel at 60 runs, 20 calls a day; the 4.3 plan now says (decision 1 and
  section 8) that at this budget the chart catches a collapse, not a slow drift. (2) **Mission 4.4 decision 1:** keep
  the cold-start real proof (3 review days, about 195 calls); in the DESIGN.md sync sitting, the Mission 4.1 plan's
  sentence on about 228 reviews becomes "without the lazy union", which reconciles the two numbers. (3) **Roadmap
  decision 5:** keep as written: `llama3.1:8b` comes back only as a locked measurement on the common batch, never as a
  reviewer in use, and its old confirmation is recorded as never run. All 34 design-session-2 decisions are now made.
- **Lock checks against the locked commits, option C (student, 2026-11-19):** both locked plans
  (`cloud_ceiling_check.md`, `tripwire_test.md`) get a written amendment: their `--check` verifies each frozen file in
  git against `git show <tag>:<path>` at the plan's lock commit (tags `ceiling-check-lock`, `tripwire-test-1-lock`),
  files outside git stay checked on disk, and working copies that differ are printed for information. Then the step 11
  CLI goes in `canary/cli.py` as the plan says (`canary.cli tripwires`). Amendment details: step 11 entry.
- **Design session 2 decisions (student, 2026-11-19):** the 34 open decisions (the last sections of
  `mission_4_3_drift.md`, `mission_4_4_campaign.md`, `mission_3_1_3_2_memory_calibration.md` and
  `roadmap_challenge_2026-11-15.md`) take their recommended defaults, **except three that stay open** until Claude
  explains them (Mission 5.1 step 11 session): Mission 4.3 decision 1 (sentinel of 60 runs, 20 a day: why not 20 runs
  on a schedule, and its daily cost as a share of the Groq budget); Mission 4.4 decision 1 (the cold start's about
  195 calls against the Mission 4.1 plan's about 228 reviews: reconcile); roadmap decision 5 (`llama3.1:8b` back as
  an RQ1 row: confirm the plan keeps it labelled development / not confirmed). **Consequence of roadmap decision 9
  (approved):** Mission 5.1 step 11 is the CLI and ledger wiring only; its `DESIGN.md` rewrite (sections 4, 6 and 10)
  moves to the later DESIGN.md sync sitting.
- **Mission 5.1 sitting C defaults kept (student, 2026-11-16):** all four as built: (1) K6 compares numbers with the
  1e-12 rounding tolerance only; (2) K3 stays as strict as built; (3) a scored model the script never fitted is
  `fired` B04; (4) the equal-predictions rule as built (K3 needs every candidate registered, K6 the arm's model among
  them). They are inside the tripwire code that step 9 hashes, so they freeze with the lock.
- **Git history rewritten 2026-11-17 (student):** Claude co-author lines removed from 5 commit messages of 2026-11-10;
  file contents unchanged; commit IDs from 2026-11-10 onward changed; IDs cited before this note refer to the old
  history, kept in the student's backup bundle canary-before-rewrite.bundle.
- **Mission 4 reviewer (student, 2026-11-14):** the union of `openai/gpt-oss-120b` (`skeptic_d`) and the tripwires: a
  run is flagged if either flags it, and each is also logged alone. Plus a **drift sentinel set**: the same
  already-reviewed runs re-asked regularly with the cache bypassed (the repeat-pass mechanism), so a verdict change
  means the reviewer changed. The union's recall and specificity are **expected, not measured**, until the locked
  tripwire test (Mission 5.1 sitting D).
- **Ceiling design fixed by the student's rule (2026-11-11, second session):** the rule (qualify under verdict ICC 0.1,
  0.2 and 0.4 with power >= 0.80 at J 0.70 and false-positive bound <= 0.05 at J 0.40; least strict level per design;
  fewest calls) was given before the simulations ran and picked **2 cells (baseline prompt only), 97.5%, 120 runs**
  (`eval/results/ceiling/design_study.json`). Groq limits read by the student: 1K requests/day, 200K tokens/day, 8K
  tokens/min, 30 requests/min; budgets set at 90%. The dead llama v1/v2 plans carry a note that their `models.yaml`
  hash no longer matches, as expected (v1 re-hashed, LF).
- **Provider approved by the student (2026-11-11, build session):** Groq `openai/gpt-oss-120b` (arm L), Gemini free
  tier (arm R, only if arm L is not SOLVABLE), Azure for Students (arm R backup). Also approved: the batch-size
  criterion, the 20-run repeat pass per cell, a daily call budget under each provider's limit, and (in the build
  request) that a batch above 40 runs adds **fresh pool-2 runs** to task-dev-2 (the outline said pool 1 with a new
  seed). Hard rules for the build: no real call, no key, never print/log/commit a key, mocked tests.
- **Approved by the student (2026-11-11):** (b) the "solvable" rule, with the batch sized by the outcome simulation;
  (c) the standard-library HTTP provider; spending cap $0; every call logged; runs resumable within the free daily
  limits; AUC from the verdict where there are no token probabilities; the claim worded "for these models".
- **Provider chosen by the student (2026-11-11): GitHub Models (free). It cannot be carried out:** GitHub Models was
  retired on 2026-07-30 (found the same day, see "Provider research"). The provider decision is open again; the
  outline is written for Claude's recommended replacement (Groq + Gemini free tier), which is **not** approved yet.
- **Ceiling check uses a free API first; no paid API for now (student, 2026-11-10).** Reviewer: GitHub Models (free);
  backup: the Gemini free tier. Pay for a model only if the free result is INCONCLUSIVE or HARD **and** a newer paid
  model would change the conclusion. This replaces proposal (a) (OpenAI, paid) in
  `docs/plans/cloud_ceiling_check_outline.md`; proposals (b) the "solvable" rule and (c) standard-library HTTP are
  still pending approval. The isolation rule is unchanged: the reviewer is called only through `canary/llm.py` with
  the blinded prompt. Nothing about GitHub Models has been checked yet (models, token probabilities, temperature,
  rate limits, data terms); that is the next session's first job, before any call.
- **llama3.1:8b not confirmed for use; llama confirmation stopped (student, 2026-11-10).** Its development AUC on
  task-dev-2 is weak (0.643, base 90% [0.487, 0.778], `eval/results/task_dev_2/dev_report.json`), and confirming it
  would need about 400 runs (~167+ laptop minutes) for 80% power on H3 at a true AUC of 0.64, against the 100
  planned. The reason is the power simulation (`eval/results/confirm_llama_2/power_sim.json`, `eval/power_sim.py`;
  section "task-dev-2 result and power"). The v2 plan stays **unlocked and is not run**: no pool-2, no
  confirm-llama-2. llama's dev numbers remain development numbers and may not be reported as a confirmed result.
- **Working rule for improving the reviewer (student, 2026-11-09).** We keep improving the reviewer until it works
  properly, but every change (prompt, task, model, cut-off, padding, hints) is chosen on development data and judged
  only on a fresh batch it has never seen. No re-tuning on a batch whose results we have seen: once a batch's results
  are known, that batch becomes development data for the next change, never the test of it. Each test batch is
  pre-registered and locked before it runs (as in `docs/plans/`).
- **Ollama only for now, no API keys.** A cloud model is added later with `/api`. Mission 1.3 must build `llm.py`
  so that switching to an API needs only a config change (`provider` in `config/models.yaml`, key in `.env`), with
  no changes to the code that calls it. Whatever is chosen, the Skeptic stays a different family from the Scientist.
- **Python 3.12.10** installed per user with winget, first on the user PATH. Python 3.11.9 stays installed but is
  unused. The project runs from `.venv`; `requirements.lock` records the exact tested versions.
- **Skeptic A runs on the fallback `gemma3:4b`.** `gemma4:e4b` is a 6.13 GB download and will not fit in 6 GB VRAM.
  Do not pull it on this machine: `resolve_roles` prefers it as soon as it is installed.
- **The Scientist is `qwen2.5-coder:7b`, with `qwen3:4b` as fallback** (replaces the earlier `qwen3.5:4b` preference).
  Chosen from a test of 5 proposals per model, with valid settings and variety weighted above speed. `qwen3.5:9b` was
  tested and removed. Skeptic B is `phi4-mini`. Entries already in the ledger were proposed by `qwen3:4b`.
- **Ollama upgraded from 0.20.2 to 0.40.13**, because the registry refused `gemma3:4b` on the old version (HTTP 412).
- **Datasets are cached as `data/cache/<name>.csv.gz`**, with the label in `__target__`, so they load offline.
- **Run folders stand alone.** Each `data/runs/<uuid>/` holds its script, config and a dataset copy; the script never
  imports `canary`, so an experiment has no route to the sealed table in the normal code path.
- **Hyperparameters are checked by scikit-learn, not by `validate_config`.** A bad value is a recorded crash. Structural
  errors (unknown dataset, model or metric) are `invalid_config`, and they stay out of the crash rate because no code ran.
- **Template choices:** the minority class is the positive class for f1 and roc_auc; multiclass f1 is macro; roc_auc is
  allowed on two-class datasets only; numeric columns are always median-imputed and text columns always imputed and
  one-hot encoded, fitted on train only; both arms share each seed's split.
- **The optional code slot from DESIGN section 3 is not built.** Nothing needs it yet; add it if the Scientist does.
- **The LLM cache key is wider than CLAUDE.md's hash(model + prompt):** it also hashes the system prompt, schema and
  temperature, because the same prompt under another schema is a different question.
- **`parse_reply` is strict:** after removing `<think>` blocks and code fences, the reply must be exactly one JSON
  value. It never searches prose for JSON, because a reply with two candidate verdicts would make the verdict a guess.
- **Retries change the prompt** by adding the rejection reason, because at temperature 0 the same prompt repeats the
  same bad reply. The cache key still uses the original prompt.
- **Providers can be set per role** (`provider:` on a role in `models.yaml`), so a cloud Scientist can sit beside local
  Skeptics. Only Ollama exists today: `/api` adds a class to `PROVIDERS`, then only config and `.env` change. Reading
  the key from `.env` is not built yet.
- **Added to `models.yaml`:** `num_ctx: 8192`, `num_predict: 1024`, and timeouts of 300 s (cold) and 120 s (warm).
- **Verdict rule (`prereg.compute_verdict`):** supported = mean effect >= `min_effect` and CI above 0; not supported =
  whole CI below `min_effect`; otherwise inconclusive. A failed run is inconclusive, with the reason stored.
- **The verdict CI uses the Nadeau-Bengio correction** (variance factor 1/n + n_test/n_train), because random splits of
  one dataset overlap and a plain t interval would be too narrow. `docs/DESIGN.md` did not specify a test.
- **Code, not the LLM, sets seeds, split and alpha.** New `science:` block in `campaign.yaml`, with `min_effect_floor:
  0.005` so trivially small effects cannot count as success. `direction` is "increase" or "decrease"; `confidence` means
  P(result reaches `min_effect` in that direction).
- **The Scientist's schema has one form per model (`anyOf`)**, using `codegen.MODEL_PARAMS`. Hand-written configs may
  still use any parameter. Tried and rejected on real replies: an open `params` object (garbled keys, repeat-loops,
  1 real crash) and one shared parameter list (mixed parameters between models). The final form gave 8 of 8 acceptable.
- **Each LLM retry uses a new seed**, because a sampling failure repeats at the same seed. Scientist retries put the
  attempt number in the prompt, because a repeated prompt would only replay the cached rejected reply.
- **Rejected proposals are printed, not stored in the ledger:** nothing was locked or run for them.
- **The ledger shares `data/canary.db` with the LLM cache.** Append-only is enforced by the API and detected by the
  chain; there is no database trigger, so a manual edit is possible and shows up in `ledger verify`.
- **The ledger keeps the real crashed run** (hypothesis `6352b91a`, entries 1-3) as a true record.
- **"Every run has an audit" is read as every run with results.** A crashed run has no finding to review, so it goes to
  the graveyard with its cause and no LLM call. `graveyard` entries are written directly; Mission 3.1 adds the module.
- **The Skeptic sees** the blinded script, results (fixed key order, no `runtime_seconds`) and pre-registration (without
  `question`). It never sees IDs or the computed verdict.
- **The Skeptic's prompt lists bug class names only,** not the catalog's examples, and does not mention testing. Hints
  would inflate measured recall; they are added and measured in Mission 6.4.
- **Audits refuse edited files:** the prereg, results and script hashes are checked first. New `ran` entries store
  `script_sha256`. The 2 older runs have only a results hash, so their scripts are not covered.
- **`llm.call` refuses prompts that may not fit,** at (num_ctx - num_predict) × 3 characters, instead of letting Ollama
  cut them silently. `science` now audits automatically; `audit` reviews anything still waiting.

- **Ground truth for a canary means "the method is broken", not "the score changed"** (see Saboteur effect sizes).
- **B01 fits the arm's preprocessor on train and test rows, and that fit is used.** An earlier version scaled X before
  the split, and the arm's own scaler undid it exactly. B01 is refused if neither arm has a scaler.
- **B10 uses the labels:** it drops rows the model got wrong (obvious: all; subtle: the most confidently wrong half), keeping
  one row per class so roc_auc cannot crash. Label-blind dropping lowered as many scores as it raised.
- **B09 subtle measures instead of using a fixed value:** it tries a ladder, mildest first, and keeps the first setting that
  lowers this control by at least `min_effect_floor`, else `NotApplicable`. So `sabotage` takes seconds for this variant.
- **Impact is kept out of run folders,** because it reveals a canary. `controls.run_canary` stores it in the sealed table.
- **Harmful includes bugs that lower a score,** because they falsify a result too (B08, B09).
- **B06 and B09 change the config as well as the script,** so `controls.clone_prereg` builds the pre-registration from the
  config that really runs. It rewrites metric names in the hypothesis sentence, and raises `NotApplicable` if the sentence
  names a hyperparameter the bug changed, because free wording cannot be rewritten safely. The mixer must catch this.
- **The sealed table is its own file, `data/sealed.db`,** with the path defined only in `sealed.py`, so ledger code connected
  to `canary.db` has no route to it. It is write-once: no update or delete method, and a second record for a run is refused.
- **Real runs now draw random seeds (`prereg.draw_seeds`), instead of always 0-4.** A clone with its source's seeds gives the
  reviewer identical text, so the cached reply would count as a second observation. Clones on other seeds would be
  recognisable if real runs stayed on 0-4. Duplicate detection now ignores seeds. Ledger entries already written keep 0-4.
- **Shams rename 4-8 variables or functions and reorder imports and helper functions,** because blinding erases comments and
  formatting. Keyword names and text values are never changed. `make_sham` is deterministic for a given `rng`.
- **`why_not_clean` refuses two bases for controls, shams and canaries:** accuracy above a 3:1 class ratio (B06) and a control
  with the exact B09 obvious settings. Milder weak settings are allowed, because whether they are a bug depends on their effect.
- **Twins live in `data/twins/`** when run through `controls.run_canary`, outside the crash rate. They are not sealed as runs;
  the canary's row points to its twin.
- **"Length class" is blinded lines // 10.** Shams keep the exact line count, so a class boundary can never separate them.
- **Added `controls-check <config>`** as this mission's proof, since CLAUDE.md gives 2.2 no command. It uses a temporary
  folder and table, so `data/sealed.db` does not exist until Mission 2.4 runs real clones.
- **`load_yaml` now caches parsed files** (keyed by path and modification time, returning a copy), to speed up the test suite.
- **`why_not_applicable` decides where a bug can go.** B06 obvious needs a class ratio above 3:1 (only `blood-transfusion`,
  `pc1` and `ozone-level-8hr`) and a non-accuracy metric; B06 subtle needs two classes; B05 needs 2 seeds. B09 obvious raises
  `TransformError` if the control already has the crippled values. The mixer must handle both errors.
- **Bugs that favour one arm hit the treatment** (B04, B05), because that is how a bug yields a false "the treatment helped".
- **B05 subtle fills dropped seeds with the mean of the kept ones,** because `results.json` needs one value per seed.
- **`sabotage-check` runs in a temporary folder,** so it stays out of the ledger and the crash rate.
- **A catch means any flag, whichever class it names,** because Rogan-Gladen (Mission 4.1) needs recall to be P(flag | bug). `named_right` is
  reported beside it, because a flag naming the wrong class may be luck, and low specificity exposes a reviewer that flags everything.
- **Harmless canaries count in the main recall,** because a canary means "the method is broken". Recall is also reported for harmful,
  harmless and unmeasured canaries separately. Only canary-measure runs count in any recall figure.
- **Specificity is reported for controls, shams and combined.**
- **Untested classes stay in overall recall at their prior and are listed as untested,** so the uniform class mix keeps its meaning.
  Worst recall is the lowest posterior mean among tested classes only.
- **The first audit of a run for a role stands,** so re-reviewing a miss cannot raise recall. Later audits are counted in `excluded`.
- **`trust.py` draws with a fixed default seed,** so a report can be reproduced. Per-class intervals are exact (`beta.ppf`); only overall recall uses Monte Carlo.
- **Added `trust` and `trust --demo`** as this mission's proof, since CLAUDE.md gives 2.3 no command. `--demo` output is labelled SYNTHETIC.

- **The pool of bases is 18 fresh Scientist proposals over a fixed grid** of dataset, metric and model (`focus`, `mixer.focus_grid`), in `data/calibration/pool.json`, not the ledger. Unprompted, the Scientist proposes nearly one experiment, so its past hypotheses would measure a narrow slice.
- **Clones share the main ledger; `scientist.propose` reads only runs sealed `real`,** so sabotaged configs never reach its prompt or duplicate check. `run_locked` now seals real runs. The 3 older real runs were backfilled, marked `backfilled`.
- **A clone runs before its lock,** because a bug can change the config the pre-registration must describe. So a clone's lock is bookkeeping, unlike a real run's. This is a known difference in the ledger's timing, invisible to the reviewer.
- **Failed audits are ledger entries** (`audit_failed`, with a kind: `invalid_reply`, `timeout_or_server`, `prompt_too_large`) and stay retryable. 3 server failures in a row stop the pass for `--resume`, so an outage is not scored as reviewer failures. Neither run had a failure, so this path has only been tested with fakes.
- **Reviews are stored every 5,** because `ModelQueue.run` returned only at the end, so a crash would have left them all out of the ledger.
- **`--runs N`:** canaries are N x 5/9, rounded to a multiple of 20, the rest split evenly between controls and shams. 180 gives 100, 40, 40. No slot was skipped.
- **Batches:** RQ1 reports one batch. The 30-run pilot is excluded (`rq1_skeptic_a_pilot.json`), so nothing changed after it could mix in. It had the same result: 30 of 30 flagged, all B01.
- **Prompt left unchanged after the pilot,** even with this result. Tuning it would lose the unhinted baseline that Mission 6.4 compares against.
- **Chance baseline:** f = flagged / reviewed. Right-type chance is shown as f/10 and as f times the reviewer's own share of naming that class. Youden's J sits beside them because f depends on the batch's mix.
- **J pools recall into one Beta.** The first version averaged per-class posteriors and gave -0.07, falsely "worse than chance", because the prior shrinks ten small classes but only one large specificity group. Found before any result was reported, and a test now covers it.
- **Removed `test_real_sandbox_result_gets_a_verdict` and one sham test case** to stay under 30 s. `test_sandbox` and the real batches cover those paths.
- **`calibrate` commit name:** used `Mission 2.4: ...`, per CLAUDE.md, because the skill's template pasted the whole request into the subject.

## Scientist model comparison
5 proposals per model using the real prompt, schema, checks and sandbox, with earlier hypotheses fed into each next
prompt. All 15 replies were valid, and every new experiment ran. Nothing was written to the ledger. The sample is small:
1 vs 2 vs 3 new experiments does not prove one model is better; the speed differences are clear.

| | `qwen3:4b` | `qwen3.5:9b` (removed) | `qwen2.5-coder:7b` (chosen) |
|---|---|---|---|
| New experiments (rest were repeats) | 1 | 2 | 3 |
| Datasets / metrics | 1 / 1 | 1 / 1 | 2 / 1 |
| Models used | `gradient_boosting` | `random_forest`, `gradient_boosting` | `decision_tree` |
| Confidence given | 0.70-0.85 | always 0.75 | always 0.80 |
| Decisive verdicts | 0 of 1 | 1 of 2 | 1 of 3 |
| Warm reply / first load | 4.3 s / 12 s | 48 s / 73 s | 16 s / 57 s |
| Share on GPU | 100% | 47% | 76% |

`qwen3.5:9b` only swapped scalers on tree models, which barely matters (effects +0.0016 and +0.0007).

## RQ1 result: Skeptic A cannot tell buggy runs from clean ones
All numbers are from `eval/results/rq1_skeptic_a.json` (`gemma3:4b`, batch `rq1-full`, seed 2404, 18 bases, 8-10 distinct bases per class).
- **It flagged every run and always named B01,** at confidence 0.95 on 178 of 180. Recall 1.00 is exactly what flagging at random at that rate scores, and the 10 of 100 right-type catches are the 10 B01 canaries. Harmful, harmless, obvious and subtle canaries were all flagged, so those splits carry no information either.
- **It is the model, not the pipeline.** Checked on 3 clean controls from the pilot by direct calls: the same B01 flag came back with no schema, in plain JSON mode and with the schema's forms reversed. Told to pass, it passes, so the schema does not force a flag. A one-line `print('hello')` script was still flagged (B03).
- **Limits:** one model, one unhinted prompt, at temperature 0. The cause is untested; the "strict reviewer" system prompt and listing bug classes as a checklist are candidates. This does not say small LLMs in general cannot review.
- **Consequence for Mission 4.1, the main risk to the plan:** Rogan-Gladen divides by recall + specificity - 1, which is 0 here, so prevalence cannot be estimated from this reviewer, and a gate would reject everything. Canary needs a reviewer with J clearly above 0 before M4 means anything.

## Early findings for the report
- **The Skeptic confidently misreads correct preprocessing as B01 leakage.** `gemma3:4b` flagged B01 at confidence 0.95
  on 2 of 2 clean runs (ledger entries 11 and 12, runs `1875ec26` and `ebc3bccd`). Its evidence describes the correct
  procedure as the bug, e.g. "the test data is transformed using information from the training data".
  - **Checked by hand and by a syntax-tree scan of fit/transform calls:** both scripts split first, then call
    `fit_transform(X_train)` and `transform(X_test)`. Re-blinding each script reproduces the hash stored with its audit,
    so this is the code the Skeptic reviewed. Only labels are used before the split (class counts, positive class, `stratify`).
  - **Limits:** this is an anecdote from 2 runs, not a false-alarm rate. Why the model does this is untested. Possible
    triggers are the names-only prompt, bug class order, and `standard_scaler` being in both configs.
  - **Decision (option A):** leave the prompt and template unchanged, and measure specificity with controls in Mission
    2.4. Hints wait for Mission 6.4, so RQ1 keeps an unhinted baseline. In the report, take the numbers from the ledger.

## Saboteur effect sizes (after the realism pass)
A planted bug breaks the method in every variant, but it does not always move the numbers. `saboteur/impact.py` records
this for each canary against its clean twin (same seeds and splits): change in control, treatment and effect, and `size`,
the largest of the three ignoring sign. Harmful means `size` >= `min_effect_floor` (0.005). Re-run with
`python -m canary.cli sabotage-check <config> [--json file]`.
- **6 configs, 114 canaries:** 95 harmful, 17 harmless, 2 unmeasured, 0 failed.
- **B01 stays small and has no fixed direction, even with the leaky fit used:** largest change -0.006 to +0.008, harmful on
  2 of 6 configs per tier. A scaler's statistics barely differ between train and all rows, so this is what scaler leakage
  really does here. Both tiers give identical numbers, because they differ only in hiding the fit in a helper.
- **B02 subtle stays below a perfect score** on all 6 configs (largest treatment or control change +0.238, was +0.563).
- **B09 subtle, 112 model/dataset/metric combinations (3 seeds):** 102 lowered the control by at least 0.005, 0 did not, 10
  refused. 6 of the 10 are `gaussian_nb` with roc_auc, where the settings tried do not lower the score. The largest drop is -0.855.
- **B10, the same 112 combinations:** raised the treatment score on 110 of 112 in each tier, 0 lowered it, 2 tied (`svm` on
  `wine` and `ozone-level-8hr` balanced_accuracy). B10 obvious often gives a very high score, which is itself a clue at that tier.
- **B06 obvious is unmeasured,** because the bug is the metric, so its twin's numbers are on another scale.

## Fixes
- Coach status line pointed at Mission 3.1 (first unticked mission) while the real next step was the ceiling check: `coach_state.current_focus` now reads the "**Current focus:**" line under In progress, and the status line and session-start hook show it first (2 tests). Change that line when the focus changes.
- Token-probability scores were all None on task-dev-1: the ollama client drops `bytes`, and an empty list was read as zero bytes. The chosen token also did not count when it was outside the model's top 20. Both fixed with tests.
- The batch log crashed on the first checklist reply (no `verdict` field): the log and the `audit` printout now show the code's decision.
- Status-line tip said "a campaign was interrupted" after a finished `calibrate` batch: `coach_state.py` now recognises the batch's closing line, reads only the log's last line, and still treats a `STOPPED` batch as interrupted.
- Stop hook said "something failed?" whenever a message used the word "failed": it now needs a traceback header, a pytest count above zero, or a line starting `Error:`.
- `qwen3:4b` crashes and "token repeat limit" aborts from the open `params` schema: fixed with one schema form per model.
- A retried proposal replayed the cached rejected reply: each retry prompt now carries its attempt number.
- OpenML download crash on non-text labels (sklearn's pandas parser under pandas 3): now uses `parser="liac-arff"`.

## Known issues
- **Line endings (2026-11-18):** `git add --renormalize .` touches every tracked file, and `git status` can hide a CRLF
  working copy of a `-text` file whose stat data has not changed (happened with `docs/plans/review_task_screen.md`).
  Before any renormalize, compare every `-text` file with its HEAD blob (`eval.tripwires_test --git-check` covers only
  the tripwire plan's frozen files). `data/calibration/pool-2.json` is CRLF on disk and outside git: its only copies
  are this disk and the step 10 backup.
- **Freeze ended 2026-11-19 (`b28e722`):** the tripwire plan's and the ceiling plan's frozen files are unfrozen. The
  two lock checks stay as reproducibility checks and will report a mismatch once a listed file changes (expected).
- **Timeouts are flagged (fail closed), so slow real runs add false alarms (2026-11-19).** A run that times out at the
  120 s sandbox limit has no readable results.json and no trustworthy replay, so the tripwires mark it
  `unverifiable`, which counts as a flag; the one false alarm of `tripwire-test-1` is exactly this (a sham with the
  B04-obvious decoy; grid search is the slowest script type). In Mission 4 the union reviewer will therefore flag slow
  real runs. **Mission 4.1 and 4.4 must measure the timeout rate on real runs** (and report it beside the union's
  specificity); nothing is changed now.
- **Real runs carry only the classes the LLM misses (student, 2026-11-14).** Real Scientist runs are rendered from the
  template, so they can carry only config-level bugs: B06 and B09. Those are exactly the classes `skeptic_d` missed
  on arm L (B06 0/6, B09 1/6). So for real runs: **B06** is covered by the tripwire rule (L1) on every run, not by
  the LLM; **B09** needs a **proposal-time guard** (check before running that the control is not crippled), since no
  tripwire and almost no LLM catch exist. **Mission 4.1 must account for this**: the canary recall averaged over 10
  classes is not the recall that applies to real runs; what applies is the recall on B06 and B09 (with the rule
  and the guard). Union numbers stay expected, not measured, until sitting D.
  **Designed 2026-11-15:** the guard (`docs/plans/b09_proposal_guard.md`) and how Mission 4.1 uses it (support,
  worst-class gate, leak term: `docs/plans/mission_4_1_trust.md`). Not built yet.
- **Under the template, real runs cannot contain a code-level bug (found in the Mission 5.1 design, 2026-11-13).**
  Real scripts are rendered from the template, so only config-level problems can occur in them (accuracy on
  imbalanced data, a weak baseline). Consequences: tripwire recall on canaries says little about real runs; the
  recall that matters for Rogan-Gladen on real runs is recall on those classes; Mission 4.2's hidden-truth runs are
  where the whole estimate is tested. To weigh before Mission 4.1.
- **`DESIGN.md` sections 4 and 10 let "a tripwire firing" validate a Mission 6.2 mutant.** A library chosen that way
  holds only tripwire-detectable bugs, so it cannot measure tripwires. Change to a behavioural oracle (twin
  difference) when the Mission 5.1 design is approved; also keep "benign rewrites" for held-out specificity.
- **B09 (weak baseline) will have no tripwire** (design, 2026-11-13): the union's worst-class recall will be the
  LLM's recall on B09. Prevention at proposal time is the proposed fix for real runs (Mission 4.1).
- **Cloud provider facts that are still unverified (2026-11-11):** Gemini's free daily limit (not published; read it
  in AI Studio), which Groq tab the limits table read belongs to (confirm in the console), Gemini's token
  probabilities (reported deprecated, secondhand), which Gemini field is "silently ignored" on 3.6 Flash and newer
  (possibly temperature), and whether either endpoint accepts the review schemas. The live smoke test and the
  consoles settle these before the lock. Mistral's free plan was not researched (its page gave a 404).
- **The free route cannot give a P(flag) score**, so the cloud AUC is verdict-based and is not the same kind of
  number as llama's 0.643 (which used token probabilities). The paired comparison in the outline says so.
- **Free tiers are one tier below the paid frontier.** A HARD result holds for the two named models only.
- **`pytest -q` timing:** 851 passed in 18.7-20.4 s on 2026-11-18 (267 slow tests deselected; `pytest -m slow`
  about 4 min). Was at or over the 30 s target on 2026-11-10/11 (607-609 tests); keep timing it twice.
- **Base-level intervals over few bases run slightly narrow:** at 100 runs on 18 bases the bootstrap spread was 0.054
  against a true 0.058 (`eval/power_sim.py` check, 2026-11-10). Read borderline lower bounds with care.
- **Reviewers are not fully repeatable at temperature 0, and the cache hides it.** phi4-mini repeated its stored reply
  75/120 times, llama3.1:8b 94/120 (all 26 differences kept the verdict), gemma3:4b 118/120. Mismatched rescore records
  store no score, so AUC for phi and llama rests on a subset chosen by the model's own instability. Any trust number built from one cached reply per run treats the reviewer as
  deterministic. Before Mission 4.3 (drift), measure repeatability by asking again with the cache bypassed, and report
  it beside recall and specificity.
- **llama3.1:8b strains the laptop's RAM:** at 75% on the GPU, Ollama's llama-server held 8.7 GB of 15.3 GB, and
  Claude Code stopped a background run on low memory. Run long llama passes from your own PowerShell window, with
  Edge closed.
- **To fix during Mission 3.1 or earlier: every Scientist model favours one dataset and `balanced_accuracy`, and always
  predicts an increase.** Across the 15 proposals, 14 used `blood-transfusion-service-center`, all 15 used
  `balanced_accuracy`, and all 15 predicted an increase. The probable cause, not yet tested, is that the prompt shows
  past hypotheses about that dataset. Changing the model did not fix this, and it limits what the campaign can study.
- **`qwen2.5-coder:7b` has its own weaknesses:** it used only `decision_tree`, always gave confidence 0.80, stated that
  breast cancer is "50/50" (it is about 63/37), and runs partly on the CPU.
- **5 seeds may be too few for decisive verdicts.** Both real runs were inconclusive, with CI widths of about 0.10 and
  0.16 against a `min_effect` of 0.005. That is honest, but if most verdicts stay inconclusive the ledger will have
  little to accept. Check this on more runs (Mission 4.4) before changing `seeds_per_arm`.
- **The Scientist barely varies.** 8 trial proposals were nearly identical (same dataset and model family, confidence
  0.75 each), and both real hypotheses used the same dataset. A constant confidence will limit what the Brier score
  shows (Mission 3.2). The graveyard and calibration feedback may help; if not, ask for dataset variety in the prompt.
- **`qwen3:4b` hypotheses contain errors in their wording,** such as "76/2:24", and claim reasons that may not hold.
  Verdicts are unaffected, because they use only the configs and results.
- **The ledger cannot detect removal of its newest entries,** or a full rewrite of the chain from an edited point. A
  test documents this. Fixing it needs the latest hash stored elsewhere, for example in git.
- **`ledger verify` reports a problem if a run folder is deleted.** `/clean` must never remove `data/runs/` folders
  that the ledger references.
- **`crash_rate()` counts every folder in `data/runs/`, including the deliberate `broken.yaml` run** (it shows 1 of 2
  now). Before reporting a crash rate against the 42% figure, count campaign runs only.
- **The sandbox guards against accidents, not attacks:** experiments can still reach the network and other files. This
  is acceptable while scripts come only from our template; revisit it before running LLM-written code (Mission 6.2).
- **The cache can hide reviewer drift.** The key uses the model tag, not its digest, so if a tag is re-pulled with new
  weights, old replies are still served. Mission 4.3 should add the digest or bypass the cache when measuring drift.
- **Neither `gemma3:4b` nor `phi4-mini` can discriminate** (see the reviewer study). Fix the review task before Mission 4.1.
- **The run phase was slower than forecast:** the whole batch took 49.5 min against a forecast of about 30 (range 25-50). Reviews matched (3.1 s each); experiments took 40 min against about 19, because the pilot's 2 canaries per variant under-sampled slow cases. B09 subtle averaged 123 s, with one slot at 496 s. Forecast from this batch's means next time.
- **`crash_rate()` now also counts clones and twins in `data/runs/`.** Campaign reporting should use the sealed table's per-type counts instead.
- **Mission 4.3:** results now store each audit's seconds and the model's digest, but the cache issue above still stands.
- **The default suite skips 10 `slow` tests** (sandbox end-to-end, timeouts, figures, big Monte Carlo). Run `pytest -m slow`
  before each commit that touches those areas; `pytest -m "slow or not slow"` runs everything.
- **Real runs with a bug-like design are not caught yet.** `why_not_clean` only protects clones. A real run using accuracy
  above 3:1 is really buggy; Mission 5.1's B06 tripwire should catch it.
- **Canaries were longer than clean runs (fixed for new batches).** rq1-full and task-dev-1 keep the cue; new plans
  are length-matched, carry decoys and are gated on five size features (see "Padding redesign"). Left: decoys are
  hard controls a reviewer may flag, and
  **real runs have neither padding nor decoys yet**: a Mission 4.1 requirement (see Missions), or calibration runs
  would no longer look like real runs and measured trust may not transfer.
- **A sham's edits can be told apart in principle.** Its imports are out of the template's usual order. (Its names were
  also longer on average; since 2026-11-09 shams pick renames that keep the length within a few characters.) A stateless reviewer sees one run at a time and has no template to
  compare with, so this should not matter, but a reviewer that learned the template could separate them.
- **Overall recall looks more certain than it is while classes are untested.** With no data at all, it reads about 0.50, 90% [0.35, 0.65],
  purely from averaging 10 flat priors. `trust` and RQ1 print "tested k of 10"; any report must show that too.
- **Mission 5.1's B10 tripwire ("test size smaller than declared") will not fire:** B10 now drops rows inside `run_arm`, so
  `split_sizes` stays normal. It needs a different check. (Designed 2026-11-13: check K5 counts the pairs that reach
  the metric.)
- **Mission 5.1's B07 tripwire needs care:** `blood-transfusion` has 246 duplicate feature rows and `pc1` 161 before any
  bug, so row overlap between splits is normal there. Compare against the overlap expected from the dataset.
  (Designed 2026-11-13: check K1 compares the rows entering the split with the dataset's, counted, so natural
  duplicates match themselves.)
- **The test suite is still close to its limit** (28.9-30.0 s of 30 s with 597 tests on 2026-11-09, test bootstrap at 200 draws; runs on a busy laptop
  measured 31-40 s with no code change, so time it twice before trimming). The broken-config and sham tests now run in-process; the 2 remaining subprocess tests take about 3 s each.
- **Cold model loads are slow** (27-110 s seen). Handled with the 300 s cold timeout and `ModelQueue`.
- **`qwen3:4b` writing reasoning into replies did not occur in schema mode:** 2 of 2 real replies were clean JSON. Plain
  text mode was not retested, and any remaining `<think>` block is stripped.
- The Ollama CLI prints `CHECK failed: mlx_compile_cache_new_` on `--version` and `list`. The commands still worked
  and the cause is unknown.
- OpenML returns temporary 503 and "not found" errors. If a download fails, re-run `cache-datasets`; it skips what is
  already cached.
- **README's status line is hand-maintained:** when task-dev-2 or confirm-llama-2 finishes, update its "Status" line
  and the "What happens next" paragraph from `eval/results/` (llama stays "not confirmed" unless `confirm.json` says so).
- `python3` still opens the Windows Store stub. Canary only uses `python`, so this is harmless.
