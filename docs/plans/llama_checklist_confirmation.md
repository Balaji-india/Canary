> **Note (2026-11-11): the `config/models.yaml` hash recorded in this plan no longer matches, as expected.** The
> file gained the cloud ceiling check's roles and providers (`/api`). This plan is dead (never run), so nothing
> depends on that hash; it is kept as the record of what was pre-registered.
>
> **SUPERSEDED on 2026-11-09 by `llama_checklist_confirmation_v2.md`. Never run: no pool-2 or `confirm-llama-1`
> data exist.** Kept, not deleted, as the record of what was pre-registered.
>
> Why: the cue probe passed (section 4a), but this plan's padding left the padding helper's size separating canaries
> from clean runs (AUC 0.15, i.e. 0.85 with direction ignored, on the pool-1 dry plan). Amended H3 had to beat that
> number, so its power was about 0 at llama's likely AUC (`eval/results/confirm_llama_1/power.json`). The locked
> cut-off was also chosen on length-confounded data and flagged 14 to 17 of 20 padded clean controls in the probe
> (`eval/results/confirm_llama_1/cue_probe.json`). v2 adds decoys to clean runs so that no size feature separates the
> run types, and chooses a new cut-off on a development batch with the new padding.
>
> The text below is byte for byte the version locked as amendment 1: SHA-256 `85ed1d4f1bc9d3873bc2eaef786865c0fd14b6e64af06ba72d6974fca144842c`, committed in `6a9eaa9`.
> Only this notice was added; the `.sha256` file now hashes the file with the notice. `eval/confirm.py` refuses the
> batch name `confirm-llama-1`.

# Pre-registration: llama-checklist confirmation on a new, length-matched pool

Written 2026-11-08, before pool-2 or the confirmation batch exists. Approved by the student with changes A-E (below).
**Amendment 1, 2026-11-09, still before pool-2, the probe or any batch data exist** (asked for by the student): H3 now
compares with the strongest trivial feature, helper size included (section 7), and a cue-sensitivity probe must pass
before anything else runs (section 4a). Reason: with length matching, line count is constant, so the old H3 was
passed by construction, while the padding helper's size separates canaries from clean runs (AUC 0.15 on the pool-1
dry run). Section 12 lists every change.
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
- Code and config at these SHA-256 values, as stored in git (LF line endings; amendment 1). Any change before
  the batch must amend this plan:
  - `canary/review_tasks.py` f4bf55eda5d33e0ad8a42947750225e3cfa216db2064b985d3f4a29bfd5cb751
  - `canary/padding.py` 7def552a8c6f80633f4e0acfac81defe5a1cf1591458177c5545a3ce76af0050
  - `canary/separation.py` e7ee3a8235951860736e2a369e00b143db9ab9027cb880e02555bff42421e68b
  - `canary/mixer.py` 4d66bb4ba52579fd92b160d581c5b6ffdcce6ca0b32c19f77dc568deb1f28867
  - `eval/confirm.py` 79ea047dbf1f1d6797ad7388c15bf7a910ec8bbd7b868f7c360a57b3f3ac56e4
  - `eval/compare_tasks.py` a27b668644abeaaf399e7770f975bcb3a53fb7f93f80d077899ac77ac2a482c5
  - `eval/cue_probe.py` b3ed18071e95ae0c9e8794e964aad19035508a0b58153b7e9753d9c56d430fe5
  - `config/models.yaml` ae10e7f5ee5c46503a4353339770de099aa1c79bb8f539669f34a24cc7e6112d
  - `config/bug_classes.yaml` 8fa225ad871e43ad2430e7f7f3b152fcbae6cd955ca45d6af6e4024738cfe90f

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

The helper's own size differs by type by design: a canary's bug lines take the place of helper lines. On the pool-1
dry plan (100 runs, seed 1109) every clean run gets 21 statements and canaries get 6 (B10 subtle) to 22 (B06 subtle);
helper-size AUC 0.15, i.e. 0.85 with the direction ignored. It does not gate the length check, but it is one of H3's
trivial features (section 7), and section 4a tests whether the reviewer reacts to it.

## 4a. Cue-sensitivity probe (amendment 1, runs first)
`python -m eval.cue_probe`, code frozen in section 2. 20 existing pool-1 controls (from `rq1-full` and `task-dev-1`:
clean runs that already ran, picked one per base in a seeded order, 18 bases), so no experiment runs. Each control is
padded twice with the code otherwise identical: **large** = the helper a clean run gets under the pool-1 batch target,
**small** = the smallest helper any run of the pool-1 dry plan gets (21 vs 6 statements, 112 vs 97 blinded lines in
the dry check). Both versions get the run's own results and pre-registration, are blinded, and are scored by
`skeptic_c_checklist` (the frozen role of section 2) with the cache bypassed. 40 reviews.

Statistic: the mean over controls of P(flag | small) - P(flag | large), with a 90% interval resampling whole bases
(2000 draws, seed 0). Decision, by code:
- **INCONCLUSIVE** if fewer than 15 controls are scored in both versions, or any prompt is too large: stop and report.
- **CUE_LIVE** if the interval excludes 0, in either direction: stop. Do not build pool-2 or run the batch; report and
  propose a padding redesign (for example decoy code in clean runs, so the helper's size has the same distribution
  for every run type).
- **NO_DETECTED_SENSITIVITY** otherwise: continue with section 9, step 1.

