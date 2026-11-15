# Plan: Mission 4.4, the campaign agent loop

Designed 2026-11-15 by Fable. Not built. Builder: Opus, 3 sittings; the real proof runs in the student's window
over 3 review days.
Depends on: Mission 4.1 (gate, real runs padded and carrying decoys), the baseline guard (sitting 1), tripwire
step 11, Mission 4.3 (sentinel, alarm, epochs) and the reviewed RQ4 bank. Read `docs/plans/mission_4_1_trust.md`
and `docs/plans/mission_4_3_drift.md` first: "support", "worst class", "epoch", "sentinel slice", "rolling window"
and "held" are defined there.

Simulation behind every "simulated" number: `docs/plans/sims/campaign_policy_sim.py`, output
`campaign_policy_sim.json` beside it. The script was committed **before its first run** (commit be2064b) with the
policy and five checks in its docstring. **Its rates are assumptions** (union recall 0.97 on each supported class,
specificity 0.98, guard leak 0 in 100, 45 reviews a day after the sentinel slice). Step 1 rebuilds it as tested
code and re-runs it with measured rates.

## 1. The problem in plain words
Everything so far is a part: a Scientist, a guard, a sandbox, tripwires, a cloud reviewer, a gate, a drift chart.
A campaign is the loop that runs them for days, on a laptop, inside a free daily quota, and can be stopped at any
line and continued. Its one piece of judgement is **when to stop doing science and check the checker**. That
judgement must be a rule that code applies and a reviewer can replay, not a feeling and not an LLM's choice.

## 2. One block, usually one review day
A campaign is a list of **blocks**. A block is planned once, sized to the day's budget, and its phases always run
in this order. Every phase is resumable: a finished slot or call is never done twice.

| # | Phase | Who | Cloud calls |
|---|---|---|---|
| 0 | **Preflight:** `ledger verify`; no locked evaluation has reviews still open; config and policy hashes equal the campaign's first record; the epoch's local identity (tripwire and library versions); read the Groq room from the call log; print the header with times in IST | code | 0 |
| 1 | **Sentinel slice** (Mission 4.3), then the charts | cloud reviewer, code | 20 |
| 2 | **Backlog:** runs of earlier blocks still waiting for the LLM | cloud reviewer | as needed |
| 3 | **Decide** the block's action (section 3) and write the decision to the trace | code | 0 |
| 4 | **Plan** the block: size, run types, canary variants, bases, decoys, order, seeds; sealed plan file | code | 0 |
| 5 | **Propose** the real slots: Scientist, checks, baseline guard, up to 3 attempts each; then unload the model | local LLM proposes, code checks | 0 |
| 6 | **Run** every slot in the sandbox: real runs padded and with a decoy, clones with their twins | code | 0 |
| 7 | **Tripwires** on every run (replay in a temporary copy), stored under `tripwire_v1` | code | 0 |
| 8 | **Lazy review:** the LLM is asked only about runs the tripwires passed, in a seeded shuffled order, until done or the daily limit | cloud reviewer | the rest |
| 9 | **Gate and ledger** for real runs that have a union verdict; trust numbers, charts and the block's outcome written | code | 0 |

A calibration block has no phase 5 and no real slot. After an alarm the block is Mission 4.3's sequence
(reference pass, baseline pass, calibration, held runs).

## 3. The policy: which action, decided by code
`campaign.decide(state)` is a **pure function**: the same state gives the same decision. The first rule that
applies wins. Every number it reads comes from `trust`, `gate` or `drift`; none comes from an LLM.

