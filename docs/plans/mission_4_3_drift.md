# Plan: Mission 4.3, control chart and drift alarms

Designed 2026-11-15 by Fable. Not built. Builder: Opus, 2 sittings. Building needs no cloud call; using it costs
sentinel calls every review day (section 3).
Depends on: Mission 4.1 (the gate reads the alarm state), tripwire step 11 (tripwire records in the ledger) and,
for the sentinel set, the reviewed RQ4 bank `rq4-bank-1`. Read `docs/plans/mission_4_1_trust.md` first.

Simulation behind every "simulated" number: `docs/plans/sims/drift_chart_sim.py`, output `drift_chart_sim.json`
beside it. The script was committed **before its first run** (commit 0782768), with the chart rules and the
selection rule in its docstring. **Its reviewer rates are assumptions** (LLM alone 0.94 on eight classes, 0.05 on
B06, 0.17 on B09; specificity 0.98; union recall 0.97 on the supported classes; a re-asked run repeats its verdict
19 times in 20). Step 2 rebuilds it as tested code and re-runs it with the rates measured in Mission 5.1 sitting D
and on the RQ4 bank; the sizes below are replaced by that run's output **before** any sentinel call is made.

## 1. The problem in plain words
Mission 4.1 turns calibration counts into a gate. Those counts describe the reviewer **on the day it was
measured**. The cloud model can change without notice, and three facts make that hard to see:
1. **The cache hides it.** A cached reply is yesterday's model. The key uses the model tag, not a digest.
2. **The lazy union hides half of it.** In campaigns the LLM is asked only when the tripwires pass. Canaries are
   almost all flagged by the tripwires, so the LLM hardly ever sees a fresh canary. If the LLM starts to pass
   everything, fresh clean runs still pass, fresh canaries are still flagged by the tripwires, and nothing looks
   wrong. Only runs the LLM is asked about **again** can show it.
3. **The pace is slow.** About 65 reviews a day. A chart that needs hundreds of runs to react is useless.

DESIGN.md section 9 has one chart (windows of 20 canaries, normal-approximation limits). It cannot do this job:
see section 4, "Why not the normal limits".

## 2. The design: three layers, each for one kind of change
| Layer | Catches | How | Cost |
|---|---|---|---|
| A. Identity checks | a change the provider or the code declares | compared on every call and every session; no statistics | none |
| B. Charts | an abrupt change nobody declared | sentinel chart (the LLM, same runs asked again) and fresh-run charts (the union) with exact small-sample limits | the sentinel calls |
| C. Rolling calibration window | a slow change | the gate's recall and specificity use only recent calibration runs | none |

Everything belongs to a **calibration epoch**: one reviewer identity over one stretch of time. An epoch record
holds the role, provider, requested model, the server's model field, the hash of the system text and the task
prompt, the wire-schema hash, the options (reasoning effort, output limit), the tripwire version
(`tripwires.version()`), the library versions (Python, numpy, scikit-learn, pandas), the start time and the
reason it started. It is a ledger entry, so it is hash-chained. **No trust number is ever computed across two
epochs** (`mission_4_1_trust.md` section 4: "never pooled").
**Added in the roadmap pass (2026-11-15):** the record also holds the **Scientist's identity** (model, prompt
version, the graveyard and feedback switches). A Scientist that proposes differently produces a different kind of
run, so calibration measured on clones of the old kind must not be mixed with the new
(`mission_3_1_3_2_memory_calibration.md`, section 6). A changed Scientist identity opens a new epoch like any
other identity field; no chart is involved. The same holds for what every run looks like: the hash of the
experiment template and of the `science` block of `config/campaign.yaml` (`seeds_per_arm`, the test share) are
identity fields too.

### 2.1 Layer A: identity checks
- **Every cloud call** already logs `server_model` and `response_id` (`data/cloud/calls.jsonl`). Added: the
  provider's `system_fingerprint` when it sends one, and all three copied into the audit's ledger entry with the
  epoch ID.
- **Server model differs from the epoch's** (for example the alias now resolves to a dated snapshot): the call's
  reply is stored as a call-log record only, the pass stops, and an alarm of kind `identity` is raised (section 5).
  This is the ceiling plan's stop rule, kept.
- **Fingerprint differs:** logged and shown; no action. What it means is provider-specific, and a rule on it
  could not be tested. The sentinel is the test.
- **Tripwire version or a library version differs from the epoch's:** before anything else that session, the
  tripwire **regression check**: the tripwires run again on the sentinel runs (in a temporary copy, never inside
  `data/runs/`) and every verdict and fired check must equal the stored record. They are deterministic, so one
  difference is an alarm of kind `tripwire_regression`; there is nothing to estimate. If all are equal, a new
  epoch starts for the union with the old tripwire records still valid (same verdicts by test).
