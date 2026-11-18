# Pre-registration: Mission 5.1 tripwire test, `tripwire-test-1` (primary) and `ceiling-ext` (secondary) -- DRAFT, NOT LOCKED

Status: DRAFT written 2026-11-18 by Claude (Opus) for review, amended the same day with the student's six points
(line endings, the gitignored pool, the end of the freeze and the git tag, the exact batch, write-once, the answers in
section 9) and an own strict review. Not locked: there is no `.sha256`, `eval.tripwires_test --lock` refuses while
the title says DRAFT, and `eval.tripwires_test --batch ...` refuses while the plan is not locked. Hashes below were
computed 2026-11-18 after the amendment; they are recomputed if any listed file changes before the lock.
Design and decisions: `docs/plans/mission_5_1_tripwires.md` (sections 7.2, 7.3, 10 steps 9-10, 12 and the student's
answers of 2026-11-13); this file adds no new rule except the points of section 9 and the procedure of section 6.

## 1. Question and what the answer may claim
Do the frozen tripwires (`v1:765b9cc1ae2371806444f41d7fa7aa17393f368af1a6e2ca3094abbc487549e5`) keep their
development behaviour on bases they have never met: few false alarms on clean runs, and `fired` (a named broken link)
on the canaries of the chain classes?
Label of every number: **known shapes, fresh bases**. Held-out shapes: not measured (Mission 6.2). B09: not covered (no
tripwire). B06 obvious: the L1 rule, reported apart (it plants and detects the same thing). A pass shows that the
execution-level checks transfer to new experiments of the same template, not that they find unknown bugs (plan
section 7.3). **The bars use Beta bounds that treat the 170 canaries and the 160 clean runs as independent; they
ignore that runs share 17 bases (clustering).** The base-level cluster intervals printed beside them show how much
that matters; they decide nothing (section 9, answer b).

## 2. What is tested
The tripwire version `v1:765b9cc1ae2371806444f41d7fa7aa17393f368af1a6e2ca3094abbc487549e5`
(`tripwires.source_version()`: `v1` plus the SHA-256 of `probe.py`, `replay.py` and `tripwires.py`, LF). All ten
checks and the verdict as built in sittings A to C, with the four sitting C defaults the student kept on 2026-11-16
(K6 1e-12 rounding tolerance only; K3 as strict as built; a scored model never fitted by the script is `fired` B04; the
equal-predictions rule as built). Fail closed: `unverifiable` is a flag.

## 3. Frozen inputs (SHA-256 of the bytes with CRLF turned into LF; for a file in git this equals the git blob)
- `canary/probe.py` 305b5482d970e14b6f1e5fe3ec3956ee62956b1d9737a2615e0bd86fef0c50e8  (tripwire code (plan step 9))
- `canary/replay.py` 1638b1fcbb73d7589a3867b8e568234f2dbde144bddefa9a3eebb27230907fd7  (tripwire code (plan step 9))
- `canary/tripwires.py` c9f7ea30671c09ac0f1543ca166d6d186608056ce79dfc002ca84dbb29b7cb27  (tripwire code (plan step 9))
- `eval/tripwires_test.py` 6e83ae7ca398e54462a24d0953000d571f3f23116fbeb0853696fe72480cd9ab  (the locked analysis, the bars and the slot-list lock (plan step 9))
- `eval/tripwires_dev.py` a8b0984e6428a87a3606b40901835f6b12e4874f0cdadaff1a043ccea539b092  (the scoring the analysis imports (`score`, `inspect_runs`, `base_bootstrap`); added)
- `canary/trust.py` 019bc8ee3fc2f3c81b9ec9f77615a6798a15e864a638e2a96082130103a2c77f  (Beta posteriors and `summarize` used by the scoring; added)
- `eval/ceiling.py` 894abf2de16dca53874f25f88e85a9463537ec8d69a15ed24cfc06bad9782085  (cluster rule and bootstrap weights; added (also frozen by the ceiling plan))
- `config/bug_classes.yaml` 8fa225ad871e43ad2430e7f7f3b152fcbae6cd955ca45d6af6e4024738cfe90f  (the class list the scoring iterates; added (also frozen by older plans))
- `data/calibration/pool-2.json` abd2aaba19fdd572a48fadb5c38d597acbd2cd5653a5f06d146cf7ac3a7c4b13  (the 17 bases the batch is built from; added; NOT in git, see below)

