"""The Scientist: propose a hypothesis, lock it, run it, and let code compute the verdict.

The LLM only fills in a proposal. Everything after that (the checks, the hash, the run and the verdict) is code.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from canary import codegen, llm, prereg, prompts, sandbox
from canary import ledger as ledger_module
from canary.config import load_yaml
from canary.ledger import Ledger

PREVIOUS_SHOWN = 10  # how many earlier hypotheses the prompt lists, to keep it short


class ProposalRejected(RuntimeError):
    """The Scientist gave no acceptable proposal in the allowed number of attempts."""


def proposal_schema(min_effect_floor: float) -> dict:
    """The JSON the Scientist must return. It has no verdict field: the LLM cannot decide one."""
    catalog = load_yaml("datasets.yaml")
    # One form per model, so choosing a model limits the output to that model's own parameters. An open params
    # object gave garbled keys and repeat-loops, and one shared list made the model mix parameters between models.
    arm = {"anyOf": [{
        "type": "object", "required": ["model", "params", "preprocessing"], "additionalProperties": False,
        "properties": {
            "model": {"enum": [model]},
            "params": {"type": "object", "additionalProperties": False,
                       "properties": {name: codegen.PARAM_SCHEMAS[name] for name in names}},
            "preprocessing": {"type": "array", "items": {"enum": sorted(codegen.SCALERS)}},
        },
    } for model, names in codegen.MODEL_PARAMS.items()]}
    properties = {
        "hypothesis": {"type": "string"},
        "dataset": {"enum": [d["name"] for d in catalog["sklearn"] + catalog["openml"]]},
        "metric": {"enum": sorted(codegen.METRICS)},
        "control_config": arm,
        "treatment_config": arm,
        "direction": {"enum": ["increase", "decrease"]},
        "min_effect": {"type": "number", "minimum": min_effect_floor, "maximum": 1},
        "predicted_effect": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    return {"type": "object", "required": list(properties), "additionalProperties": False, "properties": properties}


def _experiment_key(locked: dict) -> str:
    """Identify an experiment by what it runs, not by its wording or its seeds, which are drawn fresh each time."""
    run_config = prereg.to_run_config(locked)
    del run_config["seeds"]
    return prereg.canonical_json(run_config)


def proposal_problem(locked: dict, earlier_keys: set[str]) -> str | None:
    """Return why a proposal cannot be locked, or None. The schema cannot express these rules."""
    if not locked["hypothesis"].strip():
        return "hypothesis is empty"
    if locked["control_config"] == locked["treatment_config"]:
        return "control_config and treatment_config are identical, so there is nothing to compare"
    if locked["predicted_effect"] < locked["min_effect"]:
        return "predicted_effect is below min_effect"
    try:
        codegen.validate_config(prereg.to_run_config(locked))
    except codegen.ConfigError as exc:
        return str(exc)
    if _experiment_key(locked) in earlier_keys:
        return "this exact experiment was already run"
    return None


def propose(client: llm.LLM, question_id: str, led: Ledger) -> tuple[dict, str]:
    """Ask for a proposal until one passes the checks. Returns the record to lock and the model used."""
    campaign = load_yaml("campaign.yaml")
    science = campaign["science"]
    catalog = load_yaml("datasets.yaml")
    earlier = [e.payload["prereg"] for e in led.entries(ledger_module.PREREGISTERED)]
    earlier_keys = {_experiment_key(p) for p in earlier}
    previous = [p["hypothesis"] for p in earlier][-PREVIOUS_SHOWN:]
    schema = proposal_schema(science["min_effect_floor"])
    question = campaign["questions"][question_id]
    feedback = None
    for attempt in range(1, science["proposal_attempts"] + 1):
        prompt = prompts.scientist_prompt(question, catalog["sklearn"] + catalog["openml"], codegen.MODEL_PARAMS,
                                          sorted(codegen.METRICS), sorted(codegen.SCALERS),
                                          science["min_effect_floor"], previous,
                                          # The attempt number keeps each retry's prompt unique. With identical text
                                          # the cache and the fixed seed would return the same rejected reply.
                                          f"(attempt {attempt - 1}) {feedback}" if feedback else None)
        result = client.call("scientist", prompt, schema, system=prompts.SCIENTIST_SYSTEM)
        locked = prereg.build_prereg(result.data, question, science, campaign["seeds_per_arm"])
        feedback = proposal_problem(locked, earlier_keys)
        if feedback is None:
            return locked, result.model
    raise ProposalRejected(f"no acceptable proposal after {science['proposal_attempts']} attempts: {feedback}")


@dataclass(frozen=True)
class ScienceOutcome:
    hypothesis_id: str
    hypothesis: str
    prereg_sha256: str
    run_id: str
    run_status: str
    verdict: dict


def run_locked(locked: dict, model: str, led: Ledger, runs_dir: Path = sandbox.RUNS_DIR,
               timeout_s: float = sandbox.DEFAULT_TIMEOUT_S) -> ScienceOutcome:
    """Record the hypothesis, lock it in the ledger BEFORE running, then run it and record the verdict."""
    hypothesis_id = str(uuid.uuid4())
    digest = prereg.prereg_hash(locked)
    led.append(hypothesis_id, ledger_module.PROPOSED, {"hypothesis": locked["hypothesis"], "model": model})
    led.append(hypothesis_id, ledger_module.PREREGISTERED, {"prereg": locked, "prereg_sha256": digest})

    record = sandbox.run_config(prereg.to_run_config(locked), runs_dir, timeout_s)
    results_sha256 = None
    script_path = runs_dir / record["run_id"] / codegen.SCRIPT_NAME
    script_sha256 = hashlib.sha256(script_path.read_bytes()).hexdigest() if script_path.exists() else None
    if record["status"] == sandbox.STATUS_OK:
        raw = (runs_dir / record["run_id"] / sandbox.RESULTS_NAME).read_bytes()
        results_sha256 = hashlib.sha256(raw).hexdigest()
        verdict = prereg.compute_verdict(locked, json.loads(raw))
    else:
        verdict = prereg.failed_run_verdict(record["status"], record["reason"])
    led.append(hypothesis_id, ledger_module.RAN, {
        "run_id": record["run_id"], "run_status": record["status"], "reason": record["reason"],
        "prereg_sha256": digest, "results_sha256": results_sha256, "script_sha256": script_sha256, "verdict": verdict,
    })
    return ScienceOutcome(hypothesis_id, locked["hypothesis"], digest, record["run_id"], record["status"], verdict)
