"""Tripwire records in the ledger (Mission 5.1 step 11; docs/plans/mission_5_1_tripwires.md, sections 2.4 and 8).

Why the ledger: `trust`, the gate and Mission 4's union reviewer read reviewers' opinions from the ledger. A tripwire
record written there as an `audited` entry under its own role (`tripwire_v1`) goes through exactly the same join and
statistics as an LLM audit, and is logged alone, so the union's numbers can later be measured from its two parts'
records (plan section 8: union verdicts are computed per run from both halves, never from combined rates).

One entry per run, the first one stands (as for every reviewer role). The entry carries the verdict and suspected
class (`audit`, the shape `trust.collect_observations` reads), each check's status (so "fired" and "unverifiable" can
still be told apart), the replay status, the full tripwire version and the SHA-256 of the whole stored record, so the
record file on disk can be checked against the ledger later.

One role, one version: the role name carries the version word (`v1`), and the full version is the SHA-256 of the
three source files. If the code changes, its records would be a different reviewer; writing them under the same role
is refused, so `trust --role tripwire_v1` can never pool two versions.

What this module may see: run IDs, run folders (through `canary.tripwires`, which replays only in a temporary copy)
and stored tripwire records. It never opens the sealed table, the sealed plans or the twins, and reads no reviewer's
opinion: of other ledger entries it uses only the status flow and which runs already hold a tripwire record
(tests/test_tripwire_ledger.py checks the imports). Choosing which runs to record is the caller's job.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from canary import ledger, sandbox, tripwires
from canary.config import DATA_DIR
from canary.prereg import canonical_json

ROLE = f"tripwire_{tripwires.VERSION}"
RECORDS_DIR = DATA_DIR / "tripwires" / tripwires.VERSION  # where records made here are stored (plan section 2.4)
TEST_RECORDS_DIR = DATA_DIR / "tripwires" / "test"  # the locked test's records, one folder per batch
REPLAY_TIER = "replay"


class TripwireLedgerError(ValueError):
    """A write that would mix tripwire versions or store a record that is not a full replay-tier record."""


def record_sha256(record: dict) -> str:
    """SHA-256 of the record's canonical JSON (sorted keys), so the same record always gives the same hash."""
    return hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()


def ledger_payload(run_id: str, record: dict) -> dict:
    """The `audited` entry for one run's tripwire record. Refuses a record of another run or of the static tier.

    A static-tier `pass` vouches for S1 and S2 only (plan section 2.3), so it is not a reviewer's opinion on the run.
    """
    if record.get("run_id", run_id) != run_id:
        raise TripwireLedgerError(f"record of {record.get('run_id')} offered for {run_id}")
    if record.get("tier") != REPLAY_TIER:
        raise TripwireLedgerError(f"{run_id}: only replay-tier records go to the ledger (tier {record.get('tier')!r})")
    return {
        "run_id": run_id,
        "role": ROLE,
        "tripwire_version": record["version"],
        "record_sha256": record_sha256(record),
        "audit": {"verdict": record["verdict"], "bug_class": record["bug_class"], "evidence": record["evidence"]},
        "checks": {name: check["status"] for name, check in sorted(record["checks"].items())},
        "replay": record["replay"],
    }


def find_record(run_id: str, version: str, folders: list[Path]) -> dict | None:
    """The first stored record of this run made by this exact tripwire version, searching `folders` in order."""
    for folder in folders:
        path = folder / f"{run_id}.json"
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("version") == version and record.get("run_id", run_id) == run_id:
            return record
    return None


def recorded_runs(led: ledger.Ledger) -> dict[str, str]:
    """{run_id: tripwire version} of every run that already holds a record under ROLE (the first one stands)."""
    found: dict[str, str] = {}
    for entry in led.entries(ledger.AUDITED):
        if entry.payload.get("role") == ROLE:
            found.setdefault(entry.payload["run_id"], entry.payload["tripwire_version"])
    return found


def _ledger_state(led: ledger.Ledger) -> tuple[dict[str, str], dict[str, str]]:
    """{run_id: hypothesis_id} of runs that reached the ledger, and {hypothesis_id: latest status}."""
    hypothesis_of, latest = {}, {}
    for entry in led.entries():
        latest[entry.hypothesis_id] = entry.status
        if entry.status == ledger.RAN and "run_id" in entry.payload:
            hypothesis_of[entry.payload["run_id"]] = entry.hypothesis_id
    return hypothesis_of, latest


