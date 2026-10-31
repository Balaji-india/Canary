"""The Skeptic: an LLM reviewer that sees only a blinded run and returns a structured opinion.

Its opinion is data. Code decides later what to do with it (the trust gate, Mission 4), and how far to trust it
(the canaries, Mission 2). This module must never read run types: tests/test_skeptic.py checks its imports.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from canary import blinding, config, ledger, llm, prereg, prompts, sandbox
from canary.codegen import SCRIPT_NAME

PASS = "pass"
FLAG = "flag"
DEFAULT_ROLE = "skeptic_a"


def audit_schema(bug_ids: list[str]) -> dict:
    """Two forms, so that a pass cannot name a bug and a flag must name one."""
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


@dataclass(frozen=True)
class AuditJob:
    hypothesis_id: str
    run_id: str
    blinded: blinding.BlindedRun


@dataclass
class AuditReport:
    audited: list[dict] = field(default_factory=list)
    no_results: list[dict] = field(default_factory=list)  # failed runs, sent to the graveyard without a review
    errors: list[str] = field(default_factory=list)  # left at "ran", so a later audit tries them again


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _waiting(led: ledger.Ledger) -> list[tuple[ledger.Entry, dict]]:
    """Return (ran entry, locked pre-registration) for each hypothesis whose latest status is "ran"."""
    latest: dict[str, ledger.Entry] = {}
    locks: dict[str, dict] = {}
    for entry in led.entries():
        latest[entry.hypothesis_id] = entry
        if entry.status == ledger.PREREGISTERED:
            locks[entry.hypothesis_id] = entry.payload
    return [(e, locks[e.hypothesis_id]) for e in latest.values() if e.status == ledger.RAN]


def _prepare(entry: ledger.Entry, lock: dict, runs_dir: Path) -> AuditJob:
    """Load and blind a run after checking that the files are the ones the ledger recorded.

    A review of edited files would be worthless, so a mismatch raises ValueError rather than being reviewed.
    """
    if prereg.prereg_hash(lock["prereg"]) != lock["prereg_sha256"]:
        raise ValueError("pre-registration does not match its hash")
    run_dir = runs_dir / entry.payload["run_id"]
    raw_results = (run_dir / sandbox.RESULTS_NAME).read_bytes()
    if _sha256(raw_results) != entry.payload["results_sha256"]:
        raise ValueError("results.json does not match its stored hash")
    raw_script = (run_dir / SCRIPT_NAME).read_bytes()
    if entry.payload.get("script_sha256") not in (None, _sha256(raw_script)):
        raise ValueError(f"{SCRIPT_NAME} does not match its stored hash")
    blinded = blinding.blind_run(raw_script.decode("utf-8"), json.loads(raw_results), lock["prereg"])
    return AuditJob(entry.hypothesis_id, entry.payload["run_id"], blinded)


def audit_pending(client: llm.LLM, led: ledger.Ledger, runs_dir: Path = sandbox.RUNS_DIR,
                  role: str = DEFAULT_ROLE) -> AuditReport:
    """Review every run still waiting, and store each review in the ledger before moving on.

    A failed run has no results, so there is no finding to review: it goes straight to the graveyard with its cause.
    """
    report = AuditReport()
    bugs = config.load_yaml("bug_classes.yaml")
    schema = audit_schema(sorted(bugs))
    jobs = []
    for entry, lock in _waiting(led):
        if entry.payload["results_sha256"] is None:
            cause = f"run failed: {entry.payload['run_status']} ({entry.payload['reason']})"
            led.append(entry.hypothesis_id, ledger.GRAVEYARD, {"cause": cause, "run_id": entry.payload["run_id"]})
            report.no_results.append({"hypothesis_id": entry.hypothesis_id, "cause": cause})
            continue
        try:
            jobs.append(_prepare(entry, lock, runs_dir))
        except (OSError, ValueError, SyntaxError, KeyError) as exc:
            report.errors.append(f"{entry.hypothesis_id}: not reviewed: {exc}")

    queue = llm.ModelQueue(client)
    prompts_sent = []
    for job in jobs:
        prompt = prompts.skeptic_prompt(job.blinded, bugs)
        prompts_sent.append(prompt)
        queue.add(role, prompt, schema, system=prompts.SKEPTIC_SYSTEM)
    for job, prompt, result in zip(jobs, prompts_sent, queue.run()):
        if result.error:
            report.errors.append(f"{job.hypothesis_id}: {result.error}")
            continue
        payload = {
            "run_id": job.run_id, "role": role, "model": result.model, "audit": result.data,
            "cached": result.cached, "attempts": result.attempts,
            "blinded_script_sha256": prereg.sha256_text(job.blinded.script),
            "prompt_sha256": prereg.sha256_text(prompt),
        }
        led.append(job.hypothesis_id, ledger.AUDITED, payload)
        report.audited.append({"hypothesis_id": job.hypothesis_id, **payload})
    return report
