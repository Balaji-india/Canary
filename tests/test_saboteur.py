"""Prove each planted bug is really there, by watching the script run.

A text check ("the script contains X") would only prove the edit happened. Each oracle below watches what the running
code does, and must be False on the clean script and True on the sabotaged one, so it cannot pass by always saying yes.
Scripts run in-process on small synthetic data, which keeps 20 variants fast.
"""
import ast
import copy
import json

import numpy as np
import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.metrics import f1_score
from sklearn.model_selection import GridSearchCV
from sklearn.preprocessing import StandardScaler

from canary import blinding, codegen, datasets, sandbox
from canary.saboteur import classes, transforms

N_ROWS = 200
TEST_SIZE = 0.25
N_TEST = 50
N_TRAIN = 150


def make_config(model="decision_tree", params=None, metric="balanced_accuracy"):
    params = {"max_depth": 3} if params is None else params
    return {
        "dataset": "breast_cancer", "metric": metric, "seeds": [0, 1, 2], "test_size": TEST_SIZE,
        "control": {"model": model, "params": dict(params), "preprocessing": ["standard_scaler"]},
        "treatment": {"model": model, "params": dict(params), "preprocessing": ["standard_scaler"]},
    }


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A folder holding a synthetic imbalanced dataset (4:1), with a real but imperfect signal and unique rows."""
    rng = np.random.default_rng(0)
    label = (rng.random(N_ROWS) < 0.2).astype(int)
    frame = pd.DataFrame({
        "a": rng.normal(size=N_ROWS) + label, "b": rng.normal(size=N_ROWS), "c": rng.normal(size=N_ROWS) * 5,
        datasets.TARGET_COLUMN: label,
    })
    frame.to_csv(tmp_path / codegen.DATASET_NAME, index=False)
    monkeypatch.chdir(tmp_path)
    # B06 reads class balance from the cache, which tests must not depend on.
    monkeypatch.setattr(classes, "class_counts", lambda dataset: [4, 1])

    def first_rung_is_weaker(config):
        arm = config["control"]
        return 0.5 if transforms.WEAKENING_LADDER[arm["model"]][0].items() <= arm["params"].items() else 0.9

    monkeypatch.setattr(transforms, "_control_score", first_rung_is_weaker)  # B09 subtle must not run a sandbox here
    return tmp_path


class Trace:
    """What one run of a script did."""

    def __init__(self):
        self.prep_fit_rows = []  # rows seen by each scaler or imputer fit
        self.search_fit_rows = []  # rows seen by each GridSearchCV.fit
        self.model_fits = []  # feature arrays given to the models
        self.arms = []  # (arm, X_train, X_test, y_train, y_test, returned value)
        self.scores = []  # (arm index, X, y, value)


def execute(script, monkeypatch):
    """Run a script's main() with spies around the steps the oracles care about. Returns (trace, results, namespace)."""
    trace = Trace()
    namespace = {"__name__": "experiment_under_test"}
    exec(compile(script, "experiment.py", "exec"), namespace)
    build_model, run_arm, score = namespace["build_model"], namespace["run_arm"], namespace["score"]

    def build_spy(arm, seed):
        model = build_model(arm, seed)
        fit = model.fit

        def fit_spy(X, y, **kwargs):
            trace.model_fits.append(np.asarray(X))
            return fit(X, y, **kwargs)

        model.fit = fit_spy
        return model

    def run_spy(arm, X_train, X_test, y_train, y_test, seed, metric):
        trace.current_arm = len(trace.arms)
        value = run_arm(arm, X_train, X_test, y_train, y_test, seed, metric)
        trace.arms.append((arm, X_train, X_test, y_train, y_test, value))
        return value

    def score_spy(model, X, y, metric):
        value = score(model, X, y, metric)
        trace.scores.append((trace.current_arm, np.asarray(X), np.asarray(y), value))
        return value

    namespace.update(build_model=build_spy, run_arm=run_spy, score=score_spy)
    # The spies last for this run only, so a second run in one test does not wrap the first run's spies.
    with monkeypatch.context() as patch:
        for cls in (StandardScaler, SimpleImputer):
            original = cls.fit

            def spy(self, X, y=None, _original=original, **kwargs):
                trace.prep_fit_rows.append(len(X))
                return _original(self, X, y, **kwargs)

            patch.setattr(cls, "fit", spy)
        search_fit = GridSearchCV.fit

        def search_spy(self, X, y=None, **kwargs):
            trace.search_fit_rows.append(len(X))
            return search_fit(self, X, y, **kwargs)

        patch.setattr(GridSearchCV, "fit", search_spy)
        namespace["main"]()
    with open("results.json", encoding="utf-8") as f:
        return trace, json.load(f), namespace