**Git and line endings of each frozen file (checked 2026-11-18; `eval.tripwires_test --git-check` prints this):**

| File | In git | `-text` in `.gitattributes` now | Step 9 |
|---|---|---|---|
| `canary/probe.py` | yes | no | add `-text` |
| `canary/replay.py` | yes | no | add `-text` |
| `canary/tripwires.py` | yes | no | add `-text` |
| `eval/tripwires_test.py` | yes | no | add `-text` |
| `eval/tripwires_dev.py` | yes | no | add `-text` |
| `canary/trust.py` | yes | no | add `-text` |
| `eval/ceiling.py` | yes | yes (ceiling plan, 2026-11-12) | none |
| `config/bug_classes.yaml` | yes | yes (confirmation plan, 2026-11-08) | none |
| `data/calibration/pool-2.json` | **no: `data/` is gitignored** (`.gitignore` line 11) | not applicable | none; backed up in step 10 |
| this plan, `docs/plans/tripwire_test.md` (+ `.sha256`) | yes | yes (`docs/plans/*.md`, `*.sha256`) | none |

Why this matters (2026-11-09, reproducibility broke once): the machine's git has `core.autocrlf=true`, so a file
without `-text` is checked out with CRLF while git stores LF. On 2026-11-18 the working copies of `canary/probe.py`
and `canary/replay.py` were CRLF while their blobs are LF (they differ in nothing else). The hashes above are of the
LF bytes, which equal the git blobs; step 9 makes every working copy byte-identical to its blob before the lock.

**`pool-2.json` is outside git.** Its only copies are this disk and the step 10 backup. Its bytes on disk use CRLF:
the hash above (LF form, `abd2aaba...`) and the ceiling plan's hash of the raw bytes
(`5d5b2c8e580c033cd90f0095d61f96dcc8acc6d84ef049bbda0437301d60fc66`, checked by `eval.ceiling_lock --check`) describe
the same file. Both must match before step 10; restoring it from the backup gives both again.

**Also fixing the batch, not listed above but held by other locks:** `canary/mixer.py` (plans the slots; frozen by the
ceiling plan) and everything that builds the runs (`canary/controls.py`, `canary/saboteur/`, `canary/padding.py`,
`canary/sandbox.py`). The slot-list lock of section 4 catches any change in the planning; the git tag of step 9 and
the `git diff` of step 10 catch any change in the building code between the lock and the build.

**End of the freeze.** These files stay frozen until step 10 has written both result files
(`eval/results/tripwires/test_tripwire-test-1.json` and `test_ceiling-ext.json`) and they are committed; then they
unfreeze, as in the ceiling plan. A change before the lock means new hashes in this draft; a change after the lock and
before the results is a new tripwire version, tested on a batch it has not seen (plan section 7.2). Reproducing the
result later uses the git tag `tripwire-test-1-lock` (made at the lock commit, step 9), the backup of `data/` (step
10) and this plan's hashes: in a clone checked out at the tag, with `data/` restored from the backup and no result
file present, `--check` must say OK and `--batch` makes fresh records that must give the same tables (the replays are
deterministic; step 8 replayed 40 runs afresh with 0 differences). **Mission 4.1 sitting 1 changes `canary/trust.py`, so it starts only after step 10.**

## 4. Data
- **`tripwire-test-1` (primary, decides):** a fresh no-audit batch on pool 2 (`data/calibration/pool-2.json`, 17
  bases, none shared with pool 1), seed **1114** (no stored batch plan uses it: pilot and rq1-full 2404, task-dev-1
  1108, task-dev-2 1110, ceiling-ext 1111; 1112 was the repeat-pass sample seed). 360 runs, padded and with decoys like
  task-dev-2.
