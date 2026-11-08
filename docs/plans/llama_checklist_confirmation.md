# Pre-registration: llama-checklist confirmation on a new, length-matched pool

Written 2026-11-08, before pool-2 or the confirmation batch exists. Approved by the student with changes A-E (below).
This file is hashed; its SHA-256 is in `llama_checklist_confirmation.md.sha256`, and `eval/confirm.py` refuses to run
if either this file or the cut-off file has changed. Any amendment must be a new commit made before the batch runs,
with a new hash, and the reason written in PROGRESS.md.

## 1. Question
Does llama3.1:8b's checklist score, P(flag), rank buggy runs above clean ones on new bases once script length can no
longer give the run type away?

Why it is open: on task-dev-1 (40 runs, 17 bases) llama-checklist's fresh AUC was 0.735, base 90% [0.58, 0.86]
(`eval/results/task_dev_1/compare_tasks.json`). But blinded line count alone scored AUC 0.850 there: every clean run had
84 lines and most canaries more. llama's score rose with length within buggy runs (rho +0.46). So that AUC may be
partly a length effect. No review cell passed the screen's fixed rule, and none of that changes here.

## 2. Frozen inputs
- Role `skeptic_c_checklist`: model `llama3.1:8b` (Ollama ID `46e0c10c039e`), `num_ctx` 4096, temperature 0, task
  `checklist`; score = the highest per-class P(yes), renormalised over the two allowed words.
- Code and config at these SHA-256 values (any change before the batch must amend this plan):
  - `canary/review_tasks.py` 94e7ee7716ff7955413cbc8fc596359032cad4601faf13d8d53da8bdbc89739d
  - `canary/padding.py` b1e423ad36ae878ec15348b592434fcbd05301eeb7124f1f4dc1e0ffc9e1e9c3
  - `canary/separation.py` 518559d8de065304eb183c9c2cd9c05cc60eaf50b83c60330d99f7c114ff3f47
  - `canary/mixer.py` 04f940671fd89f9fcd025c5d09a2ca49768049525c27d11d6f514c8b9c940990
  - `eval/confirm.py` f666e64f9301e51d629b8b0b2e873385df89934ef81af7bebeb7eb8a46a28181
  - `eval/compare_tasks.py` 82a30815d3efcee54bc9aab0f9e457ee0845def8b7ecb7358847cc976e2d3fd8
  - `config/models.yaml` 9add8255ea52d41fffb731c04660a8705c831dbe698bbfc54f6bddc6bb377d89
  - `config/bug_classes.yaml` fc5ebda7f0e7eb539587749803d2813984927179ae18c6ca9d00ecad3fa02a43

## 3. The cut-off (change B)
Chosen by `eval/cutoff.py` on the fresh scores of all 40 task-dev-1 runs: the cut-off with the highest Youden's J,
the lowest on a tie. Flag a run when P(flag) >= cut-off.

Cut-off file SHA-256: `1a1c0c88d31da9a8df4d2ae1cfa3758b790e47894f305c811f5b403837aad0d0`

(`eval/results/task_dev_1/llama_checklist_cutoff.json`: cut-off 0.38452, J +0.40, recall 0.85, false alarms 0.45.)
**Caveat:** it was chosen on length-confounded data, so it may not transfer to a length-matched batch. That is why H2
(no cut-off) is co-primary.

## 4. Length matching (change A, mandatory)
Every run of the batch, whatever its type, gets one helper (`describe_settings`) that copies settings out of CONFIG and
is never used, sized so that every blinded script has the same line count and the same character count (one target
for the batch, from its pool's bases). `canary/padding.py` has the design; a padded run gives exactly the same numbers
(slow test). The target and the helper's statements are chosen without the run type.

**Length gate, two checks, both must pass before any llama audit.** Rule: for blinded line count and for character
count, the base-level 90% AUC interval contains 0.5.
1. Dry check, before anything runs: `length-check --dry` on the plan built from pool-2. If it fails: stop, report.
2. Real check, after the experiments run and before any audit: `calibrate` runs it automatically on the run folders,
   writes `data/sealed_plans/confirm-llama-1.length_check.json`, and stops without auditing if it fails. It also
   fails if any checklist prompt would exceed llama's context limit. If it fails: stop, report, audit nothing.

Diagnostic, not gating: the helper's own size differs by type by design (a canary's bug lines take the place of helper
lines; AUC 0.15 on a pool-1 dry run). A reviewer would have to react to how much settings-copying code a script has.
It is reported in the gate and in the results.

