"""The Skeptic: an LLM reviewer that sees only a blinded run and returns a structured opinion.

Its opinion is data. Code decides later what to do with it (the trust gate, Mission 4), and how far to trust it
(the canaries, Mission 2). This module must never read run types: tests/test_skeptic.py checks its imports.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from canary import blinding, config, ledger, llm, prereg, prompts, sandbox
from canary.codegen import SCRIPT_NAME

PASS = "pass"
FLAG = "flag"
DEFAULT_ROLE = "skeptic_a"
DEFAULT_CHUNK = 5  # reviews stored per chunk, and the longest stretch of an outage before the stop rule looks
DEFAULT_STOP_AFTER = 3


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
    errors: list[str] = field(default_factory=list)  # still waiting, so a later audit tries them again
    failures: list[dict] = field(default_factory=list)  # the model gave no opinion: run ID, kind and message
    stopped: str | None = None  # why the pass ended early, leaving runs waiting


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Where a hypothesis can still be reviewed. After acceptance, escalation or the graveyard nobody reviews it again.
_OPEN = (ledger.RAN, ledger.AUDIT_FAILED, ledger.AUDITED)


def _waiting(led: ledger.Ledger, role: str = DEFAULT_ROLE) -> list[tuple[ledger.Entry, dict]]:
    """Return (ran entry, locked pre-registration) for each hypothesis still without an opinion from `role`.

    A run whose last audit attempt failed still waits: the reviewer has not said anything about it yet.
    Only this role's audits count. Otherwise a second reviewer's failed reply would make the first see an audited run as
    waiting again, and a run the first reviewer audited would never wait for the second.
    """
    latest: dict[str, str] = {}
    locks: dict[str, dict] = {}
    ran: dict[str, ledger.Entry] = {}
    reviewed: set[str] = set()
    for entry in led.entries():
        latest[entry.hypothesis_id] = entry.status
        if entry.status == ledger.PREREGISTERED:
            locks[entry.hypothesis_id] = entry.payload
        elif entry.status == ledger.RAN:
            ran[entry.hypothesis_id] = entry
        elif entry.status == ledger.AUDITED and entry.payload.get("role") == role:
            reviewed.add(entry.hypothesis_id)
    return [(ran[h], locks[h]) for h, status in latest.items() if status in _OPEN and h in ran and h not in reviewed]


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
                  role: str = DEFAULT_ROLE, on_progress: Callable[[int, int, dict], None] | None = None,
                  chunk_size: int = DEFAULT_CHUNK, stop_after: int = DEFAULT_STOP_AFTER,
                  run_ids: set[str] | None = None,
                  class_order: Callable[[str], list[str]] | None = None) -> AuditReport:
    """Review every run still waiting for `role`, storing reviews after each small chunk, so a crash loses very little.

    `run_ids` limits the pass to those runs (one batch, or a sample of it). `class_order` gives, per run ID, the order
    in which the bug classes are listed, in the prompt and in the schema alike, so that the order cannot leak back in
    through either one. The order used is stored with the audit.

    A failed run has no results, so there is no finding to review: it goes straight to the graveyard with its cause.
    A failed review is stored too, because a failure that left no trace could hide a reviewer that fails more often on
    buggy code. After `stop_after` server failures in a row the pass stops: that is an outage, not a reviewer's answer.
    """
    report = AuditReport()
    bugs = config.load_yaml("bug_classes.yaml")
    default_schema = audit_schema(sorted(bugs))
    jobs = []
    for entry, lock in _waiting(led, role):
        if run_ids is not None and entry.payload["run_id"] not in run_ids:
            continue
        if entry.payload["results_sha256"] is None:
            cause = f"run failed: {entry.payload['run_status']} ({entry.payload['reason']})"
            led.append(entry.hypothesis_id, ledger.GRAVEYARD, {"cause": cause, "run_id": entry.payload["run_id"]})
            report.no_results.append({"hypothesis_id": entry.hypothesis_id, "cause": cause})
            continue
        try:
            jobs.append(_prepare(entry, lock, runs_dir))
        except (OSError, ValueError, SyntaxError, KeyError) as exc:
            report.errors.append(f"{entry.hypothesis_id}: not reviewed: {exc}")

    server_failures = 0
    done = 0
    for start in range(0, len(jobs), chunk_size):
        chunk = jobs[start:start + chunk_size]
        queue = llm.ModelQueue(client)
        prompts_sent, orders = [], []
        for job in chunk:
            order = None
            if class_order is not None:
                order = class_order(job.run_id)
                if sorted(order) != sorted(bugs):
                    raise ValueError(f"class order for {job.run_id} is not a reordering of the bug classes")
            prompt = prompts.skeptic_prompt(job.blinded, bugs, order)
            prompts_sent.append(prompt)
            orders.append({"class_order": order} if order else {})
            queue.add(role, prompt, audit_schema(order) if order else default_schema, system=prompts.SKEPTIC_SYSTEM)
        for job, prompt, order, result in zip(chunk, prompts_sent, orders, queue.run()):
            done += 1
            if result.error:
                failure = {"run_id": job.run_id, "role": role, "model": result.model, "kind": result.error_kind,
                           "error": result.error, "prompt_sha256": prereg.sha256_text(prompt), **order}
                led.append(job.hypothesis_id, ledger.AUDIT_FAILED, failure)
                report.failures.append({"hypothesis_id": job.hypothesis_id, **failure})
                report.errors.append(f"{job.hypothesis_id}: {result.error}")
                server_failures = server_failures + 1 if result.error_kind == llm.KIND_TIMEOUT_OR_SERVER else 0
                item = failure
            else:
                server_failures = 0
                payload = {
                    "run_id": job.run_id, "role": role, "model": result.model, "audit": result.data,
                    "cached": result.cached, "attempts": result.attempts, "seconds": round(result.seconds, 3),
                    "blinded_script_sha256": prereg.sha256_text(job.blinded.script),
                    "prompt_sha256": prereg.sha256_text(prompt), **order,
                }
                led.append(job.hypothesis_id, ledger.AUDITED, payload)
                report.audited.append({"hypothesis_id": job.hypothesis_id, **payload})
                item = payload
            if on_progress:
                on_progress(done, len(jobs), item)
        if server_failures >= stop_after:
            report.stopped = f"{server_failures} server failures in a row: is Ollama running?"
            break
    return report
