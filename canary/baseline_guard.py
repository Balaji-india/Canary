"""The baseline guard: stop a weak or confounded control before a real run (bug class B09 at proposal time).

Why it exists: a real Scientist run is rendered from the template, so its config is the only place a bug can hide.
A handicapped control (B09) makes "the treatment helped" partly an artifact, and no reviewer or tripwire can see it
afterwards because the script, the config and the pre-registration all agree. So code reads the proposal first.

What it asks (docs/plans/b09_proposal_guard.md, section 2):
1. In what do the two arms differ? `effective_params` lays an arm's params over scikit-learn's own defaults, read at
   run time, so a default written out and a default left out are the same thing. There is no table of "good" or
   "bad" values anywhere in this file: a guard test walks the syntax tree to keep it that way.
2. Is the control worse than its own reference (the same arm with some settings put back to the library default)?

This file never imports the saboteur, the controls, the mixer or the sealed table, and never names a hyperparameter
(apart from `random_state`, which the template sets per seed). Tests in tests/test_baseline_guard_guards.py enforce it.
"""
from __future__ import annotations

import importlib
import json
import tempfile
from functools import lru_cache
from pathlib import Path

from canary import datasets, prereg, sandbox
from canary.config import load_yaml

# Model name -> where scikit-learn keeps its class. The same table as MODELS in templates/experiment.py.tmpl (a test
# compares them); kept as text so that importing the guard does not import every estimator.
ESTIMATORS = {
    "logistic_regression": ("sklearn.linear_model", "LogisticRegression"),
    "random_forest": ("sklearn.ensemble", "RandomForestClassifier"),
    "gradient_boosting": ("sklearn.ensemble", "GradientBoostingClassifier"),
    "svm": ("sklearn.svm", "SVC"),
    "knn": ("sklearn.neighbors", "KNeighborsClassifier"),
    "decision_tree": ("sklearn.tree", "DecisionTreeClassifier"),
    "gaussian_nb": ("sklearn.naive_bayes", "GaussianNB"),
}
# The template overwrites random_state with the seed in both arms, so it is never a difference between them.
IGNORED_PARAMS = frozenset({"random_state"})
# G0 draws the same line as tripwire L1 and DESIGN.md section 6: accuracy misleads above a 3:1 class ratio (largest
# class over smallest). Our own constant: the guard may not import the saboteur; a test checks the two agree.
IMBALANCE_LINE = 3.0
# Guard seeds: fixed, from 100001 upward. Run seeds are drawn below prereg.SEED_RANGE (100000) and the oracle of
# sitting 2 starts at 200001, so the guard never looks at a real run's own splits before the lock (plan trap 4).
GUARD_SEED_START = 100_001
GUARD_SEEDS = 5  # K; step 6 of the plan may raise it to 10 by a rule fixed in advance
MODEL_FACTOR = "model"
PREPROCESSING_FACTOR = "preprocessing"


class _Missing:
    """Stands for "this arm has no such parameter" (another model, or an unknown name). Equal only to itself."""

    def __repr__(self) -> str:
        return "<missing>"


MISSING = _Missing()

# The rows of the plan's section 3 table.
G0, G1, G2, G3, G4, G5, G6 = "G0", "G1", "G2", "G3", "G4", "G5", "G6"
# What one reference run says about an arm.
WEAK = "weak"                  # the reference beats the arm by at least the floor, clearly
NOT_WEAK = "not_weak"          # the gap is clearly below the floor
INCONCLUSIVE = "inconclusive"  # these seeds cannot tell: recorded as a number, no action
UNVERIFIABLE = "unverifiable"  # the reference run crashed or timed out (rule G5)


def estimator_class(model: str) -> type:
    module, name = ESTIMATORS[model]
    return getattr(importlib.import_module(module), name)


def library_defaults(model: str) -> dict:
    """scikit-learn's own defaults for this model, read now from the installed version (never copied into code:
    defaults move between versions, plan trap 6)."""
    return {k: v for k, v in estimator_class(model)().get_params().items() if k not in IGNORED_PARAMS}


def same_value(a: object, b: object) -> bool:
    """Equality as the experiment sees it: 1 equals 1.0, but True is not 1 and None is only None."""
    if a is MISSING or b is MISSING:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return type(a) is type(b) and a == b


def effective_params(arm: dict) -> dict:
    """The parameters the model really gets: the library defaults with the arm's params laid over them.

    An unknown name is kept (it will reach scikit-learn and most likely crash the run); `unknown_params` lists it.
    """
    effective = library_defaults(arm["model"])
    effective.update({k: v for k, v in arm["params"].items() if k not in IGNORED_PARAMS})
    return effective


def unknown_params(arm: dict) -> list[str]:
    """Param names the model does not have. Reported, not a crash: the reference run will show what they do."""
    known = library_defaults(arm["model"])
    return sorted(k for k in arm["params"] if k not in known and k not in IGNORED_PARAMS)


def nondefault(arm: dict) -> list[str]:
    """Names of the arm's parameters whose effective value is not the library default (unknown names included)."""
    defaults = library_defaults(arm["model"])
    return sorted(k for k, v in effective_params(arm).items() if not same_value(v, defaults.get(k, MISSING)))