- **Prompt, schema or options differ:** a new epoch, always. Nothing is compared.
- **The cache.** (1) Every drift-measuring call bypasses the cache and writes nothing to it (`refresh=True`,
  `cache_write=False`, as the repeat pass does). (2) The cache key gets one more part, `identity`: the model
  digest for Ollama roles (from the local model list), the epoch ID for cloud roles (a cloud API gives no
  digest). A reply stored under another identity can then never be served. (3) Keys of roles without an identity
  stay exactly as they are, as the existing `endpoint` part does. Fresh campaign runs are new prompts, so they
  never hit the cache; this matters for re-asked runs and for resumed passes.

### 2.2 Layer B, part 1: the sentinel set (the LLM half, asked again)
- **What it is:** a fixed set of runs that `skeptic_d` has already reviewed in this epoch. The same prompt is sent
  again with the cache bypassed. The prompt is identical, so a different verdict means the reviewer answered
  differently: sampling noise or a changed model. This is the only instrument that sees the LLM's recall under
  the lazy union.
- **Size and pace (chosen by the rule in section 4, assumed rates): 60 runs, 20 a day.** 30 buggy (3 per bug
  class) and 30 clean (15 controls, 15 shams).
- **How the runs are chosen: by code, from the sealed table's run type, class and tier only.** A seeded draw
  (`seed 4303`) from the reviewed bank `rq4-bank-1`, after RQ4 is analysed: 3 canaries per class (tiers
  alternating by the seed), 15 controls, 15 shams, **at most 4 runs from one base**, runs with a failed first
  audit skipped. **No reply, verdict, confidence or evidence text is read to choose them**, by code or by a
  person, so the set cannot be picked to look stable. The ID list is stored in `data/sealed_plans/`, in asking
  order, without types.
- **Reference and baseline.** The reference of a run is its first stored verdict in this epoch. Right after the
  set is drawn, all 60 are asked once more (the **opening pass**). The number of verdicts that differ from the
  reference, for the buggy half and for the clean half, is the baseline of the chart. This also answers the open
  item in Known issues: repeatability is measured and reported beside recall and specificity.
- **Daily slice.** Every review day starts with the next 20 sentinel runs in a fixed rotation (10 buggy, 10
  clean, in an order mixed by type), **before any real run is reviewed**. So the whole set is asked again every 3
  review days. The chart counts **flips** (verdict differs from the reference) per half: the buggy half is the
  recall chart, the clean half the specificity chart. Direction is logged (flag to pass, pass to flag).
- **Nothing a sentinel call returns enters any trust number.** The first audit stands. Records go to
  `data/drift/sentinel.jsonl`, never to the ledger's audits.
- **Cost:** 20 of about 65 calls a day (31%), and 60 calls (0.9 day) for each opening pass. A new epoch needs two
  passes (one sets the references, one the baseline): 120 calls.
- **Until `rq4-bank-1` is analysed** the sentinel is the 20 repeat-pass runs of `ceiling-ext`, opening and
  closing the RQ4 review week, exactly as `mission_4_2_hidden_truth.md` section 6 says. That plan's trigger
  ("more than 3 of 20 changed": report the estimate split by review day) is a reporting rule, not an alarm, and
  is unchanged.
