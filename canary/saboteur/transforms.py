"""Plant one known bug in a rendered experiment: 10 classes, each with an obvious and a subtle tier.

Why edit the syntax tree: every edit names the exact statement it changes and raises TransformError if that statement
is not found exactly once. If the template changes, a transform fails loudly instead of quietly planting nothing,
which would make a clean run count as a canary.

Why B06 and B09 change the config: those bugs are bad experiment design, so they must also appear in the
pre-registration. A script that disagreed with its pre-registration would add a second, easier clue.

Why neutral names: added names and code must not announce the bug beyond what the bug itself shows. tests/test_saboteur.py
checks this, and blinding removes all comments.

Bugs that favour one arm hit the treatment arm, because that is how a bug produces a false "the treatment helped".
"""
from __future__ import annotations

import ast
import copy
import json
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path

from canary import codegen, sandbox
from canary.config import load_yaml
from canary.saboteur.classes import OBVIOUS, NotApplicable, why_not_applicable


class TransformError(RuntimeError):
    """The script does not have the shape a transform expects. Usually the template changed."""


@dataclass(frozen=True)
class Sabotaged:
    bug_id: str
    tier: str
    config: dict  # may differ from the input (B06, B09); the pre-registration must be built from this one
    script: str


# ---- Small tools for naming and editing one statement ----

def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise TransformError(f"no function {name}()")


def _simple_statements(body: list[ast.stmt]):
    """Yield (list holding it, its position, statement), going inside loops and ifs."""
    for position, statement in enumerate(body):
        if isinstance(statement, (ast.For, ast.If, ast.With, ast.While, ast.Try)):
            yield from _simple_statements(statement.body)
        else:
            yield body, position, statement


def _locate(function: ast.FunctionDef, text: str) -> tuple[list[ast.stmt], int]:
    """Find the one simple statement whose source contains `text`."""
    found = [(body, position) for body, position, statement in _simple_statements(function.body)
             if text in ast.unparse(statement)]
    if len(found) != 1:
        raise TransformError(f"{function.name}(): expected one statement with {text!r}, found {len(found)}")
    return found[0]


def _code(source: str) -> list[ast.stmt]:
    return ast.parse(source).body


def _insert_after(function: ast.FunctionDef, text: str, source: str) -> None:
    body, position = _locate(function, text)
    body[position + 1:position + 1] = _code(source)


def _insert_before(function: ast.FunctionDef, text: str, source: str) -> None:
    body, position = _locate(function, text)
    body[position:position] = _code(source)


def _replace(function: ast.FunctionDef, text: str, source: str) -> None:
    body, position = _locate(function, text)
    body[position:position + 1] = _code(source)


def _add_function(tree: ast.Module, source: str) -> None:
    """Add a helper just before main(), with the other helpers."""
    position = tree.body.index(_function(tree, "main"))
    tree.body[position:position] = _code(source)


def _add_import(tree: ast.Module, module: str, name: str) -> None:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            node.names.append(ast.alias(name))
            return
    raise TransformError(f"no import from {module}")


# ---- The bugs. Each edits the tree in place. ----

SPLIT = "train_test_split("
LOAD = "load_data()"
FINAL_SCORE = "return float(score(model, X_test_ready, y_test, metric))"