| # | Rule | Action |
|---|---|---|
| 1 | the campaign's own budget is spent (review days, real runs or end date, fixed in its first record), or a hard stop: `ledger verify` fails, a config or policy hash changed, the provider refuses the key, no reviewer identity | **stop**, with the reason |
| 2 | the Groq room is smaller than one sentinel slice | **wait**: stop cleanly and print when to resume (section 6) |
| 3 | today's sentinel slice is not finished | **sentinel** |
| 4 | a drift alarm is open | **recalibrate (drift)**: the Mission 4.3 sequence in a new epoch |
| 5 | runs wait for the LLM | **finish reviews** |
| 6 | the gate says "not enough calibration" (a supported class has fewer than 12 measuring canaries in the window, or fewer than 60 clean runs) or "reviewer uninformative" | **recalibrate (thin)** |
| 7 | the **zero-flag test** fails and the rolling window is not full (24 per class, 120 clean) | **recalibrate (wide)** |
| 8 | the zero-flag test fails and the window is full | **science, nothing auto-accepted** ("reviewer too weak for class X"); every passed run escalates |
| 9 | otherwise | **science** |

- **The zero-flag test** makes DESIGN.md section 12's "the trust interval is too wide" exact: compute the gate
  with the flag count on real runs set to 0 and the number of real runs set to the larger of the reviewed real
  runs and 60. If the gate stays closed even then, more science cannot open it; only more calibration can. It
  uses tau, the percentile and the minimum counts that Mission 4.1 already fixed. No new threshold.
- **A gate closed by flags** (many real runs flagged) is not a calibration problem. The agent keeps doing
  science; passed runs escalate; the trace says "closed by the flag rate on real runs".
- **Rule 8 exists so the agent cannot calibrate for ever** against a reviewer that is simply too weak.
- Replication (Mission 5.3) and hardening (Mission 6.4) are later rows of this table. Until they exist a
  candidate goes to the human queue.

**What triggers recalibration, in one line each:** a chart rule or an identity change (rule 4); too few recent
calibration runs (rule 6); a reviewer no better than chance on the worst class (rule 6); calibration too
uncertain for the gate to open on perfect news (rule 7).

## 4. Who decides what
| Decision | Decided by | Never by |
|---|---|---|
| what experiment to try (the hypothesis and its two configs) | the Scientist LLM, inside the schema | |
| whether a proposal may run | code: schema, `proposal_problem`, the baseline guard, later the graveyard check | an LLM |
| seeds, split, alpha, padding, decoy | code, seeded | the Scientist |
| the experiment's verdict (supported, not supported, inconclusive) | code: `prereg.compute_verdict` | an LLM |
| a slot's run type, a canary's class and tier, the order | code: the block plan, seeded, sealed | an LLM; the reviewer path never reads it |
| "this run looks buggy" (flag or pass) | the tripwires (code) and the cloud reviewer (an opinion on one blinded run) | |
| the union verdict, recall, specificity, prevalence, contamination | code | an LLM |
| accept, escalate, graveyard | code: the gate | an LLM |
| the drift alarm, the hold list, the epoch | code: Mission 4.3 | an LLM |
| the next action and the block's size | code: `campaign.decide`, the planner | an LLM |
| a queued run (guard label `control_below_default`, escalations) | the student | the agent |

The "agent" is the controller: observe the measured state, decide by rule, act, log. No LLM chooses an action.
That is CLAUDE.md's rule ("no LLM decides a verdict or a number") applied to the loop itself.

## 5. When canaries, controls, shams and sentinel runs are inserted
- **Sentinel:** the first 20 cloud calls of every review day. No real run is accepted on a day whose slice is
  unfinished or out of control (Mission 4.3).
- **Science block:** run types by `config/campaign.yaml` `mix` (real 0.50, canaries 0.30, controls 0.10, shams
  0.10; the probe share is filled with measuring canaries until Mission 6.1). The planner sizes the block so the
  LLM calls it needs (real runs, clean runs and the canaries the tripwires are expected to pass, from the window's
  measured rate) fit the day's room after the slice. At the assumed rates: 61 runs = 30 real, 18 canaries, 12
  clean, 45 calls.
- **Which canary:** the (class, tier) variants with the fewest measuring canaries in the window first, ties by a
  seeded shuffle, so the window stays even across classes. B09 keeps its even share for the blind-spot record
  although it is outside the support once the guard is tested. A variant that cannot be applied to the base falls
  back as the mixer already does.
