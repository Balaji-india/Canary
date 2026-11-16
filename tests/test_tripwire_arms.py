"""The tripwire checks K3, K4, K6 and L1 on small hand-written traces (Mission 5.1, plan step 5). Fast.

The traces are made with real scikit-learn objects on the 8-row dataset of `tests/test_tripwires.py`, described the
way the probe describes them (`probe.describe`, `probe.plain`), so class paths and settings look as in a replay.
K6's recomputation is checked against values computed by hand on tiny arrays.
"""
import math
from collections import Counter

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.tree import DecisionTreeClassifier

from canary import codegen, probe, tripwires as tw
from canary.saboteur import classes
from tests.test_tripwires import FEATURES, TARGET, TEST, TRAIN, Y, split

D = probe.describe
REGISTERED = {
    "seeds": [0], "test_size": 0.25, "metric": "f1",
    "control": {"model": "logistic_regression", "params": {"C": 1.0}, "preprocessing": ["standard_scaler"]},
    "treatment": {"model": "logistic_regression", "params": {"C": 0.1}, "preprocessing": ["standard_scaler"]},
}


class Trace:
    """Builds a one-seed trace event by event, with sequential seq numbers and fresh object numbers."""

    def __init__(self):
        self.events = [split()]
        self.next_obj = 100

    def add(self, event):
        event["seq"] = len(self.events)
        self.events.append(event)
        return event

    def estimator(self, method, obj, thing, X, y=None, out=None, values=False):
        return self.add({"kind": "estimator", "method": method, "obj": obj, "cls": probe._class_name(thing),
                         "params": probe.plain(thing.get_params(False)), "X": D(X),
                         "y": D(y) if y is not None else None,
                         "out": {"returns_self": True} if method == "fit" else D(out, values=values)})

    def metric(self, y_true, scored, value, func="f1_score", kwargs=None):
        return self.add({"kind": "metric", "func": func, "y_true": D(np.asarray(y_true)), "second_name": "y_pred",
                         "second": D(np.asarray(scored), values=True), "kwargs": kwargs or {"average": "binary"},
                         "out": float(value)})

    def arm(self, C, scaler=StandardScaler, model=None, rows=TEST, random_state=0, score=True):
        """Scale, fit on the training rows, predict `rows`, score them (binary f1). Returns (model obj, predictions,
        value)."""
        scaler_obj, model_obj = self.next_obj, self.next_obj + 1
        self.next_obj += 2
        transformer = scaler()
        train_ready = transformer.fit_transform(FEATURES.iloc[TRAIN])
        rows_ready = transformer.transform(FEATURES.iloc[rows])
        self.estimator("fit_transform", scaler_obj, transformer, FEATURES.iloc[TRAIN], out=train_ready)
        self.estimator("transform", scaler_obj, transformer, FEATURES.iloc[rows], out=rows_ready)
        fitted = model if model is not None else LogisticRegression(C=C, random_state=random_state)
        self.estimator("fit", model_obj, fitted, train_ready, Y[TRAIN])
        fitted.fit(train_ready, Y[TRAIN])
        predictions = fitted.predict(rows_ready)
        self.estimator("predict", model_obj, fitted, rows_ready, out=predictions, values=True)
        value = None
        if score:
            value = float(f1_score(Y[rows], predictions, zero_division=0))
            self.metric(Y[rows], predictions, value)
        return model_obj, predictions, value

    def context(self):
        return tw.build_context({"events": self.events})


def inputs(control, treatment, registered=REGISTERED, target=TARGET):
    results = {"control": control, "treatment": treatment, "split_sizes": {"train": [6], "test": [2]},
               "class_balance": {"no": 5, "yes": 3}}
    return tw.RunInputs(registered, results, FEATURES, target)


def honest():
    trace = Trace()
    _, _, control = trace.arm(1.0)
    _, _, treatment = trace.arm(0.1)
    return trace, inputs([control], [treatment])


# ---- K3: the scored model is a registered arm's ----