# A small search space per model, used by B04. Only the treatment arm's entry goes in the script.
SEARCH_SPACE = {
    "logistic_regression": {"C": [0.01, 0.1, 1.0, 10.0]},
    "random_forest": {"max_depth": [2, 4, 8, None]},
    "gradient_boosting": {"learning_rate": [0.03, 0.1, 0.3]},
    "svm": {"C": [0.1, 1.0, 10.0]},
    "knn": {"n_neighbors": [3, 5, 9]},
    "decision_tree": {"max_depth": [2, 4, 8, None]},
    "gaussian_nb": {"var_smoothing": [1e-9, 1e-6, 1e-3]},
}
# B09 obvious: what a crippled control looks like for each model.
CRIPPLED = {
        "logistic_regression": {"max_iter": 1}, "random_forest": {"n_estimators": 1, "max_depth": 1},
        "gradient_boosting": {"n_estimators": 1}, "svm": {"max_iter": 1}, "knn": {"n_neighbors": 1},
        "decision_tree": {"max_depth": 1}, "gaussian_nb": {"var_smoothing": 1.0},
}
# B09 subtle: settings to try, mildest first. No fixed value is always worse: heavy regularization often improves an
# overfitting tree, so _weakened_params measures each one on this experiment.
WEAKENING_LADDER = {
    "logistic_regression": [{"C": 0.01}, {"C": 0.001}, {"C": 0.0001}],
    "random_forest": [{"max_depth": 2}, {"max_depth": 1}, {"n_estimators": 1, "max_depth": 1}],
    "gradient_boosting": [{"learning_rate": 0.01}, {"learning_rate": 0.001}, {"n_estimators": 1}],
    "svm": [{"C": 0.01}, {"C": 0.001}, {"gamma": 100.0}],
    "knn": [{"n_neighbors": 25}, {"n_neighbors": 51}, {"n_neighbors": 101}, {"n_neighbors": 1}],
    "decision_tree": [{"min_samples_leaf": 20}, {"min_samples_leaf": 50}, {"max_depth": 1},
                      {"max_depth": 1, "splitter": "random"}],
    "gaussian_nb": [{"var_smoothing": 1.0}, {"var_smoothing": 10.0}, {"var_smoothing": 100.0}],
}
B02_SUBTLE_NOISE = 0.7


def _b01_obvious(tree: ast.Module, config: dict) -> None:
    # The fit on all rows replaces the train-only fit. Scaling again afterwards would undo the leak exactly.
    function = _function(tree, "run_arm")
    _replace(function, "preprocessor.fit_transform(X_train)", """
preprocessor.fit(pd.concat([X_train, X_test]))
X_train_ready = preprocessor.transform(X_train)
""")


def _b01_subtle(tree: ast.Module, config: dict) -> None:
    _add_function(tree, """
def fit_preprocessor(X_train, X_test, scaler_names):
    rows = pd.concat([X_train, X_test])
    return build_preprocessor(rows, scaler_names).fit(rows)
""")
    function = _function(tree, "run_arm")
    _replace(function, "preprocessor = build_preprocessor(", "preprocessor = fit_preprocessor(X_train, X_test, arm['preprocessing'])")
    _replace(function, "preprocessor.fit_transform(X_train)", "X_train_ready = preprocessor.transform(X_train)")


def _b02_obvious(tree: ast.Module, config: dict) -> None:
    _insert_before(_function(tree, "load_data"), "return (X, y, class_balance)", "X = X.assign(label_copy=y)")


def _b02_subtle(tree: ast.Module, config: dict) -> None:
    # Enough noise that the feature helps a lot without giving a perfect score, which would itself be a clue.
    _insert_before(_function(tree, "load_data"), "return (X, y, class_balance)",
                   f"X = X.assign(activity_index=y + np.random.default_rng(7).normal(0, {B02_SUBTLE_NOISE}, len(y)))")


def _b03_obvious(tree: ast.Module, config: dict) -> None:
    _replace(_function(tree, "run_arm"), FINAL_SCORE,
             "return float(score(model, X_train_ready, y_train, metric))")


def _b03_subtle(tree: ast.Module, config: dict) -> None:
    _insert_before(_function(tree, "run_arm"), FINAL_SCORE,
                   "X_test_ready, y_test = X_train_ready[:len(y_test)], y_train[:len(y_test)]")


def _b04_obvious(tree: ast.Module, config: dict) -> None:
    _add_import(tree, "sklearn.model_selection", "GridSearchCV")
    space = SEARCH_SPACE[config["treatment"]["model"]]
    _insert_before(_function(tree, "run_arm"), FINAL_SCORE, f"""
if arm is CONFIG['treatment']:
    search = GridSearchCV(build_model(arm, seed), {space!r}, cv=3)
    search.fit(X_test_ready, y_test)
    model = search.best_estimator_
""")


def _b04_subtle(tree: ast.Module, config: dict) -> None:
    _add_import(tree, "sklearn.model_selection", "ParameterGrid")
    space = SEARCH_SPACE[config["treatment"]["model"]]
    _insert_before(_function(tree, "run_arm"), FINAL_SCORE, f"""
if arm is CONFIG['treatment']:
    best_value = score(model, X_test_ready, y_test, metric)
    for candidate_params in ParameterGrid({space!r}):
        candidate = build_model(arm, seed).set_params(**candidate_params)
        candidate.fit(X_train_ready, y_train)
        value = score(candidate, X_test_ready, y_test, metric)
        if value > best_value:
            best_value, model = value, candidate
""")


