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
- [ ] 1.3 LLM wrapper (roles, JSON, cache, model queue)
- [ ] 1.4 Scientist, pre-registration, verdict, hash-chained ledger
- [ ] 1.5 Blinding and Skeptic

**M2 Controls and trust**
- [ ] 2.1 Saboteur: 10 classes × 2 tiers
- [ ] 2.2 Controls, shams, sealed run-type table
- [ ] 2.3 Trust statistics
- [ ] 2.4 Run mixer, calibrate command, RQ1

**M3 Memory and calibration**
- [ ] 3.1 Graveyard with similarity check
- [ ] 3.2 Brier, reliability diagram, calibration feedback

**M4 How much should we trust our findings?**
- [ ] 4.1 Prevalence, contamination, trust gate
- [ ] 4.2 Hidden-truth validation (RQ4)
- [ ] 4.3 Control chart and drift alarms
- [ ] 4.4 Campaign agent loop

**M5 Defense in depth**
- [ ] 5.1 Tripwires
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

## Running or interrupted campaigns

## Decisions
- **Ollama only for now, no API keys.** A cloud model is added later with `/api`. Mission 1.3 must build `llm.py`
  so that switching to an API needs only a config change (`provider` in `config/models.yaml`, key in `.env`), with
  no changes to the code that calls it. Whatever is chosen, the Skeptic stays a different family from the Scientist.
- **Python 3.12.10** installed per user with winget, first on the user PATH. Python 3.11.9 stays installed but is
  unused. The project runs from `.venv`; `requirements.lock` records the exact tested versions.
- **Skeptic A runs on the fallback `gemma3:4b`.** `gemma4:e4b` is a 6.13 GB download and will not fit in 6 GB VRAM.
  Do not pull it on this machine: `resolve_roles` prefers it as soon as it is installed.
- **Scientist runs on the fallback `qwen3:4b`** (already installed). `qwen3.5:4b` is optional, and pulling it
  switches the Scientist automatically. Skeptic B is `phi4-mini`.
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

## Fixes
- OpenML download crash on non-text labels (sklearn's pandas parser under pandas 3): now uses `parser="liac-arff"`.

## Known issues
- **`crash_rate()` counts every folder in `data/runs/`, including the deliberate `broken.yaml` run** (it shows 1 of 2
  now). Before reporting a crash rate against the 42% figure, count campaign runs only.
- **The sandbox guards against accidents, not attacks:** experiments can still reach the network and other files. This
  is acceptable while scripts come only from our template; revisit it before running LLM-written code (Mission 6.2).
- **Cold model loads are slow.** A first `gemma3:4b` prompt timed out at 110 s; once loaded it answered in 3.8 s. Other
  cold starts took 27-53 s. Mission 1.3 needs a generous first-call timeout and should batch per model.
- **`qwen3:4b` writes its reasoning into the reply**, even with `think=false` sent to `/api/generate`. Mission 1.3 must
  check this and get clean JSON from it.
- The Ollama CLI prints `CHECK failed: mlx_compile_cache_new_` on `--version` and `list`. The commands still worked
  and the cause is unknown.
- OpenML returns temporary 503 and "not found" errors. If a download fails, re-run `cache-datasets`; it skips what is
  already cached.
- `python3` still opens the Windows Store stub. Canary only uses `python`, so this is harmless.

## Next 3 actions
1. Run `/explain canary/sandbox.py` and `/explain canary/codegen.py` for viva prep.
2. Run `/mission 1.3` (LLM wrapper, with the config-only API switch).
3. Run `/mission 1.4` (Scientist, pre-registration, verdict, ledger).
