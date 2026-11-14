"""The tripwire checks S1, S2, K0, K1, K2, K5 and `run_tripwires` (Mission 5.1, plan step 3).

Fast tests: each check on small hand-written traces, one `ok`, one `fired` and (where it applies) one `unverifiable`,
with the evidence counts asserted. Slow tests (`pytest -m slow tests/test_tripwires.py`): real runs on three configs
(natural duplicates and imbalance, multi-class, a scaler with roc_auc): both tiers of B01, B02, B03, B07, B08 and B10
fire on the check the design names, with the class named and nothing unverifiable; the clean script, a sham, a padded
clean script and all 20 decoys pass every built check; the same run always gives the same record.

Tests may import the saboteur, decoys and padding (tests are on the scoring side); the tripwire code may not.
"""
import random
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import pytest

from canary import codegen, controls, padding, probe, replay, sandbox, tripwires as tw
from canary.saboteur import classes, decoys, transforms

D = probe.describe

# ---- Hand-written traces (fast) ----------------------------------------------------------------------------------

# Dataset: 8 rows, columns a and b; target "yes" (3 rows, the minority, label 1) or "no" (5 rows, label 0).
FEATURES = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], "b": [10, 20, 30, 40, 50, 60, 70, 80]})
TARGET = pd.Series(["no", "yes", "no", "no", "yes", "no", "yes", "no"])
Y = (TARGET == "yes").astype(int).to_numpy()
TRAIN, TEST = [0, 1, 2, 3, 4, 5], [6, 7]  # 8 rows, test_size 0.25: ceil(2.0) = 2 test rows
CONFIG = {"seeds": [0], "test_size": 0.25, "metric": "f1"}


def inputs(results=None, config=CONFIG, features=FEATURES, target=TARGET):
    results = {"split_sizes": {"train": [6], "test": [2]}, "class_balance": {"no": 5, "yes": 3}} if results is None else results
    return tw.RunInputs(config, results, features, target)


def split(seq=0, X=FEATURES, y=Y, random_state=0, test_size=0.25, stratify=True, train=TRAIN, test=TEST):
    kwargs = {"test_size": test_size, "random_state": random_state}
    if stratify:
        kwargs["stratify"] = {"data": D(y)}
    X_frame = X if isinstance(X, pd.DataFrame) else pd.DataFrame(X)
    return {"seq": seq, "kind": "split", "inputs": [D(X), D(y)], "kwargs": kwargs,
            "out": [D(X_frame.iloc[train]), D(X_frame.iloc[test]), D(y[train]), D(y[test])]}


def est(seq, method, obj, X, y=None, out=None, values=None):
    event = {"seq": seq, "kind": "estimator", "method": method, "obj": obj, "cls": "sklearn.Model", "X": D(X),
             "y": D(y) if y is not None else None}
    if method == "fit":
        event["out"] = {"returns_self": True}
    elif values is not None:
        event["out"] = D(np.asarray(values), values=True)
    else:
        event["out"] = D(out)
    return event


def metric(seq, y_true, y_pred):
    return {"seq": seq, "kind": "metric", "func": "f1_score", "y_true": D(np.asarray(y_true)), "second_name": "y_pred",
            "second": D(np.asarray(y_pred), values=True), "kwargs": {}, "out": 0.5}


def context(*events):
    return tw.build_context({"events": [split(), *events]})


def honest_events(test_rows=TEST, labels=None):
    """Fit on the training rows, predict the given rows, score them with the given labels."""
    X_test = FEATURES.iloc[test_rows]
    labels = Y[test_rows] if labels is None else labels
    predictions = [1] * len(test_rows)
    return [est(1, "fit", 9, FEATURES.iloc[TRAIN], Y[TRAIN]), est(2, "predict", 9, X_test, values=predictions),
            metric(3, labels, predictions)]


def test_s1_ok_fired_and_unverifiable():
    assert tw.check_s1_split_sizes(inputs()).status == tw.OK
    fired = tw.check_s1_split_sizes(inputs({"split_sizes": {"train": [7], "test": [3]}}))
    assert (fired.status, fired.bug_class) == (tw.FIRED, "B07") and "7 training + 3 test rows = 10" in fired.evidence
    assert "has 8 rows" in fired.evidence
    share = tw.check_s1_split_sizes(inputs({"split_sizes": {"train": [5], "test": [3]}}))
    assert share.status == tw.FIRED and "gives 2" in share.evidence and share.bug_class is None
    assert tw.check_s1_split_sizes(inputs({})).status == tw.UNVERIFIABLE


