"""The baseline guard (docs/plans/b09_proposal_guard.md). Fast: the reference runs are faked unless marked slow.

Nothing here is a recall figure: G0 and G1 are rules, and the measured rows are only measured in sitting 2.
"""
import pytest
from sklearn.linear_model import LogisticRegression

from canary import baseline_guard as guard


def arm(model="logistic_regression", params=None, preprocessing=None):
    return {"model": model, "params": dict(params or {}), "preprocessing": list(preprocessing or [])}


# ---- Step 1: the static part ---------------------------------------------------------------------------------------

def test_a_default_written_out_equals_a_default_left_out():
    default_c = LogisticRegression().get_params()["C"]
    assert guard.effective_params(arm(params={"C": default_c})) == guard.effective_params(arm())
    assert guard.factors(arm(params={"C": default_c}), arm()) == []
    assert guard.nondefault(arm(params={"C": default_c})) == []


def test_one_equals_one_point_zero_but_true_is_not_one():
    assert guard.same_value(1, 1.0)
    assert not guard.same_value(True, 1)
    assert not guard.same_value("1", 1)
    assert guard.factors(arm("knn", {"n_neighbors": 5}), arm("knn", {"n_neighbors": 5.0})) == []


def test_none_is_handled():
    assert guard.same_value(None, None)
    assert not guard.same_value(None, 0)
    tree = arm("decision_tree", {"max_depth": None})
    assert guard.nondefault(tree) == []  # None is the library default depth
    assert guard.factors(tree, arm("decision_tree", {"max_depth": 4})) == ["max_depth"]


def test_two_models_give_model_as_the_only_parameter_factor():
    assert guard.factors(arm("knn"), arm("svm", {"C": 10.0})) == ["model"]
    assert guard.factors(arm("knn"), arm("svm", preprocessing=["standard_scaler"])) == ["model", "preprocessing"]


def test_scaler_lists_are_compared_in_order():
    both = ["standard_scaler", "minmax_scaler"]
    assert guard.factors(arm(preprocessing=both), arm(preprocessing=both)) == []
    assert guard.factors(arm(preprocessing=both), arm(preprocessing=both[::-1])) == ["preprocessing"]
    assert guard.factors(arm(params={"C": 0.1}), arm(preprocessing=["robust_scaler"])) == ["C", "preprocessing"]


def test_an_unknown_parameter_is_reported_not_a_crash():
    garbled = arm(params={"C": 1.0, ": ": 'class_weight": "balanced"'})
    assert guard.unknown_params(garbled) == [": "]
    assert guard.nondefault(garbled) == [": "]
    assert guard.factors(garbled, arm()) == [": "]


def test_random_state_is_never_a_difference():
    assert guard.factors(arm("random_forest", {"random_state": 1}), arm("random_forest", {"random_state": 2})) == []
    assert guard.nondefault(arm("random_forest", {"random_state": 1})) == []


def test_defaults_are_read_from_the_library_at_run_time(monkeypatch):
    real = LogisticRegression.get_params
    assert guard.nondefault(arm(params={"C": 5.0})) == ["C"]

    def moved_default(self, deep=True):
        return {**real(self, deep), "C": 5.0}

    monkeypatch.setattr(LogisticRegression, "get_params", moved_default)
    assert guard.nondefault(arm(params={"C": 5.0})) == []
    assert guard.nondefault(arm()) == []
    assert guard.factors(arm(params={"C": 5.0}), arm()) == []


def test_nondefault_lists_every_changed_setting():
    assert guard.nondefault(arm(params={"C": 0.01, "max_iter": 5, "class_weight": "balanced"})) == [
        "C", "class_weight", "max_iter"]


def test_same_arm_needs_the_same_model_and_training():
    assert guard.same_arm(arm(params={"C": 1.0}), arm())
    assert not guard.same_arm(arm(), arm(preprocessing=["standard_scaler"]))
    assert not guard.same_arm(arm("knn"), arm("svm"))


# ---- Step 2: G0, the metric rule -----------------------------------------------------------------------------------

def test_the_guard_line_equals_the_saboteur_line():
    """The test may import the saboteur; the guard may not. So the two constants are compared here."""
    from canary.saboteur import classes
    assert guard.IMBALANCE_LINE == classes.IMBALANCE_RATIO


@pytest.mark.parametrize("counts, fires", [((300, 100), False), ((301, 100), True), ((100, 100), False),
                                           ((500, 50, 100), True), ((90, 30, 30), False)])
