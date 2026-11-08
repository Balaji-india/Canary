"""Review tasks: what the reviewer is asked, in what reply format, and how code turns its reply into a verdict.

Why this exists: under the baseline task both reviewers flagged almost every run and named B01, so the task itself is
the suspect (PROGRESS.md, reviewer study). Each task here is one way of asking. The model only fills in its reply;
`decide` is code, so no LLM decides a verdict (CLAUDE.md section 6).

- `baseline`: the original prompt, system text and schema, byte for byte. Its decision is the reply's own verdict.
- `grounded` (V1): neutral wording, and the offending line is copied before the verdict. A flag counts only if code
  finds that line in what the reviewer was shown. The raw verdict is kept too, so the wording change and the code check
  can be told apart.
- `checklist` (V2): one yes/no per bug class, each with a line. The run is flagged if any "yes" has a verified line.

`score` turns the token probabilities of the reply into P(flag), so a reviewer can be ranked by AUC even if its yes/no
answer is always the same. Ollama reports the model's probabilities before the schema constrains the next token, so the
score renormalises over the two words the schema allows at that point ("flag"/"pass", "yes"/"no").

This module sees only the blinded run, never run types: tests/test_skeptic.py checks its imports.
"""
from __future__ import annotations

import math
import re

from canary import prompts

BASELINE, GROUNDED, CHECKLIST = "baseline", "grounded", "checklist"
TASKS = (BASELINE, GROUNDED, CHECKLIST)
FLAG, PASS, YES, NO = "flag", "pass", "yes", "no"
MIN_QUOTE_CHARS = 8  # a quote shorter than this ("X)", "fit(") would be found in almost any script
TOP_LOGPROBS = 20


