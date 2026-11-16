# Plan: Mission 4.2, hidden-truth validation of the prevalence estimate (RQ4)

Designed 2026-11-15 by Fable. Not built, not locked: step 2 writes the locked plan
`docs/plans/rq4_hidden_truth.md` from this one. Builder: Opus (1 sitting for the code, 1 for the analysis); the
reviews run in the student's window over about a week.
Depends on: tripwire sitting D and step 11 (the locked tripwire version and its runner), guard sitting 1 (pool 3
is built with the guard on) and Mission 4.1 sitting 1 (the estimator).
**Changed 2026-11-15 (student's question): the bank is a new batch on a fresh pool 3, not `tripwire-test-1`**
(section 2a). Read `docs/plans/mission_4_1_trust.md` first: "support", "pooled" and "worst class" are defined there.

Simulations: `docs/plans/sims/trust_design_sim.py` (sample size) and `docs/plans/sims/rq4_bank_sim.py` (pass
marks), outputs beside them. **Reviewer rates in both are assumptions,** re-run with measured numbers in step 1.

## 1. The question
RQ4: is the prevalence estimate right? Hide the truth from the estimator, give it only the reviewer's flags on a
set of runs whose true share of buggy runs we know, and compare its interval with that share, at several shares.

## 2. The design in plain words: one reviewed bank, many hidden-truth populations
A prevalence level is only a mixture. A population with 30% buggy runs is 30 canaries and 70 clean runs. So the
expensive part (reviews) is done **once**, on a bank of runs with known truth, and every level is built from the
bank by drawing runs. Extra levels cost no reviews.

- **The bank: `rq4-bank-1`, a new batch on a fresh pool 3.** 360 runs with the same make-up as the tripwire test
  batch: 200 canaries (20 per class, 10 per variant) and 160 clean runs, padded, with decoys, built with
  `calibrate --no-audit`. The locked tripwire version then writes a tripwire record for every run (local, no
  cloud call), and `skeptic_d` reviews all 360 with the baseline prompt and arm L's settings. Each run then has
  both, so the union's verdict is known. The sizes are unchanged, so the simulations still apply.
- **One re-split** = draw an **audited set** of 100 runs with a fixed share of canaries, then a **calibration
  set** from the runs that are left: 12 canaries per class and 60 clean runs. The estimator
  (`trust.estimate`) gets the calibration set with its truth, and the audited set as **flags only**. Code compares
  its answer with the audited set's true share.
- **Levels:** 0, 0.10, 0.30, 0.50 buggy. Level 0 matters most for real use: real runs are expected to be almost
  all clean, and the estimate must say so.
- **2000 re-splits per level,** seeded. Re-split number 0 is the one shown as "the campaign" in the figure
  (estimate and interval against truth at each level); the other 1999 show how much that picture depends on luck.

### 2a. Why the bank is not `tripwire-test-1` (decided 2026-11-15)
The first draft of this plan reviewed `tripwire-test-1` with `skeptic_d`. The Mission 5.1 plan is right and that
draft was wrong, for three reasons:
1. **A recorded decision.** The student approved "no pool 3" for `tripwire-test-1` on the stated ground that
   pool 2 is used up for LLM reviewers and this batch "may never be used for" one
   (`mission_5_1_tripwires.md`, section 12, answers). Reviewing it would remove the ground that decision stands on.
2. **Not out of sample.** `skeptic_d`'s results on pool 2's bases (`ceiling-ext`) were read before this design
   was written: the B09 and B06 misses came from there. Kind C predicts "pooled fails when B09 is common". Tested
   on clones of the same 17 bases, that prediction would partly re-confirm what was already seen. The ceiling
   plan's own rule is that anything decided after reading those results is judged on a new pool.
3. **The bank becomes the first calibration set for real campaigns.** Real proposals will pass the baseline
   guard, so the bases they are compared with must have passed it too. Pool 2 was built without the guard.

**Pool 3:** built by the existing pool builder with a new seed, the guard on, and pools 1 and 2 passed as
`avoid` (so no base repeats), question q1 and the same focus grid. At least 17 bases, or stop and report. The
guard version is written into the pool file. `tripwire-test-1` stays what it was approved as: a tripwires-only
test batch. Running the locked tripwires on `rq4-bank-1` is a use of them, not a second test, though its
recall there is reported as one more "known shapes, fresh bases" figure. The efficiency search (ceiling plan,
follow-up) needs its own fresh pool after this one (pool 4).

**Three kinds of audited population** (all from the same reviews):
| Kind | How the audited canaries are drawn | What it tests | Expected |
|---|---|---|---|
| A. matched | evenly over the 10 classes | the arithmetic and the interval, when real bugs are spread like canaries | pooled estimate close to the truth |
| B. other experiments | as A, but calibration and audited runs come from **different bases**; half a bank each, so 60 audited runs and 8 calibration canaries per class | transfer from calibration clones to other experiments, the nearest thing to real runs | as A if the reviewer behaves the same across experiments |
| C. adverse mix | a large share of the canaries are B09, the class the reviewer misses | what Mission 4.1 claims: pooled fails, the worst-class bound holds | pooled too low; worst-class upper end still above the truth |

Kind C, from the bank alone: 40% of the audited canaries are B09, at levels 0.10 and 0.20 (the bank has 20 B09
canaries; 12 must stay for calibration). **Recommended top-up:** 30 more B09 canaries (batch `rq4-b09`, about an
hour on the laptop and 30 reviews) allow 50% B09 at levels 0.10 and 0.30, where the simulated failure of the
pooled estimate is clear instead of mild.

Kind B has its own pass marks, simulated in step 1 for its smaller sizes before the lock.

**Three reviewers, same runs:** the union (primary), `skeptic_d` alone, the tripwires alone. Supports: all 20
variants for every one of them (hidden-truth populations, `mission_4_1_trust.md` section 2).

### 2b. Proposed in the roadmap pass (2026-11-15), pending the student's OK
From `docs/plans/roadmap_challenge_2026-11-15.md`, findings 2, 5, 6 and 7. None changes a pass mark above; each
adds something, and all are fixed before any review exists.
1. **Kind D, guarded support.** Audited canaries are drawn evenly from the 17 supported variants only (no B09,
   no B06 obvious); the estimator gets the real-run support of `mission_4_1_trust.md` (guard on), no leak term.
   This is the configuration real campaigns use, and the only kind where the worst-class bound and the gate
   measure say something: with all 20 variants in the support the worst class is B09 and the bound is near 1.
   Same levels, same measures as kind A, plus: how often the gate opens and the true contamination when it does.
   Pass marks: simulated in step 1 before the lock, by the same rule (5th percentile across simulated banks).
   No extra review.
2. **B06-subtle top-up of 10 canaries,** in the same extra batch as the B09 top-up. The bank has 10 B06-subtle
   canaries; B06 counts in the real-run support through that variant only, and the gate needs 12 per supported
   class. With the top-up, kind D can calibrate with 12 per class at every level, and the bank can open the gate
   for campaigns afterwards. Cost: 10 reviews (session 7 becomes 10 + 30 + 10; still 7 sessions). Without it:
   kind D runs at levels 0, 0.10 and 0.30 with 8 calibration canaries per class, and the first campaign block
   calibrates B06.
3. **The bound's size, not only how often it holds:** for every kind and level the median upper end of the
   worst-class bound is reported beside the share of re-splits in which it holds.
4. **Naive baselines beside every estimate:** the raw flag rate read as prevalence, and the Rogan-Gladen point
   formula with plain proportions and no interval. Their mean error and their share within 0.10 of the truth, on
   the same re-splits.
5. **Before pool 3 is built (step 1b):** the local decisive-share check on the clean runs already made, and the
   student's decision on the campaign grid and `seeds_per_arm`. The number of seeds is visible in every
   `results.json`; changing it after the bank exists would make real runs differ from the bank's clones.
   Default: question q1 and the same focus grid stay, as section 2a says. If the student's decision changes the
   question or the grid, section 2a is amended first, before pool 3 is built (roadmap finding 24).

## 3. Sample size per level (from the simulations)
- **100 audited runs per level.** Simulated with independent runs, 20 canaries per class and 100 clean runs for
  calibration (`trust_design_sim.json`, union rates): the 90% interval is 0.04 wide at level 0, 0.13 at 0.10,
  0.18 at 0.30, 0.20 at 0.50, and holds the truth in 91% to 98% of campaigns. 150 runs would narrow it to 0.03,
  0.12, 0.15, 0.17; 60 runs widen it to 0.07, 0.17, 0.23, 0.25.
- **The bank sets the limit.** Level 0 needs 100 clean audited runs plus 60 clean calibration runs = all 160.
  Level 0.50 needs 5 canaries per class plus 12 for calibration = 17 of 20. So 100 is the largest audited set the
  bank supports at all four levels. A larger one needs a second batch and about 3 more review sessions.
- **12 canaries per class for calibration, not 20:** what the bank leaves. Simulated at 10 per class the pooled
  estimate drifts up a little at high levels (median 0.53 for a true 0.50), which is the cautious direction.

## 4. What is measured, and the pass marks (fixed before any review)
Per kind, level and reviewer, over the 2000 re-splits:
1. **Error of the pooled estimate:** mean of (median estimate minus truth), and the share of re-splits within 0.10
   of the truth.
2. **Cover:** the share of re-splits whose pooled 90% interval holds the truth.
3. **Bound:** the share of re-splits whose worst-class upper end is at or above the truth.
4. **Contamination:** among audited runs the reviewer passed, the true share of canaries, against the estimated
   contamination (pooled and worst class).
5. **Gate (a first look at RQ3):** the share of re-splits where the gate opens although the true contamination of
   that audited set is above tau.

Re-splits of one bank are not independent campaigns: the same 360 reviews are reused, and a re-split cannot draw
more or fewer canaries than its level says. So cover inside one bank runs **higher** than 90% even when all is
well, and "at least 90%" would be a soft test. The pass marks therefore come from `rq4_bank_sim.json`: what a
**correct** estimator shows on 200 simulated banks of this exact size, taking the 5th percentile across banks.

| Pass mark (union, kinds A and B) | Value |
|---|---|
| Cover of the pooled interval, each level | at least the simulated 5th percentile for that level (table in section 5) |
| Mean error of the pooled estimate, each level | within 0.05 of zero (the simulated bias from the flat priors is up to +0.026) |
| Kind C, registered prediction | pooled cover is **below** kind A's at the same level; the worst-class bound holds in at least 95% of re-splits |
| Gate | opens with true contamination above tau in at most 10% of re-splits |

**Reading the outcome (fixed now):**
- A and B pass: "the estimate is accurate when bugs are spread like the canaries, also across experiments".
- A passes, B fails: the reviewer behaves differently across experiments; calibration does not transfer, and
  Mission 4.1's intervals need the base-level correction before any gate decision. This is a finding, not a bug.
- A fails: an arithmetic or interval problem. Fix it only under a written amendment, and re-run on re-splits with
  a new seed.
- C as predicted: the reason the gate uses the worst class is shown on real reviews. C not as predicted (pooled
  still covers): say so; B09 was then not as weak as on arm L.

## 5. Pass-mark table from the bank simulation
`rq4_bank_sim.json`: 200 simulated banks of the bank's size, 100 re-splits each, assumed union rates, a correct
estimator. "Cover" is the share of a bank's re-splits whose pooled interval holds the truth.

| Kind | Level | Cover, mean over banks | Cover, 5th percentile across banks (the pass mark for A and B) | Mean error of the pooled estimate | Worst-class bound holds |
|---|---|---|---|---|---|
| A matched | 0 | 0.991 | 0.94 | +0.008 | 1.000 |
| A matched | 0.10 | 0.995 | 0.97 | -0.002 | 1.000 |
| A matched | 0.30 | 1.000 | 1.00 | +0.011 | 1.000 |
| A matched | 0.50 | 0.999 | 0.99 | +0.026 | 1.000 |
| C, 40% B09 | 0.10 | 0.934 | 0.88 | -0.031 | 1.000 |
| C, 40% B09 | 0.20 | 0.872 | 0.75 | -0.054 | 1.000 |
| C, 50% B09 (top-up) | 0.10 | 0.855 | 0.78 | -0.040 | 1.000 |
| C, 50% B09 (top-up) | 0.30 | 0.299 | 0.07 | -0.106 | 1.000 |

What the table says: inside one bank a correct estimator covers almost always, so the pass mark for A and B is
0.94 to 1.00, not 0.90. Under an adverse mix the pooled estimate reads low (by 0.03 to 0.11 here) and its cover
drops (to 0.30 at level 0.30 with the top-up, the clear case), while the worst-class bound never fails. Pass marks above 0.97 (levels 0.30 and 0.50) are set to 0.97, so
that one unlucky bank cannot fail on a handful of re-splits. Rows for `skeptic_d` alone are in the JSON.

## 6. Free-tier calendar (about 65 reviews a session)
| Session | Reviews | What |
|---|---|---|
| local build | 0 | one unattended sitting, about 2 to 3 hours (the 5.1 plan forecasts 2 hours for 360 runs with twins and replays): pool 3, `rq4-bank-1`, `rq4-b09`, tripwire records; then the lock |
| before 1 | 0 | lock check; `eval.rq4 --dry` confirms 360 + 30 runs, 0 audits by `skeptic_d` |
| 1 | 20 + 45 | sentinel set (the 20 repeat-pass runs, cache bypassed), then the first 45 runs |
| 2 to 5 | 65 each | runs 46 to 305 |
| 6 | 55 + 10 | runs 306 to 360, then the first half of the closing sentinel |
| 7 | 10 + 30 | rest of the closing sentinel; the B09 top-up |
| after 7 | 0 | lock check; `python -m eval.rq4` **once** |

- 360 reviews + 30 top-up + 40 sentinel = 430 calls = 6.6 sessions, so 7 sittings of a few minutes each. Moving
  the bank to pool 3 adds no review; it adds the local build sitting and makes guard sitting 1 a prerequisite.
  A skipped day moves the end by a day and loses nothing: `reaudit` resumes, and a stop at the daily limit is not
  a failed audit.
- Tokens: arm L used about 2600 tokens a call; 65 calls stay inside the daily token budget already configured.
- **Cheaper option, not recommended:** ask the LLM only for runs the tripwires passed (about 160 clean runs plus
  the few canaries the tripwires miss: 3 to 4 sessions). It gives the same union verdicts, but no LLM-alone result
  on 200 canaries, which is the best RQ2 data the project can get for 3 extra sessions.
- Order of review: the batch's own shuffled order, so a stop never leaves one run type behind.
- **Nobody analyses a part.** `eval/rq4.py` refuses to run until every run has an audit or a recorded failure,
  exactly as `eval/ceiling.py` does.
- **If the provider changes the model mid-way** (the server's model field, or more than 3 sentinel verdicts
  changed between opening and closing): finish, analyse once, and report the estimate split by review day next to
  the main result. Do not restart, and do not pool with arm L.

## 7. Build order
**Step 1 (Opus, with Mission 4.1 sitting 1).** `eval/rq4_power.py`: both simulations as tested code using
`trust.estimate`; re-run with the union's measured rates from sitting D; write
`eval/results/rq4/power.json`. If the measured union differs much from the assumed one, the pass-mark table is
replaced by the new one **before** step 2.
Tests: seeded; a perfect reviewer recovers every level exactly; a bank re-split never puts a run in both sets.

**Step 1b (Opus prepares, student's window runs; local, no cloud call).** After guard sitting 1 and tripwire
step 11: build pool 3 (section 2a); `calibrate --runs 360 --batch rq4-bank-1 --pool data/calibration/pool-3.json
--seed <new> --no-audit`; build `rq4-b09`; run the locked tripwires on both batches; `ledger verify`.
**Done when:** both batches exist with 0 audits and one tripwire record per run, and the pool file names the
guard version.
Proposed in section 2b, pending the student's OK: the decisive-share check and the student's decision on the
grid and `seeds_per_arm` come before this step (item 5), and the top-up batch also holds the 10 B06-subtle
canaries (item 2).

**Step 2 (Opus).** `eval/rq4.py` (re-splits, the five measures, pass marks, `--dry`, refuses partial data) and
`eval/rq4_lock.py` (or `ceiling_lock` generalised: hashes of `canary/trust.py`, `eval/rq4.py`, the tripwire
records, the batch's run-ID list, the prompt). Then write `docs/plans/rq4_hidden_truth.md` with seeds, sizes,
kinds, pass marks and commands, and its `.sha256`.
Tests (fast, synthetic bank): a known bank gives hand-checked shares; the estimator is called with flags only
(a spy asserts no sealed access on the audited side); base-disjoint re-splits share no base; kind C draws the
stated B09 share; the script refuses when one audit is missing.
The top-up: build `rq4-b09` before the lock (30 B09 canaries, 15 per tier, on pool 3 bases, no
audit). It needs a "these variants only" option in the batch planner (`canary/mixer.py`, unfrozen after sitting
D), with a test that the default plan is unchanged.
**Done when:** `python -m eval.rq4 --dry --batch rq4-bank-1` prints "360 runs, 0 reviewed, locked: OK".

**Step 3 (student's window, 7 short sessions).** Each session: `python -m eval.rq4_lock --check`, then
`python -m canary.cli reaudit --batch rq4-bank-1 --role skeptic_d` (it stops by itself at the daily budget;
`rq4-b09` the same way in session 7).
Sessions 1 and 7 also run the sentinel (`rescore --sample`, the repeat-pass command).

**Step 4 (Opus, then Fable or the student's usual model for `/evaluate`).** `python -m eval.rq4` once; results in
`eval/results/rq4/rq4.json` with per-re-split rows; `eval/figures/rq4_estimate_vs_truth.png` (re-split 0 with
intervals, the spread of the others behind it, one panel per kind); `/evaluate`; `PROGRESS.md`.
**Done when:** the JSON holds every pass mark as passed or failed and the figure exists.
Proposed (roadmap second read, 2026-11-16, finding 21): the RQ3 plan is locked before `python -m eval.rq4` runs,
because RQ3 uses re-splits of this same bank and measure 5 above already shows the gate on them.

**After RQ4:** the same 360 reviewed runs become the first calibration set for real campaigns (Mission 4.1,
section 4), under the same reviewer snapshot.

## 8. Traps
1. **The estimator must never see the audited truth.** Only `eval/rq4.py` reads the sealed table; `trust.estimate`
   takes flags. A test spies on it.
2. **Do not report cover inside one bank as if campaigns were independent.** Use the simulated pass marks and
   say "re-splits of one bank".
3. **Canaries with no effect on the numbers still count as buggy** (the project's rule: truth is "the method is
   broken"). Report the harmful-only version beside it, as a sensitivity.
4. **B06 obvious is caught by a rule (L1).** It is in the bank and counts for the union as it is; the tables show
   the result with and without it.
5. **Kind B needs enough bases on each side.** Pool 3 has at least 17 bases; split them in two halves at random per re-split and
   skip (and count) re-splits that cannot fill a set. Half a bank holds about 10 canaries per class and 80 clean
   runs, which is why kind B is smaller (60 audited, 8 per class); its intervals are wider, and that is said.
6. **First audit stands.** A run reviewed twice by `skeptic_d` keeps its first verdict; sentinel replies never
   enter the analysis.
7. **Levels share runs,** so the four levels are not four independent confirmations. Say so in the caption.
8. **Do not add a level or change a pass mark after the first review.** New ideas go into an amendment and use a
   new seed.

## 9. /challenge (strict reviewer), with the fix
| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Critical | Canaries and "hidden" buggy runs come from the same saboteur, so kind A can hardly fail: it checks arithmetic, not the real world. | Said plainly. Kinds B (other experiments) and C (adverse mix) are the tests that can fail; the claim is limited to "catalogued bug kinds". Real-world bugs need Mission 6.2's mutants. |
| 2 | Critical | Re-splits reuse one set of reviews; 2000 of them are not 2000 campaigns. | Pass marks from simulated banks of the same size (5th percentile across banks), not from the nominal 90%; the caption says "one bank". |
| 3 | Major | One bank, one model snapshot, one week. | The claim names the model, settings and dates. A second bank is the efficiency-search batch later; never pooled. |
| 4 | Major | The pass marks come from assumed reviewer rates. | Step 1 recomputes them from sitting D's measured union before the lock. |
| 5 | Major | 12 calibration canaries per class is thin; flat priors pull the pooled recall down. | Bias is simulated and reported; the mean-error mark (0.05) allows for it; the direction is cautious. |
| 6 | Major | Kind C at 0.10 and 0.20 with 40% B09 may show only a mild failure, which reads as "pooled is fine". | The B09 top-up (recommended) gives 50% at 0.30; the prediction is registered either way, and a mild result is reported as mild. |
| 7 | Major | The first draft used `tripwire-test-1` (pool 2) as the bank. That batch was approved on pool 2 only because no LLM would ever review it, and `skeptic_d`'s misses on pool 2's bases were already read when this design was written. | The bank is a new batch on a fresh pool 3 (section 2a). `tripwire-test-1` stays tripwires-only. |
| 8 | Moderate | The gate measure here is a preview, with supports of all 20 variants, so the worst-class gate will be closed almost always. | Reported as such; RQ3 proper (gate on and off, guarded populations) is Mission 5.4. |
| 9 | Minor | 100 audited runs give intervals up to 0.20 wide. | The bank's limit (section 3); a wider study needs a second batch. |

## 10. Decisions (approved by the student, 2026-11-15)
1. Review all 360 runs with the LLM (7 sessions), not only the ones the tripwires pass: **all 360.**
2. The B09 top-up of 30 canaries: **yes.**
3. Levels 0, 0.10, 0.30, 0.50 and 100 audited runs: **yes.**
4. The bank is `rq4-bank-1` on a fresh pool 3, not `tripwire-test-1` (section 2a): **decided the same day.**

**Open (roadmap pass, 2026-11-15; section 2b):** kind D; the B06-subtle top-up; the bound's median upper end and
the naive baselines; the decisive-share check and the `seeds_per_arm` decision before pool 3. Recommended: yes to
each. They are decisions 2, 3 and 4 of `docs/plans/roadmap_challenge_2026-11-15.md`; its decision 11 (the RQ3
lock before step 4) was added in the second read of 2026-11-16.