def rows(array):
    return {tuple(np.round(row, 9)) for row in array}


# ---- One oracle per class: "is this bug happening in this run?" ----

def b01_fits_on_all_rows(trace, results, namespace, config):
    return N_ROWS in trace.prep_fit_rows


def b02_feature_tracks_label(trace, results, namespace, config):
    X, y, _ = namespace["load_data"]()
    return any(abs(np.corrcoef(X[column], y)[0, 1]) > 0.3 for column in set(X.columns) - {"a", "b", "c"})


def b03_scores_only_fitted_rows(trace, results, namespace, config):
    return any(rows(X) <= rows(fit) for _, X, _, _ in trace.scores for fit in trace.model_fits)


def b04_search_sees_test_set(trace, results, namespace, config):
    if any(n == N_TEST for n in trace.search_fit_rows):
        return True
    # Model selection: the treatment's test set was scored for several candidates, and the best was kept.
    per_arm = [sum(1 for arm, *_ in trace.scores if arm == i) for i in range(len(trace.arms))]
    return max(per_arm) > 1


def b05_reports_better_than_ran(trace, results, namespace, config):
    ran = [value for arm, *_, value in trace.arms if arm is namespace["CONFIG"]["treatment"]]
    return np.mean(results["treatment"]) > np.mean(ran)


def b06_uses_misleading_metric(trace, results, namespace, config):
    if results["metric"] == "accuracy":
        return max(results["class_balance"].values()) / min(results["class_balance"].values()) > 3
    if results["metric"] != "f1":
        return False
    # The planted score is the better of two averages, so somewhere it must beat the pre-registered binary F1.
    reported = [value for *_, value in trace.arms]
    return any(v > b + 1e-12 for v, b in zip(reported, _binary_f1(trace, namespace)))


