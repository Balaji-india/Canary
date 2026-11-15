# Plan: Mission 4.1, prevalence, contamination and the trust gate with the union reviewer

Designed 2026-11-15 by Fable. Not built. Builder: Opus, 2 sittings. Building needs no cloud call.
Depends on: tripwire sitting D (the union's measured numbers) and the baseline guard
(`docs/plans/b09_proposal_guard.md`). The code can be built before both, on synthetic counts and on `skeptic_d` alone.

Simulation behind every "simulated" number here: `docs/plans/sims/trust_design_sim.py`, output
`trust_design_sim.json` beside it. **Its reviewer rates are assumptions for sizing** (union: 0.97 on nine classes,
0.17 on B09; LLM alone: 0.94 on eight classes, 0.05 on B06, 0.17 on B09; specificity 0.98), not measurements. Step 1
rebuilds it as tested code and re-runs it with the measured numbers.

## 1. The problem in plain words
Rogan-Gladen turns the reviewer's flag rate on real runs into "what share of real runs is buggy":
`prevalence = (flag rate + Sp - 1) / (Se + Sp - 1)`. It is only right if `Se` is the recall **on the kind of bugs
the real runs have**. Canaries are spread evenly over 10 classes. Real runs are not: under the template they can
only carry config-level bugs, and those are the classes the LLM misses. So the canary average is the wrong `Se`
for real runs, and nothing in the formula warns about it.

## 2. Three ideas that fix it
**Idea 1: say which bugs a population can have (its support).** A support is a list of (class, tier) variants,
written in `config/campaign.yaml`. A variant may be left out only if a named rule or test excludes it:

| Population | Support | What excludes the rest |
|---|---|---|
| real runs, guard on | all variants except B06 obvious and B09 | B06 obvious: rule G0 before the run and L1 after it. B09: rule G1, plus the measured leak (idea 3) |
| real runs, guard off | all variants except B06 obvious | L1 only |
| hidden-truth runs (Mission 4.2) | all 20 variants | nothing: the estimator is not told what was planted |

Code-level variants stay in the support of real runs. A real script is the template plus padding and a decoy, so a
fault in that pipeline could put a code-level bug into a real run; the union's recall on those classes is high, so
keeping them costs nothing.

**Idea 2: two recalls, two jobs.**
- **Pooled recall** = the mean of the per-class recalls over the support (each class its own Beta posterior, as
  `trust.overall_recall_draws` does). It is the central estimate, and it is right only if real bugs are spread
  like the canaries. It is a mean of classes, not one count over all canaries, so it does not change when some
  classes get more canaries than others.
- **Worst-class recall** = the posterior of the class with the lowest posterior mean in the support (ties by ID).
  It gives a bound that holds whatever the mix of known bug classes is. **The gate uses this one.**
- Why not pooled for the gate (simulated): if every real bug is of the worst class and 30% of real runs are buggy,
  the true contamination is 0.27, and a gate on the pooled recall still opens in 81% to 100% of campaigns. The
  worst-class gate opens in 0% to 3%.

**Idea 3: B09 is handled by prevention, and its leak is measured directly.** With B09 in the support, the worst
class has a recall near 0.2, Rogan-Gladen divides by a number near 0.2, and the estimate is too noisy to ever pass
a 0.10 gate (simulated, **zero** real bugs: the gate opens in 8% to 35% of campaigns with the union, 0% to 4% with
the LLM alone, even with 40 canaries per class, 120 clean runs and 120 real runs). With B09 out of the support the
gate opens in 97% of campaigns at 6 canaries per class, 60 clean and 30 real runs, and in 100% from 12, 60 and 60.

So B09 leaves the support only through the guard, and what the guard lets through is added back as a **leak
term**: among guard-`ok` proposals in the guard's fresh test, the oracle found k of n controls truly weak; the
leak is `Beta(1 + k, 1 + n - k)`. No credit is taken for the reviewer catching any of them. The leak counts only
what the oracle can see: weakness against library defaults. Other weak baselines (a poor default, a treatment
tuned against an untuned control) are outside it and are named as not covered.
Simulated: with a leak of 0 of 100 or 2 of 100 the gate still opens; so the guard test needs about 100 guard-`ok`
proposals with at most a few weak ones.

**Until the guard has passed its test, B09 stays in the support and no real finding is auto-accepted.** That is
the honest state, and the dashboard must show the reason.

## 3. The arithmetic (`canary/trust.py`, `canary/gate.py`)
Inputs: per-class recall posteriors from **measuring canaries of supported variants only**; the specificity
posterior from controls and shams; the flag-rate posterior on real runs `Beta(1 + flags, 1 + passes)`; the leak
posterior or none. 5000 draws, fixed seed. Per draw, for `Se` = pooled and for `Se` = worst class:
1. `den = Se + Sp - 1`. If `den <= 0` the draw's prevalence is 1 (worst case; never dropped).
2. `prevalence = clip((p + Sp - 1) / den, 0, 1)`.
3. `contamination = prevalence * (1 - Se) / (prevalence * (1 - Se) + (1 - prevalence) * Sp)`; 0 when prevalence is
   0; 1 when nothing can pass.
4. Gate figure: `total = min(1, contamination_worst + leak / (1 - p))`.

Reported every time, side by side: prevalence and contamination, pooled and worst class, each with its 5th to 95th
percentile; the worst class by name; the support; the leak; the counts behind every posterior.

**The gate, for a real run the reviewer passed:**
| Check, in order | Result |
|---|---|
| the guard labelled it `control_below_default` | escalate to the human queue |
| a class in the support has fewer than 12 measuring canaries, or fewer than 60 clean runs reviewed | closed: "not enough calibration" (the campaign agent's cue to recalibrate) |
| `Se_worst + Sp - 1 > 0` in fewer than 95% of draws | closed: "reviewer uninformative for class X" |
| 90th percentile of `total` at most tau (0.10; 0.05 under a drift alarm) | **accept** |
| otherwise | escalate (replication, then the human queue) |

A flagged real run goes to the graveyard with "flagged: class" as now. Every decision is written to the ledger
with all the numbers above. The gate is a property of the campaign's state, not of one run: all passed runs get
the same answer at a given moment.

**The union reviewer.** A run's union verdict is "flag" if its tripwire record or its first LLM audit says flag
(`mission_5_1_tripwires.md` section 8). Trust numbers for the union are computed from union verdicts on runs that
have both, never from the two halves. `trust.collect_observations` gets a sibling that builds union observations;
the gate takes any list of observations, so it works for `skeptic_d` alone today.

## 4. What the free tier allows (about 65 reviews a day)
- **Calibration is the cost, clean runs most of all.** To open the gate from nothing: 12 canaries for each of 9
  classes in the support, 60 clean runs, 60 real runs = 228 reviews, about 3.5 sessions.
- **Start from the Mission 4.2 bank.** The 360 runs of `rq4-bank-1` (200 canaries, 160 clean, on a fresh pool 3
  built with the guard on) get reviewed for Mission 4.2 anyway. After RQ4 is analysed they are the campaign's first calibration set, so science can
  start with the gate already able to open, **if the sentinel set shows the model has not changed**.
  (Roadmap pass, 2026-11-15: as sized, the bank holds 10 B06-subtle canaries, and B06 counts in the real-run
  support through that variant only, so the bank alone leaves B06 at 10 of the 12 the gate needs. With the
  proposed top-up of 10 (`mission_4_2_hidden_truth.md`, section 2b) the sentence holds; without it the first
  campaign block calibrates B06. "The model has not changed" is made exact in `mission_4_3_drift.md`, section 2.2.)
- **Spend canaries where the gate looks:** equal numbers per class in the support, not the 15% mix. B09 canaries
  are kept at a low rate for the blind-spot record only.
- **Lazy union (a decision for the student, section 8):** in campaigns, ask the LLM only when the tripwires pass;
  a tripwire flag already decides the union's verdict. This changes no union number. It saves almost every canary
  call, so a day's 65 reviews go to real and clean runs. The price: no LLM-alone verdict on tripwire-flagged runs,
  so LLM-alone numbers come from measurement batches only (where both are always asked).
- **Calibrations from different model snapshots are never pooled.** A sentinel change beyond its baseline
  (1 change in 20) closes the gate until a new calibration.

## 5. Build order (Opus)
Frozen until sitting D is done: `canary/cli.py`, `canary/mixer.py` and the other ceiling files. So: new module
entry points (`python -m canary.gate`), no new `canary.cli` subcommand yet. `canary/trust.py`,
`canary/scientist.py`, `canary/ledger.py` and `config/campaign.yaml` are not frozen.

**Sitting 1 (steps 1 to 4, and step 6): the numbers.** Step 6 changes `canary/trust.py`, which the RQ4 plan
freezes (`mission_4_2_hidden_truth.md`), so it is built here, before that lock.
- **Step 1. `eval/rq4_power.py`:** the simulation as tested code (same functions the real estimator uses, so the
  simulation cannot drift from the code). Tests: seeded and repeatable; a reviewer with recall 1 and specificity 1
  recovers the planted prevalence exactly. Re-run with measured numbers when sitting D has them.
- **Step 2. `trust.prevalence_draws` and `trust.contamination_draws`.** Tests against hand-computed values:
  `Se 0.8, Sp 0.9, p 0.3` gives prevalence 0.2857 and contamination 0.0816 (0.05714 / 0.7); `p` below `1 - Sp`
  clips to 0; `den <= 0` gives 1; prevalence 0 gives contamination 0; point posteriors (huge counts) reproduce the
  formulas to 3 decimals.
- **Step 3. Support.** `summarize(..., variants=...)` filters canaries by (class, tier); `campaign.yaml` gets
  `trust.support` per population with the excluding rule named next to each left-out variant. Tests: B06 recall in
  the support comes from subtle canaries only; a class with no canaries is `untested` and closes the gate; the
  worst class is the lowest posterior mean, ties by ID.
- **Step 4. `trust.estimate(observations, real_flags, support, leak)`** returning one record with everything in
  section 3. It takes flags for the real runs, never the sealed table. Test: its signature and imports (no sealed
  access on the real-run side); pooled and worst agree when there is one class.

**Sitting 2 (steps 5, 7, 8): the gate and the real-run pipeline.** It may run while the RQ4 reviews are under way:
it edits no file that plan freezes.
- **Step 5. `canary/gate.py`:** the table in section 3 as code; `python -m canary.gate --demo` runs it on
  synthetic counts and prints each branch. Tests: one test per row of the table; a decision record holds every
  number; the gate never accepts with an untested class.
- **Step 6. Union observations** from tripwire records and LLM audits (after tripwire step 11 exists; until then
  a stub that takes two verdict lists). Tests: flag if either; a run with a failed LLM audit and a passing tripwire
  has no union verdict and is counted, not scored.
- **Step 7. Real runs look like calibration runs** (the student's requirement of 2026-11-09): `run_locked` gives a
  real run the same padding and a decoy, the decoy drawn in the canaries' proportions and recorded in the sealed
  row. Then the length check on real runs mixed with calibration runs. Tests: a real run's blinded length class
  and helper size fall inside the calibration range; its numbers equal the plain template's (the decoy is inert).
- **Step 8. Ledger and write-up.** `ACCEPTED`, `ESCALATED`, `GRAVEYARD` entries carry the decision record;
  `PROGRESS.md`; `DESIGN.md` sections 7 and 8 rewritten to this plan.
  **Done when:** `pytest -q` under 30 s; `python -m canary.gate --demo` shows accept, escalate and both closed
  reasons; `python -m canary.gate --role skeptic_d` on the real ledger prints the full record and says "closed:
  B09 in the support, guard not tested" (the true state today).

## 6. Traps
1. **Never quote the pooled prevalence without the worst-class one and the support.** The pooled one is right
   only under the canaries' mix.
2. **Probes never feed any of this** (as now). Neither do runs whose audit failed.
3. **Ten flat priors shrink the pooled recall toward 0.5.** With few canaries per class the pooled prevalence is
   biased upward (simulated at 10 per class: median 0.53 for a true 0.50). It is the conservative direction;
   report the counts beside it.
4. **The worst class is picked from noisy means,** so its recall is a little too low on average (conservative),
   and the class can change between recalibrations. Log the class name with every decision.
5. **Runs from the same base are not independent.** The Beta posteriors treat them as independent, so intervals
   are somewhat too narrow. Report a base-level bootstrap as a sensitivity (the ceiling analysis has the code).
6. **Specificity comes from clean runs with decoys.** It transfers to real runs only after step 7.
7. **The leak term is only as fresh as the guard test.** A changed Scientist model or prompt needs a new one.
8. **Unknown bug kinds are not covered by any of this.** Every sentence says "bugs of the catalogued kinds".
   Mission 6.2's mutants are the first measurement beyond them.
9. **Do not tune tau, the percentile or the minimum counts on results.** They are fixed here.

## 7. /challenge (strict reviewer), with the fix
| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Critical | The recall in the formula does not match the bugs real runs can have; a pooled gate opens at 27% true contamination when the mix is adverse. | Support per population; the gate uses the worst class in the support (section 2). |
| 2 | Critical | Taking B09 out of the support is a claim about the guard, and G1 covers only one shape of weak baseline. | B09 leaves only with the guard on and tested; the measured leak is added back with no reviewer credit; until then the gate stays closed and says why. |
| 3 | Major | With B09 gone, real template runs have almost no way to be buggy, so the estimate is near 0 by construction. Is the mission empty? | No: on real runs it is a watch for the unexpected (a flag rate above the false-alarm rate). Whether the estimator is right is tested where bugs exist: the hidden-truth populations of Mission 4.2, including an adverse mix. Said in the report. |
| 4 | Major | Every simulated number rests on assumed reviewer rates; the union has not been measured. | Step 1 re-runs with sitting D's numbers before anything is locked; this file says "assumed" wherever a simulated number appears. |
| 5 | Major | Contamination "of catalogued kinds" may be read as contamination. | Wording rule (trap 8) and a fixed sentence in the dashboard banner. |
| 6 | Major | Clustering by base and day-to-day drift make the posteriors too confident. | Base-level sensitivity; sentinel set; no pooling across snapshots. |
| 7 | Moderate | The gate is all-or-nothing for a campaign, so "gates each finding" overstates it. | Said plainly in section 3; per-run differences come only from flags and guard labels. |
| 8 | Moderate | The gate is very cautious: at 30% buggy real runs and a good reviewer the true contamination is 0.013, yet it opens in only 3% to 78% of simulated campaigns. | Accepted: a 30% flag-implied bug rate should stop auto-acceptance. Reported as the gate's operating characteristic, measured again in RQ4. |
| 9 | Moderate | Lazy union drops LLM-alone data on tripwire-flagged runs. | The student's decision; measurement batches always ask both. |
| 10 | Minor | 12 canaries per class and 60 clean runs are round numbers. | They come from the simulation rows where the gate opens reliably with no real bugs; fixed before any real data. |

## 8. Decisions (approved by the student, 2026-11-15)
1. The gate uses the worst class in the support; pooled is shown beside it: **yes.**
2. B09 leaves the support only after the guard passes its test; until then nothing is auto-accepted: **yes.**
3. In campaigns the LLM is asked only when the tripwires pass (not in measurement batches): **yes, from Mission
   4.4 on.** The RQ4 bank is a measurement batch: both are always asked there.
4. Minimum calibration before the gate can open: 12 canaries per supported class, 60 clean runs: **yes.**
