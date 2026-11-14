"""The probe and the replay (Mission 5.1, plan steps 1 and 2).

Fast tests: row fingerprints, checked against values worked out by hand.
Slow tests (`pytest -m slow tests/test_probe.py`): real scripts in subprocesses. They prove the probe is transparent
(every number equals a plain sandbox run's, for all 7 models and 4 metrics), that a replay only reads the run folder
and leaves no temporary folder behind, and that the trace holds the script-level calls and nothing from inside
scikit-learn. This is the go / no-go of plan step 1: no check may be built on a probe that changes the numbers.
"""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from canary import probe, replay, sandbox

# ---- Fingerprints (fast) -----------------------------------------------------------------------------------------


def test_an_int_column_and_its_float_copy_hash_the_same():
    ints = pd.DataFrame({"a": [1, 2, 3], "b": [10, 20, 30]})
    assert probe.row_fingerprints(ints) == probe.row_fingerprints(ints.astype(float))
    assert probe.row_fingerprints(np.array([[1, 10], [2, 20]])) == probe.row_fingerprints(np.array([[1.0, 10.0], [2.0, 20.0]]))


def test_every_kind_of_missing_value_hashes_the_same_and_stays_stable():
    numeric = pd.DataFrame({"a": [np.nan, 1.0]})
    others = [pd.DataFrame({"a": pd.array([None, 1], dtype="Int64")}), pd.DataFrame({"a": [None, 1.0]}),
              pd.DataFrame({"a": np.array([float("nan"), 1], dtype=object)})]
    for frame in others:
        assert probe.row_fingerprints(frame) == probe.row_fingerprints(numeric)
    assert probe.row_fingerprints(numeric) == probe.row_fingerprints(numeric.copy())
    assert probe.row_fingerprints(pd.DataFrame({"a": [0.0]})) != probe.row_fingerprints(pd.DataFrame({"a": [np.nan]}))


def test_minus_zero_is_zero():
    assert probe.row_fingerprints(np.array([[-0.0]])) == probe.row_fingerprints(np.array([[0.0]]))


def test_index_and_column_order_are_ignored_but_values_are_not():
    frame = pd.DataFrame({"a": [1.0, 2.0], "b": ["x", "y"]})
    shuffled = frame[["b", "a"]].set_axis([7, 3])
    assert probe.row_fingerprints(shuffled) == probe.row_fingerprints(frame)
    assert probe.row_fingerprints(frame.assign(a=[1.0, 2.5]))[1] != probe.row_fingerprints(frame)[1]


def test_text_is_not_confused_with_a_number():
    assert probe.row_fingerprints(pd.DataFrame({"a": ["1"]})) != probe.row_fingerprints(pd.DataFrame({"a": [1]}))


def test_identical_rows_get_identical_fingerprints():
    fps = probe.row_fingerprints(np.array([[1.0, 2.0], [3.0, 4.0], [1.0, 2.0]]))
    assert fps[0] == fps[2] != fps[1]
    assert all(0 <= fp < 2 ** 64 for fp in fps)


def test_describe_keeps_values_of_one_dimensional_data_only_unless_asked():
    labels = probe.describe(np.array([0, 1, 1]))
    assert labels["values"] == [0, 1, 1] and labels["shape"] == [3] and len(labels["fp"]) == 3
    matrix = probe.describe(np.array([[0.2, 0.8], [0.6, 0.4]]))
    assert "values" not in matrix
    assert probe.describe(np.array([[0.2, 0.8]]), values=True)["values"] == [[0.2, 0.8]]
    assert probe.describe(pd.DataFrame({"z": [1], "a": [2]}))["columns"] == ["z", "a"]


def test_numbers_identical_ignores_only_the_runtime():
    stored = {"control": [0.9], "treatment": [0.8], "runtime_seconds": 1.0}
    assert replay.numbers_identical(stored, {**stored, "runtime_seconds": 2.0})
    assert not replay.numbers_identical(stored, {**stored, "treatment": [0.8000000001]})
    assert not replay.numbers_identical(stored, None)


# ---- Replays (slow) ----------------------------------------------------------------------------------------------

ARMS = {
    "logistic_regression": {"C": 1.0, "max_iter": 1000}, "random_forest": {"n_estimators": 25},
    "gradient_boosting": {"n_estimators": 25}, "svm": {"C": 1.0}, "knn": {"n_neighbors": 5},
    "decision_tree": {"max_depth": 4}, "gaussian_nb": {},
}
# Four configs per metric cover the 7 models (svm twice: without and with probability, so roc_auc goes through
# decision_function once and predict_proba once). Scalers rotate, so every preprocessing path is replayed too.
PAIRS = [("logistic_regression", "random_forest"), ("gradient_boosting", "svm"), ("knn", "decision_tree"),
         ("gaussian_nb", "svm_probability")]