def _binary_f1(trace, namespace):
    """Recompute plain binary F1 for each scored arm by rebuilding its fitted model on the same data."""
    values = []
    for arm, X_train, X_test, y_train, y_test, _ in trace.arms:
        preprocessor = namespace["build_preprocessor"](X_train, arm["preprocessing"])
        X_ready = preprocessor.fit_transform(X_train)
        seed = namespace["CONFIG"]["seeds"][len(values) // 2]
        model = namespace["MODELS"][arm["model"]](**arm["params"])
        if "random_state" in model.get_params():
            model.set_params(random_state=seed)
        model.fit(X_ready, y_train)
        values.append(f1_score(y_test, model.predict(preprocessor.transform(X_test)), average="binary"))
    return values


def b07_same_rows_on_both_sides(trace, results, namespace, config):
    # Copies keep their source row's index, so an index on both sides means the same row is in both.
    return any(set(X_train.index) & set(X_test.index) for _, X_train, X_test, *_ in trace.arms)


def b08_labels_do_not_match_rows(trace, results, namespace, config):
    _, truth, _ = namespace["load_data"]()
    return any(not np.array_equal(truth[X_test.index.to_numpy()], y_test) for _, _, X_test, _, y_test, _ in trace.arms)


def b09_control_is_crippled(trace, results, namespace, config):
    return (namespace["CONFIG"]["control"] != config["control"]
            and namespace["CONFIG"]["treatment"] == config["treatment"])


def b10_test_rows_removed(trace, results, namespace, config):
    return any(len(y) < N_TEST for _, _, y, _ in trace.scores)


ORACLES = {
    "B01": b01_fits_on_all_rows, "B02": b02_feature_tracks_label, "B03": b03_scores_only_fitted_rows,
    "B04": b04_search_sees_test_set, "B05": b05_reports_better_than_ran, "B06": b06_uses_misleading_metric,
    "B07": b07_same_rows_on_both_sides, "B08": b08_labels_do_not_match_rows, "B09": b09_control_is_crippled,
    "B10": b10_test_rows_removed,
}
ALL_VARIANTS = sorted(transforms.TRANSFORMS)


def config_for(bug_id, tier):
    # B06 subtle plants its bug in the f1 path, so its clean comparison must be f1 as well.
    return make_config(metric="f1") if (bug_id, tier) == ("B06", "subtle") else make_config()


_clean_runs = {}


def clean_run(config, monkeypatch):
    """Run each clean config once: there are only two, and the suite has a 30 s limit."""
    key = config["metric"]
    if key not in _clean_runs:
        _clean_runs[key] = execute(codegen.render_script(config), monkeypatch)
    return _clean_runs[key]


@pytest.mark.parametrize("bug_id,tier", ALL_VARIANTS)
def test_oracle_sees_the_bug_only_in_the_sabotaged_script(bug_id, tier, workdir, monkeypatch):
    config = config_for(bug_id, tier)
    oracle = ORACLES[bug_id]

    assert not oracle(*clean_run(config, monkeypatch), config), "the oracle fires on a clean script"

    sabotaged = transforms.sabotage(config, bug_id, tier)
    trace, results, namespace = execute(sabotaged.script, monkeypatch)
    assert oracle(trace, results, namespace, config), "the planted bug did not happen"
    # A canary whose results look different would be spotted by its shape instead of by its bug.
    assert sandbox.validate_results(results, sabotaged.config) is None


@pytest.mark.parametrize("tier", ["obvious", "subtle"])
def test_b01_leaky_fit_is_the_one_the_model_uses(tier, workdir, monkeypatch):
    """A train-only refit after the leak would undo it exactly, so there must be none, and the model's inputs must change."""
    config = make_config("logistic_regression", {"C": 1.0, "max_iter": 500})
    clean, _, _ = execute(codegen.render_script(config), monkeypatch)
    planted, _, _ = execute(transforms.sabotage(config, "B01", tier).script, monkeypatch)
    assert N_TRAIN not in planted.prep_fit_rows
    assert not np.allclose(planted.model_fits[0], clean.model_fits[0])


def test_b01_refused_when_no_arm_has_a_scaler():
    config = make_config()
    config["control"]["preprocessing"] = config["treatment"]["preprocessing"] = []
    assert not classes.applicable("B01", "obvious", config)


def mean_score(config, script, arm, monkeypatch):
    return np.mean(execute(script, monkeypatch)[1][arm])


def test_b02_subtle_helps_without_a_perfect_score(workdir, monkeypatch):
    config = make_config()
    clean = mean_score(config, codegen.render_script(config), "treatment", monkeypatch)
    planted = mean_score(config, transforms.sabotage(config, "B02", "subtle").script, "treatment", monkeypatch)
    assert clean < planted < 1.0


def test_b09_subtle_lowers_the_control_when_measured_for_real(workdir, monkeypatch):
    config = make_config()
    monkeypatch.setattr(transforms, "_control_score", lambda c: mean_score(c, codegen.render_script(c), "control", monkeypatch))
    clean = mean_score(config, codegen.render_script(config), "control", monkeypatch)
    assert mean_score(config, transforms.sabotage(config, "B09", "subtle").script, "control", monkeypatch) <= clean - 0.005


def ladder_scores(monkeypatch, score_of_rung):
    """Give the clean control 0.8, and each rung of the decision_tree ladder the score the test chooses."""
    ladder = transforms.WEAKENING_LADDER["decision_tree"]

    def fake(config):
        for position, rung in enumerate(ladder):
            if rung.items() <= config["control"]["params"].items():
                return score_of_rung(position)
        return 0.8

    monkeypatch.setattr(transforms, "_control_score", fake)
    return ladder


def test_b09_subtle_takes_the_mildest_setting_that_really_lowers_the_score(workdir, monkeypatch):
    ladder = ladder_scores(monkeypatch, lambda position: [0.9, 0.798, 0.7, 0.1][position])  # better, too small, enough
    assert ladder[2].items() <= transforms.sabotage(make_config(), "B09", "subtle").config["control"]["params"].items()


def test_b09_subtle_skips_a_setting_that_crashes(workdir, monkeypatch):
    ladder = ladder_scores(monkeypatch, lambda position: [None, 0.7, 0.6, 0.5][position])
    assert ladder[1].items() <= transforms.sabotage(make_config(), "B09", "subtle").config["control"]["params"].items()


def test_b09_subtle_refused_when_nothing_weakens_the_control(workdir, monkeypatch):
    ladder_scores(monkeypatch, lambda position: 0.95)
    with pytest.raises(classes.NotApplicable):
        transforms.sabotage(make_config(), "B09", "subtle")


@pytest.mark.parametrize("tier", ["obvious", "subtle"])
def test_b10_raises_the_score_and_keeps_every_class(tier, workdir, monkeypatch):
    config = make_config()
    clean = mean_score(config, codegen.render_script(config), "treatment", monkeypatch)
    trace, results, _ = execute(transforms.sabotage(config, "B10", tier).script, monkeypatch)
    assert np.mean(results["treatment"]) > clean
    assert all(len(np.unique(y)) == 2 for _, _, y, _ in trace.scores)


def test_catalog_and_transforms_cover_the_same_20_variants():
    assert set(transforms.TRANSFORMS) == {(b, t) for b in classes.catalog() for t in classes.TIERS}
    assert len(transforms.TRANSFORMS) == 20


def test_tiers_of_a_class_are_different_bugs(workdir):
    for bug_id in classes.catalog():
        config = config_for(bug_id, "subtle")
        obvious = transforms.sabotage(make_config(), bug_id, "obvious").script
        assert obvious != transforms.sabotage(config, bug_id, "subtle").script


@pytest.mark.parametrize("bug_id,tier", ALL_VARIANTS)
def test_same_input_gives_the_same_script(bug_id, tier, workdir):
    config = config_for(bug_id, tier)
    assert (transforms.sabotage(config, bug_id, tier).script
            == transforms.sabotage(copy.deepcopy(config), bug_id, tier).script)


def test_input_config_is_not_modified(workdir):
    config = make_config()
    before = copy.deepcopy(config)
    transforms.sabotage(config, "B09", "obvious")
    transforms.sabotage(config, "B06", "obvious")
    assert config == before


@pytest.mark.parametrize("bug_id,tier", ALL_VARIANTS)
def test_blinded_script_has_no_giveaway_words(bug_id, tier, workdir):
    text = blinding.blind_script(transforms.sabotage(config_for(bug_id, tier), bug_id, tier).script).lower()
    for word in ("bug", "leak", "sabot", "canary", "cheat", "cherry", "plant", "oversampl", "cripple"):
        assert word not in text


@pytest.mark.parametrize("bug_id,tier", ALL_VARIANTS)
def test_sabotaged_script_never_imports_canary(bug_id, tier, workdir):
    tree = ast.parse(transforms.sabotage(config_for(bug_id, tier), bug_id, tier).script)
    roots = {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    roots |= {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert "canary" not in roots


@pytest.mark.parametrize("model,params", [
    ("logistic_regression", {"C": 1.0, "max_iter": 500}), ("random_forest", {"n_estimators": 5}),
    ("gradient_boosting", {"n_estimators": 5}), ("svm", {"C": 1.0}), ("knn", {"n_neighbors": 5}),
    ("decision_tree", {"max_depth": 3}), ("gaussian_nb", {}),
])
def test_model_dependent_bugs_run_on_every_model(model, params, workdir, monkeypatch):
    """One seed is enough here: this only checks that scikit-learn accepts what the tables and helpers do."""
    config = make_config(model, params)
    config["seeds"] = [0]
    for variant in [("B04", "subtle"), ("B09", "obvious"), ("B10", "subtle")]:
        _, results, _ = execute(transforms.sabotage(config, *variant).script, monkeypatch)
        assert len(results["treatment"]) == 1


def test_tables_cover_every_model():
    assert set(transforms.SEARCH_SPACE) == codegen.MODELS
    assert set(transforms.CRIPPLED) == set(transforms.WEAKENING_LADDER) == codegen.MODELS


def test_weak_baseline_only_touches_the_control_arm(workdir):
    config = make_config()
    changed = transforms.sabotage(config, "B09", "obvious").config
    assert changed["treatment"] == config["treatment"]
    assert changed["control"]["params"] != config["control"]["params"]


def test_metric_bugs_change_the_config_so_the_prereg_can_match(workdir):
    assert transforms.sabotage(make_config(), "B06", "obvious").config["metric"] == "accuracy"
    assert transforms.sabotage(make_config(), "B06", "subtle").config["metric"] == "f1"


def test_accuracy_bug_refused_on_balanced_data(monkeypatch):
    monkeypatch.setattr(classes, "class_counts", lambda dataset: [60, 40])
    assert not classes.applicable("B06", "obvious", make_config())
    with pytest.raises(classes.NotApplicable):
        transforms.sabotage(make_config(), "B06", "obvious")


def test_accuracy_bug_refused_when_config_already_uses_accuracy(monkeypatch):
    monkeypatch.setattr(classes, "class_counts", lambda dataset: [90, 10])
    assert not classes.applicable("B06", "obvious", make_config(metric="accuracy"))


def test_exactly_three_to_one_is_not_imbalanced(monkeypatch):
    monkeypatch.setattr(classes, "class_counts", lambda dataset: [75, 25])
    assert not classes.applicable("B06", "obvious", make_config())


def test_averaging_bug_refused_on_multiclass(monkeypatch):
    monkeypatch.setattr(classes, "class_counts", lambda dataset: [50, 40, 30])
    assert not classes.applicable("B06", "subtle", make_config())


def test_seed_bug_refused_with_one_seed():
    config = make_config()
    config["seeds"] = [0]
    assert not classes.applicable("B05", "obvious", config)


def test_unknown_class_or_tier_is_an_error():
    with pytest.raises(KeyError):
        classes.applicable("B99", "obvious", make_config())
    with pytest.raises(KeyError):
        classes.applicable("B01", "medium", make_config())


def test_template_drift_fails_loudly():
    """If the template stops matching, planting must raise instead of leaving a clean script labelled as a canary."""
    tree = ast.parse("def main():\n    pass\n")
    with pytest.raises(transforms.TransformError):
        transforms._b01_obvious(tree, make_config())
    with pytest.raises(transforms.TransformError):
        transforms._b03_obvious(tree, make_config())


def test_ambiguous_statement_fails_loudly():
    tree = ast.parse("def f():\n    x = 1\n    x = 1\n")
    with pytest.raises(transforms.TransformError):
        transforms._replace(tree.body[0], "x = 1", "y = 2")


def test_a_transform_that_changes_nothing_is_refused(monkeypatch, workdir):
    monkeypatch.setitem(transforms.TRANSFORMS, ("B01", "obvious"), lambda tree, config: None)
    with pytest.raises(transforms.TransformError):
        transforms.sabotage(make_config(), "B01", "obvious")


def test_prepare_run_writes_the_given_script(tmp_path, monkeypatch):
    """This is the route a sabotaged script takes into a run folder."""
    monkeypatch.setattr(codegen.datasets, "load_dataset", lambda name: pd.DataFrame({"a": [1], "__target__": [0]}))
    config = make_config()
    path = codegen.prepare_run(config, tmp_path, script="print('changed')\n")
    assert path.read_text(encoding="utf-8") == "print('changed')\n"
    assert codegen.prepare_run(config, tmp_path / "plain").read_text(encoding="utf-8") == codegen.render_script(config)