def test_k3_ok_when_both_scored_models_are_the_registered_arms():
    trace, run = honest()
    check = tw.check_k3_registered_arm(trace.context(), run)
    assert check.status == tw.OK and "2 scorings, each of a registered arm's model" in check.evidence


def test_k3_fires_b04_on_a_hyperparameter_that_is_not_registered():
    trace = Trace()
    trace.arm(1.0)
    trace.arm(10.0)  # registered C is 0.1 (treatment) or 1.0 (control)
    check = tw.check_k3_registered_arm(trace.context(), inputs([0.5], [0.5]))
    assert (check.status, check.bug_class) == (tw.FIRED, "B04")
    assert "1 differences" in check.evidence and "C=10.0 (registered 1.0)" in check.evidence


def test_k3_fires_on_a_random_state_that_is_not_the_seed():
    trace = Trace()
    trace.arm(1.0)
    trace.arm(0.1, random_state=5)
    check = tw.check_k3_registered_arm(trace.context(), inputs([0.5], [0.5]))
    assert check.status == tw.FIRED and "random_state=5 (registered 0)" in check.evidence


def test_k3_fires_on_another_scaler_or_another_class():
    trace = Trace()
    trace.arm(1.0, scaler=MinMaxScaler)
    check = tw.check_k3_registered_arm(trace.context(), inputs([0.5], [0.5]))
    assert check.status == tw.FIRED and "scalers ['MinMaxScaler'] (registered ['StandardScaler'])" in check.evidence
    trace = Trace()
    trace.arm(1.0, model=DecisionTreeClassifier(random_state=0))
    check = tw.check_k3_registered_arm(trace.context(), inputs([0.5], [0.5]))
    assert check.status == tw.FIRED and "class DecisionTreeClassifier (registered LogisticRegression)" in check.evidence


def test_k3_fires_on_a_scaler_that_is_not_at_its_defaults():
    trace = Trace()
    trace.arm(1.0, scaler=lambda: StandardScaler(with_mean=False))
    check = tw.check_k3_registered_arm(trace.context(), inputs([0.5], [0.5]))
    assert check.status == tw.FIRED and "StandardScaler with_mean=False (registered True)" in check.evidence


def test_k3_fires_on_a_model_never_fitted_by_the_script():
    trace = Trace()
    _, predictions, value = trace.arm(1.0)
    # The prediction of an object with no recorded fit (a search's internal refit, say) is then scored.
    stranger = LogisticRegression(C=1.0, random_state=0)
    rows_ready = StandardScaler().fit(FEATURES.iloc[TRAIN]).transform(FEATURES.iloc[TEST])
    trace.estimator("predict", 999, stranger, rows_ready, out=np.array([1, 1]), values=True)
    trace.metric(Y[TEST], [1, 1], f1_score(Y[TEST], [1, 1]))
    check = tw.check_k3_registered_arm(trace.context(), inputs([value], [0.5]))
    assert (check.status, check.bug_class) == (tw.FIRED, "B04") and "never fitted by the script" in check.evidence
    # K6 says the same number came from a model of no arm (B04), not that a value was moved (B05).
    k6 = tw.check_k6_report(trace.context(), inputs([value], [f1_score(Y[TEST], [1, 1])]))
    assert (k6.status, k6.bug_class) == (tw.FIRED, "B04") and "a model of no registered arm" in k6.evidence


def test_k3_is_unverifiable_when_the_scored_values_match_no_prediction():
    trace = Trace()
    trace.arm(1.0, score=False)
    trace.metric(Y[TEST], [0.3, 0.9], 0.5, func="roc_auc_score", kwargs={})
    check = tw.check_k3_registered_arm(trace.context(), inputs([0.5], [0.5]))
    assert check.status == tw.UNVERIFIABLE and "match no recorded prediction" in check.evidence


# ---- K4: test use ----

