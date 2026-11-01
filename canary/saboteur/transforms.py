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
from dataclasses import dataclass

from canary import codegen
from canary.saboteur.classes import OBVIOUS, SUBTLE, NotApplicable, why_not_applicable


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
# B09: what a crippled control looks like for each model.
CRIPPLED = {
    OBVIOUS: {
        "logistic_regression": {"max_iter": 1}, "random_forest": {"n_estimators": 1, "max_depth": 1},
        "gradient_boosting": {"n_estimators": 1}, "svm": {"max_iter": 1}, "knn": {"n_neighbors": 1},
        "decision_tree": {"max_depth": 1}, "gaussian_nb": {"var_smoothing": 1.0},
    },
    SUBTLE: {
        "logistic_regression": {"C": 0.001}, "random_forest": {"max_depth": 2},
        "gradient_boosting": {"learning_rate": 0.01}, "svm": {"C": 0.01}, "knn": {"n_neighbors": 50},
        "decision_tree": {"min_samples_leaf": 50}, "gaussian_nb": {"var_smoothing": 0.1},
    },
}


def _b01_obvious(tree: ast.Module, config: dict) -> None:
    # This breaks the rule but changes no score when the config has a scaler: a scaler refitted on train undoes any
    # earlier shift and scale exactly. B01 therefore tests whether a reviewer sees the violation, not whether it hurts.
    _insert_after(_function(tree, "main"), LOAD, """
numeric = X.select_dtypes(include='number').columns
X = X.copy()
X[numeric] = StandardScaler().fit_transform(X[numeric])
""")


def _b01_subtle(tree: ast.Module, config: dict) -> None:
    # No cached dataset has missing numeric values, so an imputer alone would do nothing at all, hence the scaler too.
    # With a scaler in the config this still changes no score: see the B01 note in PROGRESS.md.
    position = tree.body.index(_function(tree, "load_data"))
    tree.body[position:position] = _code("""
def prepare_features(X):
    numeric = X.select_dtypes(include='number').columns
    X = X.copy()
    steps = Pipeline([('impute', SimpleImputer(strategy='median')), ('scale', RobustScaler())])
    X[numeric] = steps.fit_transform(X[numeric])
    return X
""")
    _replace(_function(tree, "load_data"), "X = frame", "X = prepare_features(frame)")


def _b02_obvious(tree: ast.Module, config: dict) -> None:
    _insert_before(_function(tree, "load_data"), "return (X, y, class_balance)", "X = X.assign(label_copy=y)")


def _b02_subtle(tree: ast.Module, config: dict) -> None:
    _insert_before(_function(tree, "load_data"), "return (X, y, class_balance)",
                   "X = X.assign(activity_index=y + np.random.default_rng(7).normal(0, 0.1, len(y)))")


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


def _b10_obvious(tree: ast.Module, config: dict) -> None:
    # A quarter of the rare rows stay: with none left, roc_auc would crash and the run would show nothing to review.
    _insert_after(_function(tree, "main"), SPLIT, """
values, counts = np.unique(y_test, return_counts=True)
rare = np.flatnonzero(y_test == values[np.argmin(counts)])
kept = np.setdiff1d(np.arange(len(y_test)), rare[max(1, len(rare) // 4):])
X_test, y_test = X_test.iloc[kept], y_test[kept]
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
kept = np.argsort(prediction_strength(model, X_test_ready))[len(y_test) // 5:]
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


def _sabotaged_config(config: dict, bug_id: str, tier: str) -> dict:
    changed = copy.deepcopy(config)
    if bug_id == "B06":
        changed["metric"] = "accuracy" if tier == OBVIOUS else "f1"
    elif bug_id == "B09":
        changed["control"]["params"].update(CRIPPLED[tier][changed["control"]["model"]])
    return changed


def sabotage(config: dict, bug_id: str, tier: str) -> Sabotaged:
    """Return the experiment with this bug planted. The same input always gives the same script.

    Raises NotApplicable if the bug makes no sense here, and TransformError if planting it would change nothing.
    """
    reason = why_not_applicable(bug_id, tier, config)
    if reason:
        raise NotApplicable(f"{bug_id} {tier}: {reason}")
    changed = _sabotaged_config(config, bug_id, tier)
    tree = ast.parse(codegen.render_script(changed))
    TRANSFORMS[bug_id, tier](tree, changed)
    script = ast.unparse(tree)
    if ast.dump(ast.parse(script)) == ast.dump(ast.parse(codegen.render_script(config))):
        raise TransformError(f"{bug_id} {tier} changed nothing in this experiment")
    return Sabotaged(bug_id, tier, changed, script)
