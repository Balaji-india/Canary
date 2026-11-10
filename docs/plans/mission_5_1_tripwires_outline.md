# Outline: Mission 5.1 tripwires (NOT built; waiting for the student's OK)

Written 2026-11-10 in a thinking-only session. High level on purpose: signatures and tests are settled in the mission.
Everything here is **proposed by Claude, pending the student's approval**.

## 1. What a tripwire is here
A deterministic check, no LLM, that reads one run folder (script, config, results, dataset copy) and says
"fires" or "silent", with the class it suspects. Code decides; nothing is tuned by looking at one run.

## 2. Main design choice (needs the student's OK): replay with a probe, not pattern matching
`docs/DESIGN.md` section 6 lists mostly syntax-tree checks. Proposed instead: **re-run the run's own script in the
sandbox with a probe** that wraps a few scikit-learn entry points (`train_test_split`, every `fit`, the metric
functions) and records what data reached them. The checks then test **properties of a correct experiment**, not the
shape of a planted edit.

| | Syntax-tree patterns (DESIGN) | **Replay with a probe (proposed)** |
|---|---|---|
| Build effort | 10 separate matchers | one probe + about 7 small checks |
| Scientific validity | keyed on names and shapes: breaks on shams (renamed variables), misses bugs hidden in helpers, fires on decoys | sees what the code does: renames, helpers and padding do not matter |
| Laptop time | none | one more run of each script (task-dev-2: 40 runs took 357 s) |
| Explainable in a viva | "we looked for this line" | "the test rows that were scored are the test rows that were split" |
| Risk | written by someone who read the saboteur: recall on canaries is inflated | custom code that avoids the wrapped functions is not seen |

Config-only and results-only checks (B06, part of B05 and B09) need no replay and also run on real runs for free.

## 3. Which classes get a check, and what it looks at
| Check (invariant of a correct experiment) | Classes | Looks at |
|---|---|---|
| **Fit scope:** a preprocessor is fitted only on training rows of the current split | B01 | rows reaching each preprocessing `fit` vs the split's train rows |
| **Split input:** what is split is the dataset on disk, same rows and same columns | B02, B07 | rows and columns entering `train_test_split` vs `dataset.csv.gz` without the target |
| **Scoring:** what is scored is the test split, row for row and label for label | B03, B08, B10 | rows and labels reaching the metric vs the split's test rows and labels |
| **Test use:** no model is fitted on test labels; the test metric is computed once per arm and seed | B04, B06 subtle | every `fit` and metric call that receives the test labels |
| **Report:** the per-seed numbers in `results.json` are the ones the metric returned, and equal the registered metric recomputed from the recorded predictions | B05, B06 subtle | recorded metric values vs `results.json` |
| **Metric validity:** accuracy on a class ratio above 3:1 | B06 obvious | config and `class_balance`; also catches real runs with that design (Known issues) |
| **Baseline sanity (heuristic, advisory):** the control is not clearly worse than the same model at library defaults, nor at a dummy classifier's level | B09 | one extra control fit per seed; threshold chosen on development data |
| Data screen (second line): no single feature predicts the label almost perfectly | B02 in the dataset itself | dataset only; threshold from development data |

Every class has a check. B09 is the weak one: "a poor baseline" is a matter of degree, and a clean run whose registered
control is honestly poor will fire it. It is measured and reported separately, and may stay advisory.

## 4. Known traps
- **B07 duplicate rows (PROGRESS):** `blood-transfusion` has 246 duplicate feature rows and `pc1` 161 before any bug,
  so overlap between train and test is normal there. The split-input check compares against the dataset on disk, so
  natural duplicates cannot fire it. A plain row-hash overlap would also **miss B07 subtle**, whose copies carry small
  noise and are not exact duplicates.
- **B10 does not change split sizes (PROGRESS):** rows are dropped inside `run_arm`, so `split_sizes` in
  `results.json` stays normal. The scoring check counts the rows that reach the metric instead.
- **B02 subtle is noisy:** DESIGN's "single-feature AUC of 0.99 or more" would miss a label copy with heavy noise.
  The split-input check sees the extra column directly.
- **B05 here is per seed:** DESIGN's "reported value equals the maximum" assumes one summary number; `results.json`
  holds one value per seed, so the check compares each with what the metric returned.
- **B08's decoy reorders rows and labels together.** A check on label order alone would fire on it; the scoring check
  compares row-label pairs.
- **Shams rename variables and reorder imports;** padding adds an unused helper. No check may depend on a name.
- **Template-diff shortcut is banned:** "the script differs from the template" flags every canary, but also every
  sham, decoy and padded run. It measures "was edited", not "is buggy".
- **Teaching to the test (the main validity threat).** Claude has read the saboteur. Guards: `tripwires.py` and the
  probe may not import `saboteur`, `sealed`, `controls`, `mixer` or the test oracles (import test, as for
  `skeptic.py`); no constant or name from `transforms.py` may appear in them (a test searches for them); each check's
  docstring states its invariant; the saboteur's oracles are ground-truth instruments and are not reused.
- **Rows that appear twice** (B07 with B08-style checks): row identity must survive duplicate index labels; one test
  covers both together.
- **Replay must reproduce `results.json`.** If it does not, or it crashes, that is counted and reported separately.

## 5. Measuring recall and specificity fairly
- **Same runs, same truth, same code as the LLM.** Tripwire results are stored as audits under a role `tripwire`, so
  `trust.py` computes recall per class (Beta posteriors), specificity on controls and shams, the decoy split and J
  exactly as for a reviewer. A catch is any check firing, as for the LLM; the right class is reported beside it.
- **Decoys are the specificity test.** Each decoy has its bug's place and shape but does no harm, so a check keyed on
  shape fails there. Specificity is reported for controls, shams and by decoy class.
- **Development vs test.** rq1-full, task-dev-1 and task-dev-2 are development data: the checks are built while
  looking at them. The reported numbers come from a **fresh batch on pool 2** (new bases), thresholds frozen first,
  under a locked plan. Tripwires need no LLM, so that batch can be large.
- **What recall on canaries means.** It is an upper bound: recall on the 20 known bug shapes. Recall on new shapes is
  measured later on LLM-written mutants (Mission 6.2) and reported separately.
- **Against the LLM (Mission 5.4, RQ2):** the same batch, paired: LLM only, tripwires only, union, each with recall,
  specificity and J and base-level intervals. A union raises recall and lowers specificity; both are shown.
- **Harmless canaries count as bugs** (the method is broken even if the number did not move); recall is also split by
  harmful and harmless. Replay failures are shown both ways (as flags and left out) if there are any.

## 6. Module sketch and split
- `canary/probe.py` (the wrapped entry points and the record), `canary/tripwires.py` (the checks and
  `run_tripwires(run_dir)`), `canary.cli tripwires --batch B`, tests per check: fires on both tiers of its classes,
  silent on the clean script, every decoy and shams.
- Two sittings: **5.1a** probe + fit scope, split input, scoring (B01, B02, B03, B07, B08, B10); **5.1b** test use,
  report, metric validity, baseline sanity (B04, B05, B06, B09) + ledger role + development table on task-dev-2.
- Done when (proposed): `canary.cli tripwires --batch task-dev-2` prints recall per class and specificity by control,
  sham and decoy class, with the guard tests passing.
