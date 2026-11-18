# Pre-registration: Mission 5.1 tripwire test, `tripwire-test-1` (primary) and `ceiling-ext` (secondary) -- DRAFT, NOT LOCKED

Status: DRAFT written 2026-11-18 by Claude (Opus) for review; plan step 9 says Fable writes the lock and the student
says OK. Not locked: there is no `.sha256`, `eval.tripwires_test --lock` refuses while the title says DRAFT, and
`eval.tripwires_test --batch ...` refuses while the plan is not locked. Hashes below were computed 2026-11-18 after
step 8 (no tripwire change in step 8); they are recomputed if any listed file changes before the lock.
Design and decisions: `docs/plans/mission_5_1_tripwires.md` (sections 7.2, 7.3, 10 steps 9-10, 12 and the student's
answers of 2026-11-13); this file adds no new rule except the four points of section 9.

## 1. Question and what the answer may claim
Do the frozen tripwires (`v1:765b9cc1ae2371806444f41d7fa7aa17393f368af1a6e2ca3094abbc487549e5`) keep their development behaviour on bases they have never met: few false
alarms on clean runs, and `fired` (a named broken link) on the canaries of the chain classes?
Label of every number: **known shapes, fresh bases**. Held-out shapes: not measured (Mission 6.2). B09: not covered (no
tripwire). B06 obvious: the L1 rule, reported apart (it plants and detects the same thing). A pass shows that the
execution-level checks transfer to new experiments of the same template, not that they find unknown bugs (plan
section 7.3).

## 2. What is tested
The tripwire version `v1:765b9cc1ae2371806444f41d7fa7aa17393f368af1a6e2ca3094abbc487549e5` (`tripwires.source_version()`: `v1` plus the SHA-256 of `probe.py`, `replay.py` and
`tripwires.py`, LF). All ten checks and the verdict as built in sittings A to C, with the four sitting C defaults the
student kept on 2026-11-16 (K6 1e-12 rounding tolerance only; K3 as strict as built; a scored model never fitted by the
script is `fired` B04; the equal-predictions rule as built). Fail closed: `unverifiable` is a flag.

