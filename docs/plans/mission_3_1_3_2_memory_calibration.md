# Plan: Missions 3.1 and 3.2, the graveyard, calibration feedback and the Scientist's narrow proposals

Designed 2026-11-15 by Fable. Not built. Builder: Opus, 3 sittings; the two tests run in the student's window,
**locally only**: no reviewer and no cloud call is needed anywhere in this plan (the Scientist is a local model).
Depends on: nothing in Mission 4. The prompt work must wait until `canary/prompts.py` is no longer frozen
(tripwire sitting D) or go into a new file (section 7).

Simulation behind the two test sizes: `docs/plans/sims/scientist_test_sim.py`, output `scientist_test_sim.json`
beside it, committed **before its first run** (commit dc5a833) with both selection rules in its docstring.
**Every Scientist behaviour in it is an assumption for sizing**, not a measurement.

## 1. What these missions are, what they block, and where pool 3 comes in
- **3.1 Graveyard:** a memory of what was tried and how it ended, checked before a new proposal is locked.
- **3.2 Calibration:** score the Scientist's stated confidence against what happened (Brier score, reliability
  diagram) and tell it the result; RQ6 asks whether telling helps.
- **The known issue** (PROGRESS, Known issues): every Scientist model tried put 14 of 15 proposals on one dataset,
  all 15 on `balanced_accuracy`, all 15 predicted "increase", and two of the three models stated one fixed
  confidence (0.75; 0.80), the third 0.70 to 0.85. A graveyard of one experiment and a Brier score of one
  confidence value show nothing.