def test_g0_is_silent_at_exactly_three_to_one_and_fires_just_above(monkeypatch, counts, fires):
    monkeypatch.setattr(guard, "class_counts", lambda dataset: counts)
    assert (guard.metric_problem("anything", "accuracy") is not None) == fires


@pytest.mark.parametrize("metric", ["balanced_accuracy", "f1", "roc_auc"])
def test_g0_is_silent_for_other_metrics(monkeypatch, metric):
    monkeypatch.setattr(guard, "class_counts", lambda dataset: (1000, 10))
    assert guard.metric_problem("anything", metric) is None


def test_g0_reads_real_class_counts():
    """pc1 is the catalog's imbalanced dataset (about 13:1); wine is near balance."""
    assert guard.class_ratio("pc1") > guard.IMBALANCE_LINE
    assert "balanced_accuracy" in guard.metric_problem("pc1", "accuracy")
    assert guard.metric_problem("wine", "accuracy") is None


# ---- Step 3: the measured part (fake runner; one slow real run) ----------------------------------------------------

import json

from canary import prereg, sandbox

CONFIG = {"dataset": "breast_cancer", "metric": "f1", "seeds": [1, 2, 3, 4, 5], "test_size": 0.25,
          "control": arm(params={"max_iter": 1}), "treatment": arm()}


class FakeRunner:
    """Stands in for sandbox.run_config: writes a results.json with chosen scores, or reports a failed run."""

    def __init__(self, arm_scores=None, reference_scores=None, status=sandbox.STATUS_OK):
        self.arm_scores, self.reference_scores, self.status = arm_scores, reference_scores, status
        self.configs = []

    def __call__(self, config, runs_dir, timeout_s):
        self.configs.append(config)
        run_id = f"guard-{len(self.configs)}"
        if self.status != sandbox.STATUS_OK:
            return {"run_id": run_id, "status": self.status, "reason": "exit code 1", "seconds": 0.1}
        n = len(config["seeds"])
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        results = {"control": list(self.arm_scores or [0.8] * n), "treatment": list(self.reference_scores or [0.8] * n),
                   "split_sizes": {"train": [426] * n, "test": [143] * n}}
        (run_dir / sandbox.RESULTS_NAME).write_text(json.dumps(results), encoding="utf-8")
        return {"run_id": run_id, "status": sandbox.STATUS_OK, "reason": None, "seconds": 0.1}


@pytest.mark.parametrize("arm_scores, reference_scores, answer", [
    ([0.80, 0.81, 0.79, 0.80, 0.80], [0.90, 0.91, 0.89, 0.90, 0.91], guard.WEAK),
    ([0.90, 0.91, 0.89, 0.90, 0.91], [0.90, 0.91, 0.89, 0.90, 0.91], guard.NOT_WEAK),
    ([0.80, 0.90, 0.70, 0.95, 0.75], [0.85, 0.80, 0.90, 0.78, 0.88], guard.INCONCLUSIVE),
])
def test_the_three_verdicts_map_to_weak_not_weak_and_inconclusive(arm_scores, reference_scores, answer):
    runner = FakeRunner(arm_scores, reference_scores)
    gap = guard.reference_gap(CONFIG, CONFIG["control"], CONFIG["treatment"], run=runner)
    assert gap["answer"] == answer
    expected = prereg.compute_verdict({"direction": "increase", "min_effect": 0.005, "alpha": 0.05},
                                      {"control": arm_scores, "treatment": reference_scores,
                                       "split_sizes": {"train": [426] * 5, "test": [143] * 5}})
    assert gap["mean_gap"] == pytest.approx(expected["mean_effect"])
    assert gap["ci_low"] == pytest.approx(expected["ci_low"])


def test_the_floor_and_alpha_come_from_the_campaign_config():
    from canary.config import load_yaml
    science = load_yaml("campaign.yaml")["science"]
    assert science["min_effect_floor"] == 0.005 and science["alpha"] == 0.05
    # a clear gap just under the floor is not weak, just over it is weak
    assert guard.reference_gap(CONFIG, CONFIG["control"], CONFIG["treatment"],
                               run=FakeRunner([0.8] * 5, [0.804] * 5))["answer"] == guard.NOT_WEAK
    assert guard.reference_gap(CONFIG, CONFIG["control"], CONFIG["treatment"],
                               run=FakeRunner([0.8] * 5, [0.806] * 5))["answer"] == guard.WEAK