def test_s2_ok_fired_and_unverifiable():
    assert tw.check_s2_class_balance(inputs()).status == tw.OK
    fired = tw.check_s2_class_balance(inputs({"class_balance": {"no": 5, "yes": 4}}))
    assert fired.status == tw.FIRED and "9 rows" in fired.evidence and "8 rows" in fired.evidence
    assert tw.check_s2_class_balance(inputs({})).status == tw.UNVERIFIABLE


def _replayed(status=sandbox.STATUS_OK, results=None, trace_status="finished"):
    return replay.ReplayResult(status, None if status == sandbox.STATUS_OK else "exit code 1", results,
                               {"status": trace_status, "events": [1, 2, 3]}, 1.0, "", "gone")


def test_k0_ok_only_when_the_replay_reproduces_every_number():
    stored = {"control": [0.9], "runtime_seconds": 1.0}
    ok = tw.check_k0_replay(stored, _replayed(results={"control": [0.9], "runtime_seconds": 3.0}))
    assert ok.status == tw.OK and "3 calls" in ok.evidence
    assert tw.check_k0_replay(stored, _replayed(results={"control": [0.8], "runtime_seconds": 1.0})).status == tw.UNVERIFIABLE
    assert tw.check_k0_replay(stored, _replayed(status=sandbox.STATUS_CRASH)).status == tw.UNVERIFIABLE
    assert tw.check_k0_replay(stored, _replayed(results=stored, trace_status="raised")).status == tw.UNVERIFIABLE
    assert tw.check_k0_replay(stored, None).status == tw.UNVERIFIABLE


def test_k1_ok_on_the_dataset_with_the_registered_split():
    check = tw.check_k1_data_in(context(), inputs())
    assert check.status == tw.OK and "8 rows and 2 columns" in check.evidence


def test_k1_fires_b02_on_an_extra_column():
    leaky = FEATURES.assign(copy=Y)
    check = tw.check_k1_data_in(tw.build_context({"events": [split(X=leaky)]}), inputs())
    assert (check.status, check.bug_class) == (tw.FIRED, "B02") and "3 columns" in check.evidence
    assert "extra ['copy']" in check.evidence


def test_k1_fires_b07_on_rows_the_dataset_does_not_have_and_counts_copies():
    rows = [0, 1, 2, 3, 4, 5, 6, 7, 1, 4]  # two minority rows copied
    more_X, more_y = FEATURES.iloc[rows].reset_index(drop=True), Y[rows]
    event = split(X=more_X, y=more_y, train=[0, 1, 2, 3, 4, 5, 6, 8], test=[7, 9])
    check = tw.check_k1_data_in(tw.build_context({"events": [event]}), inputs())
    assert (check.status, check.bug_class) == (tw.FIRED, "B07")
    assert "10 rows enter" in check.evidence and "2 rows the dataset does not have" in check.evidence


def test_k1_fires_b05_on_an_unregistered_split_or_seed_count():
    other_seed = tw.check_k1_data_in(tw.build_context({"events": [split(random_state=3)]}), inputs())
    assert (other_seed.status, other_seed.bug_class) == (tw.FIRED, "B05") and "random_state 3" in other_seed.evidence
    unstratified = tw.check_k1_data_in(tw.build_context({"events": [split(stratify=False)]}), inputs())
    assert unstratified.status == tw.FIRED and "not stratified" in unstratified.evidence
    two = tw.check_k1_data_in(tw.build_context({"events": [split(0), split(1)]}), inputs())
    assert two.status == tw.FIRED and "2 splits recorded for 1 registered seeds" in two.evidence