Probe runs are not in the ledger, the sealed table or the LLM cache, so they never enter any recall, specificity or
AUC estimate. Records: `eval/results/confirm_llama_1/cue_probe.jsonl`; result: `cue_probe.json`.
Limits, written before the probe: on identical code the small version is also 15 lines shorter, so the probe cannot
tell "reacts to helper size" from "reacts to length"; either would make the helper a live cue, which is why either
direction stops. With 20 controls a small reaction can go undetected: passing the probe does not prove there is none.

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
- **H3 (amendment 1):** AUC of P(flag) minus the AUC of the strongest trivial feature on the same runs. The features
  are blinded line count, blinded character count, the padding helper's size (statements) and effect spread (standard
  deviation over seeds of treatment - control). Each feature counts as max(AUC, 1 - AUC), since direction does not
  matter for a cue. The strongest feature is picked again inside each bootstrap draw, so the interval includes the
  luck of picking a maximum. Paired, base-level 90% interval; passes if the lower bound is above 0. A run missing a
  feature is left out of H3 and counted.

**Confirmed = (H1 or H2) and H3.** Anything else is "not confirmed". There is no second cut-off, no other reviewer
cell, and no re-run after seeing results.

Consequences, written down before the data:
- H1 or H2 gives two chances, so the false-positive rate of "H1 or H2" is up to about 10%, not 5%.
- H3 no longer reduces to H2. Under this padding the helper's size is expected to be the strongest feature (0.85 on
  the pool-1 dry plan), so **H3 asks llama to beat about 0.85**, and its power is low (section 8). If the probe passes
  and the batch runs with this padding, "not confirmed" is the likely outcome even for a fairly good reviewer. A
  padding redesign that removes the helper-size cue would make H3 "beat the best of the remaining features" again.
- Effect size and the best arm's score are not H3 features: they stay as diagnostics (section 10).

## 8. Power (planning numbers, `eval/results/confirm_llama_1/power.json`)
Normal approximations with a design effect of 1.27 for clustering by base (from task-dev-1). P(pass) for H2 at true
AUC 0.60, 0.65, 0.70, 0.75: 0.46, 0.78, 0.96, 1.00. For H1 at true J 0.10-0.40 (false alarms held at 0.45): 0.22,
0.55, 0.87, 0.99. If length explained most of task-dev-1's AUC, the true AUC may be near 0.6, where power is about
one half.

Amended H3 (`h3_power` in `eval/confirm_power.py`): the strongest feature's AUC is taken as the helper size's 0.85
from the pool-1 dry plan, and the two AUCs are treated as independent (a planning approximation that ignores the
pairing). P(pass) for H3 at true llama AUC 0.75, 0.85, 0.90, 0.95: 0.00, 0.05, 0.23, 0.66.

## 9. Procedure (run by the student, in their own PowerShell window, Edge closed)
0. `python -m eval.cue_probe --dry` (no model; must report 0 prompts too large), then `python -m eval.cue_probe`
   (resumable: run it again after any stop). Continue only if it prints NO_DETECTED_SENSITIVITY (section 4a).
1. `build-pool --out data/calibration/pool-2.json --avoid data/calibration/pool.json`
2. `length-check --dry --pool data/calibration/pool-2.json --runs 100 --seed 1109` (stop if it fails)
3. `calibrate --runs 100 --batch confirm-llama-1 --pool data/calibration/pool-2.json --role skeptic_c_checklist
   --seed 1109` (runs, gate 2, then llama audits; `--resume` after any stop)
4. `rescore --batch confirm-llama-1 --reviewer skeptic_c` (repeatability, diagnostic only)
5. `python -m eval.confirm --batch confirm-llama-1`

## 10. Reported, deciding nothing
Each H3 feature's own AUC; helper-size AUC with its run-level interval; the other trivial features (effect size,
best arm's score); the code's
checklist decision J (posterior, as in RQ1); repeatability (replies matched on a second call, verdict changes).

## 11. Stop rules and limits
- Stop unless the probe (section 4a) says NO_DETECTED_SENSITIVITY.
- Stop on a failed length gate, on 3 server failures in a row (`--resume` continues), or if the Scientist cannot fill
  the grid well enough to plan the batch (MixerError). Report, do not improvise.
- Limits: one model, one new pool, temperature 0; the cut-off was chosen on confounded data; the helper-size cue;
  real (non-calibration) runs are not padded yet, so a gate built on this would need real runs padded too.

## 12. Amendment log
- **Amendment 1 (2026-11-09).** Made before pool-2, the probe or any confirmation data existed: nothing had run since
  the plan was first hashed. Changes: H3 compares with the strongest of four trivial features, helper size included,
  re-picked per draw (section 7); a new cue-sensitivity probe that must pass first (section 4a, procedure step 0, stop
  rule); power for the new H3 (section 8); frozen hashes updated (section 2), with `eval/cue_probe.py` added. Also in
  section 2: six files had been hashed as Windows (CRLF) working copies; they are now hashed as stored in git (LF, which
  `.gitattributes` keeps on checkout), so anyone with the repository can reproduce every hash. Their content did not
  change (checked: identical once line endings are removed). The cut-off and its file are unchanged, and so are
  sections 1, 3, 5 and 6. The first version's hash was
  `5e288a3c9c24dcdff7b9776c7dc3f8d3e1022e4a1d2a2c0d84df46a389361099`.