**What they block.** Nothing in Missions 4.1 to 4.4 or 5.1: the gate, the estimate, the chart and the campaign
loop work without them (campaign real slots use the pool's focus grid, `mission_4_4_campaign.md` decision 4).
They are needed by: RQ6 (Mission 8.1); the Graveyard and Calibration pages (Mission 7.1); the baseline guard's
rejected proposals, which move into the graveyard (`b09_proposal_guard.md`, trap 8); and campaigns that let the
Scientist choose freely or that clone from their own proposals (`mission_4_4_campaign.md` decision 2).

**Pool 3 is built before any change to the Scientist's prompt, and the change is switched on only after RQ4 is
analysed.** The reason is section 6; in short, the reviewer sees the pre-registration, so a Scientist that
proposes differently makes real runs differ from the calibration runs cloned from older proposals.

## 2. Mission 3.1: the graveyard and the similarity check
### 2.1 What is in it
One entry per ended idea of a **real** run or a rejected real proposal; never a clone (the builder joins the
sealed table exactly as `scientist.real_preregs` does). Stored as `graveyard` ledger entries, as the crashed run
already is.

| Cause of death | Comes from |
|---|---|
| `rejected: <rule>` (guard G0, G1, G2, G5; duplicate; invalid config) | proposal checks; nothing ran |
| `crashed` | the sandbox |
| `null: not supported`, `null: inconclusive` | the code-computed verdict |
| `flagged: <class>` | the union verdict on a real run ("flagged", never "buggy") |

Accepted findings are not dead, but the similarity check searches them too, labelled "supported".

### 2.2 How similarity is measured: the experiment first, the wording second
Under the template an idea **is** its two configs. So the first measure is exact and needs no model:
- **Idea key** (code, from the configs): dataset, metric, the two models, and the **names** of the factors that
  differ between the arms (a parameter name, `preprocessing`, or `model`); values and seeds ignored. Two
  proposals with the same idea key ask the same question with other values ("depth 3 against 8", "depth 2
  against 6"). The exact-duplicate key (`_experiment_key`) stays as it is and still rejects.
- **Text similarity:** cosine between MiniLM embeddings (`all-MiniLM-L6-v2`, the stack's model, on the CPU) of
  the two hypothesis sentences. It is there to find the same idea on another dataset or under another name.

**Retrieved for a new proposal:** every entry with the same idea key, then entries with cosine at least T; ranked
same-key first, then by cosine; the top 3 are used.

### 2.3 How the threshold T is fixed (the rule now, the number by code, no eye)
DESIGN.md section 11 and `config/campaign.yaml` say 0.75. Nobody measured that number; hypothesis sentences share
most of their words, so it may retrieve everything or nothing. The rule, fixed here:
1. **Development pairs:** all pairs among the 35 bases of pools 1 and 2 (Scientist proposals; no reviewer data).
   Code labels a pair **unrelated** if the two differ in dataset **and** in the set of models **and** in the
   names of the differing factors, and **same idea** if their idea keys are equal.
2. **T = the 95th percentile of the cosine among unrelated pairs,** rounded up to two decimals. So at most about
   5 in 100 unrelated experiments would be retrieved as "similar".
3. **Usefulness check, same data:** if fewer than half of the same-idea pairs reach T, text similarity does not
   follow experiment similarity here. Then **only the idea key retrieves**; the cosine is kept for ranking and is
   reported as not useful. With fewer than 10 same-idea pairs the check cannot be made; then too only the
   idea key retrieves, until pool 3's pairs (step 4) allow the check.
4. **Judged once on fresh pairs:** pool 3's bases against the 35 older ones (pairs that did not exist when T was
   set). Pass mark: the share of unrelated pairs at or above T has a 90% upper bound of at most 0.10. If it
   fails, the consequence of step 3 applies. T is not adjusted afterwards.
The embedding model's name and revision are recorded with T: another revision gives other cosines.

### 2.4 What the Scientist is shown, and what code does with the answer
Two steps, because nothing can be "similar" before a proposal exists:
1. The Scientist proposes as now.
2. Code retrieves. **No hit:** the proposal goes on. **A hit:** the proposal is sent back once (it uses one of
   the 3 attempts) with up to 3 entries, one line each, written by code: the hypothesis, how it ended (cause of
   death or "supported"), the effect with its interval, and what differs from the new proposal (for example
   "same dataset and model; you change `max_depth` again"). The Scientist may revise or keep its proposal and
   must fill one new field, `differs` (one sentence).
- **`differs` and the hits are stored in the `PROPOSED` ledger payload, never in `locked`.** The pre-registration
  keeps its exact format, so the reviewer's prompt does not change (the guard record's rule, same reason).
- **Code never judges the sentence.** The only mechanical rejection stays the exact duplicate. A proposal that
  shares an idea key with a dead entry is allowed and labelled `revisits: <hypothesis id>`.
- **Whether the step does anything is measured** (section 5, arm 3): the share of proposals that revisit an idea
  key already in the chain, with the step on against off. Rule fixed now: the step is switched on for campaigns
  only if that share is lower with it, with a 90% interval for the difference that excludes 0. Otherwise the
  graveyard stays a record and a dashboard page, and the prompt step stays off.

## 3. Mission 3.2: Brier score, reliability diagram, feedback
### 3.1 What a prediction is and how it resolves
The Scientist states `confidence` = the probability that the result reaches `min_effect` in the predicted
direction (PROGRESS, Decisions). **Outcome, by code, for every real run that finished:** 1 if the mean signed
effect is at least `min_effect`, else 0. This is the event the Scientist was asked about, and it resolves every
run. Resolving only decisive verdicts would throw away most runs (both real runs so far were inconclusive) and
select on the outcome. The stricter outcome "verdict is `supported`" is reported beside it. Crashed runs have no
outcome and are counted. Clones never count: their numbers are manipulated on purpose.

### 3.2 The numbers (`canary/calibration.py`)
- **Brier score** = mean of (confidence - outcome) squared. Lower is better; always saying 0.5 scores 0.25.
- **Three parts** (Murphy): reliability (stated confidence against what happened, per bin), resolution (do higher
  confidences come true more often), uncertainty (the outcome rate alone). Brier = reliability - resolution +
  uncertainty, exact when a bin holds one stated value.
- **Skill against the base rate:** 1 - Brier / (rate x (1 - rate)). A Scientist that always says the same number
  cannot score above 0 here. That sentence goes into every report, because it is today's Scientist.
- **Reliability diagram:** one point per bin with its count and a Beta interval. Bins: the distinct stated values
  when there are 5 or fewer, else 5 bins of equal count. No empty ten-bin grid.
- Intervals: bootstrap over chains (or campaign blocks), because predictions in one chain are not independent.

### 3.3 Feedback to the Scientist
A block in the prompt, **built by code from the Scientist's own resolved real predictions**, numbers only, no
advice: for example "Of your last 20 predictions, 6 came true (30%). Your average stated confidence was 0.80.
When you said 0.75 or more: 5 of 17 came true." Window: the last 20 resolved predictions; no block before 5 are
resolved. No reviewer verdict and nothing about clones enters it. It sits behind a switch that is **off** in
campaigns until section 6 allows it.

### 3.4 RQ6: does the feedback help? (local, no reviewer)
- **Design, from the rule in the simulation: 8 chains of 20 resolved predictions per arm** (320 proposals and
  runs in all). Arm OFF and arm ON run the **same sequence of experiment cells** (dataset, metric, model, chosen
  by the focus grid), so chain k is equally hard in both arms; each chain has its own ledger file.
- **Statistic, fixed now:** per chain, the Brier score over predictions 11 to 20, ON minus OFF. **Test:** the
  exact sign-flip test over the 8 chain differences, one-sided, alpha 0.05.
- **Simulated** (assumed: OFF says 0.80 always; ON moves a fraction r of the way to its running outcome rate
  from the sixth prediction on): power at r = 0.5 is 1.00 when 20% of predictions come true and 0.82 when 40% do;
  with r = 0 the test fires in 0.04 to 0.05 of studies. **When 60% come true the power is 0.18**: 0.80 is then
  nearly right and there is little to fix.
- **Reading, fixed now:** (a) test passes: "feedback lowered the Brier score"; then the three parts say how:
  today almost certainly through reliability (a shifted constant), not resolution. (b) test fails and the OFF
  arm's outcome rate is 0.6 or more: "no room to improve at this base rate", not "feedback does not work".
  (c) test fails otherwise: a negative result, reported. (d) In every case: outcome rate per arm, mean and spread
  of `predicted_effect`, and the share of guard labels per arm, to see whether the ON arm changed **what it
  proposes** (safer experiments) instead of how well it predicts.

## 4. The known issue: what is proposed to fix
| Symptom | Probable cause (untested) | Fix proposed | Changes the pre-registration's look? |
|---|---|---|---|
| one dataset in 14 of 15 | the prompt lists the last 10 hypotheses, all on that dataset, and the model continues the pattern | **F2:** replace that list by a coverage table built by code (experiments so far per dataset and per metric) plus the closest earlier experiments of 2.4 | no |
| one metric in 15 of 15 | `balanced_accuracy` is first in the sorted list | **F1:** shuffle the dataset, model and metric lists per call, seeded | no |
| always "increase" | hypotheses are phrased as improvements; "treatment" means "my idea" | none now: it is a labelling habit, and the scored event is the same in either direction. Reported. Option for later: code assigns which config is the treatment | yes (direction would vary), so only with a new pool |
| confidence nearly constant | small models repeat a default | the feedback of 3.3, judged by RQ6. Option for later: a fixed five-step scale | yes (the stated values change), so only with a new pool |

F1 and F2 together are **prompt v2**. They apply to unfocused proposing only. With a focus (the pool's path and
the campaign's path) one dataset, one metric and one model are offered and no earlier list is shown, so the
focused prompt stays **byte-identical**; a test holds its hash.

**If prompt v2 fails its test,** the fallback is already in use: code picks the cell from the focus grid in
rotation and the Scientist proposes the comparison inside it. Variety then comes from the grid, and the reports
say so: "the Scientist chooses the comparison, code chooses where".

## 5. The variety test (fresh proposals only, rule fixed first, run once)
- **Three arms, 72 fresh unfocused proposals each** (3 chains of 24 with different seeds; question q1; the same
  Scientist model; the guard on; each proposal is run, so later prompts have real outcomes to show):
  arm 1 = today's prompt; arm 2 = prompt v2 (F1 + F2); arm 3 = prompt v2 plus the graveyard step of 2.4.
  Each chain has its own ledger file under `data/eval/scientist/`; nothing touches the main ledger and nobody
  reviews these runs.
- **Pass marks for arm 2 (and arm 3), on its 72 proposals pooled:**
  V1: at least 5 of the 9 datasets appear, and the most frequent has at most 40% of the proposals.
  V2: at least 3 of the 4 metrics appear, and the most frequent has at most 60%.
  V5: usability is not worse: `ProposalRejected` at most 0.20 of slots (the guard plan's bar), and the share of
  first attempts rejected by any check at most 10 points above arm 1's.
  Reported without a pass mark: the share predicting "decrease"; the number of distinct confidence values and
  their spread; the revisit share (2.4), arm 3 against arm 2, with its fixed rule.
- **Why 72** (simulated, proposals drawn independently): 72 is the smallest size at which an even proposer
  passes V1 and V2 in 1.00 of tests, a mildly uneven one (one dataset 25%, one metric 40%) in 1.00, while a
  proposer with half its proposals on one dataset passes V1 in only 0.04 and one with 75% on one metric passes V2
  in 0.00. At 54 the half-on-one-dataset proposer still passed in 0.06, above the 0.05 the rule allows.
- **Reading, fixed now:** arm 2 passes V1, V2 and V5: prompt v2 may be used wherever proposing is unfocused,
  after section 6's procedure. Arm 2 fails: the focus grid stays, for good unless a new prompt passes a new
  test. Arm 1 is the reference: if arm 1 itself passes V1 and V2, the known issue has gone away by itself
  (another model version) and v2 is not needed. Arm 3 is judged on its own: if it fails V5 (the extra turn costs
  an attempt) the graveyard step stays off, and prompt v2 is still judged by arm 2 alone.

## 6. A change to the Scientist is a change to the runs: the order of work
The reviewer is shown the pre-registration: the hypothesis sentence, both configs, `predicted_effect`,
`confidence`. Calibration runs are clones of earlier proposals. If the Scientist starts to propose differently
(other datasets, other confidence values, other wording), real runs stop looking like the clones that measured
the reviewer, and Mission 4.1's leak term, measured on the old kind of proposal, is stale
(`mission_4_1_trust.md`, trap 7). Padding and decoys were added for exactly this kind of mismatch.

**Rules, fixed here:**
1. **The pool-3 era runs on today's Scientist prompt:** pool 3, the guard's locked test, the RQ4 bank and the
   first campaigns. In that era every switch of this plan is off and the focused prompt is byte-identical.
2. **These missions can still be built and judged at any time,** because their tests run on separate chains
   that no reviewer sees.
3. **Switching something on for campaigns** (prompt v2 for unfocused proposing, the graveyard step, the
   feedback block) is allowed only after its own test has passed **and** RQ4 is analysed, and is done as a
   **Scientist change**: a new pool proposed with the new prompt and the guard on; the guard's leak measured
   again on proposals from the new prompt (its test E1, local); the campaign's calibration window refilled from
   clones of the new pool before the gate may open. RQ4 is not repeated: it tested the estimator, and its
   "other experiments" kind is the evidence for transfer across bases.
4. Changes that alter the pre-registration's look by design (direction assigned by code, a confidence scale)
   are not part of this plan. Each would be a Scientist change of its own.

### 6.1 Where this plan differs from earlier text
| Earlier text | This plan | Status |
|---|---|---|
| DESIGN.md section 11: "the 3 most similar graveyard entries (MiniLM embeddings, cosine at least 0.75)" | the idea key first; T from the percentile rule; the cosine switched off if it fails its check | decision 1 |
| DESIGN.md section 11: the Scientist receives the entries "before proposing" | after a first proposal, in one extra turn (nothing can be similar to a proposal that does not exist) | decision 2 |
| PROGRESS, Decisions: "Rejected proposals are printed, not stored in the ledger" | stored as `graveyard` entries | already foreseen in the approved guard plan (its trap 8) |
| DESIGN.md section 11: "From Mission 3 on, the Scientist sees its own recent calibration summary" | built, but off in campaigns until RQ6 has passed and section 6's procedure is done | decision 7 |
| `mission_4_3_drift.md`: an epoch is one reviewer identity | the epoch record also holds the Scientist's identity (model, prompt version, switches), so a Scientist change starts a new epoch and the calibration window can never mix the two kinds of run | added to that plan in the roadmap pass |
| PROGRESS, Known issues: "ask for dataset variety in the prompt" if nothing else helps | not done: an instruction to vary is weaker than showing counts, and its effect could not be told apart from F2 | section 4 |

## 7. Build order (Opus)
New files: `canary/graveyard.py`, `canary/calibration.py`, `canary/scientist_prompt_v2.py` (a new file, so
`canary/prompts.py`, which the ceiling lock and later the RQ4 lock hash, is never edited for this),
`eval/graveyard_threshold.py`, `eval/scientist_variety.py`, `eval/rq6.py`. Edited: `canary/scientist.py` (not
frozen) and `config/campaign.yaml` (new switches, all off).

**Sitting 1 (steps 1 to 3): Mission 3.1.**
- **Step 1. Entries and keys.** `graveyard.entries(ledger, sealed)` (real runs and rejected real proposals
  only), `graveyard.idea_key(prereg)`. Rejected proposals are written as `graveyard` entries from now on (they
  are only printed today). Tests: a clone never appears; two proposals that differ only in a value share an idea
  key; a different factor name, model or dataset gives another key; the exact-duplicate key is unchanged; the
  crashed run already in the ledger shows up with its cause.
  **Done when:** `python -m canary.graveyard` lists the real ledger's entries with causes.
- **Step 2. Similarity and the threshold.** `graveyard.similar(proposal, entries, embed, threshold)` with the
  embedder passed in (tests use a fake one: no model load in the suite). `python -m eval.graveyard_threshold`
  applies section 2.3's rule to pools 1 and 2 and writes `eval/results/graveyard/threshold.json` (T, the pair
  counts, the usefulness check, the model revision). Tests: the percentile and the rounding against a
  hand-made list of cosines; same-key entries rank first; the check switches the cosine off when it should;
  the script refuses a second run unless told to overwrite.
  **Done when:** the JSON exists and `config/campaign.yaml` takes T from it (`graveyard_similarity` is no longer
  a typed number).
- **Step 3. The two-step proposal,** behind `science.graveyard_step: false`. Tests: with the switch off the
  prompt and the `locked` record are byte-identical to today's (stored hash); with it on, a hit costs exactly
  one attempt; `differs` is in the `PROPOSED` payload and not in `locked`; the blinded reviewer prompt is the
  same with and without the step.
  **Done when:** `pytest -q` under 30 s and a dry run with a fake Scientist shows a hit, the second turn and the
  stored sentence.

**Sitting 2 (steps 4 and 5): Mission 3.2.**
- **Step 4. `canary/calibration.py`.** `resolve`, `brier`, `parts`, `skill`, `reliability_table`,
  `feedback_text`. Tests against hand-computed values: confidences 0.8, 0.8, 0.6, 0.9 with outcomes 1, 0, 1, 1
  give Brier (0.04 + 0.64 + 0.16 + 0.01) / 4 = 0.2125; a constant 0.8 with 3 of 10 true gives reliability 0.25,
  resolution 0, uncertainty 0.21, Brier 0.46 and skill below 0; the parts add up; an effect exactly at
  `min_effect` resolves to 1; a crashed run has no outcome; a clone is refused; the feedback text for a
  hand-made history is the expected sentence, and is empty below 5 resolved.
  **Done when:** `python -m canary.calibration` prints the real ledger's table (today: a handful of predictions,
  labelled as too few).
- **Step 5. The feedback switch and `eval/rq6.py`.** `science.calibration_feedback: false`; the RQ6 runner
  (paired chains, own ledger files, resumable, `--dry`), the analysis (statistic and test of 3.4; refuses
  partial data, as `eval/ceiling.py` does) and the figure. Tests: the sign-flip test on 8 hand-made differences
  equals the hand count (all 8 negative gives p = 1/256); both arms get the same cell sequence; the switch off
  leaves the prompt byte-identical; the analysis refuses when a chain is short.
  **Done when:** `python -m eval.rq6 --dry` prints "8 chains x 20 x 2 arms, 0 resolved".

**Sitting 3 (steps 6 to 9): prompt v2, the lock, the two tests.**
- **Step 6. Prompt v2** in `canary/scientist_prompt_v2.py` (F1, F2), chosen by `science.prompt_version`. Tests:
  the lists are shuffled by the seed and complete; the coverage table equals hand counts; the focused prompt is
  byte-identical under v1 and v2.
- **Step 7. Lock.** `docs/plans/scientist_tests.md` with its `.sha256`: arms, seeds, sizes, pass marks and
  readings of sections 3.4 and 5, the file hashes, the exact commands. The runners refuse without the lock and
  refuse a second run.
- **Step 8. Run once, student's window, local** (Edge closed; resumable). Forecast from measured means (a warm
  proposal about 16 s, a run about 13 s, the guard's reference run a few seconds): variety test 216 proposals
  and runs, about 2 hours; RQ6 320, about 3 hours; range 4 to 8 hours in all, over as many sittings as needed.
- **Step 9. Write-up and the pool-3 pairs.** Results from the JSON files into `PROGRESS.md`; `DESIGN.md` section
  11 rewritten; the threshold's fresh test (2.3, step 4) as soon as pool 3 exists; switches stay off until
  section 6 allows them.
  **Done when (both missions):** `eval/results/scientist/variety.json` and `eval/results/rq6.json` exist with
  every pass mark printed as passed or failed, the reliability figure exists, and Missions 3.1 and 3.2 are ticked.

## 8. Traps
1. **Only real runs and real proposals** reach the graveyard, the feedback and the Scientist's prompt. Never a
   clone, never anything that depends on a clone's type.
2. **Nothing new goes into `locked`.** `differs`, the hits and the feedback live in ledger payloads.
3. **With every switch off, the prompt bytes are today's.** Tests hold the hashes. Without this, building these
   missions would silently change the Scientist during the pool-3 era.
4. **Test chains are quarantined:** own ledger and run folders, never reviewed, never counted as campaign runs,
   never shown in the main graveyard.
5. **Never drop inconclusive runs from the Brier score.** The point outcome exists for every finished run.
6. **Do not retune T, prompt v2 or the feedback text on the test chains.** A new version is judged on new
   chains under a new lock.
7. **The embedder is mocked in tests** and the real model is loaded only when a hit must be computed. It must
   be cached locally: `doctor` checks it, because experiments must run offline.
8. **Chains are not independent proposals.** The size simulation drew proposals independently; real chains show
   their own history. Report per chain as well as pooled.
9. **A better Brier score can come from proposing safer experiments.** Always read section 3.4's point (d).

## 9. What it may claim and may not claim
**May claim:** the Scientist is shown its closest earlier experiments and its own track record, built by code
from real runs; the Brier score and its parts, for every finished real run; whether prompt v2 met pre-set
variety marks on fresh proposals; whether feedback lowered the Brier score in paired chains, with the base rate
beside it.
**May not claim:** that the Scientist "learns from failures" (it is shown text; whether it proposes differently
is the measured revisit share); that it "became calibrated" when only a constant moved (say "the stated
confidence moved toward the outcome rate"); any improvement in resolution unless the resolution part shows it;
that text similarity finds related experiments, unless section 2.3's check and fresh test passed; anything about
other Scientist models or questions than the ones tested.

## 10. /challenge (strict reviewer), with the fix
| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Critical | Under a template the idea is the config diff. An embedding of a templated sentence with a threshold of 0.75 that nobody measured is decoration. | The idea key retrieves first; T comes from a stated percentile on development pairs, with a check that switches the cosine off if it does not follow experiment similarity, and one fresh test (2.2, 2.3). |
| 2 | Critical | With a near-constant confidence RQ6 can show one thing only: a constant moving toward the base rate. "Calibration improved" would overstate it. | The three parts are always reported; the wording rule in section 9; the skill-against-base-rate sentence in every report. |
| 3 | Major | The Scientist can lower its Brier score by proposing sure things. | Paired cells fix where it works; outcome rate, predicted effect and guard labels per arm are reported (3.4 d). |
| 4 | Major | The power of RQ6 depends on a base rate nobody knows: 0.82 at 40%, 0.18 at 60%. | Stated before the data; reading (b) names the low-power case; the OFF arm measures the base rate. |
| 5 | Major | Building prompt features while pool 3 and the bank are being made could change the Scientist under them. | Switches off, byte-identity tests, a new file for prompt v2, and the Scientist-change procedure (section 6, traps 3 and 4). |
| 6 | Major | Forcing variety is wrong for a question that is about one kind of data (q2 is about imbalanced datasets). | The variety test uses q1 only and says so; for other questions the offered dataset list is the lever, set in config per question, and the pass marks are not carried over. |
| 7 | Major | Arm 2 changes two things at once (F1 and F2), so the test cannot say which one fixed what. | Accepted: the decision is whether v2 as a whole may be used. The per-symptom causes stay "probable, untested" in every text. |
| 8 | Moderate | T is set on 35 proposals from two pools that share one grid. | The fresh test on pool 3's pairs (2.3); the grid is named as a limit. |
| 9 | Moderate | The `differs` sentence is never read by code. Why ask for it? | DESIGN.md asks the Scientist to say how its idea differs; whether asking changes behaviour is measured by the revisit share, and the step stays off if it does not (2.4). |
| 10 | Moderate | About 5 to 8 hours of laptop time for two tests of a part no Mission 4 result depends on. | Both are resumable and local; they are scheduled after the RQ4 bank is built, in the review week when the laptop is otherwise idle (roadmap). |
| 11 | Minor | `graveyard_similarity: 0.75` in `config/campaign.yaml` and "cosine at least 0.75" in DESIGN.md become wrong. | Replaced in steps 2 and 9, after decision 1. |

**Second pass (same day), after reading the draft against the other plans:**
| # | Severity | Finding | Fix |
|---|---|---|---|
| 12 | Major | Section 6 said a Scientist change needs a refilled calibration window, but nothing would enforce it: Mission 4.3's epoch knows only the reviewer. | The Scientist's identity goes into the epoch record (6.1); a change then opens a new epoch by the code that already exists for reviewer changes. Written into `mission_4_3_drift.md`. |
| 13 | Major | When pools 1 and 2 hold too few same-idea pairs, the draft let an unchecked cosine trigger extra proposal turns. | Unchecked means off: only the idea key retrieves until pool 3's pairs allow the check (2.3). |
| 14 | Moderate | The draft changed three sentences of DESIGN.md section 11 and one recorded decision without listing them. | Section 6.1. |
| 15 | Moderate | The summary of the known issue overstated "constant confidence" for one of the three models. | Corrected from PROGRESS's table (section 1). |
| 16 | Moderate | The graveyard step costs an attempt, so arm 3 may reject more slots than arm 2 and look worse on V5 for a reason that is not the prompt. | V5 is judged per arm; arm 3 failing V5 keeps the step off and does not fail prompt v2 (arm 2). Said in section 5's reading. |

## 11. Decisions (for the student; recommended default first)
1. **Similarity:** the idea key first, text cosine second, with T set by the 95th-percentile rule and switched
   off if the check or the fresh test fails; this replaces the typed 0.75: **yes.**
2. **Two-step proposal** with a `differs` sentence stored outside the pre-registration, switched on for
   campaigns only if the revisit share falls: **yes.**
3. **Brier outcome:** "mean signed effect at least `min_effect`", for every finished real run; the stricter
   "supported" beside it: **yes.**
4. **RQ6 design:** 8 paired chains of 20 per arm, Brier over predictions 11 to 20, exact sign-flip test at 0.05
   (the rule's choice): **yes.**
5. **Prompt v2 = shuffled lists + coverage table,** judged on 72 fresh proposals per arm with marks V1, V2, V5;
   if it fails, the focus grid stays for good: **yes.**
6. **"Always increase" and the confidence scale are left alone for now** (reported, not changed), because
   changing them changes how a pre-registration looks: **yes.** Alternative: change them later as a Scientist
   change with a new pool.
7. **Order:** pool 3, the guard test and the RQ4 bank on today's prompt; these missions built behind switches
   that stay off in campaigns until their tests pass and RQ4 is analysed; switching on follows section 6:
   **yes.**
8. **Feedback window:** the last 20 resolved predictions, nothing before 5: **yes.**
