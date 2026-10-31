import ast
import copy

import pytest
import yaml

from canary import codegen
from canary.config import CONFIG_DIR


@pytest.fixture
def config():
    return yaml.safe_load((CONFIG_DIR / "examples" / "baseline.yaml").read_text(encoding="utf-8"))


def embedded_config(script):
    """Read the CONFIG literal back out of a generated script."""
    for node in ast.parse(script).body:
        if isinstance(node, ast.Assign) and node.targets[0].id == "CONFIG":
            return ast.literal_eval(node.value)
    raise AssertionError("no CONFIG in the script")


def test_baseline_config_is_valid(config):
    codegen.validate_config(config)


def test_script_is_valid_python_that_embeds_the_config(config):
    assert embedded_config(codegen.render_script(config)) == config


def test_same_config_gives_identical_script(config):
    assert codegen.render_script(config) == codegen.render_script(copy.deepcopy(config))


def test_script_survives_the_ast_round_trip_blinding_will_use(config):
    tree = ast.parse(codegen.render_script(config))
    assert ast.dump(ast.parse(ast.unparse(tree))) == ast.dump(tree)


def test_script_never_imports_canary(config):
    """A run folder must stand alone, and an experiment must have no route to the sealed run-type table."""
    roots = set()
    for node in ast.walk(ast.parse(codegen.render_script(config))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module.split(".")[0])
    assert "canary" not in roots


def test_a_text_value_cannot_become_code(config):
    config["control"]["params"]["solver"] = "'); import os; ('"
    script = codegen.render_script(config)
    assert embedded_config(script)["control"]["params"]["solver"] == "'); import os; ('"


def test_template_tables_match_the_validator():
    text = codegen.TEMPLATE_PATH.read_text(encoding="utf-8")
    for name in codegen.MODELS | codegen.SCALERS | (codegen.METRICS - {"f1"}):
        assert f'"{name}"' in text


@pytest.mark.parametrize("change, message", [
    (lambda c: c.update(dataset="nope"), "unknown dataset"),
    (lambda c: c.update(metric="nope"), "unknown metric"),
    (lambda c: c.update(dataset="wine", metric="roc_auc"), "two-class"),
    (lambda c: c.update(seeds=[]), "non-empty"),
    (lambda c: c.update(seeds=[1, 1]), "repeat"),
    (lambda c: c.update(seeds=[True]), "non-negative"),
    (lambda c: c.update(test_size=1.5), "between 0 and 1"),
    (lambda c: c.update(extra=1), "exactly the keys"),
    (lambda c: c.pop("control"), "exactly the keys"),
    (lambda c: c["control"].update(model="nope"), "unknown model"),
    (lambda c: c["treatment"].update(preprocessing=["nope"]), "preprocessing"),
    (lambda c: c["control"].update(params={"C": [1, 2]}), "param values"),
])
def test_bad_configs_are_rejected(config, change, message):
    change(config)
    with pytest.raises(codegen.ConfigError, match=message):
        codegen.validate_config(config)


def test_non_mapping_config_is_rejected():
    with pytest.raises(codegen.ConfigError):
        codegen.validate_config(["not", "a", "mapping"])


def test_prepare_run_writes_a_complete_folder(config, tmp_path):
    script = codegen.prepare_run(config, tmp_path / "run")
    assert script.name == codegen.SCRIPT_NAME
    assert (tmp_path / "run" / codegen.DATASET_NAME).stat().st_size > 0
    assert yaml.safe_load((tmp_path / "run" / codegen.CONFIG_NAME).read_text(encoding="utf-8")) == config
