# Plan: review-task screen on a fresh 40-run batch (`task-dev-1`)

Status: APPROVED 2026-11-08 and built; batch started the same day.

## Student's decisions (2026-11-08)
1. Pull llama3.1:8b and give it num_ctx 4096 (per-role setting). Under 90% on the GPU is accepted (120 audits only).
   If a checklist prompt plus reply will not fit in 4096, say so and use llama3.2:3b for that task.
   Measured before the batch: 5.25 GiB loaded, 75% on the GPU. Real prompts are about 2,000 llama tokens and a
   checklist reply was 153 tokens, so 4096 fits; the wrapper's size guard still refuses any prompt that might not.
2. Add token-probability scoring with AUC if Ollama returns logprobs. It does (Ollama 0.40.13). The probabilities are
   the model's before the schema constrains the token, so the score renormalises over the two words the schema allows
   at the choice point (flag/pass at the verdict; yes/no per checklist class, run score = the largest). AUC is reported
   beside J and does not change the decision rule.
3. The confirmation batch (80-100 runs) must use a NEW pool of bases from fresh Scientist proposals, not the
   rq1-full pool (`data/calibration/pool.json`).
- The decision rule stays exactly as fixed below. No prompt changes after seeing task-dev-1 results.

## Goal
Find a review task (prompt and reply format) on which a local reviewer gets Youden's J clearly above 0.
Baseline result: gemma3:4b J 0.000 and phi4-mini J +0.034, 90% [-0.020, +0.093], both on `rq1-full`.

## Never touched
- Batch `rq1-full`: no re-audits, no new roles on it.
- `eval/results/rq1_skeptic_a.json`, `rq1_skeptic_b.json`, `rq1_comparison.json`, `position_bias_skeptic_a.json` and
  `eval/figures/` (baseline figures). SHA-256 them before and after, as in the reviewer study.
- The baseline prompt text: the existing hash test must still pass.

## Batch
`python -m canary.cli calibrate --runs 40 --batch task-dev-1 --seed 1108`
- Split from `split_runs(40)`: 20 canaries (one per class x tier), 10 controls, 10 shams, so 20 buggy and 20 clean.
- Same 18-base pool as rq1-full (`data/calibration/pool.json`), new seed. The scripts differ from rq1-full's by
  seeds and the bugs drawn, not by base. This is an assumption to state in the write-up.
- `calibrate` audits automatically with `skeptic_a` (baseline prompt). That is gemma's baseline on the same runs.

## Prompt variants (3) x reviewers (3) = 9 cells, 360 audits, all on the same 40 runs
| Task | What changes from the baseline |
|---|---|
| `baseline` | nothing (byte-identical prompt and system text) |
| `grounded` (V1) | neutral system prompt (no "strict"); "many experiments are correct, pass is a normal answer"; reply order `offending_line` -> `bug_class` -> `verdict` -> evidence -> confidence. Code verifies the line. |
| `checklist` (V2) | neutral system prompt; one entry per class in fixed ID order: `{answer: yes/no, line: str}`. Code: run flagged = any yes with a verified line. Class names only, no definitions (keeps it unhinted for Mission 6.4). |

Code-side rules (no LLM decides the verdict):
- Line check: after whitespace normalisation, the quoted line must be an exact substring of the blinded script and at least
  12 characters long. A flag with an unverified line counts as pass under the grounded rule. Raw verdicts are stored too,
  so raw J and grounded J are both reported (this separates the wording change from the code check at no cost).
- Known limit: grounding only removes invented evidence. It does not catch a real, correct line misread as a bug
  (the B01 anecdote), so it may not help much on its own.
- Checklist: also report yes-answers per run and per-class J = P(yes on k | bug k) - P(yes on k | clean). Named-right
  counts only when the truth is among the yes classes, with the number of yeses shown beside it.

Reviewers: gemma3:4b (`skeptic_a_*`), phi4-mini (`skeptic_b_*`), llama3.1:8b (`skeptic_c`, `skeptic_c_*`, family llama,
different from the qwen Scientist).

## llama3.1:8b and 6 GB VRAM
- Not installed. The pull is about 4.9 GB and needs the student's OK.
- Estimate: weights about 4.6 GiB, plus KV cache at num_ctx 8192 of about 1.0 GiB (32 layers x 8 KV heads x 128 x 2 x
  2 bytes x 8192), plus about 0.3-0.5 GiB of buffers, gives about 6.0 GiB against 6.0 GiB on the card. It will spill to
  the CPU at 8192.
