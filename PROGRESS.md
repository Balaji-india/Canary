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

**M4 How much should we trust our findings?**
- [ ] 4.1 Prevalence, contamination, trust gate
  - **Requirement (student, 2026-11-09):** real Scientist runs must get the same padding and decoy treatment as
    calibration runs (`canary/padding.py`, `canary/saboteur/decoys.py`, decoys in the canaries' proportions), or
    measured trust (recall, specificity, contamination) may not transfer to them. Check it with the length gate on
    real runs mixed with calibration runs before any gate decision uses calibration numbers.
- [ ] 4.2 Hidden-truth validation (RQ4)
- [ ] 4.3 Control chart and drift alarms
- [ ] 4.4 Campaign agent loop

**M5 Defense in depth**
- [ ] 5.1 Tripwires
  - Designed, not built (2026-11-13, `docs/plans/mission_5_1_tripwires.md`: design, self-review, 12 build steps);
    waits for the student's OK on its section 12. The 2026-11-10 outline is superseded.
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
**Current focus:** Cloud ceiling check, arm L: day 1 of 3 done (67 of 120 answered); day 2 from 2026-11-13 13:11 UTC (6:41 PM IST)

**Stopped at (2026-11-13, design session, Fable):** Mission 5.1 designed, challenged and planned in
`docs/plans/mission_5_1_tripwires.md`; nothing built, no code or test file changed, so the tests were not re-run
(last run 2026-11-12: 718 passed in 29.7 s, at the limit). The ceiling arm was not touched: `campaign.log`, the call
log and every `skeptic_d` audit or result were not read, and no frozen file was edited. Arm L is as day 1 left it
(2026-11-12: 67 answered, 53 not asked yet, 0 failed, "Lock check: OK"); day 2 is the student's window tonight.
Mission 2.4 is the last mission complete.

## Mission 5.1 design (2026-11-13): not built, awaits the student's OK
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
1. **Fri 2026-11-13, after 13:11 UTC (6:41 PM IST), student's window, arm L day 2:** `.venv\Scripts\python.exe -m
   eval.ceiling_lock --check` (must end "Lock check: OK"), then `.venv\Scripts\python.exe -m canary.cli reaudit --batch
   ceiling-ext --role skeptic_d` (53 calls, about 40 min; should end "80 stored, 0 failed"), then the check again
   (120 answered, 0 not asked yet). Note the clock time the session ends.
2. **Student: read `docs/plans/mission_5_1_tripwires.md` section 12 and answer the 8 decisions** (or "approve as
   recommended"). Then Opus starts sitting A (steps 0-2: room in the test suite, the probe with its transparency
   test, pair arithmetic). New files only; lock check after the session.
3. **Sat 2026-11-14, not before the clock time Friday's session ended (rolling 24 h budget), student's window.**
   From the locked plan, section 7, in this order, reading no reply:

   ```powershell
   cd "C:\Users\Balaji Keerthi\Downloads\canary"
   # Step 0: must end "Lock check: OK", name only openai/gpt-oss-120b, and show 120 answered, 0 not asked yet.
   .venv\Scripts\python.exe -m eval.ceiling_lock --check
   # Step 3, ONLY if the check shows runs "failed once": that batch's command exactly once more, then the check again.
   #   .venv\Scripts\python.exe -m canary.cli reaudit --batch task-dev-2 --role skeptic_d
   #   .venv\Scripts\python.exe -m canary.cli reaudit --batch ceiling-ext --role skeptic_d
   # Step 4: the repeat pass (20 runs by seed, cache bypassed, nothing stored in the ledger; the first audit stands).
   .venv\Scripts\python.exe -m canary.cli rescore --batch ceiling-ext --reviewer skeptic_d --sample 20 --seed 1112
   # Step 0 again, before the analysis.
   .venv\Scripts\python.exe -m eval.ceiling_lock --check
   # Step 5: the analysis, ONCE. It writes eval/results/ceiling/arm_L.json and refuses a second run.
   .venv\Scripts\python.exe -m eval.ceiling --arm L
   ```

   If the repeat pass says "Some calls failed or hit a limit", run the same `rescore` command again after the budget
   is back (finished records are skipped). Stop and write it here, with no workaround, if a check does not end
   "Lock check: OK", if another server model appears, or on an `access`, `config` or `request_refused` stop (plan
   section 8). Then Fable reads `arm_L.json` (`/evaluate`).

Next missions after the ceiling check: 5.1 tripwires (design awaits approval), 3.1 graveyard, 3.2 calibration.
Known issues: cloud replies are not repeatable word for word at temperature 0 (verdict held on the smoke run);
Gemini's real limits unknown (only needed for arm R).

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

## Decisions
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
- **`pytest -q` is at or over the 30 s target** (30.2-35 s on 2026-11-10, 607 tests; slower while other work runs;
  one run on 2026-11-11 took 59 s for 609 passed with no code change, not re-timed).
  Next step: mark a few more slow tests or lower draws further.
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

## Next actions
1. **Cloud ceiling check on free APIs** (outline: `docs/plans/cloud_ceiling_check_outline.md`).
   a. **Student:** confirm the provider (recommended: Groq for arm L, Gemini free tier for arm R) or pick an
      alternative from outline section 2.
   b. **(Opus) `/api`** from `docs/plans/api_cloud_provider_build_plan.md`: the OpenAI-style provider, pacing and
      daily budget, call log, `cloud-smoke`, mocked tests. No real call and no key in that session. Does not wait
      for (a).
   c. `eval/ceiling.py` (verdict-based, frozen) and the `eval/power_sim.py` extension: the outcome table and the batch
      size; an extension batch on the laptop if the size is above 40.
   d. **Student:** create the two keys without a payment method, read the free limits in both consoles (outline
      section 9); then the live smoke test (needs the OK to send one blinded old run), the lock, and arm L in short
      daily sessions through `llm.py` only. Pay only if the free result is INCONCLUSIVE or HARD and a newer paid model
      would change the conclusion.
2. **Only if the ceiling check says SOLVABLE: efficiency search** for the cheapest model that still clears the bar:
   local non-Qwen code models that fit 6 GB VRAM and smaller cloud models. Each candidate is tested on its own fresh,
   never-seen batch, pre-registered and locked, with the same rules and the same bar; nothing is chosen on a batch
   whose results we have seen.
3. **`/mission 5.1` (deterministic tripwires)**, the main defence whatever the ceiling check says; then Mission 3.1.
   Needs the student's OK on the design first (`docs/plans/mission_5_1_tripwires.md`, section 12).
4. Housekeeping: `pytest -q` takes 30-35 s, over the 30 s target; trim or mark more tests slow.
