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
