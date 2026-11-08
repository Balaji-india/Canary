"""The Scientist: propose a hypothesis, lock it, run it, and let code compute the verdict.

The LLM only fills in a proposal. Everything after that (the checks, the hash, the run and the verdict) is code.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from canary import codegen, llm, prereg, prompts, sandbox, sealed
from canary import ledger as ledger_module
from canary.config import load_yaml
from canary.ledger import Ledger

PREVIOUS_SHOWN = 10  # how many earlier hypotheses the prompt lists, to keep it short


class ProposalRejected(RuntimeError):
    """The Scientist gave no acceptable proposal in the allowed number of attempts."""


def proposal_schema(min_effect_floor: float, focus: dict | None = None) -> dict:
    """The JSON the Scientist must return. It has no verdict field: the LLM cannot decide one.

    `focus` limits the choice to one dataset, metric and model. Left free, every model tried kept proposing nearly the
    same experiment, so canaries cloned from those proposals would measure the reviewer on a very narrow slice.
    """
    catalog = load_yaml("datasets.yaml")
    model_params = {focus["model"]: codegen.MODEL_PARAMS[focus["model"]]} if focus else codegen.MODEL_PARAMS
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
    } for model, names in model_params.items()]}
    properties = {
        "hypothesis": {"type": "string"},
        "dataset": {"enum": [focus["dataset"]] if focus else [d["name"] for d in catalog["sklearn"] + catalog["openml"]]},
        "metric": {"enum": [focus["metric"]] if focus else sorted(codegen.METRICS)},
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


def real_preregs(led: Ledger, table: sealed.SealedTable) -> list[dict]:
    """Pre-registrations of the Scientist's own runs, oldest first.

    Clones share the ledger, and a sabotaged config must never read as something the Scientist tried: that would
    tilt its next proposal, and any change in its behaviour could then depend on the hidden run types.
    """
    locks = {e.hypothesis_id: e.payload["prereg"] for e in led.entries(ledger_module.PREREGISTERED)}
    found = []
    for entry in led.entries(ledger_module.RAN):
        truth = table.get(entry.payload["run_id"])
        if truth is not None and truth.run_type == sealed.REAL:
            found.append(locks[entry.hypothesis_id])
    return found


def seal_unsealed_runs_as_real(led: Ledger, table: sealed.SealedTable) -> int:
    """Give a sealed row to runs from before the table existed. Every clone is sealed before its ledger entry,
    so a run in the ledger with no row can only be a real one. Returns how many were added."""
    added = 0
    for entry in led.entries(ledger_module.RAN):
        if table.get(entry.payload["run_id"]) is None:
            table.seal(entry.payload["run_id"], sealed.REAL, source=entry.hypothesis_id, details={"backfilled": True})
            added += 1
    return added


def propose(client: llm.LLM, question_id: str, led: Ledger, table: sealed.SealedTable,
            focus: dict | None = None, avoid: list[dict] | None = None) -> tuple[dict, str]:
    """Ask for a proposal until one passes the checks. Returns the record to lock and the model used.

    With a `focus`, the prompt offers only that choice and lists no earlier hypotheses, so a pool of focused
    proposals does not depend on the order it was built in.

    `avoid` holds pre-registrations a new pool must not repeat (an earlier pool's bases). They count as duplicates,
    and with a focus the ones on the same dataset are listed as earlier hypotheses. Without that, the same focused
    prompt would hit the LLM cache and return the earlier pool's proposal word for word.
    """
    campaign = load_yaml("campaign.yaml")
    science = campaign["science"]
    catalog = load_yaml("datasets.yaml")
    datasets_offered = catalog["sklearn"] + catalog["openml"]
    model_params, metrics = codegen.MODEL_PARAMS, sorted(codegen.METRICS)
    earlier = real_preregs(led, table)
    earlier_keys = {_experiment_key(p) for p in earlier}
    previous = [p["hypothesis"] for p in earlier][-PREVIOUS_SHOWN:]
    if focus:
        datasets_offered = [d for d in datasets_offered if d["name"] == focus["dataset"]]
        model_params = {focus["model"]: codegen.MODEL_PARAMS[focus["model"]]}
        metrics, previous = [focus["metric"]], []
    if avoid:
        earlier_keys |= {_experiment_key(p) for p in avoid}
        shown = [p for p in avoid if not focus or p["dataset"] == focus["dataset"]]
        previous = (previous + [p["hypothesis"] for p in shown])[-PREVIOUS_SHOWN:]
    schema = proposal_schema(science["min_effect_floor"], focus)
    question = campaign["questions"][question_id]
    feedback = None
    for attempt in range(1, science["proposal_attempts"] + 1):
        prompt = prompts.scientist_prompt(question, datasets_offered, model_params, metrics, sorted(codegen.SCALERS),
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


def record_ran(led: Ledger, hypothesis_id: str, locked: dict, digest: str, record: dict, runs_dir: Path) -> dict:
    """Write a finished run's RAN entry with its hashes and code-computed verdict. Returns the verdict."""
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
    return verdict


def run_locked(locked: dict, model: str, led: Ledger, table: sealed.SealedTable, runs_dir: Path = sandbox.RUNS_DIR,
               timeout_s: float = sandbox.DEFAULT_TIMEOUT_S) -> ScienceOutcome:
    """Record the hypothesis, lock it in the ledger BEFORE running, then run it, seal it and record the verdict."""
    hypothesis_id = str(uuid.uuid4())
    digest = prereg.prereg_hash(locked)
    led.append(hypothesis_id, ledger_module.PROPOSED, {"hypothesis": locked["hypothesis"], "model": model})
    led.append(hypothesis_id, ledger_module.PREREGISTERED, {"prereg": locked, "prereg_sha256": digest})

    record = sandbox.run_config(prereg.to_run_config(locked), runs_dir, timeout_s)
    table.seal(record["run_id"], sealed.REAL, source=hypothesis_id, details={"status": record["status"]})
    verdict = record_ran(led, hypothesis_id, locked, digest, record, runs_dir)
    return ScienceOutcome(hypothesis_id, locked["hypothesis"], digest, record["run_id"], record["status"], verdict)
