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

import argparse
import importlib
import json
import numbers
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from canary import datasets, prereg, sandbox
from canary.config import DATA_DIR, load_yaml

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
GUARD_VERSION = "1"
# Every guard result, rejected or not (plan section 3). Not the ledger: an accepted proposal also carries its record
# in the ledger's PROPOSED entry; rejected ones live only here until the graveyard exists (Mission 3.1, plan trap 8).
LOG_PATH = DATA_DIR / "guard" / "proposals.jsonl"
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
# Added 2026-11-20 (student): arms that do not differ once defaults are filled in. Human queue, never auto-accepted.
G7 = "G7"
# What one reference run says about an arm.
WEAK = "weak"                  # the reference beats the arm by at least the floor, clearly
NOT_WEAK = "not_weak"          # the gap is clearly below the floor
INCONCLUSIVE = "inconclusive"  # these seeds cannot tell: recorded as a number, no action
UNVERIFIABLE = "unverifiable"  # the reference run crashed or timed out (rule G5)
# What the guard decides about a proposal.
OK = "ok"
REJECT = "reject"            # the Scientist gets the feedback sentence and retries (science.proposal_attempts)
HUMAN_QUEUE = "human_queue"  # the run goes ahead; the trust gate (Mission 4.1) never auto-accepts it
WARN = "warn"                # the run goes ahead; the report must say the finding holds in a degraded setting
CONTROL_BELOW_DEFAULT = "control_below_default"  # G3's label
NO_DIFFERENCE = "no_difference"                  # G7's label
WEAK_REGIME = "weak_regime"                      # G4's label


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
    if isinstance(a, numbers.Real) and isinstance(b, numbers.Real):  # numpy numbers too, if a default is one
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


@dataclass(frozen=True)
class GuardRecord:
    """What the guard found for one proposal. Stored beside the pre-registration, never inside it (plan trap 1)."""

    outcome: str             # OK, REJECT, HUMAN_QUEUE or WARN
    rule: str                # the row of the plan's table that decided: G0 to G7
    label: str | None        # CONTROL_BELOW_DEFAULT (G3), WEAK_REGIME (G4), NO_DIFFERENCE (G7) or None
    feedback: str | None     # the sentence a rejected Scientist gets back; None otherwise
    factors: list            # in what the arms differ
    nondefault: dict         # per arm: names of the settings that are not the library default
    tuning_asymmetry: dict   # per arm: how many such settings (unequal tuning effort is counted, not judged)
    unknown_params: dict     # per arm: names the model does not have
    gaps: dict               # rule -> what its reference run found (see reference_gap)
    note: str | None
    k: int
    guard_seeds: list
    sklearn_version: str
    guard_version: str

    def to_dict(self) -> dict:
        return asdict(self)