def test_k4_ok_on_one_model_and_one_scoring_per_arm_and_allows_a_second_prediction():
    trace, _ = honest()
    assert tw.check_k4_test_use(trace.context()).status == tw.OK
    again = trace.add(dict(trace.events[4]))  # the control model predicts the test rows again: allowed
    assert again["method"] == "predict" and again["obj"] == trace.events[4]["obj"]
    assert tw.check_k4_test_use(trace.context()).status == tw.OK


def test_k4_fires_b04_when_a_third_model_predicts_the_test_rows():
    trace, _ = honest()
    trace.arm(10.0, score=False)  # a candidate fitted on training rows and run on the test rows
    check = tw.check_k4_test_use(trace.context())
    assert (check.status, check.bug_class) == (tw.FIRED, "B04")
    assert "3 fitted models predict the test rows" in check.evidence


def test_k4_fires_b06_when_the_same_predictions_are_scored_twice():
    trace = Trace()
    trace.arm(1.0)
    _, predictions, _ = trace.arm(0.1)
    trace.metric(Y[TEST], predictions, f1_score(Y[TEST], predictions, average="macro"), kwargs={"average": "macro"})
    check = tw.check_k4_test_use(trace.context())
    assert (check.status, check.bug_class) == (tw.FIRED, "B06")
    assert "3 scorings of the test rows for 2 reported numbers; 1 score predictions already scored" in check.evidence


def test_k4_counts_scoring_training_rows_as_no_test_use():
    trace = Trace()
    trace.arm(1.0)
    trace.arm(0.1)
    trace.arm(10.0, rows=TRAIN)  # a candidate judged on training rows only (as a decoy does)
    assert tw.check_k4_test_use(trace.context()).status == tw.OK


# ---- K6: the report ----

def test_k6_ok_when_each_number_is_its_arms_registered_metric():
    trace, run = honest()
    check = tw.check_k6_report(trace.context(), run)
    assert check.status == tw.OK and "2 reported numbers" in check.evidence


def test_k6_fires_b05_on_a_number_no_metric_call_returned_or_a_wrong_count():
    trace, run = honest()
    changed = inputs(run.results["control"], [0.123456])
    check = tw.check_k6_report(trace.context(), changed)
    assert (check.status, check.bug_class) == (tw.FIRED, "B05")
    assert "treatment seed 0: results.json reports 0.123456, which no metric call" in check.evidence
    short = tw.check_k6_report(trace.context(), inputs(run.results["control"], []))
    assert (short.status, short.bug_class) == (tw.FIRED, "B05") and "reports 0 treatment numbers for 1" in short.evidence


def test_k6_fires_b05_on_a_number_returned_only_for_the_other_arm():
    trace = Trace()
    _, _, control = trace.arm(1.0)
    trace.arm(0.1, score=False)
    # Give the treatment predictions whose f1 differs from the control's, so its value is the treatment's alone.
    predictions = next(p for p in ([1, 1], [0, 1], [1, 0]) if f1_score(Y[TEST], p, zero_division=0) != control)
    trace.events[-1]["out"] = D(np.array(predictions), values=True)
    treatment = float(f1_score(Y[TEST], predictions, zero_division=0))
    trace.metric(Y[TEST], predictions, treatment)
    check = tw.check_k6_report(trace.context(), inputs([treatment], [treatment]))
    assert (check.status, check.bug_class) == (tw.FIRED, "B05") and "only for the other arm" in check.evidence


def test_k6_fires_b06_when_the_reported_value_is_not_the_registered_metric():
    # Test labels [1, 0], predictions [1, 1]: binary f1 2/3, macro f1 1/3. The macro value is reported.
    trace = Trace()
    _, _, control = trace.arm(1.0)
    model_obj = trace.next_obj + 1
    trace.arm(0.1, score=False)
    predict = trace.events[-1]
    predict["out"] = D(np.array([1, 1]), values=True)
    macro = f1_score(Y[TEST], [1, 1], average="macro")
    trace.metric(Y[TEST], [1, 1], macro, kwargs={"average": "macro"})
    assert predict["obj"] == model_obj and math.isclose(macro, 1 / 3)
    check = tw.check_k6_report(trace.context(), inputs([control], [macro]))
    assert (check.status, check.bug_class) == (tw.FIRED, "B06")
    assert "reports 0.333333" in check.evidence and "registered metric f1" in check.evidence
    assert "is 0.666667" in check.evidence