SCALERS = [["standard_scaler"], ["minmax_scaler"], ["robust_scaler"], []]
METRICS = ["accuracy", "balanced_accuracy", "f1", "roc_auc"]


def _arm(name, scalers):
    if name == "svm_probability":
        return {"model": "svm", "params": {"C": 1.0, "probability": True}, "preprocessing": scalers}
    return {"model": name, "params": dict(ARMS[name]), "preprocessing": scalers}


def _config(metric, pair_index, dataset="breast_cancer"):
    control, treatment = PAIRS[pair_index]
    scalers = SCALERS[pair_index]
    return {"dataset": dataset, "metric": metric, "seeds": [0, 1], "test_size": 0.25,
            "control": _arm(control, scalers), "treatment": _arm(treatment, scalers)}


CASES = {f"{metric}-{i}": _config(metric, i) for metric in METRICS for i in range(len(PAIRS))}
CASES["wine-f1-macro"] = _config("f1", 1, dataset="wine")
# 13 text columns (the one-hot path, fingerprinted as text) and the dataset with 246 duplicate feature rows.
CASES["credit-g-roc_auc"] = _config("roc_auc", 1, dataset="credit-g")
CASES["blood-balanced_accuracy"] = _config("balanced_accuracy", 0, dataset="blood-transfusion-service-center")


def _hashes(folder: Path) -> dict:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    """Run a case once with the plain sandbox, then replay it; cached so several tests share one replay."""
    cache = {}

    def get(name, script=None):
        if name not in cache:
            runs = tmp_path_factory.mktemp(name)
            config = CASES[name] if name in CASES else EXTRA_CASES[name]
            if script is not None:
                script = script(config)
            record = sandbox.run_config(config, runs_dir=runs, script=script)
            assert record["status"] == sandbox.STATUS_OK, record
            run_dir = runs / record["run_id"]
            before = _hashes(run_dir)
            result = replay.replay(run_dir)
            cache[name] = {"run_dir": run_dir, "before": before, "after": _hashes(run_dir), "result": result,
                           "stored": json.loads((run_dir / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))}
        return cache[name]

    return get


EXTRA_CASES = {"b04-obvious-decoy": {
    "dataset": "breast_cancer", "metric": "f1", "seeds": [0, 1], "test_size": 0.25,
    "control": _arm("decision_tree", ["standard_scaler"]), "treatment": _arm("decision_tree", ["standard_scaler"]),
}}


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(CASES))
def test_replayed_numbers_equal_a_plain_run(name, replayed):
    case = replayed(name)
    assert case["result"].status == sandbox.STATUS_OK, case["result"]
    assert replay.numbers_identical(case["stored"], case["result"].results)


@pytest.mark.slow
def test_conditional_methods_answer_hasattr_as_without_the_probe(tmp_path):
    script = '''import json
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.svm import SVC
from sklearn.datasets import make_classification
X, y = make_classification(n_samples=60, random_state=0)
search = GridSearchCV(SVC(), {"C": [0.5, 1.0]}, cv=3)
answers = {
    "svc": hasattr(SVC(), "predict_proba"), "svc_probability": hasattr(SVC(probability=True), "predict_proba"),
    "pipeline": hasattr(Pipeline([("m", SVC())]), "predict_proba"),
    "pipeline_probability": hasattr(Pipeline([("m", SVC(probability=True))]), "predict_proba"),
    "search_unfitted": hasattr(search, "predict_proba"),
}
search.fit(X, y)
answers["search_fitted"] = hasattr(search, "predict_proba")
answers["search_decision"] = hasattr(search, "decision_function")
with open("results.json", "w") as f:
    json.dump(answers, f)
'''
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "experiment.py").write_text(script, encoding="utf-8")
    assert sandbox.run_script(plain / "experiment.py", plain, 60).returncode == 0
    expected = json.loads((plain / "results.json").read_text())
    assert expected["svc"] is False and expected["svc_probability"] is True  # the cases that matter are present
    (plain / "dataset.csv.gz").write_bytes(gzip.compress(b"a\n1\n"))
    result = replay.replay(plain)
    assert result.status == sandbox.STATUS_OK, result
    assert result.results == expected