- **When the bank may calibrate campaigns** (`mission_4_1_trust.md` section 4 says "if the sentinel set shows the
  model has not changed"; made exact here, with the number that plan already uses): the bank is epoch 1's
  calibration set only if that trigger did **not** fire, that is, at most 3 of the 20 verdicts differ between the
  opening and the closing pass of the review week. If it fired, the bank is still analysed for RQ4 as planned,
  and campaigns start with a fresh calibration in a new epoch.

### 2.3 Layer B, part 2: the fresh-run charts (the union)
Fresh calibration runs enter campaigns every day (Mission 4.4). In review order:
- **Clean chart:** windows of 20 fresh controls and shams; the count is the union's false alarms (the LLM's and
  the tripwires' logged apart; an `unverifiable` tripwire result counts as a flag and is listed).
- **Canary chart:** windows of 20 fresh measuring canaries of the supported classes; the count is the union's
  misses. Probes never enter it. Under the lazy union this chart watches the chain **saboteur, template, tripwires**
  far more than the LLM (section 1, fact 2). That is said on the dashboard.
- Baseline of both: the epoch's calibration set (at the start: the bank).

### 2.4 Layer C: the rolling calibration window
The charts do not see a slow drift (section 4). So the gate does not use the whole epoch. **`trust.estimate`
gets the most recent observations in the epoch, up to 24 measuring canaries per supported class and 120 clean
runs**: twice the minimum calibration of Mission 4.1 (12 and 60), where the simulated gate already opens
reliably. Older observations stay in every report but leave the gate. At the assumed pace the window is about 8
to 11 review days long, so a slow change in the **union** reaches the gate's numbers within that time, with no
alarm needed. The bank fills the first window. The window never crosses an epoch.
What this does not refresh: the **LLM-alone** recall (the lazy union asks it about almost no canary). It is
reported with the date it was measured and the sentinel's current flip counts beside it.

## 3. What the free tier allows
| Item | Calls | When |
|---|---|---|
| sentinel slice | 20 | every review day, first |
| opening pass | 60 | once per epoch (twice for a new epoch after an alarm) |
| fresh clean runs | all of them | the day's remaining budget (Mission 4.4 sets the mix) |
| fresh canaries | only those the tripwires pass | a few a day |
| tripwire regression check | 0 (local replays of 60 runs) | when a version changed |

A day with fewer than 20 calls left asks what it can; the slice is finished the next review day before any real
run. **A real run is never accepted on a day whose slice is unfinished or out of control.** "Days" in this plan
are review days. After a break of any length the first slice still comes first.

## 4. The chart rules, the selection rule and what the simulation gave
**Fixed before the simulation ran** (docstring of the script, commit 0782768):

**Limits are exact.** For a slice or window of m runs, the limit at tail probability t is the smallest count c
with `P(X >= c) <= t`, where `X ~ BetaBinomial(m, 1 + f0, 1 + n0 - f0)` and f0 of n0 is the baseline count. The
Beta-binomial carries the uncertainty of a small baseline into the limit. Westgard's levels are kept as tail
probabilities: "3 sigma" = 0.00135, "2 sigma" = 0.0228.

| Rule | Lab name | Fires when |
|---|---|---|
| R1 | 1_3s | one slice or window at or beyond the 3-sigma limit |
| R2 | 2_2s | two in a row, each at or beyond the 2-sigma limit |
| R3 | stands in for 4_1s and 10_x | the count summed over the last W slices or windows at or beyond the 3-sigma limit for that many runs |

4_1s and 10_x need runs "on one side of the centre line". With counts near 0 of 10 there is no such side, so a
cumulative count replaces them. Any rule on any chart is an alarm.

**Why not the normal limits of DESIGN.md section 9** (`normal_approximation_at_0.97` in the JSON): at recall 0.97
and windows of 20, "p minus 3 sigma" is 0.856, so the chart alarms at 17 or fewer catches. The true probability
of that is 0.021 per window, not 0.00135: a false alarm about every 48 windows. The 2-sigma limit lands on the
same count. Near 0 or 1 the normal curve is the wrong shape for 20 runs.

**Two models of a re-asked run,** because 19 of 20 cannot tell them apart: "independent" (every ask is a fresh
draw at the class rate, the noisiest case) and "sticky" (a run keeps its verdict; a re-ask flips 1 time in 20).
A design had to qualify under both.

**Selection rule for the sentinel.** Candidates: 20, 40 or 60 runs; 6, 10 or 20 a day; W of 3, 5 or 7; standard
or stricter tails (54 in all). Qualify: (a) any alarm in 30 quiet review days at most 0.10; (b) alarm within 2
review days at least 0.95 when the LLM passes everything and when it flags everything; (c) alarm within 7 review
days at least 0.80 for a recall drop from 0.77 to 0.60. Choice: fewest calls a day, then the smallest set, then
the smallest W, then standard tails. If nothing meets (c), drop (c) and say so.

**What the simulation gave** (assumed rates; 4000 simulated campaigns per cell; worst of the two models unless
both are shown):
- **No candidate meets (c).** 3 of 54 meet (a) and (b), all with 60 runs and 20 a day. By the rule: **60 runs, 20
  a day, W = 3, standard tails.**
- **A recall drop from 0.77 to 0.60 is not seen reliably**: alarm within 7 days in 0.11 (independent) and 0.16
  (sticky) of campaigns, within 14 days in 0.19 and 0.22. This is a limit of the information (10 buggy re-asks a
  day against a baseline known from 30 runs), not of the rule: no candidate reached 0.11 with fewer calls.

| Change (from one day to the next) | Chart that sees it | Alarm within 1 day | 2 days | 7 days | 14 days |
|---|---|---|---|---|---|
| nothing (false alarm, 30 quiet days) | sentinel | 0.002 in 30 days | | | |
| | clean chart, canary chart | 0.008 and 0.020 in 30 days | | | |
| LLM flags everything | sentinel, clean half (R1) | 1.00 | 1.00 | 1.00 | 1.00 |
| | clean chart | 0 | 1.00 | 1.00 | 1.00 |
| LLM passes everything | sentinel, buggy half | 0.77 / 0.95 | 0.97 / 1.00 | 0.99 / 1.00 | 0.99 / 1.00 |
| | fresh charts | not visible (lazy union) | | | |
| LLM recall 0.77 to 0.30 | sentinel, buggy half | 0.25 / 0.32 | 0.54 / 0.68 | 0.90 / 0.92 | 0.96 / 0.94 |
| LLM recall 0.77 to 0.60 | sentinel, buggy half | 0.01 | 0.02 / 0.05 | 0.11 / 0.16 | 0.19 / 0.22 |
| specificity 0.98 to 0.90 | sentinel, clean half | 0.00 | 0.00 | 0.02 | 0.03 / 0.04 |
| | clean chart | 0 | 0.05 | 0.41 | 0.63 |
| tripwires lose one supported class | canary chart | 0.10 | 0.24 | 0.70 | 0.88 |
| | regression check, if a version changed | at once | | | |

Two values in a cell are independent / sticky. The clean and canary rows use the bank as baseline (160 clean, 170
supported canaries) and the assumed pace of 15 fresh clean runs and 20 fresh canaries a day; with the smaller
baseline of a recalibration (60 and 108) they are slower (specificity drop: 0.31 within 14 days; class lost: 0.77).
- **Which rule fires first** (chosen design, day 2, independent model): for "passes everything" R1 0.91, R2 0.93,
  R3 0.72; for recall 0.30, R1 0.41, R2 0.38, R3 0.18, and by day 7 R3 leads (0.86). R2 and R3 matter for the
  partial changes; R1 for the total ones.
- **Limits at the expected baseline:** clean chart: R1 at 5 flags of 20, R2 at 3 twice, R3 at 9 of 60. Canary
  chart: R1 at 6 misses of 20, R2 at 4 twice, R3 at 10 of 60. Sentinel limits depend on the opening pass and are
  printed by `python -m canary.drift status`.
- **Whole chart family, no change:** about 0.03 false alarms in 30 review days (the three figures above added).
  The rules are cautious: the Beta-binomial pays for the small baseline.

**What "slow" means in days at 65 reviews a day.** A total change: 1 to 2 review days. A large partial change
(recall 0.30): a week. A moderate one (0.60) or a specificity drop to 0.90: mostly not within two weeks by the
charts; the rolling window (2.4) carries the union's part of it into the gate within 8 to 11 days.

## 5. What an alarm does
One kind of alarm, whatever fired it (R1, R2, R3, `identity`, `tripwire_regression`). In order:
1. **Pause auto-accept.** The gate answers "closed: drift alarm" for every run. The alarm is a ledger entry with
   the chart, the rule, the counts, the limits and the epoch.
2. **Hold what the alarm puts in doubt (look-back).** Real runs accepted inside the alarm's evidence window get a
   `held` entry (append-only; nothing is deleted): R1, since the previous in-control slice; R2, since the slice
   before the first of the two; R3, since the slice before its W; `identity`, since the last call that still
   showed the old server model. A lab does the same: results since the last good control are re-tested.
3. **Recalibrate in a new epoch.** Two sentinel passes (references, then baseline); fresh clean runs and fresh
   canaries until the minimum calibration of Mission 4.1 holds in the new epoch (12 per supported class, 60
   clean); the held runs are reviewed once in the new epoch (their first audit there stands). Old-epoch numbers
   are kept for the record and never mixed in. Canaries are never re-reviewed: calibration runs are new runs.
4. **Re-open tightened.** With the minimum calibration met, the gate works at tau 0.05 (`gate.tau_alarm`) until 3
   sentinel slices in a row are in control; then tau returns to 0.10.

Cost of one alarm at the free tier: 120 sentinel calls, 60 clean runs, the few canaries the tripwires pass and the
held runs: about 3 to 4 review days. With about 0.03 false alarms in 30 days that is affordable.

**Tripwires against the LLM.**
| | LLM half | Tripwire half |
|---|---|---|
| Can it change silently? | yes (the provider) | no (code and libraries, both hashed and recorded) |
| How a change is found | sentinel chart, clean chart, server-model field | version check, then the regression check: exact equality |
| Statistics | exact limits on flips | none: one difference is an alarm |
| After a change | new epoch, new calibration | fix or accept the new version; new epoch for the union; LLM-alone numbers carry on |
| Model retired or key refused | no union exists: the gate is closed, local work may go on | not affected |

### 5.1 Where this plan differs from earlier text (nothing approved is changed without a decision below)
| Earlier text | This plan | Status |
|---|---|---|
| DESIGN.md section 9: limits `p +- k sigma` (normal approximation) | exact Beta-binomial limits at the same sigma levels; rule R3 added | decision 2 |
| DESIGN.md section 9: an alarm "makes the agent spend its next runs on canaries until the chart recovers" | recalibration spends the LLM's calls on the sentinel and on clean runs, because under the lazy union canaries reach the LLM only when the tripwires pass them; canaries are still run and still counted for the union; "recovers" = 3 in-control slices | follows from the approved lazy union; decision 3 |
| `config/campaign.yaml` `control_chart` block (window 20, two rule names) | window 20 kept for the fresh charts; rules and tails written out; sentinel block added | changed in build step 8 |
| `mission_4_1_trust.md` section 4: "a sentinel change beyond its baseline (1 change in 20) closes the gate" | "beyond its baseline" = rule R1, R2 or R3 on the sentinel chart | a definition, same intent |
| `mission_4_1_trust.md`: the gate reads all calibration runs | the gate reads the rolling window (2.4); `trust.estimate` itself is unchanged, only what it is given | decision 5 |
| `mission_4_2_hidden_truth.md` section 6: sentinel = the 20 repeat-pass runs, twice | unchanged; its trigger is reused for "may the bank calibrate campaigns" (2.2) | decision 9 |
| First audit stands (PROGRESS, Decisions) | unchanged for every calibration run; a **held real run** gets one review in the new epoch, which is that epoch's first | decision 4 |

## 6. Build order (Opus)
Frozen until tripwire sitting D is done: `canary/llm.py`, `canary/cli.py`, `canary/skeptic.py`,
`canary/mixer.py`, `canary/prompts.py`. `canary/trust.py` will be frozen by the RQ4 lock. So the chart lives in a
**new module `canary/drift.py`**, with `python -m canary.drift` as its entry point.

**Sitting 1 (steps 1 to 3): the arithmetic. New files only, any day.**
- **Step 1. Limits and rules.** `drift.limit(n0, f0, m, tail)`, `drift.rules(counts, n0, f0, m, span)` returning
  which of R1, R2, R3 fire at which index.
  Tests against hand-computed values: with a baseline of 0 flips in 10, `P(X = 2 of 2) = (1/12)(2/13) = 0.0128`,
  so the 2-sigma limit for m = 2 is 2 and no 3-sigma limit exists (the function returns m + 1 and R1 cannot fire);
  a limit never falls when the baseline count rises; R2 needs two neighbours; R3 ignores the first W - 1 slices;
  a huge baseline reproduces the plain binomial limit.
  **Done when:** these tests pass and `pytest -q` stays under 30 s.
- **Step 2. `eval/drift_power.py`:** the simulation as tested code that calls `drift.limit` and `drift.rules`, so
  it cannot differ from the chart. Adds a base-level random effect (verdict ICC 0.1, 0.2, 0.4, as the ceiling
  design did), because runs of one base are not independent. Tests: seeded and repeatable; with no noise and no
  change no rule ever fires; "flags everything" always fires on the first slice. It also prints two things this
  plan needs and does not have: the probability that "more than 3 of 20 differ" fires when nothing changed (the
  bank rule of 2.2), and the day-to-day spread of the flip rate from the three passes over the `ceiling-ext`
  sentinel (ceiling repeat pass, RQ4 opening, RQ4 closing), read as counts only.
  **Done when:** it reproduces `drift_chart_sim.json`'s choice from the assumed rates, then writes
  `eval/results/drift/power.json` from the measured rates. **If the measured run chooses another design, that
  design replaces section 2.2's sizes and the student is told before step 6.**
- **Step 3. Chart state from records.** `drift.chart(observations, baseline)` for the fresh charts (windows in
  review order, epoch-bound) and `drift.sentinel_chart(records, references)`; `drift.calibration_window(observations,
  support)` for layer C. Tests: a window never crosses an epoch; probes and failed audits are left out; the
  rolling window keeps exactly 24 per class and 120 clean, newest first; observations outside it still appear in
  the report structure.
  **Done when:** `python -m canary.drift --demo` prints, on synthetic records, each rule firing once, the alarm
  record and the hold list.

**Sitting 2 (steps 4 to 8): wiring. After tripwire sitting D; steps 4 and 5 before the RQ4 lock, or else after
RQ4 is analysed; never while a lock that names these files is open.**
- **Step 4. Identity in `canary/llm.py`.** `system_fingerprint` in the call log; `LLMResult` carries server
  model, response ID and fingerprint; the cache key's `identity` part; the Ollama digest read once per session.
  Tests (mocked): every key stored today is unchanged when no identity is given; one prompt under two epochs
  gives two keys; a changed digest is a cache miss; a drift call writes nothing to the cache; a reply whose
  server model differs raises the `identity` stop and stores no audit.
- **Step 5. Epochs.** Ledger entry `calibration_epoch`; `drift.current_epoch()` compares the identity fields and
  opens a new epoch when one differs; audits carry the epoch ID. Tests: each identity field alone opens a new
  epoch; `trust.collect_observations` filtered by epoch never returns two epochs; `ledger verify` passes.
- **Step 6. Sentinel.** `python -m canary.drift sentinel-draw --batch rq4-bank-1 --seed 4303` (reads run type,
  class, tier and base; writes the ID list); `sentinel-pass --opening` and `--slice` (through `skeptic.rescore`,
  cache bypassed, records appended; stops cleanly at the daily budget and resumes). Tests: the draw gives 3 per
  class, 15 and 15, at most 4 per base, and is the same for the same seed; a spy shows the draw reads only whether
  a first audit exists (the entry's status), never a payload's verdict, class, confidence or evidence; a sentinel reply never becomes a ledger audit; two identical `response_id`s are refused as "served
  twice", not counted as stable.
- **Step 7. Alarm, hold, gate.** Alarm and `held` ledger entries; `gate` reads tau and "closed: drift alarm" from
  the alarm state; recovery after 3 in-control slices. Tests: one test per row of section 5's list; a held run is
  never deleted; the look-back window of each rule; the gate cannot accept on a day whose slice is unfinished.
- **Step 8. Regression check and write-up.** `python -m canary.drift tripwire-check` (temporary copy; byte test
  that `data/runs/` is untouched); `config/campaign.yaml` `control_chart` block rewritten to these rules;
  `DESIGN.md` section 9 rewritten; Known issues updated; dashboard data file for Mission 7.1.
  **Done when (the mission):** `pytest -q` under 30 s; `python -m canary.drift --demo` shows every branch; a
  **drill with a fake provider** (replies switch to "pass" on a chosen call) ends in an alarm, a hold list, a new
  epoch and a re-opened gate at tau 0.05; `python -m canary.drift status` on the real ledger prints the epoch and
  "no sentinel yet" or the opening-pass baseline.

## 7. Traps
1. **Never read sentinel replies to choose or change the set.** The draw uses the sealed table's type, class,
   tier and base. The chart uses the verdict field only.
2. **Sentinel calls never feed recall, specificity, the flag rate or RQ4.** First audit stands.
3. **A slice must be real calls.** Check that every record has a new `response_id`; a provider-side cache would
   make the sentinel look perfectly stable.
4. **Do not pool across epochs,** not even "to get tighter limits". Not the bank with a recalibration either.
5. **The canary chart is not an LLM chart** under the lazy union. Do not describe it as one.
6. **Replays for the regression check run in a temporary copy,** as every tripwire replay does.
7. **Do not edit `canary/llm.py` or the cache key while a lock that hashes it is open** (the ceiling lock now,
   the RQ4 lock later). A changed key in the middle of a review week would re-ask or mis-serve runs.
8. **Old cache entries of local roles stop matching** once the digest is in the key. Nothing is lost: verdicts
   live in the ledger, and "first audit stands" is a ledger rule.
9. **Runs of one base move together.** The simulation here treats runs as independent, so real false alarms may
   be more frequent than 0.03 in 30 days. The draw limits runs per base, and step 2 re-runs with a base effect.
10. **No threshold may be changed after the first opening pass.** A new idea is a new rule, simulated under a
    criterion written first, and starts with a new epoch.

## 8. What it may claim and may not claim
**May claim:** every review call is tied to a recorded reviewer identity; results from two identities are never
mixed; a total failure of the LLM reviewer (passes everything, flags everything) raises an alarm within 1 to 2
review days with the simulated probabilities of section 4; findings accepted just before an alarm are held and
reviewed again; the gate's union numbers are at most about 8 to 11 review days old.
Campaign results are reported per epoch.
**At the decided budget (60 sentinel runs, 20 calls a day; section 10, decision 1) the chart catches a collapse,
not a slow drift.**
**May not claim:** that Canary "detects reviewer drift" without the size of the change: a recall drop from 0.77
to 0.60 is mostly not detected within two weeks; that any detection probability was observed on a real provider
change (all are simulated with assumed rates until one happens); that the canary chart monitors the LLM; that a
quiet chart shows the model is unchanged; anything about bug shapes outside the catalog.

## 9. /challenge (strict reviewer), with the fix
| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Critical | Under the lazy union the fresh charts cannot see the LLM lose recall, so "the control chart watches the reviewer" is false for the half that can change silently. | The sentinel's buggy half is the LLM recall chart; the canary chart is labelled as a chain check (2.3, trap 5). |
| 2 | Critical | The headline case of the mission (recall 0.77 to 0.60) is not detected: 0.11 to 0.16 within a week. A reader of DESIGN.md section 9 expects it to be. | Said in sections 4 and 8. The rolling window bounds how stale the union's numbers can be; the LLM-alone recall is reported with its measurement date. The claim is limited to total and large changes. |
| 3 | Major | An undetected LLM recall loss matters only as far as the union's recall depends on the LLM, and that dependence is not measured yet. If the tripwires carry every supported class, the mission protects little; if they do not, the gap in finding 2 is serious. | Step 2 reports, from the bank where both were asked, the union's recall per supported class minus the tripwires' alone. That figure is printed with every alarm-free day's status, so the reader sees what an unseen LLM failure could cost. |
| 4 | Major | The same 60 runs are asked for the whole epoch. A model change that leaves these prompts alone is invisible, and a provider that returns stored answers would fake stability. | New draw (new seed) at every epoch; `response_id` check (trap 3); the fresh clean chart covers new prompts for specificity. For recall on new prompts nothing covers it under the lazy union: stated. |
| 5 | Major | The baseline rests on 30 runs per half, so the limits are loose: 0.002 false alarms where 0.10 was allowed. Power is left unused. | Accepted for version 1, because every cheaper fix (a baseline that grows with in-control slices, choosing sentinel runs the LLM flagged) is a new rule. Each may be simulated later under a criterion written first; none is adopted here. |
| 6 | Major | Runs are simulated as independent; clones of one base share a verdict more often than chance. | At most 4 sentinel runs per base; step 2 adds the base effect at three ICC levels before the sizes are final (trap 9). |
| 7 | Major | Reviewing held runs again looks like asking until the answer is "pass". | One review per run in the new epoch, its first audit there stands, the old audit stays in the ledger, and the report shows both. Canaries are never asked again. |
| 8 | Moderate | 20 sentinel calls take 31% of every review day. | The rule's result under criterion (b). The cheaper 40 runs at 10 a day (W = 3) sees "passes everything" within 2 days in 0.63 of campaigns (0.93 within 5 days) and recall 0.30 within a week in 0.55. The student decides (section 10, decision 1). |
| 9 | Moderate | A false alarm throws away a good calibration (3 to 4 days). | About 0.03 in 30 review days; accepted. No "appeal" path: it would be a second, untested rule. |
| 10 | Moderate | The rolling window size (twice the minimum calibration) is a judgement, not a simulated optimum. | Tied to the approved minimum of Mission 4.1; step 2 reports the gate's opening rate with this window from the measured rates; a decision for the student (decision 5). |
| 11 | Moderate | "Review days" hide calendar time: after a three-week break the last accepted findings were released under a slice three weeks old. | The slice comes first on every review day and nothing is accepted before it is in control (section 3). Findings accepted before the break stand unless the first slice after it alarms, and then the look-back holds them. |
| 12 | Minor | DESIGN.md section 9 and `campaign.yaml` still describe the normal-approximation chart. | Changed in step 8, after the student approves decision 2. Until then section 5.1 says where this plan differs. |

**Second pass (same day), after reading the draft against the other plans:**
| # | Severity | Finding | Fix |
|---|---|---|---|
| 13 | Major | The draft never said when the reviewed bank may serve as the first calibration set, although Mission 4.1 makes that depend on the sentinel. A new threshold invented here would be a threshold chosen after the plans were approved. | The trigger Mission 4.2 already fixed is reused (2.2). Its price is stated: with a baseline of 1 change in 20, more than 3 changes is not rare when nothing changed, and a false trigger costs a fresh calibration (about 3.5 sessions, `mission_4_1_trust.md` section 4). Step 2 prints that probability; the student decides with the number (decision 9). |
| 14 | Major | The baseline is one opening pass on one day. If the provider's answers vary more between days than within a day (load, routing), the limits are too tight and false alarms exceed the simulated 0.03. | Step 2 measures the day-to-day spread on the `ceiling-ext` sentinel's three passes. Rule fixed now: if the spread is above what the within-day model gives (the Beta-binomial 95% limit of step 1), the opening pass is split over two review days. |
| 15 | Major | A campaign that spans two epochs has two reviewers. A single table over the whole campaign would mix them. | Every campaign-level figure (RQ3 included) is reported per epoch, with the alarm between them shown (section 8). |
| 16 | Moderate | The draft changed how earlier text reads (DESIGN.md section 9, two lines of Mission 4.1) without listing it. | Section 5.1. |
| 17 | Moderate | When the gate cannot open for another reason (B09 still in the support), the daily slice protects no accepted finding and still costs 20 calls. | Kept: calibration runs reviewed on those days feed the trust numbers, and a change in the middle of them would mix two reviewers. Mission 4.4's budget counts the slice on every review day. |

## 10. Decisions (for the student; recommended default first)
1. **Sentinel size and pace:** 60 runs, 20 a day (the rule's choice; 31% of a day's calls). Alternative: 40
   runs, 10 a day (15%), which fails criterion (b) as finding 8 shows. **Default: 60 and 20,** re-decided by the
   same rule when step 2 has measured rates.
   **Decided (student, 2026-11-19): 60 runs, 20 calls a day, kept.** At this budget the chart catches a
   collapse (the LLM passing or flagging everything), not a slow drift: a recall drop from 0.77 to 0.60 is
   seen within a week in only 0.11 to 0.16 of simulated campaigns (section 4). Reports say so.
2. **Replace DESIGN.md section 9's normal-approximation limits** by exact Beta-binomial limits at the same sigma
   levels, and add the cumulative rule R3: **yes.**
3. **One kind of alarm for every rule:** pause auto-accept, new epoch, tau 0.05 until 3 in-control slices.
   Alternative: R2 only tightens tau and does not start a new epoch. **Default: one kind.**
4. **Look-back:** hold and re-review the real runs accepted inside the alarm's evidence window: **yes.**
5. **Rolling calibration window:** the most recent 24 measuring canaries per supported class and 120 clean runs
   in the epoch (twice the minimum calibration): **yes.**
6. **During an LLM alarm:** the gate stays closed until the new calibration (matches Mission 4.1's text).
   Alternative: fall back to the tripwires alone as the reviewer, with their own measured numbers. **Default:
   closed;** the tripwire-only numbers are shown, not used to accept.
7. **A changed `system_fingerprint`** is logged and shown, with no action: **yes.** A changed server-model field
   stops the pass and raises an alarm: **yes** (the ceiling plan's rule).
8. **Build steps 4 and 5 (identity in `llm.py`, epochs) before the RQ4 lock,** so the bank's reviews already carry
   the epoch and the fingerprint: **yes, if sitting D is done in time; otherwise after RQ4 is analysed.**
9. **The bank calibrates campaigns only if Mission 4.2's trigger did not fire** (at most 3 of 20 sentinel verdicts
   differ between the opening and the closing pass): **yes,** reusing the approved number. Alternative: a looser
   exact limit, which would need its own simulation first.

## 11. Amendment 1 (2026-11-21, Opus, build-order row 6): the rule for step 2's measured re-run
Written and committed **before `eval/drift_power.py` is run** (code and its synthetic tests exist; neither the
reproduction nor the measured part has run). It fixes what step 2 leaves open. Nothing in sections 1 to 10 changes.
1. **Order.** First the reproduction: the assumed rates at ICC 0, seed 4303, 4000 campaigns, in the design script's
   random-number order. It must give the design's choice (60 runs, 20 a day, W = 3, standard tails); its worst-case
   table for all 54 candidates and the fresh charts' tails are compared and printed. If the choice differs, the
   measured part is not run and the command exits 1.
2. **Which measured rates (the RQ4 bank does not exist yet).** The measured run uses what is measured and analysed
   today; it is run again by this same rule on `rq4-bank-1` after RQ4 is analysed (row 16), before the sentinel
   draw (row 17), and that run replaces this one. Every rate is the posterior mean Beta(1 + s, 1 + f), as in
   `eval/rq4_power.py`; counts come from `rq4_power.measured_counts` (through `canary.trust`, each checked against
   its locked result file).
   - LLM on the sentinel's buggy half: `skeptic_d` per class over **both tiers** (the draw alternates tiers), arm L
     (task-dev-2 and ceiling-ext, 120 runs). LLM specificity: arm L's clean runs.
   - Sticky flip rate: the ceiling repeat pass (`arm_L.json`, `repeat_pass`: verdicts changed of runs asked).
   - Fresh charts (the union): per-run union on arm L's batches; false-alarm rate from its clean runs; miss rate =
     1 minus the mean of the per-class posterior means over the supported classes (`real_guard_tested`, B09 out);
     "class lost" uses the number of supported classes as the design did (k - 1 of k).
   - Pace: 12 fresh clean runs and 18 fresh canaries a review day (`mission_4_4_campaign.md` section 9: step 2
     re-runs with that plan's mix). Baselines unchanged: 160 and 170 (bank), 60 and 108 (recalibration).
3. **Changes with measured rates.** "drop" and "collapse" keep the design's size as a ratio of the mean recall:
   every class times 0.600 / 0.774 and 0.302 / 0.774. "pass everything" and "flag everything" as designed;
   "specificity drop" sets the false-alarm rate to 0.10. Criterion (c) therefore reads "the mean recall falls to
   0.775 of its value".
4. **Base effect.** A latent normal with verdict ICC 0.1, 0.2 and 0.4 (as `eval/ceiling_power.py`), plus ICC 0.
   Sentinel: 4 runs per base (the most the draw allows), in a random layout; one base effect for the flag
   propensity and an independent one for the flip propensity. Fresh charts: the baseline's runs spread evenly over
   17 bases (pool 3's minimum); fresh runs come in blocks of 4 clones of one base drawn at random from the same 17
   (`mission_4_4_campaign.md`: at most 4 clones per base per block).
5. **Selection.** The same 54 candidates, criteria (a), (b), (c) and order as section 4. A candidate qualifies only
   if it meets them under both models **and at every ICC (0, 0.1, 0.2, 0.4)**, the worst case, as the ceiling
   design's "under every ICC". Fresh charts: standard tails unless the 30-quiet-day alarm share exceeds 0.05 at any
   ICC, then strict. If the choice differs from the decided 60 runs and 20 a day (W = 3, standard), the student is
   told before step 6; nothing changes by itself (decision 1).
6. **Printed, deciding nothing now.** (a) The bank rule (2.2, decision 9): P(more than 3 of 20 verdicts differ
   between two passes | nothing changed), exact for the sticky model at the point estimate and at the posterior
   mean, averaged over the flip rate's Beta posterior, and simulated under both models at every ICC for 20 runs of
   one canary per class and 10 clean in 5 bases of 4 (the repeat pass's own mix is not read). (b) Finding 3: per
   class, the union's catches minus the tripwires' alone on arm L's batches (tripwire counts from the committed
   result files; the run counts must match). (c) Finding 10: how often the gate opens with the rolling window (24
   per class, 120 clean), measured union with B09 out, through `rq4_power.simulate` (1000 reps, 1000 draws; 60 and
   120 real runs; prevalence 0 and 0.1).
7. **Day-to-day spread (finding 14), rule fixed now, applied when the three passes exist.** For each pass (ceiling
   repeat pass, RQ4 opening, RQ4 closing), its count of verdicts that differ from the first stored verdict is
   compared with the 95% limit `drift.limit(40, f, 20, 0.05)`, where f of 40 is the other two passes pooled. Any
   pass at or beyond its limit means "spread above the within-day model": the opening pass is split over two
   review days. Until the RQ4 week only one pass exists, so it is printed as not computable.
8. **Seeds and reads.** Reproduction seed 4303, measured run 4304, 4000 campaigns; nothing is re-run with another
   seed or setting after its output is seen. The ledger and the sealed table are opened read-only through `trust`
   (their SHA-256 checked before and after); no ledger write; arm R is never read; no model is called.
9. **Status of the measured run (student, 2026-11-21, with the "go"):** provisional, dev rates; replaced by the
   `rq4-bank-1` run (row 16). Its numbers are never presented as the final design choice. The sealed table is read
   for this run only, only through `trust`, only for arm L and `tripwire-test-1`, both databases read-only with
   their SHA-256 checked before and after.