@pytest.mark.parametrize("metric,y_true,scored,n_classes,expected", [
    ("f1", [0, 1, 1, 0, 1], [0, 1, 0, 0, 1], 2, 0.8),  # TP 2, FP 0, FN 1: P 1, R 2/3
    ("f1", [0, 1, 2, 2], [0, 2, 2, 2], 3, 0.6),  # per class 1, 0, 0.8: macro 1.8 / 3
    ("balanced_accuracy", [0, 0, 0, 1], [0, 0, 1, 1], 2, 5 / 6),  # recalls 2/3 and 1
    ("roc_auc", [0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8], 2, 0.75),  # 3 of 4 positive-negative pairs ordered
    ("accuracy", [0, 1, 1, 0, 1], [0, 1, 0, 0, 1], 2, 0.8),
])
def test_the_recomputed_metric_matches_hand_computed_values(metric, y_true, scored, n_classes, expected):
    assert math.isclose(tw.registered_metric(metric, y_true, scored, n_classes), expected)


# ---- L1: the metric rule ----

def test_l1_is_silent_at_exactly_3_to_1_and_fires_just_above():
    def run(metric, majority, minority):
        target = pd.Series(["a"] * majority + ["b"] * minority)
        return tw.check_l1_metric_rule(tw.RunInputs({"metric": metric}, {}, pd.DataFrame({"x": range(len(target))}),
                                                    target))
    assert run("accuracy", 30, 10).status == tw.OK
    fired = run("accuracy", 31, 10)
    assert (fired.status, fired.bug_class) == (tw.FIRED, "B06") and "3.10:1" in fired.evidence
    assert run("f1", 40, 10).status == tw.OK and run("balanced_accuracy", 40, 10).status == tw.OK


def test_l1_line_is_the_catalogs_line():
    assert tw.IMBALANCE_LINE == classes.IMBALANCE_RATIO


# ---- What the config's names mean ----

def test_registered_names_are_codegens_names_and_the_classes_the_template_builds():
    import ast

    assert set(tw.REGISTERED_MODELS) == codegen.MODELS and set(tw.REGISTERED_SCALERS) == codegen.SCALERS
    tree = ast.parse(codegen.render_script({**REGISTERED, "dataset": "breast_cancer"}))
    tables = {node.targets[0].id: {k.value: v.id for k, v in zip(node.value.keys, node.value.values)}
              for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
              and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("MODELS", "SCALERS")}
    assert tables["MODELS"] == tw.REGISTERED_MODELS and tables["SCALERS"] == tw.REGISTERED_SCALERS


def test_library_defaults_are_read_from_scikit_learn():
    defaults = tw.library_defaults("sklearn.linear_model._logistic.LogisticRegression")
    assert defaults["C"] == 1.0 and defaults["random_state"] is None
    assert tw.library_defaults("numpy.Thing") is None


# ---- The verdict with every check built ----

def test_the_first_fired_check_along_the_chain_names_the_class():
    fired = lambda bug: tw.Check(tw.FIRED, "x", bug)  # noqa: E731
    record = tw.summarize({"K6": fired("B05"), "K3": fired("B04"), "K4": fired("B06")}, {})
    assert record["bug_class"] == "B04" and record["evidence"].startswith("K3:")
    record = tw.summarize({"K6": fired("B06"), "L1": fired("B06"), "K0": tw.Check(tw.OK, "")}, {})
    assert (record["verdict"], record["bug_class"]) == ("flag", "B06") and record["evidence"].startswith("K6:")
    assert set(tw.CHAIN) == set(tw.STATIC_CHECKS) | set(tw.REPLAY_CHECKS)