- **Which base a clone copies:** pool 3 and, from the second block on, this campaign's own guard-`ok` real
  proposals of earlier blocks, drawn evenly, **whatever their review verdict was**, at most 4 clones per base per
  block, never with the base's seeds. This is DESIGN.md section 2 ("cloned from real Scientist hypotheses"); it
  changes a recorded decision, see section 9 and decision 2.
- **Calibration block:** no real slot. Clean runs up to the day's LLM room; canaries for the classes furthest
  below target (12, then 24), up to the laptop-time cap. Canaries cost almost no LLM call under the lazy union.
- **Order:** slots are shuffled; the review order is a second seeded shuffle of the runs the tripwires passed, so
  a stop at the daily limit never leaves one run type behind. Run IDs are random. The plan file is sealed.
- **Real runs look like calibration runs:** padding and a decoy drawn in the canaries' proportions (Mission 4.1
  step 7). A block refuses to start if that step is not built.

## 6. Budget
| Resource | Limit | What the code does |
|---|---|---|
| Groq free tier | 180,000 tokens in any 24 hours (about 65 reviews), 45 s between calls | the existing budget check in `canary/llm.py` stops before the call that would pass the limit; the campaign catches that stop, finishes phase 9 for what it has, writes a `wait` record and exits with code 0 |
| Laptop time | `campaign.max_block_minutes`, default 120 (one sitting) | the planner sizes the block from measured mean seconds per proposal, run, clone, replay and review (kept in `data/campaigns/timings.json`, updated after every block); each phase also checks the clock and stops at a slot boundary |
| Memory | one local model at a time (6 GB VRAM, 15 GB RAM) | the Scientist is loaded only in phase 5 and unloaded before phase 6; the reviewer is in the cloud; the embedding model of Mission 3.1 runs on the CPU in phase 5 only |
| The campaign itself | review days, real runs or an end date, given when it starts | rule 1 |

**The message at the daily limit** (times computed from the call log, shown in IST = UTC + 5:30 with UTC beside
it; the offset is one config value, `campaign.display_utc_offset`):
```
Groq daily limit reached at 21:14 IST. Nothing was stored against the reviewer.
First calls possible from 19:02 IST tomorrow (13:32 UTC); a full day's budget (about 65 reviews) from 21:14 IST.
Waiting for review: 7 runs. Resume with:  python -m canary.campaign --resume demo-1
```
"First calls" is the oldest call of the last 24 hours plus 24 hours; "full budget" is the newest one plus 24
hours. Rule 2 will not start a session before there is room for a whole slice, so three-call sessions cannot
happen. Campaigns run in the student's own PowerShell window (Edge closed for long sessions), never from Claude
Code. Progress goes to `data/runs/campaign.log` as now.

**No campaign review call while a locked evaluation's reviews are open** (the RQ4 bank week): they share one
quota and one reviewer, and campaign calls would sit between the bank's reviews. Preflight refuses.

## 7. The trace: why each decision was taken, replayable
Every decision is one JSON line in `data/campaigns/<id>/trace.jsonl`, and its SHA-256 is a ledger entry
(`campaign_decision`), so the trace cannot be rewritten without breaking the chain. A record holds:
- **identity:** campaign ID, block number, decision number, time (UTC and IST), epoch ID, git commit, the hash of
  the policy source and of `config/campaign.yaml`, the ledger's head hash at that moment;
- **the state the policy saw:** per supported class the measuring canaries in the window (caught, total); clean
  runs (passed, total); real runs reviewed and flagged in this campaign and epoch; the gate record of Mission 4.1
  (pooled and worst class, the class name, the 90th percentile of the gate figure, tau, the leak, the support);
  the zero-flag test's figure; alarm state and the day's slice counts and limits; runs waiting; the Groq room in
  calls and tokens; minutes allowed; what is left of the campaign's budget;
- **every rule of section 3** with true or false and the numbers that made it so, down to the one that fired;
- **the action** and its parameters (block size, counts per run type, the seed), and a one-line rationale built
  by code from the rule, for example `recalibrate (thin): class B04 has 9 of 12 measuring canaries in the window`;