## 3. Frozen inputs (SHA-256 of the bytes with CRLF turned into LF, so the value equals the git blob on any checkout)
- `canary/probe.py` 305b5482d970e14b6f1e5fe3ec3956ee62956b1d9737a2615e0bd86fef0c50e8  (tripwire code (plan step 9))
- `canary/replay.py` 1638b1fcbb73d7589a3867b8e568234f2dbde144bddefa9a3eebb27230907fd7  (tripwire code (plan step 9))
- `canary/tripwires.py` c9f7ea30671c09ac0f1543ca166d6d186608056ce79dfc002ca84dbb29b7cb27  (tripwire code (plan step 9))
- `eval/tripwires_test.py` 26abf073f534690b3fc3da3f3dec449d0e97b261d613108f94cea48a8788c0e1  (the locked analysis and the bars (plan step 9))
- `eval/tripwires_dev.py` a8b0984e6428a87a3606b40901835f6b12e4874f0cdadaff1a043ccea539b092  (the scoring the analysis imports (`score`, `inspect_runs`, `base_bootstrap`); added to the plan's four)
- `canary/trust.py` 019bc8ee3fc2f3c81b9ec9f77615a6798a15e864a638e2a96082130103a2c77f  (Beta posteriors and `summarize` used by the scoring; added)
- `eval/ceiling.py` 894abf2de16dca53874f25f88e85a9463537ec8d69a15ed24cfc06bad9782085  (cluster rule and bootstrap weights; added (also frozen by the ceiling plan))
- `config/bug_classes.yaml` 8fa225ad871e43ad2430e7f7f3b152fcbae6cd955ca45d6af6e4024738cfe90f  (the class list the scoring iterates; added (also frozen by older plans))
- `data/calibration/pool-2.json` abd2aaba19fdd572a48fadb5c38d597acbd2cd5653a5f06d146cf7ac3a7c4b13  (the 17 bases the batch is built from; added (not tracked by git: hashed as on disk))

These stay frozen until both result files of section 6 exist. A change before the lock means new hashes in this
draft; a change after the lock is a new tripwire version, tested on a batch it has not seen (plan section 7.2).

## 4. Data
- **`tripwire-test-1` (primary, decides):** a fresh no-audit batch on pool 2 (`data/calibration/pool-2.json`, 17
  bases, none shared with pool 1), seed **1114** (no stored batch plan uses it: pilot and rq1-full 2404, task-dev-1
  1108, task-dev-2 1110, ceiling-ext 1111; 1112 was the repeat-pass sample seed). 360 runs, padded and with decoys like
  task-dev-2. Never reviewed by any LLM and never used to choose anything about one (student, 2026-11-13 and
  2026-11-15).
- **Dry plan, 2026-11-18** (`canary.cli length-check --dry --pool data/calibration/pool-2.json --runs 360 --seed
  1114`, and `mixer.plan_batch` on the same arguments): 200 canaries (10 per variant: every class 20, both tiers 10),
  80 controls, 80 shams; each of the 20 decoy variants on 8 clean runs; length gate PASSED ("line_count AUC 0.500,
  base 90% [0.50, 0.50]; char_count AUC 0.500, base 90% [0.50, 0.50]; statement_count AUC 0.500, base 90% [0.48,
  0.52]; helper_statements AUC 0.500, base 90% [0.45, 0.54]; helper_chars AUC 0.488, base 90% [0.44, 0.53]; largest
  blinded script 6162 characters"). B06 obvious fits 5 of the 17 bases, B06 subtle 13, every other variant 17.
- **Recall denominator (chain classes):** every canary except B09 (both tiers, 20) and B06 obvious (10): **170
  canaries** = B01-B05, B07, B08, B10 both tiers and B06 subtle, 10 per variant, 17 variants.
- **Specificity denominator:** all **160** clean runs (80 controls + 80 shams, each with a decoy).
- **`ceiling-ext` (secondary, decides nothing):** the 80 runs of the ceiling check, only after `eval.ceiling --arm L`
  (done 2026-11-14, `eval/results/ceiling/arm_L.json`). Reported with the same table so Mission 5.4 can compare
  tripwires, LLM and union on the same runs. Pool 2, so the same label.
- The script refuses a batch whose scored-run count is not 360 (primary) or 80 (secondary): a skipped slot needs an
  amendment, never a silently smaller test.

## 5. Scoring and the bars (`eval/tripwires_test.py`, frozen above; plan section 12 decision 6, approved 2026-11-13)
- Records: `tripwires.run_tripwires` on each run folder's path only (replay in a temporary copy), stored in
  `data/tripwires/test/<batch>/`; joined to the sealed table afterwards by `eval.tripwires_dev.score`. No audit, no
  ledger, no model.
- **Bar 1, specificity:** passes / 160, where a pass is verdict `pass` (a `fired` or `unverifiable` flag is a false
  alarm). Beta(1 + passes, 1 + false alarms), **90% interval, lower bound (5th percentile) >= 0.95**. Clears with at
  most 3 false alarms (0: 0.9816, 1: 0.9709, 2: 0.9614, 3: 0.9525, 4: 0.9441).
- **Bar 2, chain-class `fired` recall:** fired / 170 (a canary flagged only `unverifiable` is not fired). Beta(1 +
  fired, 1 + not fired), **90% lower bound >= 0.90**. Clears with at most 10 not fired (10: 0.9028, 11: 0.8958).
- A run without a record (no folder, crash of the inspection) counts against both bars.
- **Clustering:** base-level 90% intervals (one cluster per comparison, near-twins merged, the ceiling rule of
  2026-11-12; at most 17 clusters on pool 2) are printed beside both bars and **decide nothing**: the bars are the Beta
  bounds, as decision 6 words them. With all-pass counts a cluster bootstrap collapses to one value (plan section 7.1).
- Reported beside, deciding nothing: the full development table (per class, tier, impact, right class named, any flag,
  specificity by control, sham and decoy class, J, the gold-twin reference row, replays reproduced, no-op canaries,
  A1), with the B09 misses listed.
- **Outcome:** TEST PASSED if both bars are met on `tripwire-test-1`, else TEST FAILED. `ceiling-ext`: "reported
  only".

## 6. Procedure
Step 9 (after the student's OK of this draft; Fable or Opus):
1. `.venv\Scripts\python.exe -m eval.ceiling_lock --check` ends "Lock check: OK".
2. Remove "DRAFT, NOT LOCKED" from the title and the Status paragraph; recompute section 3 if any file changed.
3. Add `canary/probe.py`, `canary/replay.py`, `canary/tripwires.py`, `eval/tripwires_test.py`, `eval/tripwires_dev.py`
   to `.gitattributes` as `-text` (then `git add --renormalize .`, so git keeps storing LF; the LF hashes above do not
   change).
4. `.venv\Scripts\python.exe -m eval.tripwires_test --lock` writes `docs/plans/tripwire_test.md.sha256`; `.venv\Scripts\python.exe -m eval.tripwires_test
   --check` ends "Tripwire lock check: OK". Commit.

Step 10 (student's window; no Ollama, no cloud):
1. `.venv\Scripts\python.exe -m eval.ceiling_lock --check` and `.venv\Scripts\python.exe -m eval.tripwires_test --check`: both OK.
2. `.venv\Scripts\python.exe -m canary.cli calibrate --runs 360 --batch tripwire-test-1 --pool data/calibration/pool-2.json --seed 1114
   --no-audit` (after a stop: the same command with `--resume`). Must end with 360 runs done, 0 skipped, length gate
   PASSED.
3. `.venv\Scripts\python.exe -m eval.tripwires_test --batch tripwire-test-1`
4. `.venv\Scripts\python.exe -m eval.tripwires_test --batch ceiling-ext`
5. Both lock checks again; `.venv\Scripts\python.exe -m canary.cli ledger verify` OK.
Forecast (measured rates): the build about 55 to 90 minutes (ceiling-ext, pool 2: 1035 s for 80 slots, about 8.6 s
per script run; 560 script runs is about 80 minutes; pool 2's trial times give 84; task-dev-2's pool-1 rate gives 55);
replays about 10 to 20 minutes for 360 and 3 to 5 for 80 (step 8: 180 replays in 4 min 40 s with 4 workers; pool 2
has one base near 81 s). In all about 1.2 to 2 hours.

## 7. Stop rules and deviations
- Any hash of section 3, or the ceiling lock, that no longer matches: stop; nothing is scored.
- The batch build skips a slot, or its length gate fails: stop and report; scoring a smaller or leaky batch needs an
  amendment written before the first replay.
- A crash of `eval.tripwires_test` part way: run the same command again (stored records of the same version are
  reused); the result file is written once, at the end.
- Nobody looks at records of a test batch before the result file is written.

## 8. After the outcome
- PASSED or FAILED, `PROGRESS.md` reports both tables under "known shapes, fresh bases", with "held-out shapes: not
  measured (Mission 6.2)" and "B09: not covered". Mission 5.1 is ticked after step 10 (plan section 11).
- FAILED: every false alarm and every not-fired chain canary is explained; a fix is a new version tested on a new
  batch, never a re-run of this one.
- Then the ceiling files unfreeze, and step 11 (wiring, ledger role `tripwire_v1`) can start.

## 9. Points for the student before the lock (drafted as recommended)
1. **Frozen list:** the plan names four files; this draft adds `eval/tripwires_dev.py` (the scoring the test imports;
   without it the analysis could change after the lock), `canary/trust.py`, `eval/ceiling.py`,
   `config/bug_classes.yaml` and `pool-2.json`. Recommended: keep the additions.
2. **Bars on the Beta bounds, cluster intervals beside:** as decision 6 words it. Option: also require the base-level
   lower bounds; with 17 clusters and near-perfect counts they add little.
3. **Specificity pooled over controls and shams (160).** Per type is shown beside (80 each).
4. **Exact run count required** (360 / 80) rather than scoring whatever ran.
