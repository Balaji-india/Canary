# Plan: Mission 4.2, hidden-truth validation of the prevalence estimate (RQ4)

Designed 2026-11-15 by Fable. Not built, not locked: step 2 writes the locked plan
`docs/plans/rq4_hidden_truth.md` from this one. Builder: Opus (1 sitting for the code, 1 for the analysis); the
reviews run in the student's window over about a week.
Depends on: tripwire sitting D (the batch `tripwire-test-1` and its tripwire records) and Mission 4.1 sitting 1
(the estimator). Read `docs/plans/mission_4_1_trust.md` first: "support", "pooled" and "worst class" are defined there.

Simulations: `docs/plans/sims/trust_design_sim.py` (sample size) and `docs/plans/sims/rq4_bank_sim.py` (pass
marks), outputs beside them. **Reviewer rates in both are assumptions,** re-run with measured numbers in step 1.

## 1. The question
RQ4: is the prevalence estimate right? Hide the truth from the estimator, give it only the reviewer's flags on a
set of runs whose true share of buggy runs we know, and compare its interval with that share, at several shares.

## 2. The design in plain words: one reviewed bank, many hidden-truth populations
A prevalence level is only a mixture. A population with 30% buggy runs is 30 canaries and 70 clean runs. So the
expensive part (reviews) is done **once**, on a bank of runs with known truth, and every level is built from the
bank by drawing runs. Extra levels cost no reviews.

- **The bank: `tripwire-test-1`.** 360 runs that sitting D builds anyway: 200 canaries (20 per class, 10 per
  variant) and 160 clean runs, padded, with decoys. `skeptic_d` has never reviewed them. After the tripwire test
  is finished and written up, `skeptic_d` reviews all 360 with the baseline prompt and arm L's settings. Each run
  then has a tripwire record and an LLM audit, so the union's verdict is known. (Its plan says the batch may not be
  used to **choose** anything about an LLM reviewer. Here nothing is chosen: the reviewer and prompt are fixed.)
- **One re-split** = draw an **audited set** of 100 runs with a fixed share of canaries, then a **calibration
  set** from the runs that are left: 12 canaries per class and 60 clean runs. The estimator
  (`trust.estimate`) gets the calibration set with its truth, and the audited set as **flags only**. Code compares
  its answer with the audited set's true share.
- **Levels:** 0, 0.10, 0.30, 0.50 buggy. Level 0 matters most for real use: real runs are expected to be almost
  all clean, and the estimate must say so.
- **2000 re-splits per level,** seeded. Re-split number 0 is the one shown as "the campaign" in the figure
  (estimate and interval against truth at each level); the other 1999 show how much that picture depends on luck.

**Three kinds of audited population** (all from the same reviews):
| Kind | How the audited canaries are drawn | What it tests | Expected |
|---|---|---|---|
| A. matched | evenly over the 10 classes | the arithmetic and the interval, when real bugs are spread like canaries | pooled estimate close to the truth |
| B. other experiments | as A, but calibration and audited runs come from **different bases** | transfer from calibration clones to other experiments, the nearest thing to real runs | as A if the reviewer behaves the same across experiments |
| C. adverse mix | a large share of the canaries are B09, the class the reviewer misses | what Mission 4.1 claims: pooled fails, the worst-class bound holds | pooled too low; worst-class upper end still above the truth |

Kind C, from the bank alone: 40% of the audited canaries are B09, at levels 0.10 and 0.20 (the bank has 20 B09
canaries; 12 must stay for calibration). **Recommended top-up:** 30 more B09 canaries (batch `rq4-b09`, about an
hour on the laptop and 30 reviews) allow 50% B09 at levels 0.10 and 0.30, where the simulated failure of the
pooled estimate is clear instead of mild.

**Three reviewers, same runs:** the union (primary), `skeptic_d` alone, the tripwires alone. Supports: all 20
variants for every one of them (hidden-truth populations, `mission_4_1_trust.md` section 2).

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
| C, 50% B09 (top-up) | 0.30 | ROW_PENDING | | | |

