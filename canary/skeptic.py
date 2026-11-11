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

from canary import blinding, config, ledger, llm, prereg, review_tasks, sandbox
from canary.codegen import SCRIPT_NAME

PASS = "pass"
FLAG = "flag"
DEFAULT_ROLE = "skeptic_a"
DEFAULT_CHUNK = 5  # reviews stored per chunk, and the longest stretch of an outage before the stop rule looks
DEFAULT_STOP_AFTER = 3


audit_schema = review_tasks.baseline_schema  # the baseline task's schema


def task_of(models_cfg: dict, role: str) -> str:
    """The review task a role uses (`task:` in models.yaml), the baseline unless set. Unknown names fail early."""
    task = models_cfg["roles"][role].get("task", review_tasks.BASELINE)
    if task not in review_tasks.TASKS:
        raise ValueError(f"role {role}: unknown review task {task!r}")
    return task


def _role_top_logprobs(models_cfg: dict, role: str) -> int | None:
    """The role's own `top_logprobs` (or the one on the role its alias points to), None if neither sets it."""
    roles = models_cfg["roles"]
    for cfg in (roles[role], roles[roles[role].get("use_role", role)]):
        if "top_logprobs" in cfg:
            return int(cfg["top_logprobs"])
    return None


def top_logprobs_of(models_cfg: dict, role: str) -> int:
    """How many token probabilities a role's reviews ask for: the role's setting, else the global
    `llm.review_top_logprobs`. Cloud roles set 0, because their providers give none."""
    own = _role_top_logprobs(models_cfg, role)
    return own if own is not None else int(models_cfg["llm"].get("review_top_logprobs", 0))


# Failures that count toward the "N in a row" stop: the endpoint may be down, or refuse every request alike.
_STREAK_KINDS = (llm.KIND_TIMEOUT_OR_SERVER, llm.KIND_REQUEST_REFUSED)


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


