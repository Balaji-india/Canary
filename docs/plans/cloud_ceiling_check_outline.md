# Outline: cloud ceiling check (NOT built, NOT run, NOT locked)

Written 2026-11-10 as an outline for the student's OK. Nothing here is code yet, and no cloud call has been made.
When approved, it becomes a locked pre-registration (`docs/plans/cloud_ceiling_check.md` + `.sha256`) **before** any
cloud call.

## 1. Question
Is the review task solvable at all from a blinded run? llama3.1:8b reached development AUC 0.643 (base 90%
[0.487, 0.778]) on task-dev-2. If a strong cloud reviewer clearly does better on the same runs, the task is solvable
and the local models are the weak link; if it does not, the task itself is hard and Canary should lean on tripwires.

## 2. Reviewer
- **One strong cloud model of another family than the qwen Scientist.** Proposed: an OpenAI model (GPT family), because
  AUC needs token probabilities and, as of 2026-11, OpenAI's Chat Completions is the one major API still returning
  `top_logprobs` (up to 20) on strong models:
  - non-reasoning models (GPT-4.1) return them; GPT-5.x reportedly does only with reasoning effort "none"; o-series
    reasoning models refuse them.
  - Gemini: `responseLogprobs` is deprecated for Gemini 3.x and fails on recent models.
  - Anthropic (Claude): the API returns no token probabilities, so it could give the verdict J but no AUC.
- **Model choice rule, fixed before data:** a one-call smoke test on a toy prompt (not a task-dev-2 run) tries the
  newest GPT-5.x at reasoning "none", then GPT-4.1; the first that returns `top_logprobs` is the reviewer. Temperature 0.
- **Optional second arm (verdict only, reported, deciding nothing):** the same model with reasoning on, to see whether
  reasoning raises the ceiling. No AUC is possible there.

## 3. Data and prompts
- The 40 task-dev-2 runs (pool 1, seed 1110, 20 canaries, padded, decoys), via `canary.cli reaudit --batch task-dev-2
  --role <cloud role>`: no new experiments run, nothing re-tuned.
- Two roles: `skeptic_d` (baseline prompt) and `skeptic_d_checklist` (checklist prompt), the same templates llama got
  (`canary/review_tasks.py`), unchanged.
- These runs have been seen by us, but no part of the cloud reviewer is chosen on them, so the working rule holds.
  Any later choice (prompt, model, cut-off) made from this result must be judged on a fresh batch.
- **Ground truth stays local.** Only the blinded script and results go out; the sealed table never leaves the laptop
  (`skeptic.py`/`blinding.py` already cannot read it). Experiments never see the key (`sandbox.py` passes an env allowlist).

## 4. Scoring (same as llama)
Per prompt, from `eval.compare_tasks --batch task-dev-2` plus a small `eval/ceiling.py` that applies the rule:
- Verdict-level Youden's J of the code's decision (Beta posteriors, as in RQ1), recall, specificity (controls, shams,
  and by decoy class).
- AUC of P(flag) (token probabilities mapped to the same format as Ollama's), run-level and base-level 90% and 95% intervals.
- Trivial-feature baselines (line, character and statement count, helper statements and characters, effect spread)
  and the paired gap: AUC minus the strongest trivial feature, re-picked in every base-level draw.
- No cut-off is chosen on these runs (a J at a tuned cut-off would be optimistic on 40 runs).

## 5. Rule for "solvable" (to be approved and locked before any call)
Two prompts give two chances, so the rule uses **95% base-level intervals** (Bonferroni over 2 prompts).
- **SOLVABLE** if, for at least one prompt, both hold: the AUC's lower bound is above llama's development AUC (read
  from `eval/results/task_dev_2/dev_report.json`, not typed in), and the lower bound of AUC minus the strongest
  trivial feature is above 0.
- **HARD** if, for both prompts, the AUC's upper bound is below 0.75 (0.75 is the usual "acceptable discrimination"
  line): even a strong model is a weak reviewer here.
- **INCONCLUSIVE** otherwise. The next step would then be 40 fresh runs on new bases (pool 2 is free now), not a re-tune.
- Planning note: with 40 runs on 16 bases, a lower bound above 0.643 needs a true AUC of roughly 0.85 or more. The
  exact power will be computed before the lock by reusing `eval/power_sim.py` at 40 runs.

## 6. What `/api` needs (none of it exists yet)
- `canary/llm.py` has one provider, `OllamaProvider`; the `Provider` protocol and per-role `provider:` key already
  allow a second. Needed: `OpenAIProvider` (`installed_models` from `/v1/models`, `generate` with a strict JSON schema,
  temperature 0, `logprobs` + `top_logprobs: 20`, tokens mapped to the Ollama-style dicts `review_tasks.score` reads;
  `unload` does nothing), registered in `PROVIDERS`. Mocked-HTTP tests, no network in the suite.
- **New-code choice (student's OK, CLAUDE.md section 4):** the `openai` SDK (a new dependency) or a ~60-line
  standard-library HTTP client (no new dependency). The wrapper already does retries, the cache and schema checks,
  so the standard library is enough; Claude's suggestion is the standard library.
- `config/models.yaml`: `skeptic_d: {provider: openai, model: <chosen by the smoke test>, temperature: 0.0,
  family: gpt}` and `skeptic_d_checklist: {use_role: skeptic_d, task: checklist}`.
- `doctor` reports "key present" (never the key) and whether the model answers.

## 7. Key setup (`.env`, already in `.gitignore`)
1. Create a key in the OpenAI dashboard and set a **hard monthly budget limit of $5** there.
2. Copy `.env.example` to `.env` and add `OPENAI_API_KEY=...` (`.env.example` gets the name with an empty value).
3. `python-dotenv` (already a dependency) loads it in `llm.py`; the key is never logged, cached or written to results.

## 8. Cost (estimate; prices from secondary aggregators, 2026-11; check OpenAI's pricing page before running)
- Prompt size measured on the 40 runs: 8.3k (baseline) and 8.4k (checklist) characters on average, about 2.5-3k
  tokens; replies about 100-400 tokens.
- Per call at most: GPT-4.1 ($2 in / $8 out per million) about $0.01; GPT-5 at reasoning "none" ($1.25 / $10) about
  $0.008; GPT-4.1 mini ($0.40 / $1.60) about $0.002.
- Calls: 40 runs x 2 prompts = 80, plus up to 80 for a repeatability pass and about 10 smoke calls: **at most about
  $1.5-2 in total** for the main arm. The optional reasoning arm adds hidden reasoning tokens: budget about $3 more.
  The SQLite cache makes any re-run free.
- Time: no GPU; at a few seconds per call, about 5-15 minutes. Claude may run it after the student's OK (sending
  blinded runs to an outside service is the student's call).

## 9. Order once approved
1. Student approves sections 2, 5 and 6 (provider, rule, standard library vs SDK).
2. `/api`: provider + tests; `pytest -q`; commit.
3. Lock `docs/plans/cloud_ceiling_check.md` (this outline, with the power numbers) + `.sha256`; commit.
4. Smoke test (toy prompt) picks the model; key and budget set.
5. `reaudit` both roles on task-dev-2; `eval.compare_tasks` and `eval.ceiling`; `/evaluate`; commit.
6. SOLVABLE: efficiency search (Next actions 2). HARD or INCONCLUSIVE: Mission 5.1 first, as planned anyway.
