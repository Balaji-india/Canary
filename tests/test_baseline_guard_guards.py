"""Guards: the baseline guard has no route to the ground truth and no hand-written list of values (plan section 5).

Why: the people who designed the guard have read the saboteur, which plants B09 by handicapping the control. If the
guard could read the sealed table, or held a table of "bad" hyperparameter values, a good score on planted canaries
would prove nothing. These tests read the guard's source, in the style of tests/test_tripwire_guards.py.
"""
import ast
import re

import pytest

from canary import baseline_guard, codegen
from tests.test_skeptic import PACKAGE, canary_imports, reachable_modules
from tests.test_tripwire_guards import GUARD_CONFIG, _saboteur_vocabulary, _tokens

SOURCE = PACKAGE / "baseline_guard.py"
ALLOWED = {"canary.codegen", "canary.config", "canary.datasets", "canary.prereg", "canary.sandbox"}
FORBIDDEN_MODULES = ("canary.sealed", "canary.controls", "canary.mixer", "canary.trust", "canary.padding",
                     "canary.ledger", "canary.scientist", "canary.skeptic", "canary.blinding")


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def _docstring_ids(tree: ast.AST) -> set:
    return {id(owner.body[0].value) for owner in ast.walk(tree)
            if isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and owner.body
            and isinstance(owner.body[0], ast.Expr)}


def _parameter_names() -> set:
    """Every hyperparameter any of the seven models has, plus the ones the Scientist may set. `random_state` is left
    out (the guard ignores it by name), and so are the config's own keys (`metric` is also a knn parameter)."""
    names = set(codegen.PARAM_SCHEMAS)
    for model in baseline_guard.ESTIMATORS:
        names |= set(baseline_guard.estimator_class(model)().get_params())
    return names - baseline_guard.IGNORED_PARAMS - codegen.CONFIG_KEYS - codegen.ARM_KEYS


def test_guard_imports_only_what_is_allowed():
    assert canary_imports(SOURCE) <= ALLOWED


def test_no_import_chain_from_the_guard_reaches_ground_truth():
    reached = reachable_modules("canary.baseline_guard")
    assert reached - {"canary.baseline_guard"} <= ALLOWED, reached
    for module in reached:
        assert module not in FORBIDDEN_MODULES and not module.startswith("canary.saboteur"), module


def test_guard_never_names_the_sealed_table_plans_twins_or_the_catalog():
    source = _source()
    for word in ("sealed.db", "run_types", "run_type", "sealed_plans", "twins", "bug_classes", "canary.saboteur",
                 "from canary import saboteur", "IMBALANCE_RATIO"):
        assert word not in source, f"baseline_guard.py mentions {word}"


def test_no_identifier_or_text_the_saboteur_adds_appears_in_the_guard():
    assert not (_saboteur_vocabulary() & _tokens(ast.parse(_source())))


def test_the_guard_names_no_hyperparameter_in_text():
    """Defaults come from scikit-learn at run time; the guard never names a setting, so it cannot single one out."""
    tree = ast.parse(_source())
    docstrings = _docstring_ids(tree)
    names = _parameter_names()
    assert {"C", "max_iter", "max_depth", "n_neighbors", "var_smoothing"} <= names  # proves the list is real
    texts = {node.value for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings}
    assert not (texts & names), texts & names
    keywords = {node.arg for node in ast.walk(tree) if isinstance(node, ast.keyword) and node.arg}
    assert not (keywords & names), keywords & names


def test_the_guard_holds_no_table_of_parameter_values():
    """No dict literal keyed by a parameter name, and no dict, list, tuple or set literal holding a number."""
    tree = ast.parse(_source())
    names = _parameter_names()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                assert not (isinstance(key, ast.Constant) and key.value in names), ast.unparse(node)
            for value in node.values:
                assert not (isinstance(value, ast.Constant) and isinstance(value.value, (int, float))
                            and not isinstance(value.value, bool)), ast.unparse(node)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            numbers = [e for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, (int, float))
                       and not isinstance(e.value, bool)]
            assert len(numbers) < 2, ast.unparse(node)


def test_the_estimator_table_matches_the_template():
    """The guard reads defaults from the same classes the experiment script builds."""
    rendered = codegen.render_script(GUARD_CONFIG)
    tree = ast.parse(rendered)
    imported = {alias.name: node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                for alias in node.names}
    models = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                  and getattr(node.targets[0], "id", None) == "MODELS")
    template = {key.value: (imported[value.id], value.id) for key, value in zip(models.keys, models.values)}
    assert template == baseline_guard.ESTIMATORS
    assert set(template) == codegen.MODELS


def test_the_template_still_sets_random_state_per_seed():
    """The guard ignores random_state only because the template overwrites it with the seed in both arms."""
    rendered = codegen.render_script(GUARD_CONFIG)
    assert re.search(r'if "random_state" in model\.get_params\(\):\s+model\.set_params\(random_state=seed\)', rendered)


@pytest.mark.parametrize("word", ["saboteur", "B09", "canary_measure", "sabotage"])
def test_guard_code_has_no_saboteur_words_outside_docstrings(word):
    tree = ast.parse(_source())
    docstrings = _docstring_ids(tree)
    texts = [node.value for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]
    identifiers = _tokens(tree) - set(texts)
    assert not any(word in t for t in texts) and not any(word in i for i in identifiers)


@pytest.mark.parametrize("name", ["skeptic.py", "blinding.py", "review_tasks.py", "prompts.py"])
def test_reviewer_code_never_reads_the_guard_record(name):
    """Real runs carry a `guard` record in their PROPOSED entry and clones do not (mixer.py writes theirs), so that
    key tells a real run from a clone. The reviewer's code path must never read it, nor PROPOSED entries at all."""
    source = (PACKAGE / name).read_text(encoding="utf-8")
    for word in ("guard", "PROPOSED", "proposed"):
        assert word not in source, f"{name} mentions {word}"