- **the outcome,** appended when the block ends: slots run, crashed, reviewed, waiting; calls and tokens used;
  where it stopped and why.

`python -m canary.campaign replay --id <id>` does two checks for every decision: (1) the policy, given the stored
state, returns the stored action; (2) the stored state is rebuilt from the ledger as it stood at that head hash
and matches. Trust draws use a seed derived from the campaign seed and the decision number, so both are exact.

## 8. What the simulation gave (assumed rates; 300 campaigns of 30 review days per cell)
| World | Start | Calibration blocks | First science block | Gate open, share of days | Real runs reviewed in 30 days | Real runs passing the open gate (10th to 90th percentile) |
|---|---|---|---|---|---|---|
| no real bug | bank | 0 | day 1 | 1.00 | 900 | 877 to 887 |
| no real bug | cold | 2 | day 3 | 0.93 | 840 | 817 to 828 |
| 5% of real runs buggy (supported classes) | bank | 0 | day 1 | 1.00 | 900 | 829 to 848 |
| 5% of real runs buggy | cold | 2 | day 3 | 0.93 | 783 median passing | 773 to 793 |
| one supported class at recall 0.60 | bank | 0 | day 1 | 0.99 | 900 | 845 to 886 |
| one supported class at recall 0.60 | cold | 2 | day 3 | 0.92 | 840 | 788 to 828 |

All five checks fixed before the run passed: no campaign had more than 2 calibration blocks in a row (limit 4);
from the bank the gate was open on every day; from cold every campaign reached science by day 3; with a weak
class every campaign was doing science on day 10; with 5% buggy real runs the true share of buggy runs among
accepted ones was 0.0015 on average and under tau in every campaign.
What the table does **not** say:
- "Passing the gate" counts runs, not findings. A run whose own verdict is inconclusive passes too, and both real
  runs so far were inconclusive. The share of decisive verdicts is unknown; the real proof measures it.
- The "too weak" state (rule 8) never occurred, even at recall 0.60: with almost no flags the estimated
  prevalence is near 0 and a weak class costs little. It is kept as the guard against a loop, and step 1 adds a
  world that reaches it (recall 0.20), with the same checks.
- About 30 real runs a day is the pace **if** every review call succeeds and the laptop keeps up.

## 9. Where this plan differs from earlier text
| Earlier text | This plan | Status |
|---|---|---|
| PROGRESS, Decisions: "The pool of bases is 18 fresh Scientist proposals over a fixed grid ... not the ledger", because unprompted proposals were nearly one experiment | campaign clones copy pool 3 **and** the campaign's own guard-`ok` real proposals | decision 2; sensible only once the Scientist varies (the fix in `mission_3_1_3_2_memory_calibration.md`); until then pool 3 only |
| DESIGN.md section 12: recalibrate "when the trust interval is too wide" | the zero-flag test (section 3) | a definition, no new number |
| DESIGN.md section 8: escalation "tripwires, then replication, then the human queue" | tripwires run on every run first (already changed by `mission_5_1_tripwires.md` section 8); escalation is replication, then the human queue | already approved |
| `mission_4_3_drift.md` simulated 15 fresh clean runs and 20 fresh canaries a day | the configured mix gives about 12 and 18, so the fresh charts and the rolling window are a little slower than simulated there (window about 10 to 13 review days, not 8 to 11) | Mission 4.3 step 2 re-runs with this plan's mix |
| CLAUDE.md: "`canary campaign --resume`" | `python -m canary.campaign --resume <id>`, with `canary.cli campaign` as a thin alias once `canary/cli.py` is not frozen | same command in substance |

## 10. Build order (Opus)
New module `canary/campaign.py`; entry point `python -m canary.campaign`. It may read the sealed table (it plans
run types); `skeptic.py` and `blinding.py` may not import it (the existing import guard test gets this name).

