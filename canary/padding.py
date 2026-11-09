"""Length matching: make canaries and clean runs indistinguishable by blinded line count and character count.

Why: every bug that adds code adds lines (B10 subtle adds 15), while every clean script from the template has the same
length. On task-dev-1, line count alone separated buggy from clean runs (AUC 0.85), better than any reviewer. A
reviewer that tends to flag longer code would then look like it finds bugs.

How: every calibration run, whatever its type, gets one helper, `describe_settings`, that copies settings out of
CONFIG into a dict, plus one call to it in main(). Its result is never used, so the numbers cannot change. The helper's
size is set so that every blinded script in a batch has the same line count and the same character count (one target
per batch, from its pool of bases). Length is then constant, so it carries no information about the run type at all.
A first version drew a random target per run; that is also type-blind, but the random ranks left AUC noise of about
+-0.06, enough to fail the length gate by luck.

What it does not hide: how big the helper is. A canary's bug lines take the place of helper lines, so canaries get a
smaller helper. A reviewer would have to know the helper's usual size to use that; a stateless reviewer that sees one
run at a time does not. This is logged as a known limit.
"""
from __future__ import annotations

import ast
import random
from dataclasses import dataclass

from canary import blinding, codegen

FUNCTION = "describe_settings"
CALL = f"run_settings = {FUNCTION}(CONFIG)"
# Lines added on top of the clean script. It must exceed the most lines any bug adds (15, B10 subtle) plus the
# helper's 7 fixed lines (def, dict, two arm aliases, return, blank line, call), with room for at least 4 statements so
# the character target can still be hit exactly. tests/test_padding.py checks every variant.
LINE_HEADROOM = 28
# Characters per added line in the target. Tuned on the pool-1 bases so that the shortest helper (B10 subtle) and the
# longest (clean runs) can both hit the target exactly with the statements below. tests/test_padding.py checks it.
CHARS_PER_LINE = 49

_HEAD = "    summary = {}\n    control = config['control']\n    treatment = config['treatment']\n"

# One-line statements that read CONFIG and nothing else, valid for every config the template accepts. Most are short
# on purpose: on average they must match the bug lines they stand in for (about 47 characters).
_ARM = [
    "summary['{a}_model'] = {a}['model']",
    "summary['{a}_scalers'] = list({a}['preprocessing'])",
    "summary['{a}_n_scalers'] = len({a}['preprocessing'])",
    "summary['{a}_params'] = dict({a}['params'])",
    "summary['{a}_n_params'] = len({a}['params'])",
    "summary['{a}_param_names'] = sorted({a}['params'])",
    "summary['{a}_scaled'] = bool({a}['preprocessing'])",
    "summary['{a}_label'] = {a}['model'].replace('_', ' ')",
    "summary['{a}_scaler_text'] = ', '.join({a}['preprocessing']) or 'none'",
    "summary['{a}_param_text'] = ', '.join((f'{{k}}={{v}}' for k, v in sorted({a}['params'].items())))",
]
_GLOBAL = [
    "summary['dataset'] = config['dataset']",
    "summary['metric'] = config['metric']",
    "summary['n_seeds'] = len(config['seeds'])",
    "summary['seeds'] = list(config['seeds'])",
    "summary['first_seed'] = min(config['seeds'])",
    "summary['last_seed'] = max(config['seeds'])",
    "summary['test_size'] = config['test_size']",
    "summary['train_share'] = round(1 - config['test_size'], 4)",
    "summary['n_arms'] = 2",
    "summary['stratified'] = True",
    "summary['seeded'] = True",
    "summary['kind'] = 'tabular'",
    "summary['task'] = 'classification'",
    "summary['arms'] = ['control', 'treatment']",
    "summary['same_model'] = control['model'] == treatment['model']",
    "summary['same_scalers'] = control['preprocessing'] == treatment['preprocessing']",
    "summary['shared_params'] = sorted(set(control['params']) & set(treatment['params']))",
    "summary['metric_label'] = config['metric'].replace('_', ' ')",
    "summary['comparison'] = f\"{treatment['model']} vs {control['model']}\"",
    "summary['seed_text'] = f\"{len(config['seeds'])} seeds\"",
    # Two long ones, so a small helper (B10 subtle on a long config) can still reach the character target.
    "summary['param_changes'] = {k: (control['params'].get(k), treatment['params'].get(k)) "
    "for k in sorted(set(control['params']) | set(treatment['params']))}",
    "summary['description'] = f\"{config['dataset']}: {treatment['model']} "
    "({', '.join(treatment['preprocessing']) or 'no scaling'}) vs {control['model']} "
    "({', '.join(control['preprocessing']) or 'no scaling'})\"",
]
STATEMENTS = _GLOBAL + [s.format(a=arm) for arm in ("control", "treatment") for s in _ARM]


class PaddingError(RuntimeError):
    """The script cannot reach its target length (the bug added more than the headroom allows)."""


@dataclass(frozen=True)
class Target:
    lines: int
    chars: int


@dataclass(frozen=True)
class Padded:
    script: str
    target_lines: int
    target_chars: int
    statements: int  # helper statements added; secret, because canaries get fewer (see the module docstring)
    chars_off: int  # final blinded characters minus the target


def length(script: str) -> tuple[int, int]:
    """Blinded line count and character count: what the reviewer actually sees."""
    blinded = blinding.blind_script(script)
    return len(blinded.splitlines()), len(blinded)


