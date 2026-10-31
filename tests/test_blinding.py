import ast

import pytest
import yaml

from canary import blinding, codegen
from canary.config import CONFIG_DIR

PLAIN = "def f(x):\n    return x + 1\n\ny = f(2)\n"
DECORATED = '''"""Module docstring: this run is a canary."""
# planted bug here
def f(x):
    """Add one."""
    return   x+1   # sneaky

y   =   f(2)
'''


def results():
    return {"schema_version": 1, "dataset": "wine", "metric": "f1", "seeds": [0], "control": [0.9], "treatment": [0.8],
            "class_balance": {"0": 1}, "split_sizes": {"train": [3], "test": [1]}, "runtime_seconds": 1.5}


def test_comments_docstrings_and_format_do_not_change_the_output():
    assert blinding.blind_script(DECORATED) == blinding.blind_script(PLAIN)


def test_cue_words_in_comments_and_docstrings_are_gone():
    blinded = blinding.blind_script(DECORATED)
    for cue in ("canary", "planted", "sneaky", "Add one"):
        assert cue not in blinded


def test_a_function_holding_only_a_docstring_stays_valid():
    blinded = blinding.blind_script('def f():\n    """Doc."""\n\nclass C:\n    """Doc."""\n')
    ast.parse(blinded)
    assert "Doc" not in blinded


def test_module_holding_only_a_docstring_becomes_empty():
    assert blinding.blind_script('"""Doc."""').strip() == ""


def test_real_code_differences_stay_visible():
    """Blinding must never hide the planted bug itself: finding it is the reviewer's job."""
    assert blinding.blind_script("y = f(X_test)") != blinding.blind_script("y = f(X_train)")


def test_string_values_that_are_not_docstrings_are_kept():
    assert "'keep me'" in blinding.blind_script("x = 1\n'keep me'\ny = 'keep me'")


def test_blinding_twice_changes_nothing():
    once = blinding.blind_script(DECORATED)
    assert blinding.blind_script(once) == once


def test_generated_script_blinds_to_valid_python_with_same_behaviour_shape():
    config = yaml.safe_load((CONFIG_DIR / "examples" / "baseline.yaml").read_text(encoding="utf-8"))
    source = codegen.render_script(config)
    blinded = blinding.blind_script(source)
    ast.parse(blinded)
    assert '"""' not in blinded
    assert "train_test_split" in blinded


def test_invalid_script_raises():
    with pytest.raises(SyntaxError):
        blinding.blind_script("def (")


def test_results_have_one_key_order_whatever_the_input_order():
    shuffled = dict(reversed(list(results().items())))
    assert blinding.blind_results(shuffled) == blinding.blind_results(results())


def test_runtime_is_hidden():
    assert "runtime" not in blinding.blind_results(results())


def test_prereg_shows_only_the_listed_keys():
    prereg = {key: 1 for key in blinding.PREREG_KEYS}
    text = blinding.blind_prereg({**prereg, "question": "secret", "verdict": "supported"})
    assert "secret" not in text and "supported" not in text
    assert "hypothesis" in text
