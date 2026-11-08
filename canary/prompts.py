"""Prompt text, kept apart from logic so that it can be read and compared in one place."""
from __future__ import annotations

SCIENTIST_SYSTEM = (
    "You are a careful machine learning scientist. You propose one small, testable experiment comparing a control "
    "classifier with a treatment classifier on one tabular dataset. You predict the result before it is run, and "
    "your prediction is scored later, so be honest about your uncertainty."
)

SKEPTIC_SYSTEM = (
    "You are a strict reviewer of machine learning experiments. You look for methodological bugs that would make "
    "the reported results untrustworthy. You judge only the code and the numbers you are shown."
)


def skeptic_prompt(blinded, bug_classes: dict, order: list[str] | None = None) -> str:
    """Build the review prompt from a BlindedRun.

    It lists bug class names only, not the catalog's examples: those would hand the reviewer the answers and
    inflate its measured recall. Adding such hints is a separate, measured step (self-hardening, Mission 6.4).
    It also says nothing about controls or planted bugs, because a reviewer told it is being tested may act differently.
    `order` lists the classes in another order (the position-bias diagnostic). Left out, the prompt is exactly the
    baseline's, sorted by ID, so every reviewer measured without it sees the same text.
    """
    ids = sorted(bug_classes) if order is None else order
    classes = "\n".join(f"- {bug_id}: {bug_classes[bug_id]['name'].replace('_', ' ')}" for bug_id in ids)
    return f"""Review this experiment.

Pre-registration:
{blinded.prereg}

Experiment script:
```python
{blinded.script}
```

Results:
{blinded.results}

Bug classes:
{classes}

Reply as JSON:
- verdict: "flag" if you find a methodological bug from the classes above, otherwise "pass".
- bug_class: the id of the bug class if you flag, otherwise null.
- evidence: one or two sentences. If you flag, name the exact code or number that shows the bug.
- confidence: your probability from 0 to 1 that your verdict is correct."""


# Review-task variants (the review-task screen, batch task-dev-1). Fixed before that batch ran; do not tune them on its
# results. The neutral system text drops "strict" and makes "pass" a normal answer, since both reviewers flagged
# almost everything under the baseline wording. Both variants keep bug class names only, with no definitions, so they
# stay unhinted like the baseline (hints are Mission 6.4's measured step).
SKEPTIC_SYSTEM_NEUTRAL = (
    "You review machine learning experiments for methodological bugs that would make the reported results "
    "untrustworthy. Many experiments are correct, and finding no bug is a normal outcome. You judge only the code and "
    "the numbers you are shown."
)


def _review_material(blinded, classes: str) -> str:
    return f"""Review this experiment.

Pre-registration:
{blinded.prereg}

Experiment script:
```python
{blinded.script}
```

Results:
{blinded.results}

Bug classes:
{classes}"""


def class_lines(bug_classes: dict, ids: list[str]) -> str:
    return "\n".join(f"- {bug_id}: {bug_classes[bug_id]['name'].replace('_', ' ')}" for bug_id in ids)


def skeptic_prompt_grounded(blinded, bug_classes: dict) -> str:
    """V1: evidence first. The reviewer must copy the offending line before it gives a verdict; code checks the copy."""
    return _review_material(blinded, class_lines(bug_classes, sorted(bug_classes))) + """

Many experiments have no bug, so "pass" is a normal answer. Flag only if a specific line you were shown is a bug from
the classes above.

Reply as JSON, in this order:
- offending_line: copy, character for character, the one line of the script, pre-registration or results that shows
  the bug. If no line shows a bug, an empty string.
- verdict: "flag" if that line shows a bug from the classes above, otherwise "pass".
- bug_class: the id of the bug class if you flag, otherwise null.
- evidence: one or two sentences explaining why.
- confidence: your probability from 0 to 1 that your verdict is correct."""


def skeptic_prompt_checklist(blinded, bug_classes: dict) -> str:
    """V2: one yes/no question per bug class in one call, instead of picking a single class."""
    return _review_material(blinded, class_lines(bug_classes, sorted(bug_classes))) + """

Answer every bug class separately. Many experiments have no bug, so "no" is a normal answer for every class.

Reply as JSON with one entry per bug class id, in the order listed. Each entry has, in this order:
- line: copy, character for character, the one line of the script, pre-registration or results that shows this bug.
  If no line shows it, an empty string.
- answer: "yes" if the experiment has this bug, otherwise "no"."""


def scientist_prompt(question: str, datasets_cfg: list[dict], model_params: dict[str, list[str]], metrics: list[str],
                     scalers: list[str], min_effect_floor: float, previous: list[str],
                     feedback: str | None = None) -> str:
    """Build the proposal prompt. Seeds and the split are not offered: code sets them."""
    datasets = "\n".join(f"- {d['name']}: {d['classes']} classes" + (f" ({d['note']})" if d.get("note") else "")
                         for d in datasets_cfg)
    models = "\n".join(f"- {name}: {', '.join(params)}" for name, params in model_params.items())
    earlier = "\n".join(f"- {h}" for h in previous) or "- none yet"
    prompt = f"""Research question: {question}

Datasets:
{datasets}

Models, with the only parameters allowed for each:
{models}

Metrics: {", ".join(metrics)}. Higher is better for all of them. roc_auc needs a two-class dataset.
Scalers for "preprocessing" (a list, may be empty): {", ".join(scalers)}.

Hypotheses already tested (propose something different):
{earlier}

Propose one experiment as JSON:
- hypothesis: one sentence saying what changes and what you expect.
- dataset, metric: choose from the lists above.
- control_config and treatment_config: each has model, params, preprocessing. Change one thing between them.
  Use only the parameters listed for that model, with values scikit-learn accepts.
- direction: "increase" if you expect the treatment to score higher than the control, otherwise "decrease".
- min_effect: the smallest metric difference you would count as a real effect, at least {min_effect_floor}.
- predicted_effect: the size of the difference you expect, as a positive number, at least min_effect.
- confidence: your probability from 0 to 1 that the result will reach min_effect in your predicted direction."""
    if feedback:
        prompt += f"\n\nYour previous proposal was rejected: {feedback}. Propose a corrected one."
    return prompt
