# Pre-registration v2: llama-checklist confirmation with decoy padding

**Status: DRAFT, not locked.** Written 2026-11-09, before `task-dev-2`, pool-2 or `confirm-llama-2` exist. It
supersedes `llama_checklist_confirmation.md` (v1, never run; the reason is in its notice). Two steps happen before the
confirmation batch, in this order:
1. **Development batch `task-dev-2`** (section 5): chooses a new cut-off. Its rules are fixed by this draft and by the
   code in the commit that adds this file (`eval/cutoff.py`).
2. **Re-lock** (section 6): the cut-off file's SHA-256 and the frozen code hashes are written into section 4, the
   status line becomes LOCKED, and this file's SHA-256 goes into `llama_checklist_confirmation_v2.md.sha256`.
   `eval/confirm.py` refuses to run until both hashes match. No pool-2 data may exist before this commit.

## 1. Question
Does llama3.1:8b's checklist score, P(flag), rank buggy runs above clean ones on new bases, once no trivial feature
(script size, the padding helper's size, effect spread) can give the run type away?

## 2. Why v2
v1's length matching padded every script to one length with a never-used helper. But a bug's lines took the place of
helper lines, so canaries had smaller helpers: helper-size AUC 0.15 on the pool-1 dry plan, i.e. 0.85 with direction
ignored. With that cue, v1's amended H3 had power about 0, and its cut-off (chosen on length-confounded task-dev-1)
flagged most padded clean runs.

## 3. Design: decoy padding
- **Decoys** (`canary/saboteur/decoys.py`): each clean run (control or sham) gets one bug variant as its decoy, cycling
  through all 20 variants in a seeded order (`mixer.decoy_assignment`), so decoys come in the canaries' proportions
  (100-run batch: 3 canaries and 2 decoys per variant; 40-run batch: 1 and 1). A decoy is the same edit as its bug, in
  the same place, with the same number of lines and statements, the same added helper or import, and about the same
  characters, written so it changes no number. Clean slots with a decoy only take bases its bug applies to.
- **Then the usual padding** (`canary/padding.py`) brings every script to one line and character count.
- **Shams** now choose renames that change the script's length least (`controls.make_sham`): random renames made shams
  about 170 characters longer, which left them a smaller helper.
- **Harmless, tested:** on synthetic data, every decoy gives exactly the clean script's numbers on 3 settings (decision
  tree / balanced accuracy, logistic regression / f1, SVM / roc_auc), and its bug class's oracle stays silent
  (`tests/test_decoys.py`, slow). A one-off check on real data (breast_cancer, wine (3 classes), diabetes; 47 decoy
  runs in the sandbox) also gave the clean numbers every time.
- **Length gate**, now on five features: blinded line count, character count and statement count, and the helper's
  size in statements and in characters. Each needs a base-level 90% AUC interval containing 0.5, on the dry plan and
  again on the real run folders before any audit.

**Dry proof on pool 1** (`python -m eval.padding_proof`, `eval/results/padding_v2/dry_proof.json`): with decoys, every
feature's interval contains 0.5 on the task-dev-2 plan (40 runs, seed 1110) and on a 100-run plan (seed 1109). Without
decoys, helper size is 0.150 on both. Effect spread, which no padding can change, is 0.521, base 90% [0.469, 0.567], on
the 220 existing pool-1 runs (rq1-full and task-dev-1).

## 4. Frozen inputs (filled in at the re-lock)
- Role `skeptic_c_checklist`: model `llama3.1:8b` (Ollama ID `46e0c10c039e`), `num_ctx` 4096, temperature 0, task
  `checklist`; score = the highest per-class P(yes), renormalised over the two allowed words, stored with each audit.
- Code and config SHA-256 (as stored in git, LF): to be filled in at the re-lock for `canary/saboteur/decoys.py`,
  `canary/controls.py`, `canary/padding.py`, `canary/mixer.py`, `canary/separation.py`, `canary/review_tasks.py`,
  `eval/confirm.py`, `eval/compare_tasks.py`, `eval/cutoff.py`, `config/models.yaml`, `config/bug_classes.yaml`.
- Cut-off file `eval/results/task_dev_2/llama_checklist_cutoff.json`: SHA-256 to be filled in at the re-lock, as a
  line of the form "Cut-off file SHA-256: `<64 hex>`" (`eval/confirm.py` reads it).

## 5. Step 1: development batch `task-dev-2` (pool 1)
- 40 runs on pool 1 (`data/calibration/pool.json`), plan seed 1110: 20 canaries (one per class and tier), 10 controls
  and 10 shams, each clean run with a decoy (one per variant), all padded. Reviewer `skeptic_c_checklist`.
- Length gate on the dry plan and on the run folders, as in section 3. If it fails: stop, report, audit nothing.
- **Cut-off rule** (`python -m eval.cutoff --batch task-dev-2`, written once, never overwritten): on the score stored
  with the first audit of each of the 40 runs, the cut-off with the highest Youden's J, the lowest on a tie. Any run
  without a score: fill it with `rescore --batch task-dev-2 --reviewer skeptic_c --fresh` first.