**Sitting 1 (steps 1 to 3): the policy, with no run and no call.**
- **Step 1. `eval/campaign_power.py`:** the simulation as tested code that calls `campaign.decide` and
  `trust.estimate` (so it cannot differ from the loop); adds the recall-0.20 world and two baseline controllers
  (never recalibrate; recalibrate every fifth block) under a planted reviewer change, to show what the rule buys.
  Tests: seeded; reproduces `campaign_policy_sim.json`'s checks from the assumed rates.
  **Done when:** `eval/results/campaign/power.json` exists from measured rates and prints the five checks.
- **Step 2. `campaign.State` and `campaign.decide`.** Tests: one test per row of section 3, in order (a state
  that satisfies rules 4 and 6 gives rule 4); the function is pure (same state twice, same record; no clock, no
  file, no random call inside); the zero-flag test against a hand-made gate record; rule 8 fires only with a full
  window; a state with no reviewer identity stops.
  **Done when:** `python -m canary.campaign --explain` prints the table with a synthetic state for each row.
- **Step 3. State from the ledger.** `campaign.state_from_ledger(campaign_id, up_to_head)` builds the state from
  ledger entries, tripwire records, the sealed table and the call log. Tests: a hand-built ledger gives the
  hand-counted state; clones never count as real runs; runs of another epoch are left out; the same head hash
  gives the same state after later entries are appended.
  **Done when:** it prints the state of the real ledger without error ("no campaign yet" is a valid answer).

**Sitting 2 (steps 4 to 6): the block, on a fake provider.**
- **Step 4. Planner.** Block size from the room and the minutes; run types by the mix (largest remainder);
  canary variants by need; bases; decoys; two seeded shuffles; the sealed plan file. Tests: the counts for 61
  runs are 30, 18 and 12 (rounding stated in the plan file); no base gives more than 4 clones; the LLM calls
  planned never exceed the room; the review order mixes run types (no run type is absent from the first third);
  the same seed gives the same plan.
- **Step 5. Phases 5 to 9 and resume.** Reuses `scientist.propose`, the guard, `mixer.execute_slot`, the
  tripwire runner, `skeptic.audit` and `gate`. Tests (fake provider, fake clock, temporary folders): a block runs
  end to end; killing it after any phase and resuming repeats no slot and no audit; a run flagged by the
  tripwires is never sent to the LLM; a run whose LLM call failed has no union verdict and waits; real runs
  reach the gate only with an in-control slice; the reviewer path never opens the sealed file (the existing spy).
- **Step 6. Budget, wait and the trace.** The daily-limit stop becomes a `wait` record with both times in IST and
  UTC; trace records and their ledger hashes; `replay`. Tests: the fake clock crosses a daily limit in the middle
  of phase 8 and `--resume` continues with the first waiting run; the printed times equal hand-computed ones for
  a hand-made call log (a call at 13:32 UTC frees at 19:02 IST the next day); editing one trace line makes
  `replay` and `ledger verify` fail; `replay` passes on an untouched trace.
  **Done when (fast proof):** `pytest -q` under 30 s, and `python -m canary.campaign --demo-fake` runs a
  three-block campaign on the fake provider that stops at a fake daily limit, resumes, meets a planted reviewer
  change (alarm, hold, recalibration in a new epoch, science again) and replays clean.

**Sitting 3 (steps 7 and 8): the real proof and the write-up.**
- **Step 7. Real campaign, student's window, 3 review days, after RQ4 is analysed.**
  `python -m canary.campaign --id demo-1 --question q1 --review-days 3 --calibration cold`, then
  `--resume demo-1` on the following days. `--calibration cold` starts the rolling window empty (the epoch and
  the sentinel stay), so the agent must calibrate before science; the fresh calibration runs it collects stay in
  the window and are not wasted. Forecast at the assumed rates: days 1 and 2 calibrate, day 3 does science, each
  day stops at the Groq limit after about 65 calls.
  **Done when (the mission):** the trace shows at least one `recalibrate`, one `wait` across a real daily limit
  followed by a resume, and one `science` block; `python -m canary.campaign replay --id demo-1` passes;
  `ledger verify` passes; the report prints, from the trace and the ledger, the runs per type, the share of
  decisive verdicts among real runs, and the gate's state with its reason (today's true reason may be "B09 in the
  support, guard not tested": then nothing is auto-accepted and that is the correct output).