@dataclass
class RecordReport:
    """What `record_runs` did with each run, so nothing is skipped silently."""
    written: list[str] = field(default_factory=list)
    would_write: list[str] = field(default_factory=list)  # dry run: a record is ready, nothing was written
    already_recorded: list[str] = field(default_factory=list)
    not_in_ledger: list[str] = field(default_factory=list)  # no `ran` entry: nothing to attach a record to
    closed: list[str] = field(default_factory=list)  # accepted, escalated or in the graveyard: the flow allows no review
    no_record: list[str] = field(default_factory=list)  # dry run, or no run folder: no record of this version exists
    made: list[str] = field(default_factory=list)  # records made now (replayed in a temporary copy) and stored
    verdicts: Counter = field(default_factory=Counter)

    def summary(self) -> str:
        parts = [f"{len(self.written)} written", f"{len(self.would_write)} ready (dry run, not written)",
                 f"{len(self.already_recorded)} already recorded", f"{len(self.not_in_ledger)} not in the ledger",
                 f"{len(self.closed)} closed", f"{len(self.no_record)} without a record", f"{len(self.made)} made now"]
        verdicts = ", ".join(f"{k} {v}" for k, v in sorted(self.verdicts.items())) or "none"
        return "; ".join(parts) + f"; verdicts {verdicts}"


def record_runs(run_ids: list[str], led: ledger.Ledger, *, write: bool = False, folders: list[Path] | None = None,
                runs_dir: Path = sandbox.RUNS_DIR, records_dir: Path = RECORDS_DIR,
                inspect=tripwires.run_tripwires) -> RecordReport:
    """Attach each run's tripwire record to the ledger under ROLE. Safe to repeat: recorded runs are skipped.

    A stored record of the current version (searched in `folders`, then `records_dir`) is used as it is: the same run
    always gives the same record. Otherwise, only when `write` is set, the record is made now from the run folder's
    path (`inspect`; the replay runs in a temporary copy, nothing is written in `runs_dir`) and stored in
    `records_dir`. Without `write` nothing is made, stored or appended: the report says what would happen.

    Raises TripwireLedgerError before any write if ROLE already holds records of another tripwire version.
    """
    version = tripwires.source_version()
    others = sorted({v for v in recorded_runs(led).values() if v != version})
    if others:
        raise TripwireLedgerError(f"role {ROLE} already holds records of version {others[0][:19]}...; this code is "
                                  f"{version[:19]}... A changed tripwire is a new reviewer: give it a new VERSION.")
    search = list(folders or []) + [records_dir]
    report = RecordReport()
    hypothesis_of, latest = _ledger_state(led)
    recorded = recorded_runs(led)
    for run_id in run_ids:
        if run_id in recorded:
            report.already_recorded.append(run_id)
            continue
        hypothesis = hypothesis_of.get(run_id)
        if hypothesis is None:
            report.not_in_ledger.append(run_id)
            continue
        if ledger.AUDITED not in ledger.TRANSITIONS[latest[hypothesis]]:
            report.closed.append(run_id)
            continue
        record = find_record(run_id, version, search)
        if record is None and write and (runs_dir / run_id).is_dir():
            record = {"run_id": run_id, **inspect(runs_dir / run_id)}
            records_dir.mkdir(parents=True, exist_ok=True)
            (records_dir / f"{run_id}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
            report.made.append(run_id)
        if record is None:
            report.no_record.append(run_id)
            continue
        payload = ledger_payload(run_id, record)
        report.verdicts[payload["audit"]["verdict"]] += 1
        if not write:
            report.would_write.append(run_id)
            continue
        entry = led.append(hypothesis, ledger.AUDITED, payload)
        latest[hypothesis] = entry.status
        recorded[run_id] = version
        report.written.append(run_id)
    return report


def verify_records(led: ledger.Ledger, folders: list[Path]) -> list[str]:
    """Problems between the ledger's tripwire entries and the record files (empty means every file matches).

    The ledger stores each record's hash; a record file edited or lost after it was written shows up here.
    """
    problems = []
    for entry in led.entries(ledger.AUDITED):
        payload = entry.payload
        if payload.get("role") != ROLE:
            continue
        record = find_record(payload["run_id"], payload["tripwire_version"], folders)
        if record is None:
            problems.append(f"entry {entry.seq}: no record file of {payload['run_id']} with its version")
        elif record_sha256(record) != payload["record_sha256"]:
            problems.append(f"entry {entry.seq}: the record file of {payload['run_id']} does not match its hash")
    return problems
