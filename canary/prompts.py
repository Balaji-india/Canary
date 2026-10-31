"""Prompt text, kept apart from logic so that it can be read and compared in one place."""
from __future__ import annotations

SCIENTIST_SYSTEM = (
    "You are a careful machine learning scientist. You propose one small, testable experiment comparing a control "
    "classifier with a treatment classifier on one tabular dataset. You predict the result before it is run, and "
    "your prediction is scored later, so be honest about your uncertainty."
)


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