- Reported, deciding nothing: AUC of P(flag) with its base-level interval, each trivial feature's AUC, and recall and
  false alarms at the chosen cut-off. These are development numbers: the batch that chose the cut-off cannot confirm it.
- **Stop rule:** if the chosen cut-off's J is 0 or below, stop and report before the re-lock. H1 could then not pass,
  and the student decides whether the confirmation should run on H2 and H3 alone.

## 6. Step 2: re-lock
Fill in section 4, run `python -m eval.confirm_power` (H1's grid needs the new cut-off), copy its H1 numbers into
section 9, set the status to LOCKED, write this file's SHA-256 to its `.sha256` file, run `pytest`, and commit. Only
then step 3.

## 7. Step 3: confirmation batch `confirm-llama-2` (pool 2)
- New pool: `build-pool --out data/calibration/pool-2.json --avoid data/calibration/pool.json` (same grid as pool 1; no
  pool-1 base may come back; the pool is written once). If the Scientist cannot fill the grid well enough to plan the
  batch (MixerError), stop and report.
- 100 runs: 60 canaries (3 per class and tier), 20 controls and 20 shams, plan seed 1109, decoys and padding as above.
- Length gate on the dry plan and on the run folders; on failure stop and audit nothing.

## 8. Hypotheses and decision
All intervals are 90%, resampling whole bases (2000 draws, seed 0), on the first llama-checklist audit of each run.
- **H1:** J at the locked task-dev-2 cut-off. Passes if the lower bound is above 0.
- **H2:** AUC of P(flag). Passes if the lower bound is above 0.5.
- **H3:** AUC of P(flag) minus the AUC of the strongest trivial feature on the same runs: blinded line count,
  character count, statement count, helper statements, helper characters and effect spread, each counted as
  max(AUC, 1 - AUC), the strongest picked again in every draw. Passes if the lower bound is above 0.

**Confirmed = (H1 or H2) and H3.** Anything else is "not confirmed". No second cut-off, no other reviewer, no re-run
after seeing results. Consequences written before the data: "H1 or H2" gives two chances (false-positive rate up to
about 10%); with decoys, the size features sit at about 0.5, so H3 in practice asks llama to beat effect spread (0.521
on existing pool-1 runs).

## 9. Power (planning numbers, `eval/results/confirm_llama_2/power.json`)
Normal approximations, design effect 1.27 for clustering by base (from task-dev-1). At true llama AUC 0.60, 0.65,
0.70, 0.75: P(H2 passes) 0.46, 0.78, 0.96, 1.00; P(H3 passes) 0.22, 0.41, 0.65, 0.85 (strongest feature effect spread
at 0.521; the two AUCs treated as independent, which ignores their pairing). H1: filled in at the re-lock.

## 10. Procedure (run by the student, own PowerShell window, Edge closed)
Step 1 (development):
1. `python -m eval.padding_proof` (must print "Overall: PASS")
2. `canary.cli length-check --dry --pool data/calibration/pool.json --runs 40 --seed 1110` (stop if FAILED)
3. `canary.cli calibrate --runs 40 --batch task-dev-2 --pool data/calibration/pool.json --role skeptic_c_checklist
   --seed 1110` (`--resume` after any stop; stops itself if the length gate fails)
4. `python -m eval.cutoff --batch task-dev-2`

Step 2: re-lock (Claude, then the student's OK). Step 3 (confirmation):
5. `canary.cli build-pool --out data/calibration/pool-2.json --avoid data/calibration/pool.json`
6. `canary.cli length-check --dry --pool data/calibration/pool-2.json --runs 100 --seed 1109`
7. `canary.cli calibrate --runs 100 --batch confirm-llama-2 --pool data/calibration/pool-2.json --role
   skeptic_c_checklist --seed 1109`
8. `canary.cli rescore --batch confirm-llama-2 --reviewer skeptic_c` (repeatability, diagnostic only)
9. `python -m eval.confirm --batch confirm-llama-2`

## 11. Reported, deciding nothing
Each H3 feature's own AUC; effect size and best arm's score; the code's checklist decision J (posterior, as in RQ1);
specificity on controls and shams separately, and on clean runs by decoy class (do some decoys draw flags?);
repeatability (replies matched on a second call, verdict changes).

## 12. Limits, written before the data
- **Decoys are hard controls.** They look like real but redundant code (a refit, an identity re-index, a search whose
  result is unused). A reviewer may flag them, which lowers measured specificity. Real runs carry neither decoys nor
  padding, so before Mission 4.1 applies these numbers to real findings, real runs need the same treatment.
- **The best arm's score separates** (0.591, base 90% [0.541, 0.650], on existing pool-1 runs): several bugs really
  inflate scores. That is the bug's footprint in the results, which a reviewer may legitimately notice, and no padding
  can remove it. Reported, not in H3.
- The cut-off comes from 40 runs on pool-1 bases that earlier batches also used; it may be noisy. H2 needs no cut-off.
- One model, temperature 0, one new pool. llama is not fully repeatable at temperature 0 (PROGRESS.md, Known issues).
- Dry checks use each slot's first base; a real fallback base (B09 subtle) is checked by the gate on the run folders.