def blinded_run(led: ledger.Ledger, run_id: str, runs_dir: Path = sandbox.RUNS_DIR) -> blinding.BlindedRun:
    """The blinded view of one finished run, by full ID or unique prefix (`cloud-smoke` uses old run 1875ec26)."""
    ran = [e for e in led.entries(ledger.RAN) if str(e.payload.get("run_id", "")).startswith(run_id)]
    if len(ran) != 1:
        raise ValueError(f"run {run_id}: {len(ran)} finished runs match, need exactly 1")
    locks = [e for e in led.entries(ledger.PREREGISTERED) if e.hypothesis_id == ran[0].hypothesis_id]
    return _prepare(ran[0], locks[0].payload, runs_dir).blinded


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
    buggy code. After `stop_after` server failures (or refused requests) in a row the pass stops: that is an outage or
    a systematic refusal, not a reviewer's answer.

    A daily limit, an access problem or a config problem (`llm.STOP_KINDS`) writes nothing to the ledger and ends the
    pass after the current chunk. Why: a quota stop depends on how many calls were made, not on the run, so it says
    nothing about the reviewer, and a trace in the ledger would later count as a failed audit against it. The runs not
    asked simply stay waiting, and the same command continues with them after the reset.
    """
    report = AuditReport()
    bugs = config.load_yaml("bug_classes.yaml")
    bug_ids = sorted(bugs)
    task = task_of(client.cfg, role)
    # Token probabilities give each audit a score for AUC. Off unless models.yaml asks, so tests and old paths keep
    # their cached replies (a call with probabilities always asks the model). Cloud roles set 0 on the role.
    top_logprobs = top_logprobs_of(client.cfg, role)
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
    stop_reason = None
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
            system, prompt, schema = review_tasks.build(task, job.blinded, bugs, order)
            prompts_sent.append(prompt)
            orders.append({"class_order": order} if order else {})
            queue.add(role, prompt, schema, system=system, top_logprobs=top_logprobs)
        for job, prompt, order, result in zip(chunk, prompts_sent, orders, queue.run()):
            if result.error and result.error_kind in llm.STOP_KINDS:
                stop_reason = stop_reason or result.error  # nothing stored: the run was not asked, or not answered
                continue
            done += 1
            if result.error:
                failure = {"run_id": job.run_id, "role": role, "model": result.model, "kind": result.error_kind,
                           "error": result.error, "prompt_sha256": prereg.sha256_text(prompt), **order}
                led.append(job.hypothesis_id, ledger.AUDIT_FAILED, failure)
                report.failures.append({"hypothesis_id": job.hypothesis_id, **failure})
                report.errors.append(f"{job.hypothesis_id}: {result.error}")
                server_failures = server_failures + 1 if result.error_kind in _STREAK_KINDS else 0
                item = failure
            else:
                server_failures = 0
                # Code, not the model, turns the reply into the verdict that trust statistics use.
                payload = {
                    "run_id": job.run_id, "role": role, "model": result.model, "audit": result.data,
                    "task": task, "decision": review_tasks.decide(task, result.data, job.blinded),
                    "cached": result.cached, "attempts": result.attempts, "seconds": round(result.seconds, 3),
                    "blinded_script_sha256": prereg.sha256_text(job.blinded.script),
                    "prompt_sha256": prereg.sha256_text(prompt), **order,
                }
                if top_logprobs:
                    payload["score"] = review_tasks.score(task, result.logprobs, bug_ids)
                led.append(job.hypothesis_id, ledger.AUDITED, payload)
                report.audited.append({"hypothesis_id": job.hypothesis_id, **payload})
                item = payload
            if on_progress:
                on_progress(done, len(jobs), item)
        if stop_reason:
            report.stopped = f"stopped without storing anything for the runs not yet reviewed: {stop_reason}"
            break
        if server_failures >= stop_after:
            where = "is the API reachable, and does it accept the request?" if client.cloud_entry(role) else \
                "is Ollama running?"
            report.stopped = f"{server_failures} server failures in a row: {where}"
            break
    return report


def rescore(client: llm.LLM, led: ledger.Ledger, role: str, run_ids: set[str], runs_dir: Path = sandbox.RUNS_DIR,
            done: set[str] | None = None, on_record: Callable[[dict], None] | None = None,
            stop_after: int = DEFAULT_STOP_AFTER, always_score: bool = False) -> list[dict]:
    """Ask the same question again to get token probabilities for audits stored without a score.

    Why it is safe: the prompt is rebuilt from the same files and must hash to the audit's stored `prompt_sha256`,
    and a score is kept only when the new reply equals the stored one. The ledger, the stored verdicts and the LLM
    cache are not written; the caller stores each record. `done` holds run IDs already rescored for this role.
    Only the first audit of a run counts, as everywhere else. Returns one record per run tried.

    `always_score` (the "fresh" pass) keeps the score of a reply that differs from the stored one too. Matched-only
    AUC rests on the runs where the model happened to repeat itself, which may be its most certain ones; a fresh score
    for every run removes that selection. It is a score of the new reply, not of the stored verdict, and is reported
    as such.

    A role with `top_logprobs: 0` (cloud roles) has no probabilities to give, so this becomes the **repeat pass**: the
    same question asked again with the cache bypassed (and not written), recording whether the reply and the verdict
    changed, with `score` None. Without the bypass the cache would hand back the stored reply and every run would look
    perfectly repeatable. A daily-limit or access stop ends the pass with nothing recorded for the run.
    """
    task = task_of(client.cfg, role)
    bugs = config.load_yaml("bug_classes.yaml")
    bug_ids = sorted(bugs)
    repeat_only = _role_top_logprobs(client.cfg, role) == 0
    top_logprobs = 0 if repeat_only else (client.cfg["llm"].get("review_top_logprobs") or review_tasks.TOP_LOGPROBS)
    done = done or set()
    locks, ran, first = {}, {}, {}
    for entry in led.entries():
        if entry.status == ledger.PREREGISTERED:
            locks[entry.hypothesis_id] = entry.payload
        elif entry.status == ledger.RAN and "run_id" in entry.payload:
            ran[entry.payload["run_id"]] = entry
        elif entry.status == ledger.AUDITED and entry.payload.get("role") == role and entry.payload["run_id"] in run_ids:
            first.setdefault(entry.payload["run_id"], entry)
    records, server_failures = [], 0
    for run_id in sorted(set(first) - done):
        audit = first[run_id]
        base = {"role": role, "run_id": run_id, "task": task, "audit_entry_hash": audit.hash,
                "prompt_sha256": audit.payload["prompt_sha256"]}
        try:
            job = _prepare(ran[run_id], locks[ran[run_id].hypothesis_id], runs_dir)
        except (OSError, ValueError, SyntaxError, KeyError) as exc:
            record = {**base, "outcome": "files_changed", "detail": str(exc)}
        else:
            system, prompt, schema = review_tasks.build(task, job.blinded, bugs, audit.payload.get("class_order"))
            if prereg.sha256_text(prompt) != audit.payload["prompt_sha256"]:
                record = {**base, "outcome": "prompt_changed"}
            else:
                try:
                    # Repeat pass: refresh=True so the cache cannot hand back the stored reply.
                    result = client.call(role, prompt, schema, system=system, top_logprobs=top_logprobs,
                                         cache_write=False, refresh=repeat_only)
                except llm.LLMError as exc:
                    server_failures = server_failures + 1 if exc.kind in _STREAK_KINDS else 0
                    if on_record:
                        on_record({**base, "outcome": "call_failed", "kind": exc.kind, "retry": True})
                    if server_failures >= stop_after or exc.kind in llm.STOP_KINDS:
                        break
                    continue  # not stored, so a resume tries it again
                server_failures = 0
                matched = result.data == audit.payload["audit"]
                scored = (matched or always_score) and not repeat_only
                record = {**base, "outcome": "matched" if matched else "reply_differs", "model": result.model,
                          "attempts": result.attempts, "seconds": round(result.seconds, 3),
                          "score": review_tasks.score(task, result.logprobs, bug_ids) if scored else None}
                if not matched:
                    # Diagnostics only: did the repeat change the verdict, or only the wording? It decides nothing.
                    stored = audit.payload.get("decision") or audit.payload["audit"]
                    new = review_tasks.decide(task, result.data, job.blinded)
                    changed = sorted(k for k in result.data if result.data.get(k) != audit.payload["audit"].get(k))
                    record.update({"new_decision": new, "verdict_changed": new["verdict"] != stored["verdict"],
                                   "fields_changed": changed})
        records.append(record)
        if on_record:
            on_record(record)
    return records