def shape(blinded: str) -> dict:
    """The size features of an already blinded script: lines, characters and statements (every statement node, so a
    multi-line CONFIG dict counts once and a loop counts with its body)."""
    statements = sum(isinstance(node, ast.stmt) for node in ast.walk(ast.parse(blinded)))
    return {"line_count": len(blinded.splitlines()), "char_count": len(blinded), "statement_count": statements}


def helper_chars(blinded: str) -> int | None:
    """Characters of the padding helper in an already blinded script, or None if it has none (a diagnostic: the
    helper's line count is fixed by the gate, but its statements could be longer on one run type)."""
    for node in ast.parse(blinded).body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNCTION:
            return len(ast.unparse(node))
    return None


def batch_target(clean_configs: list[dict]) -> Target:
    """One length for every run of a batch, from the clean scripts of its pool's bases. Run types are not an input."""
    sizes = [length(codegen.render_script(c)) for c in clean_configs]
    chars = sorted(c for _, c in sizes)[len(sizes) // 2]
    return Target(max(n for n, _ in sizes) + LINE_HEADROOM, chars + LINE_HEADROOM * CHARS_PER_LINE)


def _with_helper(script: str, chosen: list[int]) -> str:
    tree = ast.parse(script)
    body = "".join(f"    {STATEMENTS[i]}\n" for i in chosen)
    helper = ast.parse(f"def {FUNCTION}(config):\n{_HEAD}{body}    return summary\n").body
    main = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    if main is None:
        raise PaddingError("no main() to call the helper from")
    position = tree.body.index(main)
    tree.body[position:position] = helper
    main.body.insert(0, ast.parse(CALL).body[0])
    return ast.unparse(tree)


def _statement_chars() -> list[int]:
    """Blinded characters each statement adds inside the helper, newline included."""
    return [len(ast.unparse(ast.parse(s))) + 4 + 1 for s in STATEMENTS]


def _closest_subset(sizes: list[int], k: int, need: int, rng: random.Random) -> list[int]:
    """k statement indices whose sizes sum as close to `need` as single swaps can get. Deterministic for a given rng."""
    chosen = set(rng.sample(range(len(sizes)), k))
    total = sum(sizes[i] for i in chosen)
    while True:
        best, swap = abs(total - need), None
        for i in sorted(chosen):
            for j in sorted(set(range(len(sizes))) - chosen):
                gap = abs(total - sizes[i] + sizes[j] - need)
                if gap < best:
                    best, swap = gap, (i, j)
        if swap is None:
            break
        chosen.remove(swap[0])
        chosen.add(swap[1])
        total += sizes[swap[1]] - sizes[swap[0]]
    # A small helper (B10 subtle leaves room for only a few statements) can get stuck one swap away from exact:
    # then try swapping two statements at once.
    while total != need:
        best, swap = abs(total - need), None
        inside, outside = sorted(chosen), sorted(set(range(len(sizes))) - chosen)
        for a, i1 in enumerate(inside):
            for i2 in inside[a + 1:]:
                for b, j1 in enumerate(outside):
                    for j2 in outside[b + 1:]:
                        gap = abs(total - sizes[i1] - sizes[i2] + sizes[j1] + sizes[j2] - need)
                        if gap < best:
                            best, swap = gap, (i1, i2, j1, j2)
        if swap is None:
            break
        chosen -= {swap[0], swap[1]}
        chosen |= {swap[2], swap[3]}
        total += sizes[swap[2]] + sizes[swap[3]] - sizes[swap[0]] - sizes[swap[1]]
    return sorted(chosen)


def pad_script(script: str, target: Target, rng: random.Random) -> Padded:
    """Add the helper so the blinded script has exactly `target.lines` lines and as close to `target.chars` as it can.

    `script` is the script that will run: the clean render, a sham, or a canary. `rng` only chooses which statements
    fill the helper. Raises PaddingError if the script is already too long, or if the template has no main().
    """
    target_lines, target_chars = target.lines, target.chars
    bare_lines, bare_chars = length(_with_helper(script, []))
    k = target_lines - bare_lines
    if not 0 < k <= len(STATEMENTS):
        raise PaddingError(f"needs {k} helper statements to reach {target_lines} lines (allowed 1..{len(STATEMENTS)})")
    chosen = _closest_subset(_statement_chars(), k, target_chars - bare_chars, rng)
    padded = _with_helper(script, chosen)
    lines, chars = length(padded)
    if lines != target_lines:
        raise PaddingError(f"padded to {lines} lines, target {target_lines}")
    return Padded(padded, target_lines, target_chars, k, chars - target_chars)


def strip_padding(script: str) -> str:
    """The script without the helper and its call: used by tests to prove padding added nothing else."""
    tree = ast.parse(script)
    tree.body = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name == FUNCTION)]
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main" and node.body \
                and ast.unparse(node.body[0]) == CALL:
            node.body = node.body[1:]
    return ast.unparse(tree)


@dataclass(frozen=True)
class Padder:
    """A batch's target and one run's RNG, passed down to where the run's script is written."""
    target: Target
    rng: random.Random

    def pad(self, script: str) -> Padded:
        return pad_script(script, self.target, self.rng)

    def details(self, padded: Padded) -> dict:
        """What the sealed table keeps. Secret: canaries get fewer helper statements."""
        return {"target_lines": padded.target_lines, "target_chars": padded.target_chars,
                "statements": padded.statements, "chars_off": padded.chars_off}
