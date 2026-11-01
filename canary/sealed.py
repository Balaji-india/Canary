"""The sealed run-type table: the only record of which runs are canaries, controls, shams or real.

Why it is sealed: the reviewer's catch rate means something only if the reviewer cannot learn a run's type. So the
table has its own database file, and the path is defined here and nowhere else. The Skeptic's code never imports this
module (tests/test_skeptic.py checks that, through every module it imports, and spies on the files it opens).

Why write-once: the type is fixed when the run finishes, before any review. If it could change later, a miss could be
relabelled after seeing the reviewer's answer. There is deliberately no update or delete method.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from canary.config import DATA_DIR

SEALED_DB_PATH = DATA_DIR / "sealed.db"
PLANS_DIR = DATA_DIR / "sealed_plans"  # a batch's plan names each slot's type, so it is as secret as the table

REAL = "real"
CANARY_MEASURE = "canary_measure"
CANARY_PROBE = "canary_probe"
CONTROL = "control"
SHAM = "sham"
RUN_TYPES = {REAL, CANARY_MEASURE, CANARY_PROBE, CONTROL, SHAM}
CANARY_TYPES = {CANARY_MEASURE, CANARY_PROBE}


class SealedError(ValueError):
    """A record that contradicts itself, or a second record for the same run."""


@dataclass(frozen=True)
class Truth:
    run_id: str
    run_type: str
    bug_id: str | None
    tier: str | None
    twin_run_id: str | None
    source: str | None  # the hypothesis this run was cloned from
    details: dict  # for a canary: status, reason and impact from its clean twin
    created_at: str

    @property
    def known_buggy(self) -> bool:
        return self.run_type in CANARY_TYPES

    @property
    def known_clean(self) -> bool:
        """A real run is neither: its truth is what the whole system is trying to estimate."""
        return self.run_type in (CONTROL, SHAM)


class SealedTable:
    def __init__(self, path: Path = SEALED_DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS run_types (run_id TEXT PRIMARY KEY, run_type TEXT NOT NULL, "
                       "bug_id TEXT, tier TEXT, twin_run_id TEXT, source TEXT, details TEXT NOT NULL, "
                       "created_at TEXT NOT NULL)")

    def seal(self, run_id: str, run_type: str, bug_id: str | None = None, tier: str | None = None,
             twin_run_id: str | None = None, source: str | None = None, details: dict | None = None) -> Truth:
        """Record a run's type once. Raises SealedError if the record is inconsistent or the run already has one."""
        if run_type not in RUN_TYPES:
            raise SealedError(f"unknown run type {run_type!r}")
        if run_type in CANARY_TYPES and not (bug_id and tier):
            raise SealedError("a canary must name its bug and tier")
        if run_type not in CANARY_TYPES and (bug_id or tier or twin_run_id):
            raise SealedError(f"a {run_type} run has no planted bug")
        truth = Truth(run_id, run_type, bug_id, tier, twin_run_id, source, details or {},
                      datetime.now(timezone.utc).isoformat())
        try:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("INSERT INTO run_types VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (run_id, run_type, bug_id, tier, twin_run_id, source, json.dumps(truth.details),
                            truth.created_at))
        except sqlite3.IntegrityError as exc:
            raise SealedError(f"run {run_id} already has a sealed type") from exc
        return truth

    def _select(self, where: str = "", args: tuple = ()) -> list[Truth]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("SELECT run_id, run_type, bug_id, tier, twin_run_id, source, details, created_at "
                              f"FROM run_types {where} ORDER BY created_at, run_id", args).fetchall()
        return [Truth(r[0], r[1], r[2], r[3], r[4], r[5], json.loads(r[6]), r[7]) for r in rows]

    def get(self, run_id: str) -> Truth | None:
        found = self._select("WHERE run_id = ?", (run_id,))
        return found[0] if found else None

    def all(self) -> list[Truth]:
        return self._select()