def baseline_schema(bug_ids: list[str]) -> dict:
    """Two forms, so that a pass cannot name a bug and a flag must name one. The original schema, unchanged."""
    def form(verdict: str, bug_class: dict) -> dict:
        return {
            "type": "object", "required": ["verdict", "bug_class", "evidence", "confidence"],
            "additionalProperties": False,
            "properties": {
                "verdict": {"enum": [verdict]},
                "bug_class": bug_class,
                "evidence": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        }
    return {"anyOf": [form(PASS, {"type": "null"}), form(FLAG, {"enum": bug_ids})]}


def _grounded_schema(bug_ids: list[str]) -> dict:
    """Two forms that share their first field, so the line is written before the verdict is chosen."""
    def form(verdict: str, bug_class: dict) -> dict:
        return {
            "type": "object", "required": ["offending_line", "verdict", "bug_class", "evidence", "confidence"],
            "additionalProperties": False,
            "properties": {
                "offending_line": {"type": "string"},
                "verdict": {"enum": [verdict]},
                "bug_class": bug_class,
                "evidence": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        }
    return {"anyOf": [form(PASS, {"type": "null"}), form(FLAG, {"enum": bug_ids})]}


def _checklist_schema(bug_ids: list[str]) -> dict:
    entry = {"type": "object", "required": ["line", "answer"], "additionalProperties": False,
             "properties": {"line": {"type": "string"}, "answer": {"enum": [YES, NO]}}}
    return {"type": "object", "required": list(bug_ids), "additionalProperties": False,
            "properties": {bug_id: entry for bug_id in bug_ids}}


def build(task: str, blinded, bug_classes: dict, order: list[str] | None = None) -> tuple[str, str, dict]:
    """Return (system text, prompt, schema) for a task. Only the baseline supports a shuffled class order."""
    bug_ids = sorted(bug_classes)
    if task == BASELINE:
        return (prompts.SKEPTIC_SYSTEM, prompts.skeptic_prompt(blinded, bug_classes, order),
                baseline_schema(order or bug_ids))
    if order is not None:
        raise ValueError(f"task {task} does not support a class order")
    if task == GROUNDED:
        return prompts.SKEPTIC_SYSTEM_NEUTRAL, prompts.skeptic_prompt_grounded(blinded, bug_classes), _grounded_schema(bug_ids)
    if task == CHECKLIST:
        return prompts.SKEPTIC_SYSTEM_NEUTRAL, prompts.skeptic_prompt_checklist(blinded, bug_classes), _checklist_schema(bug_ids)
    raise ValueError(f"unknown review task {task!r} (known: {', '.join(TASKS)})")


def _normalise(text: str) -> str:
    return " ".join(text.split())


def quote_found(quote: str, blinded) -> bool:
    """True if the quote, whitespace collapsed, appears in what the reviewer saw (script, pre-registration or results).

    Surrounding backticks or quote marks are ignored, since models often wrap code in them. Too-short quotes and quotes
    without a letter are refused: they would match almost anything.
    """
    q = _normalise(quote).strip("`'\" ")
    if len(q) < MIN_QUOTE_CHARS or not re.search(r"[A-Za-z]", q):
        return False
    return any(q in _normalise(text) for text in (blinded.script, blinded.prereg, blinded.results))


def decide(task: str, reply: dict, blinded) -> dict:
    """The code's verdict from a reply. `raw_verdict` is what the reply says before the line check."""
    if task == BASELINE:
        return {"verdict": reply["verdict"], "bug_class": reply["bug_class"], "raw_verdict": reply["verdict"]}
    if task == GROUNDED:
        verified = quote_found(reply["offending_line"], blinded)
        flagged = reply["verdict"] == FLAG and verified
        return {"verdict": FLAG if flagged else PASS, "bug_class": reply["bug_class"] if flagged else None,
                "raw_verdict": reply["verdict"], "raw_bug_class": reply["bug_class"], "line_verified": verified}
    if task == CHECKLIST:
        yes = [b for b in sorted(reply) if reply[b]["answer"] == YES]
        verified = [b for b in yes if quote_found(reply[b]["line"], blinded)]
        return {"verdict": FLAG if verified else PASS, "bug_class": verified[0] if verified else None,
                "raw_verdict": FLAG if yes else PASS, "yes_classes": yes, "verified_classes": verified}
    raise ValueError(f"unknown review task {task!r}")


# ---- token-probability scores -------------------------------------------------------------------------------------

def _token_bytes(token: dict) -> bytes:
    """A token's bytes, or its text when they are not reported. The ollama client (0.6.3) drops `bytes`, and an
    empty list means "not reported": treating it as zero bytes made every task-dev-1 score None."""
    raw = token.get("bytes")
    return bytes(raw) if raw else token["token"].encode("utf-8")


def choice_probability(logprobs: list[dict], value_start: int, first: str, second: str) -> dict | None:
    """P(first) / (P(first) + P(second)) for the string value that starts at byte `value_start` of the reply.

    The token covering `value_start` is where the model chose. Each alternative there is extended with the reply text
    before that token, and counted for a word if what it writes from `value_start` on starts that word (or the word and
    its closing quote). Alternatives that stop before `value_start`, or fit neither word, are left out. The chosen token
    always counts, so at least one word has mass. If only one has, the other's mass is below the reported alternatives
    and is counted as 0 (`both_seen` False).
    """
    offset = 0
    for token in logprobs:
        data = _token_bytes(token)
        if offset + len(data) <= value_start:
            offset += len(data)
            continue
        before = data[:value_start - offset]  # the part of the chosen token that comes before the value
        mass = {first: 0.0, second: 0.0}
        # The chosen token counts too: under the schema it may have been outside the model's own top alternatives.
        candidates = {_token_bytes(alt): alt for alt in (token.get("top_logprobs") or [])}
        candidates.setdefault(data, token)
        for alt in candidates.values():
            alt_bytes = _token_bytes(alt)
            if not alt_bytes.startswith(before):
                continue  # another path through the text, not a choice of value
            text = alt_bytes[len(before):].decode("utf-8", errors="ignore")
            for word in (first, second):
                if _starts_value(text, word):
                    mass[word] += math.exp(alt["logprob"])
                    break
        total = mass[first] + mass[second]
        if total == 0:
            return None
        return {"p": mass[first] / total, "both_seen": mass[first] > 0 and mass[second] > 0}
    return None


def _starts_value(text: str, word: str) -> bool:
    """True if `text`, written at the start of a JSON string value, begins `word` ("fl", "flag", 'flag"', 'flag",')."""
    head, quote, _ = text.partition('"')
    if not head:
        return False
    return head == word if quote else word.startswith(head)


def score(task: str, logprobs: list[dict] | None, bug_ids: list[str]) -> dict | None:
    """P(flag) from the reply's token probabilities, or None if they are missing or the choice point is not found.

    Baseline and grounded: the choice between "flag" and "pass" at the verdict. Checklist: P(yes) for each class, and
    the run's score is the largest of them, since one "yes" flags the run.
    """
    if not logprobs:
        return None
    text = b"".join(_token_bytes(t) for t in logprobs)
    if task in (BASELINE, GROUNDED):
        match = re.search(rb'"verdict"\s*:\s*"', text)
        if not match:
            return None
        choice = choice_probability(logprobs, match.end(), FLAG, PASS)
        return None if choice is None else {"p_flag": choice["p"], "both_seen": choice["both_seen"]}
    if task == CHECKLIST:
        per_class = {}
        for bug_id in bug_ids:
            entry = re.search(rb'"' + re.escape(bug_id.encode()) + rb'"\s*:\s*\{', text)
            if not entry:
                return None
            answer = re.compile(rb'"answer"\s*:\s*"').search(text, entry.end())
            if not answer:
                return None
            choice = choice_probability(logprobs, answer.end(), YES, NO)
            if choice is None:
                return None
            per_class[bug_id] = round(choice["p"], 6)
        return {"p_flag": max(per_class.values()), "per_class": per_class}
    raise ValueError(f"unknown review task {task!r}")
