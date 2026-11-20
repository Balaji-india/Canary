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
MODEL_FACTOR = "model"
PREPROCESSING_FACTOR = "preprocessing"


class _Missing:
    """Stands for "this arm has no such parameter" (another model, or an unknown name). Equal only to itself."""

    def __repr__(self) -> str:
        return "<missing>"


MISSING = _Missing()


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
