# Plan: the baseline guard (B09 at proposal time)

Designed 2026-11-15 by Fable. Sitting 1 built 2026-11-20 (Opus). Not locked: this is a build plan, the locked test
plan is step 7. Changed 2026-11-20 by the student's decisions (G7, trap 7, the development fact): section 10.
Builder: Opus, 2 sittings. No cloud call is needed anywhere in this plan (only the local Scientist model and
scikit-learn runs), so the free-tier limit does not apply.

## 1. The problem in plain words
A real Scientist run is rendered from the template, so the only bugs it can carry are in its config. One of them
is the weak baseline (B09): the control is handicapped, so "the treatment helped" is partly an artifact. The cloud
reviewer caught 1 of 6 B09 canaries and no tripwire can check it, because the script, the config and the
pre-registration all agree with each other. So it has to be stopped **before the run**, by code that reads the
proposal.

The hard part: a simple control is not always a bug. "Depth 1 against depth 8" is an honest question. "Scaling
helps logistic regression", run with a control that also has `max_iter=1`, is not.

## 2. The idea: a fair control differs from the treatment in one thing only
The guard does not judge whether a control "looks weak". It asks two questions that code can answer.

**Question 1 (static, no run): in what do the two arms differ?**
- `effective(arm)` = the library's own defaults for that model, read at run time from
  `MODELS[model]().get_params()`, with the arm's `params` laid over them. A default written out (`C: 1.0`) and a
  default left out are the same thing. `random_state` is ignored.
- `factors(control, treatment)` = `"model"` if the models differ, else every parameter whose effective value
  differs; plus `"preprocessing"` if the scaler lists differ.

**Question 2 (measured, one short run): is this arm worse than its own reference?**
- The **reference** of an arm is the same arm with some settings put back to the library default (which settings:
  the table below). No hand-written table of "good" or "bad" values exists anywhere in the guard.
- `reference_gap(arm, reference)` runs one ordinary experiment in a temporary folder through `sandbox.run_config`,
  with `control = arm` and `treatment = reference`, on the registered dataset and metric, on **guard seeds**
  (fixed, 100001 upward, so never a run seed: run seeds are below 100000). The answer is read with the existing
  `prereg.compute_verdict` (direction increase, `min_effect` = `science.min_effect_floor` = 0.005, same alpha):
  - `supported`: the reference beats the arm by at least the floor, clearly. The arm is **weak**.
  - `not_supported`: the gap is clearly below the floor. **Not weak.**
  - `inconclusive`: these seeds cannot tell. Recorded as a number, no action.
- The only numbers the guard uses are the existing floor, the existing alpha and the number of guard seeds K
  (5, or 10 if step 6 says so). None is tuned on bug data.

## 3. What the guard decides
| # | What code finds | Example | Outcome | Reason for that outcome |
|---|---|---|---|---|
| G0 | accuracy on a dataset with a class ratio above 3:1 | accuracy on `pc1` | **reject** (retry with feedback) | the same rule as tripwire L1; cheaper to stop it before the run |
| G1 | same model, arms differ in 2 or more factors; or two models with different preprocessing | control `max_iter=1`, no scaler; treatment default, with scaler | **reject** | the comparison is confounded; the Scientist can fix it in one retry |
| G2 | two models; the control is **weak** against itself at library defaults | `logistic_regression {C: 0.0001}` against a random forest | **reject** | a handicap on a setting that is not the question: the B09 shape |
| G3 | one factor, a parameter; the control's value is not the default, and the control is **weak** against the default value | depth 1 against depth 8, where the default depth beats depth 1 | run, label `control_below_default`; at the gate it goes to the **human queue**, never auto-accepted | it may be the honest point of the experiment; a person decides; the claim is worded "against a control weaker than the library default" |
| G4 | one factor; settings shared by both arms are not defaults, and the control is **weak** against the control with those settings at default | both arms `max_iter=1` | run, label `weak_regime` (**warn**) | the finding is true as locked but holds only in a degraded setting; the report must say so |
| G5 | the reference run crashed or timed out | `gamma: 0.0` | **reject** | the real run would very likely crash too |
| G6 | none of the above | one factor, everything else at defaults or not weak | `ok` | |
| G7 | no factor: the arms are the same once defaults are filled in (added 2026-11-20) | `{C: 1.0}` against `{}` | run, label `no_difference`; **human queue**, never auto-accepted | the hypothesis names a change the experiment does not make |