- **Step 8. Write-up.** `PROGRESS.md`; `DESIGN.md` sections 2 and 12 rewritten to this plan; README; the coach
  tips in `.claude/coach_state.py`; the trace file's format documented for the Lab Monitor page (Mission 7.1).

## 11. Traps
1. **The policy is pure.** No clock, random draw, file read or LLM call inside `decide`. Everything it needs is in
   the state. Otherwise `replay` proves nothing.
2. **The reviewer path must not learn anything from the campaign.** One blinded run per call, no block number, no
   order hint, no "calibration" wording. The plan file is sealed; `campaign.log` shows IDs and counts.
3. **A daily-limit stop is not a failed audit** (existing rule). Nothing is written for runs not yet asked.
4. **Do not let a stop rule look at results.** "Stop when 10 findings are accepted" is optional stopping. The
   campaign's stop rule is fixed in its first record; any evaluation (RQ3, RQ4) uses campaigns with a budget stop.
5. **A control is only as clean as its base.** Bases must be guard-`ok`. They are **not** chosen by their review
   verdict: choosing "passed" bases would select runs the reviewer already likes and inflate specificity.
6. **Never plan a block larger than the room,** or real runs pile up unreviewed while the Scientist keeps
   proposing. Backlog first (rule 5).
7. **One quota.** Sentinel, backlog and block reviews all draw on it; so does any locked evaluation (refused in
   preflight).
8. **Hashes fixed at the campaign's start.** A changed config, policy or tripwire version in the middle is a new
   campaign (or a new epoch); the old one is closed with a `stop` record, never silently continued.
9. **The Scientist is told nothing that depends on a clone's type.** `real_preregs` already filters; calibration
   feedback (Mission 3.2) uses real runs only.
10. **Replays and guard reference runs never write under `data/runs/`.**
11. **IST is display only.** Every stored time is UTC.

## 12. What it may claim and may not claim
**May claim:** a campaign runs unattended inside a free daily quota and continues exactly after any stop; every
action was chosen by a published rule from measured numbers and can be replayed from the ledger; the loop
interrupts science for calibration when one of four stated conditions holds; no LLM chose an action, a verdict or
a number.
**May not claim:** that the agent "learns" or "reasons" about when to recalibrate (it applies fixed rules); that
the policy is the best one (it is compared with two simple controllers in simulation only); a throughput of
findings (only of reviewed runs, until the share of decisive verdicts is measured); that a quiet campaign means
a clean ledger (see the claims of Missions 4.1 and 4.3); anything from the fake-provider demo about a real model.