What the table says: inside one bank a correct estimator covers almost always, so the pass mark for A and B is
0.94 to 1.00, not 0.90. Under an adverse mix the pooled estimate reads low (by 0.03 to 0.05 here) and its cover
drops, while the worst-class bound never fails. A pass mark of 1.00 (level 0.30) is replaced by 0.97 so that one
unlucky bank cannot fail it on a handful of re-splits. Rows for `skeptic_d` alone are in the JSON.

## 6. Free-tier calendar (about 65 reviews a session)
| Session | Reviews | What |
|---|---|---|
| before 1 | 0 | lock check; `eval.rq4 --dry` confirms 360 runs, 0 audits by `skeptic_d` |
| 1 | 20 + 45 | sentinel set (the 20 repeat-pass runs, cache bypassed), then the first 45 runs |
| 2 to 5 | 65 each | runs 46 to 305 |
| 6 | 55 + 10 | runs 306 to 360, then the first half of the closing sentinel |
| 7 | 10 (+ 30) | rest of the closing sentinel; the B09 top-up if chosen |
| after 7 | 0 | lock check; `python -m eval.rq4` **once** |

- 360 reviews + 40 sentinel = 400 calls = 6.2 sessions, so 7 sittings of a few minutes each; with the top-up 430.
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

**Step 2 (Opus).** `eval/rq4.py` (re-splits, the five measures, pass marks, `--dry`, refuses partial data) and
`eval/rq4_lock.py` (or `ceiling_lock` generalised: hashes of `canary/trust.py`, `eval/rq4.py`, the tripwire
records, the batch's run-ID list, the prompt). Then write `docs/plans/rq4_hidden_truth.md` with seeds, sizes,
kinds, pass marks and commands, and its `.sha256`.
Tests (fast, synthetic bank): a known bank gives hand-checked shares; the estimator is called with flags only
(a spy asserts no sealed access on the audited side); base-disjoint re-splits share no base; kind C draws the
stated B09 share; the script refuses when one audit is missing.
**Done when:** `python -m eval.rq4 --dry --batch tripwire-test-1` prints "360 runs, 0 reviewed, locked: OK".

**Step 3 (student's window, 7 short sessions).** Each session: `python -m eval.rq4_lock --check`, then
`python -m canary.cli reaudit --batch tripwire-test-1 --role skeptic_d` (it stops by itself at the daily budget).
Sessions 1 and 7 also run the sentinel (`rescore --sample`, the repeat-pass command).

**Step 4 (Opus, then Fable or the student's usual model for `/evaluate`).** `python -m eval.rq4` once; results in
`eval/results/rq4/rq4.json` with per-re-split rows; `eval/figures/rq4_estimate_vs_truth.png` (re-split 0 with
intervals, the spread of the others behind it, one panel per kind); `/evaluate`; `PROGRESS.md`.
**Done when:** the JSON holds every pass mark as passed or failed and the figure exists.

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
5. **Kind B needs enough bases on each side.** Pool 2 has 17 bases; split them 9 and 8 at random per re-split and
   skip (and count) re-splits that cannot fill a set.
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
| 7 | Moderate | Reviewing the tripwire test batch with the LLM could be seen as reusing a locked test set. | The tripwire test is finished and written up first; nothing about the reviewer is chosen on this batch; the RQ4 lock lists it. |
| 8 | Moderate | The gate measure here is a preview, with supports of all 20 variants, so the worst-class gate will be closed almost always. | Reported as such; RQ3 proper (gate on and off, guarded populations) is Mission 5.4. |
| 9 | Minor | 100 audited runs give intervals up to 0.20 wide. | The bank's limit (section 3); a wider study needs a second batch. |

## 10. Decisions for the student (defaults apply unless changed)
1. Review all 360 runs with the LLM (7 sessions), not only the ones the tripwires pass. Default: all 360.
2. The B09 top-up of 30 canaries. Default: yes.
3. Levels 0, 0.10, 0.30, 0.50 and 100 audited runs. Default: yes.