@pytest.mark.slow
def test_the_run_folder_is_byte_identical_and_the_temporary_folder_is_gone(replayed):
    case = replayed("roc_auc-0")
    assert case["before"] == case["after"]
    assert set(case["before"]) == {"experiment.py", "config.yaml", "dataset.csv.gz", "results.json",
                                   "run_record.json", "stdout.log", "stderr.log"}
    assert not Path(case["result"].workdir).exists()


def _seeds(trace):
    """Cut the events into one list per split."""
    seeds = []
    for event in trace["events"]:
        if event["kind"] == "split":
            seeds.append([])
        seeds[-1].append(event)
    return seeds


@pytest.mark.slow
@pytest.mark.parametrize("name,prediction", [("roc_auc-0", "predict_proba"), ("roc_auc-1", None), ("f1-0", "predict")])
def test_trace_holds_the_script_level_calls_of_each_arm_and_nothing_from_inside(name, prediction, replayed):
    case = replayed(name)
    trace = case["result"].trace
    assert trace["status"] == "finished" and trace["version"] == probe.TRACE_VERSION
    seeds = _seeds(trace)
    assert len(seeds) == 2 and not [e for e in trace["events"] if e["seq"] < seeds[0][0]["seq"]]
    config = CASES[name]
    for events in seeds:
        assert events[0]["kind"] == "split" and len(events) == 11
        for arm, chunk in zip(("control", "treatment"), (events[1:6], events[6:11])):
            methods = [e.get("method", e["kind"]) for e in chunk]
            # svm without probability scores through decision_function, everything else through predict_proba
            expected = prediction or ("decision_function" if config[arm]["params"].get("probability") is not True
                                      and config[arm]["model"] == "svm" else "predict_proba")
            assert methods == ["fit_transform", "transform", "fit", expected, "metric"]
            assert chunk[0]["cls"].endswith("ColumnTransformer") and chunk[0]["obj"] == chunk[1]["obj"]
            assert chunk[2]["obj"] == chunk[3]["obj"] != chunk[0]["obj"]
    inside = ("Pipeline", "SimpleImputer", "Scaler", "OneHotEncoder")
    assert not [e for e in trace["events"] if e["kind"] == "estimator" and e["cls"].endswith(inside)]


@pytest.mark.slow
def test_the_metric_value_and_the_split_are_recorded_exactly(replayed):
    case = replayed("f1-0")
    events = case["result"].trace["events"]
    metrics = [e for e in events if e["kind"] == "metric"]
    assert [m["out"] for m in metrics[0::2]] == case["stored"]["control"]
    assert [m["out"] for m in metrics[1::2]] == case["stored"]["treatment"]
    split = next(e for e in events if e["kind"] == "split")
    assert split["kwargs"]["random_state"] == 0 and split["kwargs"]["test_size"] == 0.25
    assert [len(part["fp"]) for part in split["out"]] == [426, 143, 426, 143]


@pytest.mark.slow
def test_a_grid_search_on_training_rows_is_one_call_with_no_internal_metric(replayed):
    from canary.saboteur import decoys

    case = replayed("b04-obvious-decoy", script=lambda config: decoys.decoy_script(config, "B04", "obvious"))
    result = case["result"]
    assert result.status == sandbox.STATUS_OK and replay.numbers_identical(case["stored"], result.results)
    for events in _seeds(result.trace):
        searches = [e for e in events if e["kind"] == "estimator" and e["cls"].endswith("GridSearchCV")]
        assert [e["method"] for e in searches] == ["fit"]
        assert len([e for e in events if e["kind"] == "metric"]) == 2
        assert not [e for e in events if e.get("method") == "score"]


def _broken_run(tmp_path, script):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "experiment.py").write_text(script, encoding="utf-8")
    (run_dir / "dataset.csv.gz").write_bytes(gzip.compress(b"a\n1\n"))
    return run_dir


@pytest.mark.slow
def test_a_crash_is_a_recorded_status_with_the_trace_kept(tmp_path):
    result = replay.replay(_broken_run(tmp_path, "raise RuntimeError('planned failure')\n"))
    assert result.status == sandbox.STATUS_CRASH
    assert result.trace["status"] == "raised" and "planned failure" in result.trace["error"]
    assert not Path(result.workdir).exists()


@pytest.mark.slow
def test_a_timeout_is_a_recorded_status_not_an_exception(tmp_path):
    result = replay.replay(_broken_run(tmp_path, "import time\ntime.sleep(60)\n"), timeout_s=3)
    assert result.status == sandbox.STATUS_TIMEOUT and result.results is None
    assert not Path(result.workdir).exists()