def test_k1_fires_when_labels_are_not_a_relabelling_of_the_target():
    shuffled = np.array([1, 0, 0, 1, 0, 0, 1, 0])  # same counts, other rows
    check = tw.check_k1_data_in(tw.build_context({"events": [split(y=shuffled)]}), inputs())
    assert (check.status, check.bug_class) == (tw.FIRED, "B08")
    flipped = 1 - Y  # the majority class became label 1
    check = tw.check_k1_data_in(tw.build_context({"events": [split(y=flipped)]}), inputs())
    assert check.status == tw.FIRED and "label 1 is the majority class (5 of 8 rows)" in check.evidence


def test_k1_unverifiable_without_recorded_rows():
    event = split()
    del event["inputs"][0]["fp"]
    assert tw.check_k1_data_in(tw.build_context({"events": [event]}), inputs()).status == tw.UNVERIFIABLE


def test_k2_ok_on_training_fits_and_fires_on_test_rows():
    assert tw.check_k2_fit_scope(context(*honest_events())).status == tw.OK
    everything = tw.check_k2_fit_scope(context(est(1, "fit", 4, FEATURES)))  # a scaler on all 8 rows
    assert (everything.status, everything.bug_class) == (tw.FIRED, "B01") and "sees 2 test rows" in everything.evidence
    on_test = tw.check_k2_fit_scope(context(est(1, "fit", 5, FEATURES.iloc[TEST], Y[TEST])))
    assert (on_test.status, on_test.bug_class) == (tw.FIRED, "B04") and "on 2 test rows" in on_test.evidence


def test_k2_judges_a_fit_before_the_split_against_the_first_seed():
    trace = {"events": [est(0, "fit", 4, FEATURES), split(seq=1)]}
    check = tw.check_k2_fit_scope(tw.build_context(trace))
    assert (check.status, check.bug_class) == (tw.FIRED, "B01")


def test_k2_unverifiable_on_rows_that_match_nothing():
    stranger = pd.DataFrame({"a": [99.0], "b": [99]})
    assert tw.check_k2_fit_scope(context(est(1, "fit", 4, stranger))).status == tw.UNVERIFIABLE
    assert tw.check_k2_fit_scope(tw.build_context({"events": []})).status == tw.UNVERIFIABLE


def test_k5_ok_when_the_test_pairs_are_scored():
    check = tw.check_k5_scoring(context(*honest_events()))
    assert check.status == tw.OK and "1 metric calls" in check.evidence


def test_k5_fires_b03_on_training_rows():
    check = tw.check_k5_scoring(context(*honest_events(test_rows=[0, 2])))
    assert (check.status, check.bug_class) == (tw.FIRED, "B03") and "2 training pairs" in check.evidence


def test_k5_fires_b10_on_dropped_test_rows_with_the_count():
    check = tw.check_k5_scoring(context(*honest_events(test_rows=[6])))
    assert (check.status, check.bug_class) == (tw.FIRED, "B10") and "1 of the 2 test pairs: 1 left out" in check.evidence


def test_k5_fires_b08_on_test_rows_with_labels_that_are_not_theirs():
    check = tw.check_k5_scoring(context(*honest_events(labels=Y[TEST][::-1])))  # (row 6, 1), (row 7, 0) swapped
    assert (check.status, check.bug_class) == (tw.FIRED, "B08") and "2 of them" in check.evidence


def test_k5_links_a_probability_column_and_is_unverifiable_without_a_prediction():
    proba = [[0.2, 0.8], [0.7, 0.3]]
    events = [est(1, "fit", 9, FEATURES.iloc[TRAIN], Y[TRAIN]),
              est(2, "predict_proba", 9, FEATURES.iloc[TEST], values=proba), metric(3, Y[TEST], [0.8, 0.3])]
    assert tw.check_k5_scoring(context(*events)).status == tw.OK
    unlinked = honest_events()[:1] + [metric(3, Y[TEST], [0.1, 0.9])]
    check = tw.check_k5_scoring(context(*unlinked))
    assert check.status == tw.UNVERIFIABLE and "match no recorded prediction" in check.evidence
    assert tw.check_k5_scoring(context()).status == tw.UNVERIFIABLE  # no metric call at all