def _b05_obvious(tree: ast.Module, config: dict) -> None:
    _insert_before(_function(tree, "main"), "'schema_version'", "treatment = [max(treatment)] * len(treatment)")


def _b05_subtle(tree: ast.Module, config: dict) -> None:
    # The results schema needs one value per seed, so the dropped seeds are filled with the mean of the kept ones.
    _insert_before(_function(tree, "main"), "'schema_version'", """
cut = sorted(treatment)[max(1, (len(treatment) - 1) // 2)]
kept_mean = float(np.mean([v for v in treatment if v >= cut]))
treatment = [v if v >= cut else kept_mean for v in treatment]
""")


def _b06_obvious(tree: ast.Module, config: dict) -> None:
    """Only the config changes: the template already supports accuracy."""


def _b06_subtle(tree: ast.Module, config: dict) -> None:
    function = _function(tree, "score")
    _replace(function, "average = ", "")
    _replace(function, "return f1_score(", """
return max(f1_score(y_test, y_pred, average='binary'), f1_score(y_test, y_pred, average='macro'))
""")


def _b07_obvious(tree: ast.Module, config: dict) -> None:
    _insert_after(_function(tree, "main"), LOAD, """
values, counts = np.unique(y, return_counts=True)
rare = np.flatnonzero(y == values[np.argmin(counts)])
X = pd.concat([X, X.iloc[rare]])
y = np.concatenate([y, y[rare]])
""")


def _b07_subtle(tree: ast.Module, config: dict) -> None:
    _insert_after(_function(tree, "main"), LOAD, """
rng = np.random.default_rng(11)
picked = rng.choice(len(y), size=len(y) // 3, replace=False)
copies = X.iloc[picked].copy()
numeric = copies.select_dtypes(include='number').columns
copies[numeric] = copies[numeric].astype(float) + rng.normal(0, 0.01, (len(picked), len(numeric))) * X[numeric].std().to_numpy()
X = pd.concat([X, copies])
y = np.concatenate([y, y[picked]])
""")


def _b08_obvious(tree: ast.Module, config: dict) -> None:
    _insert_after(_function(tree, "main"), SPLIT, "y_test = np.random.default_rng(seed).permutation(y_test)")


def _b08_subtle(tree: ast.Module, config: dict) -> None:
    _insert_after(_function(tree, "main"), SPLIT, """
order = X_test.reset_index(drop=True).sort_values(X_test.columns[0]).index.to_numpy()
X_test = X_test.iloc[order]
y_test = np.roll(y_test[order], 1)
""")


def _b09(tree: ast.Module, config: dict) -> None:
    """Only the config changes: see _sabotaged_config."""


# B10 looks at the labels on purpose: dropping rows without them (rare classes, low confidence) lowered as many scores
# as it raised. The subtle tier drops the most confidently wrong rows: the least confident wrong ones can be a model's
# best-ranked positives, and dropping those lowers roc_auc. At least one row per class stays, because roc_auc crashes on a single class.
def _b10_obvious(tree: ast.Module, config: dict) -> None:
    _insert_before(_function(tree, "run_arm"), FINAL_SCORE, """
wrong = model.predict(X_test_ready) != y_test
dropped = []
for value in np.unique(y_test):
    rows = np.flatnonzero(wrong & (y_test == value))
    dropped.extend(rows[:(y_test == value).sum() - 1])
kept = np.setdiff1d(np.arange(len(y_test)), dropped)
X_test_ready, y_test = X_test_ready[kept], y_test[kept]
""")


def _b10_subtle(tree: ast.Module, config: dict) -> None:
    _add_function(tree, """
def prediction_strength(model, X):
    if hasattr(model, 'predict_proba'):
        return model.predict_proba(X).max(axis=1)
    margin = np.abs(model.decision_function(X))
    return margin if margin.ndim == 1 else margin.max(axis=1)
""")
    _insert_before(_function(tree, "run_arm"), FINAL_SCORE, """
wrong = model.predict(X_test_ready) != y_test
strength = prediction_strength(model, X_test_ready)
dropped = []
for value in np.unique(y_test):
    rows = np.flatnonzero(wrong & (y_test == value))
    rows = rows[np.argsort(-strength[rows])][:(len(rows) + 1) // 2]
    dropped.extend(rows[:(y_test == value).sum() - 1])
kept = np.setdiff1d(np.arange(len(y_test)), dropped)
X_test_ready, y_test = X_test_ready[kept], y_test[kept]
""")


