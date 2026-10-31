"""Blinding: what a reviewer sees must not reveal how a run was made.

Canaries, controls and shams are only useful if the reviewer cannot tell them apart from real runs by accident.
So comments, docstrings and formatting are removed, results have one fixed shape, and IDs never reach the reviewer.
The planted difference itself stays visible: finding it is the reviewer's job.

This module must never read run types. tests/test_skeptic.py fails if it imports anything that could.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass

# Fixed order for every run. runtime_seconds is left out: it varies with machine load and could act as a cue.
RESULT_KEYS = ("dataset", "metric", "seeds", "control", "treatment", "class_balance", "split_sizes")
# Only what a reviewer needs from the lock. The computed verdict is not part of it, so it cannot sway the review.
PREREG_KEYS = ("hypothesis", "dataset", "metric", "control_config", "treatment_config", "direction", "min_effect",
               "predicted_effect", "confidence", "seeds", "test_size", "alpha")
_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class BlindedRun:
    """Everything a reviewer is allowed to see, as text. It deliberately has no ID field."""

    script: str
    results: str
    prereg: str


def _strip_docstrings(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, _DOCSTRING_OWNERS) and ast.get_docstring(node, clean=False) is not None:
            # A function body cannot be empty, so a function that held only a docstring gets `pass`.
            node.body = node.body[1:] or ([ast.Pass()] if not isinstance(node, ast.Module) else [])


def blind_script(source: str) -> str:
    """Return the script with comments, docstrings and formatting normalized. Raises SyntaxError if it is invalid.

    Parsing drops comments and layout, and ast.unparse writes the code back in one standard style.
    """
    tree = ast.parse(source)
    _strip_docstrings(tree)
    return ast.unparse(tree)


def blind_results(results: dict) -> str:
    """Return results as JSON with the same keys in the same order for every run."""
    return json.dumps({key: results[key] for key in RESULT_KEYS}, indent=1)


def blind_prereg(prereg: dict) -> str:
    return json.dumps({key: prereg[key] for key in PREREG_KEYS}, indent=1)


def blind_run(source: str, results: dict, prereg: dict) -> BlindedRun:
    return BlindedRun(blind_script(source), blind_results(results), blind_prereg(prereg))
