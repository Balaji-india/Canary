"""Guards: the tripwire code cannot reach the ground truth and copies nothing from the saboteur (Mission 5.1, step 4).

Why: the tripwires were written by someone who read the bug catalog (plan section 7.3). These tests make sure the code
itself has no route to a run's type (sealed table, sealed plans, twins, ledger, mixer, trust, controls, padding,
saboteur) and is not keyed on the planted shapes: no identifier or text constant that a transform, a decoy or the
padding adds to a rendered script appears in the tripwire source. Names that belong to Python, numpy or pandas
(`iloc`, `sorted`, ...) are library vocabulary, not the saboteur's, and are left out of that comparison.
"""
import ast
import builtins
import functools
import hashlib
import keyword
import random
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from canary import codegen, padding, sandbox, tripwires
from canary.saboteur import classes, decoys, transforms
from tests.test_skeptic import PACKAGE, canary_imports, reachable_modules

SOURCES = ("probe.py", "replay.py", "tripwires.py")
ALLOWED = {
    "probe.py": set(),
    "replay.py": {"canary.codegen", "canary.probe", "canary.sandbox"},
    "tripwires.py": {"canary.codegen", "canary.datasets", "canary.probe", "canary.replay", "canary.sandbox"},
}
PERMITTED = {"canary.config", "canary.codegen", "canary.datasets", "canary.sandbox", "canary.probe", "canary.replay"}
FORBIDDEN_MODULES = ("canary.sealed", "canary.controls", "canary.mixer", "canary.trust", "canary.padding",
                     "canary.ledger")


@pytest.mark.parametrize("name", SOURCES)
def test_tripwire_code_imports_only_what_is_allowed(name):
    assert canary_imports(PACKAGE / name) <= ALLOWED[name]
    assert ALLOWED[name] <= PERMITTED


@pytest.mark.parametrize("start", ["canary.probe", "canary.replay", "canary.tripwires"])
def test_no_import_chain_from_tripwire_code_reaches_ground_truth(start):
    reached = reachable_modules(start)
    assert start == "canary.probe" or "canary.sandbox" in reached  # proves the walk follows imports
    assert reached - {start} <= PERMITTED, reached
    for module in reached:
        assert module not in FORBIDDEN_MODULES and not module.startswith("canary.saboteur"), module


@pytest.mark.parametrize("name", SOURCES)
def test_tripwire_code_never_names_the_sealed_table_plans_or_twins(name):
    source = (PACKAGE / name).read_text(encoding="utf-8")
    for word in ("sealed.db", "run_types", "run_type", "sealed_plans", "twins"):
        assert word not in source, f"{name} mentions {word}"


def _tokens(tree: ast.AST) -> set:
    """Identifiers (names, functions, arguments, attributes, keywords) and text constants other than docstrings."""
    docstrings = {id(owner.body[0].value) for owner in ast.walk(tree)
                  if isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and owner.body
                  and isinstance(owner.body[0], ast.Expr)}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            found.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            found.add(node.value)
    return found


def _library_vocabulary() -> set:
    words = set(dir(builtins)) | set(keyword.kwlist)
    for thing in (np, np.ndarray, np.dtype, np.random.Generator, pd, pd.DataFrame, pd.Series, pd.Index, str, list, dict):
        words |= set(dir(thing))
    return words


GUARD_CONFIG = {"dataset": "breast_cancer", "metric": "f1", "seeds": [0, 1], "test_size": 0.25,
                "control": {"model": "decision_tree", "params": {"max_depth": 3}, "preprocessing": ["standard_scaler"]},
                "treatment": {"model": "random_forest", "params": {"n_estimators": 5}, "preprocessing": ["standard_scaler"]}}


@functools.lru_cache(maxsize=1)
def _saboteur_vocabulary() -> frozenset:
    """Every identifier and text constant a transform, a decoy or the padding adds to the rendered clean script."""
    clean = _tokens(ast.parse(codegen.render_script(GUARD_CONFIG)))
    added = set()
    for bug, tier in sorted(transforms.TRANSFORMS):
        added |= _tokens(ast.parse(decoys.decoy_script(GUARD_CONFIG, bug, tier))) - clean
        try:
            sabotaged = transforms.sabotage(GUARD_CONFIG, bug, tier, measure=False)
        except classes.NotApplicable:  # B06 obvious: accuracy on balanced data is no bug
            continue
        added |= _tokens(ast.parse(sabotaged.script)) - clean
    padded = padding.pad_script(codegen.render_script(GUARD_CONFIG), padding.batch_target([GUARD_CONFIG]),
                                random.Random(2)).script
    added |= _tokens(ast.parse(padded)) - clean
    return frozenset(w for w in added - _library_vocabulary() if len(w.strip(" ,._")) > 2)


def test_the_saboteur_vocabulary_is_found_at_all():
    """Proves the next test compares against something: names the transforms, decoys and padding really add."""
    vocabulary = _saboteur_vocabulary()
    assert {"label_copy", "prediction_strength", "fit_preprocessor", "describe_settings", "kept"} <= vocabulary


@pytest.mark.parametrize("name", SOURCES)
def test_no_identifier_or_text_the_saboteur_adds_appears_in_tripwire_code(name):
    tokens = _tokens(ast.parse((PACKAGE / name).read_text(encoding="utf-8")))
    assert not (_saboteur_vocabulary() & tokens)


@pytest.mark.parametrize("name", ["check_s1_split_sizes", "check_s2_class_balance", "check_k0_replay",
                                  "check_k1_data_in", "check_k2_fit_scope", "check_k5_scoring"])
def test_every_check_states_its_invariant(name):
    assert getattr(tripwires, name).__doc__.startswith("Invariant:")


def _hashes(folder: Path) -> dict:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.mark.slow
def test_a_full_inspection_beside_ground_truth_opens_no_database_and_changes_nothing(tmp_path, monkeypatch):
    """The code tests above read the source; this one watches a real inspection with ground truth lying next to it."""
    from canary import sealed

    runs = tmp_path / "runs"
    record = sandbox.run_config(GUARD_CONFIG, runs_dir=runs)
    run_dir = runs / record["run_id"]
    table = sealed.SealedTable(tmp_path / "sealed.db")
    table.seal(record["run_id"], sealed.CANARY_MEASURE, "B03", "obvious")
    (tmp_path / "twins" / record["run_id"]).mkdir(parents=True)
    (tmp_path / "sealed_plans").mkdir()
    (tmp_path / "sealed_plans" / "batch.json").write_text("{}", encoding="utf-8")
    before = _hashes(run_dir)
    opened = []

    def spy(*args, **kwargs):
        opened.append(args)
        raise AssertionError("a tripwire opened a database")

    monkeypatch.setattr(sqlite3, "connect", spy)
    result = tripwires.run_tripwires(run_dir)
    assert result["verdict"] == "pass" and not opened
    assert _hashes(run_dir) == before