- **Rule: no LLM ever audits `tripwire-test-1`** (student, 2026-11-13 and 2026-11-15): it is built with `--no-audit`,
  never given to `reaudit`, `rescore`, `audit` or a `calibrate` without `--no-audit`, and never used to choose anything
  about a reviewer. The stored batch plan carries `"no_audit": true`, so `calibrate --resume` refuses to audit it, and
  `eval.tripwires_test` refuses a primary batch planned with audits. If an audit of it ever happens, it is written in
  `PROGRESS.md` as a deviation; the tripwire result is unaffected (the tripwires never read an audit).
- **Role in the stored plan:** `skeptic_a`, the default of `calibrate --role`, since step 10 gives no `--role`. It is
  used for one thing only: the length gate reads that role's context size from `config/models.yaml` to check that
  every blinded prompt would fit. No model is loaded or called (`llm.LLM()` opens no Ollama client until a call).
  `skeptic_a` has the global 8192 tokens, about 24,000 characters by the cautious 3 characters per token; pool-2
  prompts are far below that (ceiling-ext's largest 8445 characters; task-dev-2 passed under a 4096-token role).
  (ceiling-ext's stored plan carries `skeptic_d`.)
- **Dry plan, 2026-11-18** (`canary.cli length-check --dry --pool data/calibration/pool-2.json --runs 360 --seed
  1114`, and `mixer.plan_batch` on the same arguments): 200 canaries (10 per variant: every class 20, both tiers 10),
  80 controls, 80 shams; each of the 20 decoy variants on 8 clean runs; length gate PASSED ("line_count AUC 0.500,
  base 90% [0.50, 0.50]; char_count AUC 0.500, base 90% [0.50, 0.50]; statement_count AUC 0.500, base 90% [0.48,
  0.52]; helper_statements AUC 0.500, base 90% [0.45, 0.54]; helper_chars AUC 0.488, base 90% [0.44, 0.53]; largest
  blinded script 6162 characters"). B06 obvious fits 5 of the 17 bases, B06 subtle 13, every other variant 17.
- **Slot-list lock (exact batch).** SHA-256 of the canonical JSON (sorted keys, no spaces) of the batch plan's
  `seed, runs, split, length_match, decoys, length_target, bases, slots` (`eval.tripwires_test.slots_sha256`; the batch
  name, role, pool file name and no-audit flag are left out). `--check` recomputes the primary's dry plan and compares;
  once a batch is built, `--check` and `--batch` compare its stored plan (`data/sealed_plans/<batch>.json`) and refuse
  on any difference. Check of the method: `mixer.plan_batch("ceiling-ext", 80, pool 2, 1111)` today gives exactly the
  hash of ceiling-ext's plan stored on 2026-11-12, and the batch name and role do not change the hash.
- Slot list `tripwire-test-1` cf3481120cd536f2c55cd966d00df836344393037e8ffca101533ced20d0125b  (dry plan: pool 2, seed 1114, 360 runs)
- Slot list `ceiling-ext` 39ffcae8c7ff7003800635ec1913fc7648abaf76dca01059a6ee82861f787542  (its stored plan, 2026-11-12)
- **Every planned slot is scored; none is dropped.** For each of the 360 slots: its sealed run (if a crash left an
  earlier sealed run of the slot behind, the latest one, which is the one `--resume` completed; each earlier one is
  listed in `superseded_runs` with its slot, sealed time, its own status and reason, the run that replaced it and why),
  or, if the slot has no sealed run (no base fitted, or the build failed), a stand-in
  with no record (`not_built_slots`). A run that crashed in the sandbox is inspected like any other: with no
  `results.json` its checks are `unverifiable` (checked 2026-11-18 on a copy), so it is a flag. Therefore a slot that
  fails to build or crashes counts against both bars: a chain canary as not fired, a clean run as a false alarm (B09
  and B06 obvious slots touch no bar). A sealed run whose slot is not in the plan, or whose type differs from its
  slot's, stops the test.
- **Recall denominator (chain classes):** every canary except B09 (both tiers, 20) and B06 obvious (10): **170
  canaries** = B01-B05, B07, B08, B10 both tiers and B06 subtle, 10 per variant, 17 variants.
- **Specificity denominator:** all **160** clean runs (80 controls + 80 shams, each with a decoy).
- **`ceiling-ext` (secondary, decides nothing):** the 80 runs of the ceiling check, only after `eval.ceiling --arm L`
  (done 2026-11-14, `eval/results/ceiling/arm_L.json`). Reported with the same table so Mission 5.4 can compare
  tripwires, LLM and union on the same runs. Pool 2, so the same label. It was reviewed by `skeptic_d` by design.

## 5. Scoring and the bars (`eval/tripwires_test.py`, frozen above; plan section 12 decision 6, approved 2026-11-13)
- Records: `tripwires.run_tripwires` on each run folder's path only (replay in a temporary copy), stored in
  `data/tripwires/test/<batch>/`; joined to the sealed table afterwards by `eval.tripwires_dev.score`. No audit, no
  ledger, no model.
- **Bar 1, specificity:** passes / 160, pooled over controls and shams, where a pass is verdict `pass` (a `fired` or
  `unverifiable` flag is a false alarm). Beta(1 + passes, 1 + false alarms), **90% interval, lower bound (5th
  percentile) >= 0.95**. Clears with at most 3 false alarms (0: 0.9816, 1: 0.9709, 2: 0.9614, 3: 0.9525, 4: 0.9441).
  Controls (80) and shams (80) are also printed apart, beside the bar, deciding nothing.
- **Bar 2, chain-class `fired` recall:** fired / 170 (a canary flagged only `unverifiable` is not fired). Beta(1 +
  fired, 1 + not fired), **90% lower bound >= 0.90**. Clears with at most 10 not fired (10: 0.9028, 11: 0.8958).
- A slot without a record (not built, no folder, a crash of the inspection) counts against both bars.
- **Clustering:** base-level 90% intervals (one cluster per comparison, near-twins merged, the ceiling rule of
  2026-11-12; at most 17 clusters on pool 2) are printed beside both bars and **decide nothing**: the bars are the Beta
  bounds, as decision 6 words them, and they ignore clustering (section 1). With all-pass counts a cluster bootstrap
  collapses to one value (plan section 7.1). A stand-in slot is put in the cluster of its first candidate base.
- Reported beside, deciding nothing: the full development table (per class, tier, impact, right class named, any flag,
  specificity by control, sham and decoy class, J, the gold-twin reference row, replays reproduced, no-op canaries,
  A1), with the B09 misses listed.
- **Outcome:** TEST PASSED if both bars are met on `tripwire-test-1`, else TEST FAILED. `ceiling-ext`: "reported
  only".
- **Write-once:** `eval.tripwires_test --batch <b>` refuses when `eval/results/tripwires/test_<b>.json` exists, for
  both batches (tests `test_the_run_once_writes_the_result_and_refuses_a_second[tripwire-test-1]` and
  `[ceiling-ext]`: the second call is refused and the file is unchanged). The result file is committed right after
  step 10, so deleting it to run again would show in git.

## 6. Procedure
Step 9 (after the student's OK of this draft; Opus or Fable; PowerShell in the project folder):
1. `.venv\Scripts\python.exe -m eval.ceiling_lock --check` ends "Lock check: OK".
2. `.venv\Scripts\python.exe -m eval.tripwires_test --check` ends "Tripwire lock check: hashes OK, plan NOT LOCKED
   (draft)".
3. `git status --porcelain --untracked-files=no` prints nothing (no tracked file changed).
4. Append to `.gitattributes`, with LF, under a comment naming this plan: `canary/probe.py -text`,
   `canary/replay.py -text`, `canary/tripwires.py -text`, `canary/trust.py -text`, `eval/tripwires_test.py -text`,
   `eval/tripwires_dev.py -text`.
5. `.venv\Scripts\python.exe -m eval.tripwires_test --sync-lf`: every frozen file in git whose working copy differs
   from `git show HEAD:<path>` only in line endings is rewritten with the blob's bytes (on 2026-11-18 that would be
   `canary/probe.py` and `canary/replay.py`); it refuses, writing nothing, if any file differs in content. This comes
   BEFORE anything is staged.
6. `git add --renormalize .`
7. `git diff --cached --stat` shows only `.gitattributes`, and `git diff --cached --name-only` prints only
   `.gitattributes`. Anything else: stop, `git reset`, find out why.
8. `.venv\Scripts\python.exe -m eval.tripwires_test --git-check` ends "Line endings: OK": for each of the 8 frozen files
   in git, `-text yes`, `working copy = HEAD blob yes`, `listed hash = SHA-256 of HEAD blob yes`; `pool-2.json`
   "outside git".
9. `git commit -m "Mission 5.1 step 9: .gitattributes -text for the tripwire test's frozen files"`
10. Edit this plan: remove "-- DRAFT, NOT LOCKED" from the title, rewrite the Status paragraph with the date of the
    student's OK (LF, `newline="\n"`). Recompute section 3 only if a file changed (then stop and show the student).
11. `.venv\Scripts\python.exe -m eval.tripwires_test --lock` writes `docs/plans/tripwire_test.md.sha256`;
    `.venv\Scripts\python.exe -m eval.tripwires_test --check` ends "Tripwire lock check: OK";
    `.venv\Scripts\python.exe -m eval.ceiling_lock --check` ends "Lock check: OK".
12. `git add docs/plans/tripwire_test.md docs/plans/tripwire_test.md.sha256` and
    `git commit -m "Mission 5.1 step 9: tripwire test plan locked"`; then `--git-check` again ends "Line endings: OK".
13. `git tag tripwire-test-1-lock` (on the lock commit). The student pushes it: `git push origin tripwire-test-1-lock`.

Step 10 (student's window; no Ollama, no cloud; PowerShell in the project folder):
1. `git diff --stat tripwire-test-1-lock -- canary eval config` and `git status --porcelain --untracked-files=no -- canary eval config`
   both print nothing (the code that builds and scores is the code at the lock).
2. `.venv\Scripts\python.exe -m eval.ceiling_lock --check` ("Lock check: OK"),
   `.venv\Scripts\python.exe -m eval.tripwires_test --check` ("Tripwire lock check: OK"; this also re-plans the batch
   and compares the slot-list hash) and `.venv\Scripts\python.exe -m eval.tripwires_test --git-check` ("Line endings:
   OK").
3. Build: `.venv\Scripts\python.exe -m canary.cli calibrate --runs 360 --batch tripwire-test-1 --pool data/calibration/pool-2.json --seed 1114 --no-audit`
   It ends "Batch tripwire-test-1: ... runs done, ... skipped, nothing audited." and "Length gate PASSED: ...".
   **If it stops part way** (crash, window closed, power): run exactly
   `.venv\Scripts\python.exe -m canary.cli calibrate --batch tripwire-test-1 --resume --no-audit`
   as often as needed (finished slots are skipped). **Never run `--runs` again under this batch name** (it is refused,
   "already exists") and never build under another name. A skipped slot is not a reason to rebuild: it counts against.
4. `.venv\Scripts\python.exe -m eval.tripwires_test --check` again: "Tripwire lock check: OK" now also means the
   stored plan of `tripwire-test-1` gives the locked slot-list hash.
5. Back up `data/` (pool 2 and the batch exist nowhere else):
   `New-Item -ItemType Directory -Force "$HOME\canary-backups" | Out-Null`
   `Compress-Archive -Path data -DestinationPath "$HOME\canary-backups\data-2026-11-18-tripwire-test.zip"`
   (about 50 MB before the batch; the date in the name is this plan's, whatever the day of the build;
   `Compress-Archive` refuses to overwrite an existing zip, which is intended).
6. `.venv\Scripts\python.exe -m eval.tripwires_test --batch tripwire-test-1`
7. `.venv\Scripts\python.exe -m eval.tripwires_test --batch ceiling-ext`
8. `.venv\Scripts\python.exe -m eval.ceiling_lock --check`, `.venv\Scripts\python.exe -m eval.tripwires_test --check`
   and `.venv\Scripts\python.exe -m canary.cli ledger verify`: all OK.
9. Commit `eval/results/tripwires/test_tripwire-test-1.json` and `test_ceiling-ext.json` (next session); then the
   freeze ends (section 3).
Forecast (measured rates): the build about 55 to 90 minutes (ceiling-ext, pool 2: 1035 s for 80 slots, about 8.6 s
per script run; 560 script runs is about 80 minutes; pool 2's trial times give 84; task-dev-2's pool-1 rate gives 55);
replays about 10 to 20 minutes for 360 and 3 to 5 for 80 (step 8: 180 replays in 4 min 40 s with 4 workers; pool 2
has one base near 81 s). In all about 1.2 to 2 hours.

## 7. Stop rules and deviations
- Any hash of section 3, the slot-list lock, the line-ending check or the ceiling lock that no longer matches, or a
  non-empty `git diff` of step 10.1: stop; nothing is built or scored.
- The length gate of the built batch fails: stop and report; scoring a leaky batch needs an amendment written before
  the first replay. (A skipped or crashed slot is not a stop: it counts against, section 4.)
- A crash of `eval.tripwires_test` part way: run the same command again (stored records of the same version are
  reused); the result file is written once, at the end.
- Nobody looks at records of a test batch before the result file is written.

## 8. After the outcome
- PASSED or FAILED, `PROGRESS.md` reports both tables under "known shapes, fresh bases", with "held-out shapes: not
  measured (Mission 6.2)", "B09: not covered" and "the bars ignore clustering; cluster intervals beside". Mission 5.1
  is ticked after step 10 (plan section 11).
- FAILED: every false alarm and every not-fired chain canary is explained; a fix is a new version tested on a new
  batch, never a re-run of this one.
- Then the frozen files unfreeze (section 3), step 11 (wiring, ledger role `tripwire_v1`) can start, and Mission 4.1
  sitting 1 may change `canary/trust.py`.

## 9. The student's answers (2026-11-18), recorded before the lock
- (a) **Frozen list:** the plan names four files; the five additions `eval/tripwires_dev.py`, `canary/trust.py`,
  `eval/ceiling.py`, `config/bug_classes.yaml` and `pool-2.json`: **yes**.
- (b) **Bars on the Beta 90% lower bounds; base-level cluster bounds printed beside them, deciding nothing: yes**, and
  the claim states that the Beta bound ignores clustering (section 1, section 5, section 8).
- (c) **Specificity pooled over controls and shams (160): yes**, also printed per type (80 each), deciding nothing.
- (d) **Exactly 360 / 80 runs: yes, as made precise in point 4:** the batch is the locked slot list (section 4); every
  slot is scored, and a slot that fails to build or crashes counts against both bars, never dropped.
- **Three more answers (2026-11-18, with the OK to lock):**
  1. **End of the freeze: yes**, it ends when both result files (`test_tripwire-test-1.json` and
     `test_ceiling-ext.json`) exist and are committed (section 3).
  2. **The latest sealed run of a slot counts: yes**, and every earlier one is listed with its reason, provided nothing
     in the build re-runs a slot because of its outcome. Checked in the code on 2026-11-18: `calibrate --resume` runs
     only the slots that `mixer.finished_slots` does not return, i.e. slots with no ledger `RAN` entry, and
     `scientist.record_ran` writes that entry for every run whatever its status (ok, crash or timeout). So a slot is
     rebuilt only if it never started, was interrupted between sealing and its ledger entry, or was skipped (no base
     fitted; then it is tried again with the same seeded candidates and gives the same skip). No outcome triggers a
     rebuild. `eval/tripwires_test.py` lists each superseded run with its slot, sealed time, status, reason, the run
     that replaced it and why (section 4).
  3. **Backup name: yes**, `data-2026-11-18-tripwire-test.zip` whatever day the build runs (step 10.5).
- Nothing open: the student gave the OK to lock on 2026-11-18.