@pytest.mark.parametrize("status", [sandbox.STATUS_CRASH, sandbox.STATUS_TIMEOUT, sandbox.STATUS_INVALID_RESULTS])
def test_a_failed_reference_run_is_unverifiable(status):
    gap = guard.reference_gap(CONFIG, CONFIG["control"], CONFIG["treatment"], run=FakeRunner(status=status))
    assert gap["answer"] == guard.UNVERIFIABLE and gap["run_status"] == status and gap["mean_gap"] is None


def test_no_run_when_the_reference_equals_the_arm():
    runner = FakeRunner()
    assert guard.reference_gap(CONFIG, arm(params={"C": 1.0}), arm(), run=runner) is None
    assert runner.configs == []


def test_the_reference_run_uses_guard_seeds_and_the_registered_setting():
    runner = FakeRunner()
    guard.reference_gap(CONFIG, CONFIG["control"], CONFIG["treatment"], run=runner)
    (seen,) = runner.configs
    assert seen["seeds"] == guard.guard_seeds() and len(seen["seeds"]) == guard.GUARD_SEEDS == 5
    assert seen["control"] == CONFIG["control"] and seen["treatment"] == CONFIG["treatment"]
    assert (seen["dataset"], seen["metric"], seen["test_size"]) == ("breast_cancer", "f1", 0.25)


@pytest.mark.parametrize("k", [5, 10])
def test_guard_seeds_are_never_run_seeds_or_oracle_seeds(k):
    seeds = guard.guard_seeds(k)
    assert len(set(seeds)) == k
    assert min(seeds) >= prereg.SEED_RANGE  # run seeds are drawn below 100000
    assert max(seeds) < 200_001  # the oracle of sitting 2 starts at 200001


def test_the_reference_run_writes_nothing_under_the_runs_folder(tmp_path, monkeypatch):
    seen = []
    runner = FakeRunner()

    def watching(config, runs_dir, timeout_s):
        seen.append(runs_dir)
        return runner(config, runs_dir, timeout_s)

    guard.reference_gap(CONFIG, CONFIG["control"], CONFIG["treatment"], run=watching)
    (folder,) = seen
    assert sandbox.RUNS_DIR.resolve() not in folder.resolve().parents and not folder.exists()


def test_references_put_back_only_their_own_settings():
    control = arm(params={"C": 0.01, "max_iter": 5}, preprocessing=["standard_scaler"])
    treatment = arm(params={"C": 1.0, "max_iter": 5}, preprocessing=["standard_scaler"])
    assert guard.reference_for(guard.G3, control, treatment) == arm(params={"max_iter": 5},
                                                                    preprocessing=["standard_scaler"])
    assert guard.reference_for(guard.G4, control, treatment) == arm(params={"C": 0.01},
                                                                    preprocessing=["standard_scaler"])
    other = {"model": "knn", "params": {"n_neighbors": 3}, "preprocessing": ["standard_scaler"]}
    assert guard.reference_for(guard.G2, control, other) == arm(preprocessing=["standard_scaler"])


def test_preprocessing_as_the_tested_factor_has_no_scaler_as_its_default():
    control = arm(params={"max_iter": 5}, preprocessing=["minmax_scaler"])
    treatment = arm(params={"max_iter": 5}, preprocessing=["standard_scaler"])
    assert guard.reference_for(guard.G3, control, treatment) == arm(params={"max_iter": 5})
    assert guard.reference_for(guard.G4, control, treatment) == arm(preprocessing=["minmax_scaler"])


def test_a_reference_needs_one_factor_of_the_same_model():
    with pytest.raises(ValueError):
        guard.reference_for(guard.G3, arm(params={"C": 0.1, "max_iter": 5}), arm())
    with pytest.raises(ValueError):
        guard.reference_for(guard.G4, arm(), arm("knn"))


@pytest.mark.slow
def test_a_real_run_finds_one_iteration_of_logistic_regression_weak():
    """The plan's example: `max_iter: 1` on breast_cancer is weak against the library default (real sandbox run)."""
    gap = guard.reference_gap(CONFIG, CONFIG["control"], CONFIG["treatment"], run=sandbox.run_config)
    assert gap["run_status"] == sandbox.STATUS_OK and gap["answer"] == guard.WEAK, gap