## 13. /challenge (strict reviewer), with the fix
| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Critical | "Agent" oversells a nine-row rule table. A reviewer will ask what is agentic and what it is compared with. | Named a rule-based controller in every text (section 4, 12). Its claim is replayable decisions from measured trust. Step 1 compares it with "never recalibrate" and "every fifth block" under a planted change, in simulation, labelled as such. |
| 2 | Critical | With the bank as the start the agent never recalibrates in simulation (0 blocks in 30 days). The mission's proof would then depend on luck or on a staged event. | The real proof starts cold on purpose (step 7) and says so; the fake-provider demo shows the alarm path; the report states which recalibrations were forced by the setup and which happened by themselves. |
| 3 | Major | Throughput is counted in runs. If most real verdicts are inconclusive, 30 reviews a day buy almost no findings, and a third of the quota goes to the sentinel. | The real proof reports the decisive share (step 7). Reviewing only decisive real runs is listed as decision 3, not adopted: it would make real runs a different population from the calibration runs. `seeds_per_arm` stays a separate decision (Known issues). |
| 4 | Major | Cloning controls from the campaign's own real proposals assumes those proposals are clean. A buggy base makes a "clean" control that is rightly flagged and counted as a false alarm. | Bases must be guard-`ok`; under the template the only config bugs left are the guard's measured leak; the union's specificity is reported with and without clones of campaign bases. Decision 2. |
| 5 | Major | Selecting bases that passed review would bias specificity upward. | Bases are drawn whatever their verdict (trap 5), with a test. |
| 6 | Major | Optional stopping: a campaign that stops on "enough findings" reports its trust numbers at a favourable moment. | Budget stops only, fixed in the first record (trap 4). |
| 7 | Major | Resume after a crash between the provider's reply and the ledger write could ask twice and keep the second answer. | Non-sentinel calls write the cache before the ledger, so the repeated call returns the stored reply; a test kills the process at that point. The first audit stands. |
| 8 | Major | The campaign and the RQ4 bank week would share a quota and interleave calls of two purposes. | Preflight refuses while a locked evaluation is open (section 6, trap 7). |
| 9 | Moderate | The zero-flag test uses random draws; near tau the decision could differ between two evaluations. | Seed derived from the campaign seed and the decision number; `replay` checks equality (section 7). |
| 10 | Moderate | A block equals a review day only if the student runs it daily. | Blocks are counted in review days everywhere; the header shows the calendar gap since the last block, and the sentinel slice comes first whatever the gap. |
| 11 | Moderate | The laptop-time model starts with no measurements. | First block uses the means already measured (PROGRESS: runs, B09 subtle, proposals); the planner halves the first block's size and corrects from its own timings. |
| 12 | Minor | IST is hard-coded in the request. | One config value; stored times are UTC (trap 11). |

**Second pass (same day), after reading the draft against the other plans:**
| # | Severity | Finding | Fix |
|---|---|---|---|
| 13 | Major | The draft let the campaign clone from its own proposals although a recorded decision says clones come from a pool built on a grid, and the reason for that decision (the Scientist proposes nearly one experiment) still holds today. | Section 9 names the conflict. Until the Scientist's variety fix has passed its own test (`mission_3_1_3_2_memory_calibration.md`), campaigns clone from pool 3 only; decision 2 asks the student. |
| 14 | Major | Real proposals come from the Scientist unprompted; pool 3's bases come from a grid. Calibration and real runs are then different populations, the very thing padding and decoys were added to prevent. | Real slots of a campaign are proposed with the same focus grid as the pool (code picks the cell, the Scientist proposes inside it), until the variety fix is judged. Stated in section 5 through decision 4; RQ4's kind B measures transfer across bases. |
| 15 | Moderate | The trace stores the state, but a reader also needs what the agent would have done under the other rules. | Every rule's truth value and numbers are stored down to the firing rule (section 7); `--explain` prints the rest for any stored state. |
| 16 | Moderate | Mission 4.3's simulated pace (15 clean, 20 canaries a day) differs from this plan's mix (12, 18). | Listed in section 9; Mission 4.3 step 2 re-runs with this mix before its sizes are final. |

## 14. Decisions (for the student; recommended default first)
1. **The real proof starts cold** (`--calibration cold`, 3 review days, about 195 calls), so the trace shows a
   real recalibration: **yes.** Alternative: start from the bank and accept that only the fake-provider demo
   shows recalibration.
2. **Bases for campaign clones:** pool 3 only until the Scientist's variety fix has passed its test; after that,
   pool 3 plus the campaign's own guard-`ok` real proposals. This changes the recorded "pool, not the ledger"
   decision once its reason is gone. **Default: as written.** Alternative: pool only, for good.
3. **Review every real run** (as approved in Mission 4.1), not only the ones with a decisive verdict: **yes.**
   The alternative saves calls but changes the population the flag rate describes.
4. **Real slots use the pool's focus grid** (code picks dataset, metric and model in rotation; the Scientist
   proposes the comparison inside the cell) until the variety fix is judged: **yes.**
5. **Block budget defaults:** 120 minutes of laptop time per block; a block per review day; the campaign's own
   stop is a number of review days: **yes.**
6. **The trace's hash goes into the ledger** (`campaign_decision` entries), so the ledger grows by one entry per
   decision: **yes.**