def test_k5_is_unverifiable_when_equal_predictions_came_from_different_rows():
    # A constant classifier gives [1, 1] on the test rows and on two training rows: which rows were scored is unknown.
    events = [est(1, "fit", 9, FEATURES.iloc[TRAIN], Y[TRAIN]),
              est(2, "predict", 9, FEATURES.iloc[[0, 1]], values=[1, 1]),
              est(3, "predict", 9, FEATURES.iloc[TEST], values=[1, 1]), metric(4, Y[TEST], [1, 1])]
    check = tw.check_k5_scoring(context(*events))
    assert check.status == tw.UNVERIFIABLE and "different rows" in check.evidence
    same_rows = events[:1] + [est(2, "predict", 9, FEATURES.iloc[TEST], values=[1, 1])] + events[2:]
    assert tw.check_k5_scoring(context(*same_rows)).status == tw.OK  # a second predict on the same rows is fine


def test_an_error_inside_a_check_or_a_missing_file_is_unverifiable_not_a_crash(tmp_path):
    def broken(_):
        raise KeyError("seeds")

    check = tw._guarded(broken, None)
    assert check.status == tw.UNVERIFIABLE and "broken could not run" in check.evidence
    record = tw.run_tripwires(tmp_path, replay=False)  # an empty folder: nothing can be read
    assert record["verdict"] == "flag" and record["bug_class"] is None and record["tier"] == "static"
    assert {c["status"] for n, c in record["checks"].items() if n in ("S1", "S2")} == {tw.UNVERIFIABLE}


def test_the_verdict_fails_closed_and_the_first_link_names_the_class():
    ok, fired_s1, fired_k1 = tw.Check(tw.OK, "fine"), tw.Check(tw.FIRED, "rows", "B07"), tw.Check(tw.FIRED, "x", "B02")
    record = tw.summarize({"S1": fired_s1, "K1": fired_k1, "K2": ok}, {"status": "ok", "seconds": 1.0})
    assert (record["verdict"], record["bug_class"]) == ("flag", "B02") and record["evidence"] == "K1: x"
    doubtful = tw.summarize({"S1": ok, "K0": tw.Check(tw.UNVERIFIABLE, "replay crashed")}, {})
    assert (doubtful["verdict"], doubtful["bug_class"], doubtful["evidence"]) == ("flag", None, "K0: replay crashed")
    clean = tw.summarize({"S1": ok, "S2": ok}, {})
    assert clean["verdict"] == "pass" and clean["checks"]["K3"]["status"] == tw.NOT_BUILT
    assert clean["version"].startswith("v1:") and len(clean["version"]) == 3 + 64


# ---- Real runs (slow) --------------------------------------------------------------------------------------------

CONFIGS = {
    # natural duplicates (246 feature rows) and a 3.2:1 imbalance; binary f1 on the minority class
    "blood": {"dataset": "blood-transfusion-service-center", "metric": "f1", "seeds": [0, 1], "test_size": 0.25,
              "control": {"model": "logistic_regression", "params": {"C": 1.0, "max_iter": 1000},
                          "preprocessing": ["standard_scaler"]},
              "treatment": {"model": "random_forest", "params": {"n_estimators": 25}, "preprocessing": ["standard_scaler"]}},
    "wine": {"dataset": "wine", "metric": "balanced_accuracy", "seeds": [0, 1], "test_size": 0.25,
             "control": {"model": "knn", "params": {"n_neighbors": 5}, "preprocessing": ["minmax_scaler"]},
             "treatment": {"model": "decision_tree", "params": {"max_depth": 4}, "preprocessing": ["minmax_scaler"]}},
    "breast": {"dataset": "breast_cancer", "metric": "roc_auc", "seeds": [0, 1], "test_size": 0.25,
               "control": {"model": "svm", "params": {"C": 1.0}, "preprocessing": ["standard_scaler"]},
               "treatment": {"model": "logistic_regression", "params": {"C": 0.5, "max_iter": 1000},
                             "preprocessing": ["standard_scaler"]}},
}
# The check plan section 4 names for each class built in this step.
EXPECTED_CHECK = {"B01": "K2", "B02": "K1", "B03": "K5", "B07": "K1", "B08": "K5", "B10": "K5"}
CANARIES = [(c, b, t) for c in CONFIGS for b in EXPECTED_CHECK for t in classes.TIERS]
CLEAN = [(c, kind) for c in CONFIGS for kind in ("clean", "sham", "padded")]
DECOYS = [(c, b, t) for c in CONFIGS for (b, t) in sorted(transforms.TRANSFORMS)]
BUILT = ("S1", "S2", "K0", "K1", "K2", "K5")