def _names(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _confounded(tested: list[str]) -> str:
    if MODEL_FACTOR in tested:
        return ("the arms use different models and different preprocessing, so a difference could come from either; "
                "give both arms the same preprocessing so that only the model differs")
    return (f"the arms differ in {_names(tested)}, so a difference could come from any of them; change one thing "
            "only and keep every other setting the same in both arms")


def _weak_control(control: dict, gap: dict) -> str:
    # This tells the Scientist the control's gap before the lock. It concerns the control only, never the treatment
    # or the effect (plan trap 5; the report must say so).
    return (f"the control ({control['model']} with {_names(nondefault(control))} changed) scores below the same model "
            f"at scikit-learn's default settings (mean gap {gap['mean_gap']:.3f} on the guard's own splits); leave "
            "the control's settings at their defaults, or compare one setting of one model")


def _unverifiable(gap: dict) -> str:
    return ("the control could not be checked: a short run of it against its default-setting reference ended in "
            f"{gap['run_status']} ({gap['reason']}); choose settings that run")


def check_config(experiment: dict, run=None, k: int = GUARD_SEEDS, timeout_s: float | None = None) -> GuardRecord:
    """Decide one experiment config by the rules of the plan's section 3, in this order:

    G0 (metric rule), G1 (more than one factor) and G7 (no factor) are read from the config, with no run. A two-model proposal then
    has one reference (G2); a one-factor proposal has G3, then G4. G5 is any of those reference runs failing. A G3
    finding already sends the run to a person, so G4 is not measured after it (one run saved; noted in the record).
    """
    import sklearn

    control, treatment = experiment["control"], experiment["treatment"]
    tested = factors(control, treatment)
    changed = {"control": nondefault(control), "treatment": nondefault(treatment)}
    gaps: dict = {}

    def done(outcome: str, rule: str, label: str | None = None, feedback: str | None = None,
             note: str | None = None) -> GuardRecord:
        return GuardRecord(outcome=outcome, rule=rule, label=label, feedback=feedback, factors=tested,
                           nondefault=changed, tuning_asymmetry={arm: len(names) for arm, names in changed.items()},
                           unknown_params={"control": unknown_params(control), "treatment": unknown_params(treatment)},
                           gaps=gaps, note=note, k=k, guard_seeds=guard_seeds(k), sklearn_version=sklearn.__version__,
                           guard_version=GUARD_VERSION)

    problem = metric_problem(experiment["dataset"], experiment["metric"])
    if problem:
        return done(REJECT, G0, feedback=problem)
    if len(tested) >= 2:
        return done(REJECT, G1, feedback=_confounded(tested))
    if not tested:
        # The hypothesis names a change that the experiment does not make (for example a default written out in
        # one arm only). A person decides; it is never auto-accepted (student, 2026-11-20).
        return done(HUMAN_QUEUE, G7, label=NO_DIFFERENCE,
                    note="the arms train the same model in the same way, so the run can only find no effect")

    def measure(rule: str) -> dict | None:
        gap = reference_gap(experiment, control, reference_for(rule, control, treatment), run, k, timeout_s)
        if gap is not None:
            gaps[rule] = gap
        return gap

    if tested == [MODEL_FACTOR]:
        gap = measure(G2)
        if gap and gap["answer"] == UNVERIFIABLE:
            return done(REJECT, G5, feedback=_unverifiable(gap))
        if gap and gap["answer"] == WEAK:
            return done(REJECT, G2, feedback=_weak_control(control, gap))
        return done(OK, G6)
    gap = measure(G3)
    if gap and gap["answer"] == UNVERIFIABLE:
        return done(REJECT, G5, feedback=_unverifiable(gap))
    if gap and gap["answer"] == WEAK:
        # No feedback: the run goes ahead, so nothing about the gap reaches the proposal (plan section 8, item 10).
        return done(HUMAN_QUEUE, G3, label=CONTROL_BELOW_DEFAULT,
                    note="claim wording: against a control weaker than the library default; G4 not measured")
    gap = measure(G4)
    if gap and gap["answer"] == UNVERIFIABLE:
        return done(REJECT, G5, feedback=_unverifiable(gap))
    if gap and gap["answer"] == WEAK:
        return done(WARN, G4, label=WEAK_REGIME,
                    note="the finding holds only in a setting both arms share that is weaker than the default")
    return done(OK, G6)


def check_proposal(locked: dict, run=None, k: int = GUARD_SEEDS, timeout_s: float | None = None) -> GuardRecord:
    """The guard for a pre-registration about to be locked. It reads the record and never changes it."""
    return check_config(prereg.to_run_config(locked), run, k, timeout_s)


def log_record(record: GuardRecord, locked: dict, path: Path | None = None) -> Path:
    """Append one guard result with the proposal it judged (sitting 2 counts outcomes on natural proposals)."""
    path = LOG_PATH if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"logged_at": datetime.now(timezone.utc).isoformat(), "prereg_sha256": prereg.prereg_hash(locked),
            "hypothesis": locked["hypothesis"], "dataset": locked["dataset"], "metric": locked["metric"],
            "control_config": locked["control_config"], "treatment_config": locked["treatment_config"],
            "guard": record.to_dict()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")
    return path


def _load(path: Path) -> dict:
    """A run config (as in config/examples/) or a pre-registration (with control_config), from YAML or JSON."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return prereg.to_run_config(loaded) if "control_config" in loaded else loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m canary.baseline_guard",
                                     description="Print what the baseline guard says about one experiment config. "
                                                 "A reference run goes in a temporary folder; nothing is logged.")
    parser.add_argument("path", type=Path, help="a run config or a pre-registration (YAML or JSON)")
    parser.add_argument("--k", type=int, default=GUARD_SEEDS, help="number of guard seeds")
    args = parser.parse_args(argv)
    record = check_config(_load(args.path), k=args.k)
    label = f", label {record.label}" if record.label else ""
    tested = _names(record.factors) if record.factors else "no difference"
    print(f"Baseline guard: {record.outcome} (rule {record.rule}{label}); factors: {tested}")
    print(json.dumps(record.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