TRANSFORMS = {
    ("B01", "obvious"): _b01_obvious, ("B01", "subtle"): _b01_subtle,
    ("B02", "obvious"): _b02_obvious, ("B02", "subtle"): _b02_subtle,
    ("B03", "obvious"): _b03_obvious, ("B03", "subtle"): _b03_subtle,
    ("B04", "obvious"): _b04_obvious, ("B04", "subtle"): _b04_subtle,
    ("B05", "obvious"): _b05_obvious, ("B05", "subtle"): _b05_subtle,
    ("B06", "obvious"): _b06_obvious, ("B06", "subtle"): _b06_subtle,
    ("B07", "obvious"): _b07_obvious, ("B07", "subtle"): _b07_subtle,
    ("B08", "obvious"): _b08_obvious, ("B08", "subtle"): _b08_subtle,
    ("B09", "obvious"): _b09, ("B09", "subtle"): _b09,
    ("B10", "obvious"): _b10_obvious, ("B10", "subtle"): _b10_subtle,
}


def _control_score(config: dict) -> float | None:
    """Mean control score of a clean run of this config, or None if it failed. Runs in a temporary folder."""
    with tempfile.TemporaryDirectory() as folder:
        record = sandbox.run_config(config, Path(folder))
        if record["status"] != sandbox.STATUS_OK:
            return None
        results = json.loads((Path(folder) / record["run_id"] / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))
    return statistics.fmean(results["control"])


def _weakened_params(config: dict) -> dict:
    """Return the mildest setting that measurably lowers this control, or raise NotApplicable.

    The same seeds and splits are used when the canary runs, so the drop measured here is the drop it will have.
    Mildest first, because the next rung can be so extreme (an F1 near zero) that the score itself gives the bug away.
    """
    floor = load_yaml("campaign.yaml")["science"]["min_effect_floor"]
    clean = _control_score(config)
    if clean is None:
        raise NotApplicable("B09 subtle: the clean run failed, so there is nothing to compare with")
    for rung in WEAKENING_LADDER[config["control"]["model"]]:
        trial = copy.deepcopy(config)
        trial["control"]["params"].update(rung)
        score = _control_score(trial)
        if score is not None and score <= clean - floor:
            return rung
    raise NotApplicable("B09 subtle: no setting lowers this control by the minimum effect")


def _sabotaged_config(config: dict, bug_id: str, tier: str, measure: bool = True) -> dict:
    changed = copy.deepcopy(config)
    if bug_id == "B06":
        changed["metric"] = "accuracy" if tier == OBVIOUS else "f1"
    elif bug_id == "B09":
        # Without measuring, B09 subtle takes the ladder's first rung: right length, maybe not the setting a run uses.
        crippled = (CRIPPLED[changed["control"]["model"]] if tier == OBVIOUS else
                    _weakened_params(config) if measure else WEAKENING_LADDER[config["control"]["model"]][0])
        changed["control"]["params"].update(crippled)
    return changed


def sabotage(config: dict, bug_id: str, tier: str, measure: bool = True) -> Sabotaged:
    """Return the experiment with this bug planted. The same input always gives the same script.

    Raises NotApplicable if the bug makes no sense here, and TransformError if planting it would change nothing.
    B09 subtle runs the experiment to choose its setting, so unlike the others it takes seconds and needs the dataset.
    `measure=False` skips that (the length gate's dry check only needs the script's size, not the exact setting).
    """
    reason = why_not_applicable(bug_id, tier, config)
    if reason:
        raise NotApplicable(f"{bug_id} {tier}: {reason}")
    changed = _sabotaged_config(config, bug_id, tier, measure)
    tree = ast.parse(codegen.render_script(changed))
    TRANSFORMS[bug_id, tier](tree, changed)
    script = ast.unparse(tree)
    if ast.dump(ast.parse(script)) == ast.dump(ast.parse(codegen.render_script(config))):
        raise TransformError(f"{bug_id} {tier} changed nothing in this experiment")
    return Sabotaged(bug_id, tier, changed, script)
