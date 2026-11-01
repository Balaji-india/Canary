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

## In progress
None. Mission 2.3 is complete, and no mission is part-way through.

## Running or interrupted campaigns
None.

## Decisions
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
- Stop hook said "something failed?" whenever a message used the word "failed": it now needs a traceback header, a pytest count above zero, or a line starting `Error:`.
- `qwen3:4b` crashes and "token repeat limit" aborts from the open `params` schema: fixed with one schema form per model.
- A retried proposal replayed the cached rejected reply: each retry prompt now carries its attempt number.
- OpenML download crash on non-text labels (sklearn's pandas parser under pandas 3): now uses `parser="liac-arff"`.

## Known issues
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
- **`gemma3:4b` looks prone to false alarms:** 2 of 2 real audits flagged B01 at confidence 0.95 on clean scripts,
  calling correct fit-on-train, transform-on-test "leakage". Its earlier trial on a clean script was also a false flag.
  This is too few runs to conclude anything, and the prompt was deliberately not tuned. Mission 2.4 measures it. If
  specificity is this low, the trust gate will reject most findings, so RQ1 is the first thing to check.
- **Real runs with a bug-like design are not caught yet.** `why_not_clean` only protects clones. A real run using accuracy
  above 3:1 is really buggy; Mission 5.1's B06 tripwire should catch it.
- **A sham's edits can be told apart in principle.** Its imports are out of the template's usual order, and its names are
  slightly longer on average (about 1-2% more characters). A stateless reviewer sees one run at a time and has no template to
  compare with, so this should not matter, but a reviewer that learned the template could separate them.
- **Overall recall looks more certain than it is while classes are untested.** With no data at all, it reads about 0.50, 90% [0.35, 0.65],
  purely from averaging 10 flat priors. `trust` prints "tested k of 10"; RQ1 and any report must show that too.
- **Mission 2.4 must report failed audits.** A failed LLM reply writes no ledger entry, so `trust.py` cannot see it. It is not counted as a
  miss, which would inflate recall if the reviewer fails more often on canaries.
- **Mission 2.4 must seal real runs too.** `scientist.run_locked` does not write to the sealed table, and the 2 existing
  real runs have no row. It must also report recall by harmful and harmless using `impact_class`.
- **The mixer must catch `NotApplicable`** from `sabotage`, `clone_prereg` and the `run_*` functions, and choose another base.
- **Mission 5.1's B10 tripwire ("test size smaller than declared") will not fire:** B10 now drops rows inside `run_arm`, so
  `split_sizes` stays normal. It needs a different check.
- **Mission 5.1's B07 tripwire needs care:** `blood-transfusion` has 246 duplicate feature rows and `pc1` 161 before any
  bug, so row overlap between splits is normal there. Compare against the overlap expected from the dataset.
- **The test suite is still close to its limit** (28 s of 30 s after the trim). The broken-config and sham tests now run in-process; the 2 remaining subprocess tests take about 3 s each.
- **Cold model loads are slow** (27-110 s seen). Handled with the 300 s cold timeout and `ModelQueue`.
- **`qwen3:4b` writing reasoning into replies did not occur in schema mode:** 2 of 2 real replies were clean JSON. Plain
  text mode was not retested, and any remaining `<think>` block is stripped.
- The Ollama CLI prints `CHECK failed: mlx_compile_cache_new_` on `--version` and `list`. The commands still worked
  and the cause is unknown.
- OpenML returns temporary 503 and "not found" errors. If a download fails, re-run `cache-datasets`; it skips what is
  already cached.
- `python3` still opens the Windows Store stub. Canary only uses `python`, so this is harmless.

## Next 3 actions
1. Run `/mission 2.4` (mixer, calibrate, RQ1), using `trust.summarize` for recall by impact and specificity by type.
2. Run `/mission 3.1` (graveyard with similarity check), and address the Scientist's lack of variety there.
3. Run `/mission 3.2` (Brier score, reliability diagram, calibration feedback).