def _clean_script(name, kind):
    """The plain render (None), a sham, or the plain render with the length-matching helper."""
    config = CONFIGS[name]
    if kind == "sham":
        return controls.make_sham(config, random.Random(1)).script
    if kind == "padded":
        return padding.pad_script(codegen.render_script(config), padding.batch_target([config]), random.Random(2)).script
    return None


def _key(kind, case):
    return (kind,) + case


@pytest.fixture(scope="module")
def records(tmp_path_factory):
    """Run every case once (in parallel threads: each is its own subprocess), then its tripwire record."""
    runs = tmp_path_factory.mktemp("tripwire-runs")
    cases = [_key("canary", c) for c in CANARIES] + [_key("clean", c) for c in CLEAN] + [_key("decoy", c) for c in DECOYS]

    def one(key):
        kind, case = key[0], key[1:]
        config = CONFIGS[case[0]]
        if kind == "canary":
            if not classes.applicable(case[1], case[2], config):
                return key, None
            sabotaged = transforms.sabotage(config, case[1], case[2])
            run_config, script = sabotaged.config, sabotaged.script
        elif kind == "decoy":
            run_config, script = config, decoys.decoy_script(config, case[1], case[2])
        else:
            run_config, script = config, _clean_script(*case)
        record = sandbox.run_config(run_config, runs_dir=runs, script=script)
        assert record["status"] == sandbox.STATUS_OK, (key, record)
        run_dir = runs / record["run_id"]
        return key, {"run_dir": run_dir, "record": tw.run_tripwires(run_dir)}

    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(pool.map(one, cases))


def _not_unverifiable(record):
    return [n for n in BUILT if record["checks"][n]["status"] == tw.UNVERIFIABLE]


@pytest.mark.slow
@pytest.mark.parametrize("config,bug,tier", CANARIES)
def test_each_built_class_fires_on_its_check_with_the_class_named(config, bug, tier, records):
    result = records[_key("canary", (config, bug, tier))]
    if result is None:
        pytest.skip(f"{bug} {tier} is not applicable to {config}")
    record = result["record"]
    assert record["verdict"] == "flag", record
    assert record["checks"][EXPECTED_CHECK[bug]]["status"] == tw.FIRED, record
    assert record["bug_class"] == bug, record
    assert not _not_unverifiable(record), record


@pytest.mark.slow
@pytest.mark.parametrize("config,kind", CLEAN)
def test_clean_sham_and_padded_scripts_pass_every_built_check(config, kind, records):
    record = records[_key("clean", (config, kind))]["record"]
    assert record["verdict"] == "pass", record
    assert all(record["checks"][n]["status"] == tw.OK for n in BUILT), record


@pytest.mark.slow
@pytest.mark.parametrize("config,bug,tier", DECOYS)
def test_every_decoy_passes_every_built_check(config, bug, tier, records):
    record = records[_key("decoy", (config, bug, tier))]["record"]
    assert record["verdict"] == "pass", record
    assert all(record["checks"][n]["status"] == tw.OK for n in BUILT), record


@pytest.mark.slow
def test_the_same_run_always_gives_the_same_record(records):
    for key in (_key("clean", ("blood", "clean")), _key("canary", ("blood", "B07", "subtle"))):
        first = records[key]
        again = tw.run_tripwires(first["run_dir"])
        strip = lambda r: {**r, "replay": {**r["replay"], "seconds": None}}  # noqa: E731  (only timing may differ)
        assert strip(again) == strip(first["record"])


@pytest.mark.slow
def test_the_static_tier_runs_without_executing_anything(records):
    run_dir = records[_key("canary", ("wine", "B07", "obvious"))]["run_dir"]
    record = tw.run_tripwires(run_dir, replay=False)
    assert record["replay"]["status"] == tw.SKIPPED and "K0" not in record["checks"] and record["tier"] == "static"
    assert record["checks"]["S1"]["status"] == tw.FIRED and record["bug_class"] == "B07"
