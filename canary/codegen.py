"""Turn an experiment config into a complete Python script.

Why a template: free-form generated code crashes often (Sakana's AI Scientist lost 42% of its experiments to
coding errors). Here a hypothesis is only a config, so the code around it is always the same known-good script.

Why the output is deterministic and has no run ID in it: two runs with the same config must be byte-identical,
because the Skeptic must not be able to tell run types apart from incidental differences (blinding, Mission 1.5).
"""
from __future__ import annotations

import pprint
from pathlib import Path
from string import Template

import yaml

from canary import datasets
from canary.config import load_yaml

TEMPLATE_PATH = Path(__file__).parent / "templates" / "experiment.py.tmpl"
SCRIPT_NAME = "experiment.py"
CONFIG_NAME = "config.yaml"
DATASET_NAME = "dataset.csv.gz"  # the template reads this exact name from its working directory

# These must match the MODELS and SCALERS tables and the score() function in the template.
MODELS = {"logistic_regression", "random_forest", "gradient_boosting", "svm", "knn", "decision_tree", "gaussian_nb"}
SCALERS = {"standard_scaler", "minmax_scaler", "robust_scaler"}
METRICS = {"accuracy", "balanced_accuracy", "f1", "roc_auc"}

# What the Scientist may set. An open `params` object let the small models write garbled keys and loop until Ollama
# aborted, so each name and type is listed. validate_config stays wider: hand-written configs may use any parameter.
MODEL_PARAMS = {
    "logistic_regression": ["C", "max_iter", "class_weight"],
    "random_forest": ["n_estimators", "max_depth", "class_weight"],
    "gradient_boosting": ["n_estimators", "learning_rate", "max_depth"],
    "svm": ["C", "kernel", "gamma", "class_weight"],
    "knn": ["n_neighbors", "weights"],
    "decision_tree": ["max_depth", "min_samples_leaf", "class_weight"],
    "gaussian_nb": ["var_smoothing"],
}
PARAM_SCHEMAS = {
    "C": {"type": "number"},
    "class_weight": {"enum": ["balanced"]},
    "gamma": {"type": "number"},
    "kernel": {"enum": ["linear", "rbf", "poly", "sigmoid"]},
    "learning_rate": {"type": "number"},
    "max_depth": {"type": "integer"},
    "max_iter": {"type": "integer"},
    "min_samples_leaf": {"type": "integer"},
    "n_estimators": {"type": "integer"},
    "n_neighbors": {"type": "integer"},
    "var_smoothing": {"type": "number"},
    "weights": {"enum": ["uniform", "distance"]},
}
CONFIG_KEYS = {"dataset", "metric", "seeds", "test_size", "control", "treatment"}
ARM_KEYS = {"model", "params", "preprocessing"}


class ConfigError(ValueError):
    """The config cannot produce a script at all. Hyperparameter values are not checked here: see validate_config."""


def _validate_arm(name: str, arm: object) -> None:
    if not isinstance(arm, dict) or set(arm) != ARM_KEYS:
        raise ConfigError(f"{name} must have exactly the keys {sorted(ARM_KEYS)}")
    if arm["model"] not in MODELS:
        raise ConfigError(f"{name}: unknown model {arm['model']!r}")
    if not isinstance(arm["params"], dict) or not all(isinstance(k, str) for k in arm["params"]):
        raise ConfigError(f"{name}: params must be a mapping with text keys")
    if not all(v is None or isinstance(v, (bool, int, float, str)) for v in arm["params"].values()):
        raise ConfigError(f"{name}: param values must be plain numbers, text, booleans or null")
    steps = arm["preprocessing"]
    if not isinstance(steps, list) or not all(isinstance(s, str) and s in SCALERS for s in steps):
        raise ConfigError(f"{name}: preprocessing must be a list drawn from {sorted(SCALERS)}")


def validate_config(config: object) -> None:
    """Reject configs that are structurally wrong, and raise ConfigError with the reason.

    Hyperparameter names and values are left to scikit-learn on purpose: keeping a copy of its rules here would
    go out of date. A bad value therefore shows up as a recorded crash, which is what the crash rate counts.
    """
    if not isinstance(config, dict) or set(config) != CONFIG_KEYS:
        raise ConfigError(f"config must have exactly the keys {sorted(CONFIG_KEYS)}")
    catalog = load_yaml("datasets.yaml")
    classes = {d["name"]: d["classes"] for d in catalog["sklearn"] + catalog["openml"]}
    if config["dataset"] not in classes:
        raise ConfigError(f"unknown dataset {config['dataset']!r}")
    if config["metric"] not in METRICS:
        raise ConfigError(f"unknown metric {config['metric']!r}")
    if config["metric"] == "roc_auc" and classes[config["dataset"]] != 2:
        raise ConfigError("roc_auc needs a two-class dataset")
    seeds = config["seeds"]
    if not isinstance(seeds, list) or not seeds or not all(type(s) is int and s >= 0 for s in seeds):
        raise ConfigError("seeds must be a non-empty list of non-negative integers")
    if len(set(seeds)) != len(seeds):
        raise ConfigError("seeds must not repeat")
    test_size = config["test_size"]
    if type(test_size) is not float or not 0 < test_size < 1:
        raise ConfigError("test_size must be a number between 0 and 1")
    _validate_arm("control", config["control"])
    _validate_arm("treatment", config["treatment"])


def render_script(config: dict) -> str:
    """Return the experiment script for a valid config. The same config always gives the same text."""
    validate_config(config)
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    # pformat writes a Python literal: text values are quoted, so a config value cannot become code.
    return template.substitute(config=pprint.pformat(config, sort_dicts=False, width=100),
                               target_column=repr(datasets.TARGET_COLUMN))


def prepare_run(config: dict, run_dir: Path) -> Path:
    """Write the script, the config and a copy of the dataset to run_dir. Returns the script path.

    The dataset copy makes a run folder complete on its own: the script does not import Canary, needs no paths
    from outside, and can be re-run later even if the cache changes.
    """
    script = render_script(config)
    run_dir.mkdir(parents=True, exist_ok=True)
    datasets.load_dataset(config["dataset"]).to_csv(run_dir / DATASET_NAME, index=False)
    (run_dir / CONFIG_NAME).write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    script_path = run_dir / SCRIPT_NAME
    script_path.write_text(script, encoding="utf-8")
    return script_path