- At num_ctx 4096 the KV cache halves, to about 5.4 GiB total, which should fit or nearly fit. Prompts are about
  1.3-1.6k tokens, and checklist replies are probably at most about 600 tokens. The wrapper's size guard
  ((4096-1024) x 3 = 9216 chars) still refuses anything that would be cut.
- Go/no-go before the batch: load it with one real prompt, then `ollama ps`. If GPU >= 90%, go. Otherwise run it
  at partial offload (slower, inside the forecast's high end), or fall back to llama3.2:3b (2 GB; same family but
  no larger than the others). The student chooses.

## Build steps (one mission, about 1.5-2.5 h)
1. `prompts.py`: `SKEPTIC_SYSTEM_NEUTRAL`, `skeptic_prompt_grounded`, `skeptic_prompt_checklist`. Baseline untouched.
2. `canary/review_tasks.py` (new): schema per task, `reduce(task, reply, blinded_script)` -> code verdict, classes,
   line verified. Add it to the Skeptic import allowlist test (it reads only the blinded script).
3. `skeptic.py`: task per role (models.yaml `task:` key, default `baseline`); store `task`, the raw reply and the
   code verdict with each audit.
4. `config/models.yaml`: 8 alias roles plus `skeptic_c`; `llm.py`: per-role `num_ctx` override (only if the VRAM check
   needs it).
5. `trust.py` / `eval/rq1.py`: read the code verdict for non-baseline tasks. **Guard:** refuse to write
   `rq1_skeptic_a.json` or the baseline figures for any batch other than `rq1-full`. New results go to
   `eval/results/task_dev/`.
6. `eval/compare_tasks.py`: 9-cell table, J with 90% interval, paired bootstrap of delta J against the same model's
   baseline on the same runs, plus invalid-reply and verified-line rates.
7. Tests (mocked LLM, fast): baseline hash unchanged, field order in schemas, line check (exact, normalised, short
   quotes rejected), checklist reduction, the rq1 output guard, the import allowlist. The suite is already at
   29 s of 30 s, so mark anything slow `slow`.

## Decision rule, fixed before the run
- Primary: J (any flag; grounded or checklist rule for V1 and V2) with 90% interval, per cell.
- A cell passes the screen if the lower 90% bound of J > 0. Report the point estimate and delta J as well.
- Power: with 20 buggy and 20 clean runs, the 90% half-width is about +/-0.22 near J 0.4, so only J of about 0.35 or more
  can clear the bar. A real but smaller gain may be missed. This is a screen, not the result.
- Winner's curse: picking the best of 6 new cells inflates its dev J. Any cell that passes must be confirmed on a
  second fresh batch (`task-confirm-1`, 80-100 runs) before a gate is built on it. That batch MUST use a new pool of
  bases built from fresh Scientist proposals (not `data/calibration/pool.json`, which rq1-full and task-dev-1 share),
  so the confirmation is not on the same 18 base experiments the winner was picked on. rq1-full stays untouched.
- If nothing passes: Mission 5.1 tripwires become the main defence, and the next round tries logprob scoring (AUC),
  separate calls per class, or describe-then-judge.

## Run order (background, logged to data/runs/campaign.log, resumable)
0. Back up `data/` to `~\canary-backups\data-<date>.zip` and hash the baseline files.
1. `calibrate --runs 40 --batch task-dev-1 --seed 1108` (runs and baseline gemma audits).
2. `reaudit --batch task-dev-1 --role` for each of: skeptic_a_grounded, skeptic_a_checklist, skeptic_b,
   skeptic_b_grounded, skeptic_b_checklist, then skeptic_c, skeptic_c_grounded, skeptic_c_checklist (the slowest last).
3. `python -m eval.compare_tasks --batch task-dev-1`; re-hash the baseline files; `ledger verify`.

## Forecast
- Experiments: 40/180 of the rq1-full experiment phase (40 min), so about 9 min, range 6-15 (one B09-subtle slot took 496 s).
- Audits: gemma about 3.1 s and phi about 2.3 s per baseline audit (measured). llama3.1:8b is unmeasured: 6-15 s estimated.
  Grounded x1.3-2, checklist x3-6 (longer replies). Nine cells come to about 45-100 min, plus 9 model loads (5-18 min),
  plus 0-20% retries.
- Machine time: about 1.4 h, range 1.0-2.3 h. Build: 1.5-2.5 h. Pull: 5-20 min. Interpretation: 20-30 min.
- Total: about 3-5 h, so two sessions (build + start; then results).