## 5. New pool (change E)
`build-pool --out data/calibration/pool-2.json --avoid data/calibration/pool.json`: fresh Scientist proposals over the
same fixed dataset x metric x model grid as pool 1 (`campaign.yaml` `grid_rounds: 2`, 18 foci). No pool-1 base may come
back: same experiment ignoring wording and seeds counts as the same base. The Scientist is shown the pool-1 hypotheses
on the same dataset, and the code refuses duplicates and refuses to write a pool that shares any base. A focus that
gives no acceptable proposal is dropped and logged. The pool is written once.

## 6. Batch
`confirm-llama-1`, 100 runs: 60 canaries (3 per class and tier), 20 controls, 20 shams, plan seed 1109. 100 is in the
approved 80-100 range; 90 is not possible because canaries come in whole rounds of the 20 variants.

## 7. Hypotheses and decision (change D)
All intervals are 90%, resampling whole bases (2000 draws, seed 0), on the first llama-checklist audit of each run,
using the score stored with that audit.
- **H1:** J at the locked cut-off. Passes if the lower bound is above 0.
- **H2:** AUC of P(flag). Passes if the lower bound is above 0.5.
- **H3:** AUC of P(flag) minus AUC of blinded line count, on the same runs. Passes if the lower bound is above 0.

**Confirmed = (H1 or H2) and H3.** Anything else is "not confirmed". There is no second cut-off, no other reviewer
cell, and no re-run after seeing results.

Two consequences, written down before the data:
- H1 or H2 gives two chances, so the false-positive rate of "H1 or H2" is up to about 10%, not 5%.
- With length matching, every run has the same line count, so line count's AUC is exactly 0.5 and **H3 reduces to
  H2**. In practice "confirmed" then means H2 passes; H1 passing alone cannot confirm. This follows from change A and
  is accepted as written.

## 8. Power (planning numbers, `eval/results/confirm_llama_1/power.json`)
Normal approximations with a design effect of 1.27 for clustering by base (from task-dev-1). P(pass) for H2 at true
AUC 0.60, 0.65, 0.70, 0.75: 0.46, 0.78, 0.96, 1.00. For H1 at true J 0.10-0.40 (false alarms held at 0.45): 0.22,
0.55, 0.87, 0.99. If length explained most of task-dev-1's AUC, the true AUC may be near 0.6, where power is about
one half.

## 9. Procedure (run by the student, in their own PowerShell window, Edge closed)
1. `build-pool --out data/calibration/pool-2.json --avoid data/calibration/pool.json`
2. `length-check --dry --pool data/calibration/pool-2.json --runs 100 --seed 1109` (stop if it fails)
3. `calibrate --runs 100 --batch confirm-llama-1 --pool data/calibration/pool-2.json --role skeptic_c_checklist
   --seed 1109` (runs, gate 2, then llama audits; `--resume` after any stop)
4. `rescore --batch confirm-llama-1 --reviewer skeptic_c` (repeatability, diagnostic only)
5. `python -m eval.confirm --batch confirm-llama-1`

## 10. Reported, deciding nothing
Character-count AUC; helper-size AUC; trivial-feature AUCs (effect spread, effect size, best arm's score); the code's
checklist decision J (posterior, as in RQ1); repeatability (replies matched on a second call, verdict changes).

## 11. Stop rules and limits
- Stop on a failed length gate, on 3 server failures in a row (`--resume` continues), or if the Scientist cannot fill
  the grid well enough to plan the batch (MixerError). Report, do not improvise.
- Limits: one model, one new pool, temperature 0; the cut-off was chosen on confounded data; the helper-size cue;
  real (non-calibration) runs are not padded yet, so a gate built on this would need real runs padded too.