References used: G2: all of the control's parameters at default. G3: only the tested parameter at default.
G4: only the shared parameters at default (the tested factor stays as the control has it). For preprocessing as
the tested factor, "default" means no scaler. When the reference equals the arm, nothing is run.

Rejections give the Scientist a sentence it can act on ("the arms differ in max_iter and preprocessing; change one
thing only") through the existing retry loop (`science.proposal_attempts`, 3). Every guard result, rejected or
not, is appended to `data/guard/proposals.jsonl`; an accepted proposal also carries its guard record in the ledger.

**Not covered, said plainly:**
- A treatment tuned hard against a control at defaults (unequal tuning effort). v1 only records the count of
  non-default parameters per arm (`tuning_asymmetry`).
- A control at library defaults where the default itself is poor (for example an unscaled SVM). The control is
  then weak in the everyday sense, but it is the documented default, and that is disclosed.
- Weak gaps the K-seed test cannot see. Step 7 measures how large a gap must be before the guard sees it.

## 4. False alarms on honest simple controls
- **Reject (G1) on an honest two-factor idea.** Cost: one retry, and two-factor questions cannot be asked in one
  run. Evidence so far (development data, not a test): all 35 bases in pools 1 and 2 differ in exactly one factor.
  **Corrected 2026-11-20:** of the 3 real runs, 2 differ in one factor; the first (Mission 1.4) does not once
  defaults are filled in: its control has the garbled key `": "` where `class_weight` should be, so its arms differ
  in `": "`, `class_weight` and `preprocessing`, and G1 rejects it. That run crashed. The 1-factor count above was
  read from the raw configs.
- **Reject (G1) for a difference that does nothing** (a `gamma` under a linear kernel). Harmless to reject: the
  retry removes a needless difference.
- **Queue (G3) on an honest simple control** ("a stump against depth 8"). Cost: a person looks at it. It is not
  thrown away. Step 7 reports how often this happens on fresh proposals.
- **G3 when the treatment is the library default.** The control's reference is then the treatment itself, so G3
  fires exactly when the hypothesis is true. Every finding of the form "the default beats my unusual value" goes
  to a person. That is intended (the unusual value is the strawman), but it can be many: E1 counts them, and
  the student may turn G3 into a label without the queue (decision 2).
- **Warn (G4) on a sensible shared choice.** `class_weight: balanced` lowers plain accuracy, so with the accuracy
  metric the guard may call the regime weak. That is why G4 only warns.
- **When library defaults are bad**, the reference is weak and the guard goes quiet. This is a miss, not a false
  alarm, and it is the safe direction for honest proposals.

## 5. Measuring the guard fairly (no circularity)
What would be circular, and the rule against it:
1. **G0 and G1 are rules, not detectors.** The saboteur's B09 changes only the control, so every B09 canary cloned
   from a one-factor base has two differing factors, and G1 rejects it by definition. That is not evidence. G0 and
   G1 are reported as rules, outside any recall figure, exactly like L1. Nobody may write "the guard detects B09
   with recall 1.0".
2. **No value lists.** The guard may not import `canary.saboteur`, `canary.controls` or `canary.sealed`, and its
   source may not contain a table of hyperparameter values. Defaults come from scikit-learn at run time. A guard
   test enforces both.
3. **The designers have read the saboteur.** So the measured part has no free threshold: the floor and alpha
   already exist; K is fixed in step 6 on development data before the test data exist.
4. **Truth is behaviour, never "the guard fired" and never "the saboteur planted it".** The oracle is a twin
   difference on 10 **oracle seeds** (200001 upward, disjoint from guard and run seeds): the mean paired drop of the
   arm against its reference, or against its unperturbed base. "Truly weak" means a mean drop of at least the floor.
   The oracle uses no interval, like `saboteur/impact.py`.
5. **Fresh data, judged once.** Pools 1 and 2 are development data. The test uses proposals that do not exist yet.

**The test has two parts (step 7 locks them; both run once):**
- **E1, natural proposals.** At least 120 fresh raw proposals from the Scientist (questions q1 and q2, the focus
  grid and unfocused), generated with the guard **off**, then passed through the guard. Reported: the share of each
  outcome G0 to G6 with Beta intervals (this is a result in itself: how often a small LLM scientist proposes a
  confounded or weak control); then with the guard **on**: attempts per accepted proposal and the share of
  `ProposalRejected`. For every proposal with a measured gap: the guard's answer against the oracle's.
- **E2, planted handicaps of shapes nobody hand-picked.** Take guard-`ok` fresh bases. A generator changes one
  setting by a mechanical recipe over the whole legal range of the schema (numbers: log-uniform over a range
  declared in the locked plan; choices: any other allowed value), in three shapes of 40 each: control only (rule
  G1, reported as a rule), both arms (G4), the control's value of the tested factor (G3). The oracle labels each
  one weak or not by behaviour. Reported for G3 and G4: recall by size of the true gap (floor to 0.02, 0.02 to
  0.05, above 0.05) and the false-alarm rate on the ones the oracle calls not weak.
- **Bars, fixed now.** False-alarm rate of "weak": upper end of the 90% interval at most 0.10. Recall for true gaps
  above 0.05: lower end at least 0.80. Usability: `ProposalRejected` at most 0.20 (upper end). **If a bar fails,
  the measured rows (G2 to G4) become advisory numbers only: no reject, no queue from them.** G0, G1 and G5 stay.
- **Held-out shapes:** weak-baseline mutants written by an LLM are Mission 6.2. Until then that cell reads "not
  measured", the same convention as the tripwires.

## 6. Build order (Opus)
New file `canary/baseline_guard.py`. Not frozen and safe to edit: `canary/scientist.py`, `config/campaign.yaml`.
**Frozen until tripwire sitting D is done: `canary/cli.py`, `canary/mixer.py`, `canary/prompts.py`** (ceiling
lock). So: no new CLI subcommand (use `python -m canary.baseline_guard`), and the Scientist's prompt text is not
changed (the feedback sentence travels through the existing retry argument).

**Sitting 1 (steps 1 to 4): the guard exists and is wired.**
- **Step 1. Static part.** `effective_params(arm)`, `factors(control, treatment)`, `nondefault(arm)`.
  Tests (fast): a default written out equals a default left out; `1` equals `1.0`; `None` handled; two models give
  `["model"]`; scaler lists compared in order; an unknown parameter name is reported, not a crash; defaults are
  read from the library (monkeypatch a model's `get_params` and see the answer change). Guard tests: import
  allow-list; no `saboteur` vocabulary; no dict of parameter values in the source (walk the syntax tree).
- **Step 2. G0, the metric rule.** Own constant for the ratio; a test asserts it equals `classes.IMBALANCE_RATIO`
  (the test may import the saboteur, the guard may not). Class counts from `datasets.load_dataset`.
  Tests: silent at exactly 3:1, fires just above; silent for other metrics.
- **Step 3. Measured part.** `reference_for(rule, control, treatment)`, `reference_gap(config, arm, reference,
  run=sandbox.run_config)`. `run` is a parameter so tests inject a fake that returns chosen scores.
  Tests (fast, fake runner): the three verdicts map to weak / not weak / inconclusive; crash maps to unverifiable;
  no run when the reference equals the arm; guard seeds are all at least 100000. One slow test with a real run:
  `logistic_regression {max_iter: 1}` on `breast_cancer` is weak against its default.
- **Step 4. Decision and wiring.** `check_proposal(locked) -> GuardRecord` (outcome, rule, factors, gaps, K,
  scikit-learn version, guard version). In `scientist.proposal_problem`: a reject returns the feedback sentence.
  In `scientist.run_locked`: the record goes into the `PROPOSED` payload under `guard`. Append every result to
  `data/guard/proposals.jsonl`. Switch `science.baseline_guard: true` in `config/campaign.yaml`.
  Tests: each row of the table in section 3 from a hand-made proposal; the `locked` record and its hash are
  unchanged by the guard (so the reviewer's prompt is unchanged: a test builds the blinded text with and without);
  the guard off gives today's behaviour exactly.
  **Done when:** `pytest -q` passes under 30 s; `python -m eval.ceiling_lock --check` is OK;
  `python -m canary.baseline_guard config/examples/baseline.yaml` prints a record.

**Sitting 2 (steps 5 to 8): measure it.**
- **Step 5. Oracle and generator.** `eval/guard_oracle.py` (twin difference on oracle seeds) and
  `eval/guard_perturb.py` (the mechanical recipe; seeded). Tests: seeds disjoint; the recipe never returns the
  original value; fake-runner arithmetic against hand-computed gaps.
- **Step 6. Development run.** `python -m eval.guard_dev` on the 35 bases of pools 1 and 2: outcome table, time per
  proposal, and for K = 5 and K = 10 the share of inconclusive gaps. Rule fixed now: use K = 5 unless more than
  half of the measured gaps are inconclusive, then K = 10.
- **Step 7. Lock and test.** Write `docs/plans/b09_guard_test.md` (sizes, recipe ranges, seeds, bars from section
  5, the exact commands) with its `.sha256`; then generate the fresh proposals and run
  `python -m eval.guard_test` **once**. Output `eval/results/guard/guard_test.json` with raw per-proposal rows.
- **Step 8. Write-up.** `PROGRESS.md`, `docs/DESIGN.md` (section 11 gets the guard; section 4 says B09 is handled
  at proposal time on real runs), Known issues updated. Every number from the JSON.
  **Done when:** the JSON exists, each bar is printed as passed or failed, and the consequence in section 5 is
  applied in `config/campaign.yaml` (`baseline_guard_measured: enforce` or `advisory`).

## 7. Traps
1. **Do not put the guard record inside `locked`.** The pre-registration text is what the reviewer sees and what
   clones copy. A new key would make real runs differ from calibration runs.
2. **Do not run the guard on clones.** A B09 canary fails G1 by construction; running the guard there would also
   need the sealed table. Clones are cloned from bases that already passed.
3. **Pool 3 must be built with the guard on,** or calibration bases and real proposals come from different
   distributions.
4. **Seeds:** guard seeds, oracle seeds and run seeds must never overlap, or the guard has looked at the run's
   own splits before the lock.
5. **The feedback leaks a little data** (the control's gap) to the Scientist before it locks. It concerns the
   control only, never the treatment or the effect. Say so in the report.
6. **Library defaults move between scikit-learn versions.** The record stores the version; never copy defaults
   into the source.
7. **Time.** A reference run is an ordinary sandbox run (seconds; the slow models up to a minute). **At most two
   per proposal attempt (amended 2026-11-20, student):** G2 needs one; a one-factor proposal needs G3's and, when G3
   does not find the control weak, G4's (in the sitting-1 listing 10 of 38 proposals needed two). After a G3
   finding G4 is not measured. Use a temporary folder: nothing under `data/runs/`, nothing in the crash rate.
8. **The rejected-proposal log is not the ledger.** When the graveyard exists (Mission 3.1), rejected proposals
   move there with the guard rule as cause of death.
9. **Mission 4.1 depends on this plan** for two things only: the label on each real run, and the leak rate from
   step 7 (weak controls among guard-`ok` proposals, by the oracle). See `docs/plans/mission_4_1_trust.md`.

## 8. /challenge (strict reviewer), with the fix
| # | Severity | Finding | Fix (already in the sections above) |
|---|---|---|---|
| 1 | Critical | Reporting G1 on B09 canaries as recall would be circular: the rule and the planting are the same line. | G0 and G1 are rules, outside recall (5.1). The informative test is E2's shapes for G3 and G4 and E1's oracle comparison. |
| 2 | Major | "Weak against library defaults" misses a control at a poor default, and misses a treatment tuned against a default control. | Said plainly as not covered (section 3). `tuning_asymmetry` recorded. Claims say "against the library default", never "a fair baseline". |
| 3 | Major | Five seeds with the corrected interval give a weak test: many gaps will be inconclusive, so the measured rows may rarely fire. | K decided by a fixed rule on development data (step 6); recall reported by gap size; a failed bar turns the measured rows advisory (5). |
| 4 | Major | The oracle and the guard use the same kind of measurement, so they share blind spots (both compare with library defaults). | The oracle uses more seeds, disjoint seeds, and in E2 compares with the unperturbed base, not with defaults. What both miss is listed under "not covered". |
| 5 | Major | The guard looks at data before the pre-registration is locked. | Control arm only, on seeds no run can draw; it can only remove weak controls, which makes effects smaller, not larger. Disclosed (trap 5). |
| 6 | Moderate | One-factor only forbids real interaction questions. | Accepted cost for v1; measured as the G1 share in E1. If it is high on fresh proposals, the student decides whether to allow declared two-factor designs. |
| 7 | Moderate | E2's recipe is still written by people who know the catalog. | The recipe is mechanical over the schema's whole range and locked before data; LLM-written mutants stay "not measured" until 6.2. |
| 8 | Moderate | Rejected proposals vanish today, so the natural rate of weak controls could not be reported. | Every guard result is logged (section 3). |
| 9 | Minor | The human queue does not exist yet. | Until Mission 4.1, G3 is a label only; the gate reads it later. |
| 10 | Major | With the treatment at the default, G3's reference run is the experiment itself on other seeds: the guard has in effect run the experiment before the lock, and queues every true finding of that form. | The Scientist gets no feedback from G3 (the run proceeds), so nothing leaks into the proposal; the gap is stored, never shown to the reviewer; the volume is measured in E1 (section 4). |

## 9. Decisions (approved by the student, 2026-11-15)
1. One factor only (G1 rejects): **yes.**
2. G3 goes to the human queue, G4 only warns: **yes.**
3. Add G0 (the L1 rule at proposal time) in the same module: **yes.**
4. The bars in section 5: **as written.**

Sitting 1 is now a prerequisite of the RQ4 bank: pool 3 is built with the guard on
(`mission_4_2_hidden_truth.md`, section 2a).

## 10. Changes after sitting 1 (student, 2026-11-20), before the guard test is locked
1. **The guard record stays in the PROPOSED ledger entry of real runs only.** The ledger already differs between
   real runs and clones (a clone's lock is written after its run, accepted in Mission 2.4), because the reviewer
   never sees the ledger; a test enforces that reviewer code never reads the guard key. Copying a base's record
   onto its clones would be false for B09 canaries; a separate file would lose the ledger's tamper evidence.
2. **Two reference runs per attempt are allowed** (G3, then G4 when G3 finds nothing): trap 7 amended.
3. **The development fact in section 4 is corrected** for the garbled first real run (G1 rejects it).
4. **Arms identical after defaults go to the human queue (new row G7), never auto-accepted;** they were `ok` in
   sitting 1.
5. **Pool files store each base's guard record** (`mixer.build_pool`, key `guard` beside `prereg`), so pool 3 is
   built with the records.