def factors(control: dict, treatment: dict) -> list[str]:
    """In what the two arms differ: "model" if the models differ, else every parameter whose effective value
    differs; plus "preprocessing" if the scaler lists differ (compared in order, because the order is applied)."""
    if control["model"] != treatment["model"]:
        found = [MODEL_FACTOR]
    else:
        ours, theirs = effective_params(control), effective_params(treatment)
        found = [name for name in sorted(set(ours) | set(theirs))
                 if not same_value(ours.get(name, MISSING), theirs.get(name, MISSING))]
    if list(control["preprocessing"]) != list(treatment["preprocessing"]):
        found.append(PREPROCESSING_FACTOR)
    return found


def same_arm(a: dict, b: dict) -> bool:
    """Two arms that train the same model in the same way (so a reference equal to its arm needs no run)."""
    return a["model"] == b["model"] and not factors(a, b)


@lru_cache(maxsize=None)  # a cached dataset does not change while the program runs
def class_counts(dataset: str) -> tuple[int, ...]:
    """Rows per class of a registered dataset, read offline (the catalog does not record balance)."""
    labels = datasets.load_dataset(dataset)[datasets.TARGET_COLUMN].astype(str)
    return tuple(labels.value_counts().tolist())


def class_ratio(dataset: str) -> float:
    counts = class_counts(dataset)
    return max(counts) / min(counts)


def metric_problem(dataset: str, metric: str) -> str | None:
    """G0, a rule (never reported as recall): accuracy on a dataset whose class ratio is above the line."""
    if metric != "accuracy":
        return None
    ratio = class_ratio(dataset)
    if ratio <= IMBALANCE_LINE:
        return None
    return (f"accuracy is misleading on {dataset}: its class ratio is {ratio:.1f}:1, above {IMBALANCE_LINE:g}:1, so "
            f"predicting the largest class alone scores high; choose balanced_accuracy, f1 or roc_auc instead")


def guard_seeds(k: int = GUARD_SEEDS) -> list[int]:
    return list(range(GUARD_SEED_START, GUARD_SEED_START + k))


def _copy_arm(arm: dict, params: dict | None = None, preprocessing: list | None = None) -> dict:
    return {"model": arm["model"], "params": dict(arm["params"] if params is None else params),
            "preprocessing": list(arm["preprocessing"] if preprocessing is None else preprocessing)}


def reference_for(rule: str, control: dict, treatment: dict) -> dict:
    """The control's reference for a rule: the control with some settings put back to the library default.

    G2 (two models): all of the control's parameters at default. G3 (one factor): only the tested factor at default.
    G4 (one factor): only the settings both arms share at default; the tested factor stays as the control has it.
    For preprocessing, "default" means no scaler. Leaving a name out of `params` is how a default is set, so no
    default value is ever written here.
    """
    if rule == G2:
        return _copy_arm(control, params={})
    tested = factors(control, treatment)
    if len(tested) != 1 or tested == [MODEL_FACTOR]:
        raise ValueError(f"rule {rule} needs one factor of the same model, got {tested}")
    factor = tested[0]
    if rule == G3:
        if factor == PREPROCESSING_FACTOR:
            return _copy_arm(control, preprocessing=[])
        return _copy_arm(control, params={k: v for k, v in control["params"].items() if k != factor})
    if rule == G4:
        shared = set(nondefault(control)) - {factor}
        return _copy_arm(control, params={k: v for k, v in control["params"].items() if k not in shared})
    raise ValueError(f"rule {rule} has no reference")


def default_runner():
    """The sandbox, looked up at call time (tests replace this function so that no real run starts by accident)."""
    return sandbox.run_config


def reference_gap(experiment: dict, arm: dict, reference: dict, run=None, k: int = GUARD_SEEDS,
                  timeout_s: float | None = None) -> dict | None:
    """Run the arm against its reference once, on guard seeds, in a temporary folder; None if they are the same arm.

    The experiment is an ordinary one (`control` = the arm, `treatment` = the reference) on the registered dataset,
    metric and split size, so it goes through the same template and sandbox as a real run but never under
    data/runs/ and never into the crash rate. The answer is read with the existing verdict code: direction increase,
    min_effect = the existing floor, the existing alpha. No number here is tuned on bug data.
    """
    if same_arm(arm, reference):
        return None
    science = load_yaml("campaign.yaml")["science"]
    run = run or default_runner()
    timeout_s = sandbox.DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
    reference_run = {"dataset": experiment["dataset"], "metric": experiment["metric"], "seeds": guard_seeds(k),
                     "test_size": experiment["test_size"], "control": _copy_arm(arm),
                     "treatment": _copy_arm(reference)}
    found = {"reference": _copy_arm(reference), "answer": UNVERIFIABLE, "mean_gap": None, "ci_low": None,
             "ci_high": None, "seeds_used": None, "run_status": None, "reason": None, "seconds": None}
    with tempfile.TemporaryDirectory(prefix="canary-guard-", ignore_cleanup_errors=True) as folder:
        record = run(reference_run, Path(folder), timeout_s)
        found.update(run_status=record["status"], reason=record.get("reason"), seconds=record.get("seconds"))
        if record["status"] != sandbox.STATUS_OK:
            return found
        results = json.loads((Path(folder) / record["run_id"] / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))
    verdict = prereg.compute_verdict({"direction": "increase", "min_effect": science["min_effect_floor"],
                                      "alpha": science["alpha"]}, results)
    answer = {prereg.SUPPORTED: WEAK, prereg.NOT_SUPPORTED: NOT_WEAK}.get(verdict["outcome"], INCONCLUSIVE)
    found.update(answer=answer, mean_gap=verdict["mean_effect"], ci_low=verdict["ci_low"],
                 ci_high=verdict["ci_high"], seeds_used=len(results["control"]),
                 arm_scores=results["control"], reference_scores=results["treatment"])
    return found
