"""Decoys: the same size and shape as each bug, and provably harmless.

Harmless is checked by running, not by reading: on synthetic data (the saboteur oracles' set-up), each decoy script
must give exactly the clean script's numbers, and the bug class's oracle must stay silent on it.
"""
import ast

import pytest

from canary import blinding, codegen
from canary.saboteur import decoys, transforms
from canary.saboteur.classes import NotApplicable
from tests.test_padding import CONFIG
from tests.test_saboteur import ORACLES, clean_run, execute, make_config, workdir  # noqa: F401 (fixture)

ALL_VARIANTS = sorted(transforms.TRANSFORMS)


def shape(script):
    blinded = blinding.blind_script(script)
    return len(blinded.splitlines()), sum(isinstance(n, ast.stmt) for n in ast.walk(ast.parse(blinded)))


def test_every_decoy_has_its_bugs_line_and_statement_count():
    checked = 0
    for bug_id, tier in ALL_VARIANTS:  # one test, not 20: the suite has a 30 s limit
        try:
            bug = transforms.sabotage(CONFIG, bug_id, tier, measure=False).script
        except NotApplicable:
            continue  # B06 obvious needs imbalanced data here; it has no code anyway
        assert shape(decoys.decoy_script(CONFIG, bug_id, tier)) == shape(bug), (bug_id, tier)
        checked += 1
    assert checked == len(ALL_VARIANTS) - 1


def test_variants_that_only_change_config_get_the_clean_script():
    clean = codegen.render_script(CONFIG)
    for variant in (("B03", "obvious"), ("B06", "obvious"), ("B09", "obvious"), ("B09", "subtle")):
        assert decoys.decoy_script(CONFIG, *variant) == ast.unparse(ast.parse(clean))
    assert decoys.decoy_script(CONFIG, "B10", "subtle") != ast.unparse(ast.parse(clean))


# Three settings, so the decoys meet predict_proba and decision_function, a binary f1 and roc_auc.
HARMLESS_CONFIGS = [make_config(), make_config("logistic_regression", {"C": 1.0, "max_iter": 500}, "f1"),
                    make_config("svm", {"C": 1.0}, "roc_auc")]


@pytest.mark.slow
@pytest.mark.parametrize("config", HARMLESS_CONFIGS, ids=["tree-balanced", "logistic-f1", "svm-roc_auc"])
@pytest.mark.parametrize("bug_id,tier", ALL_VARIANTS)
def test_a_decoy_changes_no_number_and_its_bugs_oracle_stays_silent(bug_id, tier, config, workdir, monkeypatch):
    _, clean_results, _ = clean_run(config, monkeypatch) if config is HARMLESS_CONFIGS[0] else \
        execute(codegen.render_script(config), monkeypatch)
    trace, results, namespace = execute(decoys.decoy_script(config, bug_id, tier), monkeypatch)
    for key in ("control", "treatment", "split_sizes", "class_balance", "seeds", "metric"):
        assert results[key] == clean_results[key], key
    assert not ORACLES[bug_id](trace, results, namespace, config), "the decoy does what the bug does"
