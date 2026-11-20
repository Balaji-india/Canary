"""Append-only findings ledger with a hash chain.

Each entry stores the hash of the entry before it and a hash of its own content, so changing or removing any
entry breaks every link after it. `verify` recomputes the chain.

The chain alone cannot show that its newest entries were removed (the shorter chain is still valid), or that the
whole chain was rewritten from an edited point onwards. The **anchor** closes that gap (roadmap findings 14 and 26):
`python -m canary.ledger anchor` writes the head's entry number and hash into `ledger_anchor.json`, a file git
tracks, and `verify` then checks that the chain still holds that hash at that entry number. Entries added after the
anchor are normal (an honest append never fails the check), so the two heads are never compared for equality.
What stays open: entries added after the newest anchor can still be removed unnoticed until the next anchor, and
someone who rewrites both the database and the anchor file is caught only by git's history of that file.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from canary.config import DB_PATH, ROOT
from canary.prereg import canonical_json, sha256_text

GENESIS_HASH = "0" * 64
ANCHOR_PATH = ROOT / "ledger_anchor.json"  # tracked by git; anchors the real ledger at DB_PATH only

PROPOSED = "proposed"
PREREGISTERED = "preregistered"
RAN = "ran"
AUDITED = "audited"
AUDIT_FAILED = "audit_failed"  # the reviewer gave no opinion. Kept in the chain, so failures cannot vanish from a report.
REPLICATED = "replicated"
ACCEPTED = "accepted"
ESCALATED = "escalated"
GRAVEYARD = "graveyard"

# The status flow from docs/DESIGN.md section 11. None means the hypothesis has no entries yet.
TRANSITIONS = {
    None: {PROPOSED},
    PROPOSED: {PREREGISTERED, GRAVEYARD},
    PREREGISTERED: {RAN},
    RAN: {AUDITED, AUDIT_FAILED, GRAVEYARD},
    AUDIT_FAILED: {AUDITED, AUDIT_FAILED, GRAVEYARD},
    # AUDITED again: a second reviewer role (Skeptic B, a diagnostic) may review a run the first one already audited.
    AUDITED: {AUDITED, AUDIT_FAILED, REPLICATED, ACCEPTED, ESCALATED, GRAVEYARD},
    REPLICATED: {ACCEPTED, ESCALATED, GRAVEYARD},
    ESCALATED: {ACCEPTED, GRAVEYARD},
    ACCEPTED: set(),
    GRAVEYARD: set(),
}


class LedgerError(ValueError):
    """An entry that breaks the status flow."""


@dataclass(frozen=True)
class Entry:
    seq: int
    hypothesis_id: str
    status: str
    payload: dict
    created_at: str
    prev_hash: str
    hash: str


def _entry_hash(seq: int, hypothesis_id: str, status: str, payload_text: str, created_at: str, prev_hash: str) -> str:
    return sha256_text(canonical_json([seq, hypothesis_id, status, payload_text, created_at, prev_hash]))


class Ledger:
    """There is deliberately no update or delete method: entries can only be added."""

    def __init__(self, path: Path = DB_PATH, *, anchor_path: Path | None = None):
        """`anchor_path` defaults to the tracked anchor file for the real ledger only, so a test's temporary ledger
        is never checked against the real ledger's anchor."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        if anchor_path is None and Path(path).resolve() == DB_PATH.resolve():
            anchor_path = ANCHOR_PATH
        self.anchor_path = anchor_path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS ledger (seq INTEGER PRIMARY KEY, hypothesis_id TEXT NOT NULL, "
                       "status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, "
                       "prev_hash TEXT NOT NULL, hash TEXT NOT NULL)")

    def append(self, hypothesis_id: str, status: str, payload: dict) -> Entry:
        """Add one entry. Raises LedgerError if the status flow does not allow it."""
        payload_text = canonical_json(payload)
        created_at = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as db:
            db.execute("BEGIN IMMEDIATE")  # read the tail and write in one step, so two writers cannot fork the chain
            try:
                current = db.execute("SELECT status FROM ledger WHERE hypothesis_id = ? ORDER BY seq DESC LIMIT 1",
                                     (hypothesis_id,)).fetchone()
                current_status = current[0] if current else None
                if status not in TRANSITIONS[current_status]:
                    raise LedgerError(f"{hypothesis_id}: cannot go from {current_status} to {status}")
                tail = db.execute("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
                seq, prev_hash = (tail[0] + 1, tail[1]) if tail else (1, GENESIS_HASH)
                entry_hash = _entry_hash(seq, hypothesis_id, status, payload_text, created_at, prev_hash)
                db.execute("INSERT INTO ledger VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (seq, hypothesis_id, status, payload_text, created_at, prev_hash, entry_hash))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return Entry(seq, hypothesis_id, status, payload, created_at, prev_hash, entry_hash)

    def _rows(self) -> list[tuple]:
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT seq, hypothesis_id, status, payload, created_at, prev_hash, hash "
                              "FROM ledger ORDER BY seq").fetchall()

    def entries(self, status: str | None = None) -> list[Entry]:
        rows = [Entry(r[0], r[1], r[2], json.loads(r[3]), r[4], r[5], r[6]) for r in self._rows()]
        return [e for e in rows if status is None or e.status == status]

    def verify(self, runs_dir: Path | None = None) -> list[str]:
        """Return every problem found (empty means intact). Reads raw rows, so a corrupt payload is reported.

        With `runs_dir`, also compares each results.json with the hash stored when the run finished. That catches
        an edited result, which the chain alone cannot see because the file lives outside the database.
        """
        problems = []
        expected_prev = GENESIS_HASH
        expected_seq = 1
        for seq, hypothesis_id, status, payload_text, created_at, prev_hash, stored in self._rows():
            if seq != expected_seq:
                problems.append(f"entry {seq}: expected number {expected_seq} (an entry is missing)")
            if prev_hash != expected_prev:
                problems.append(f"entry {seq}: does not link to the entry before it")
            if _entry_hash(seq, hypothesis_id, status, payload_text, created_at, prev_hash) != stored:
                problems.append(f"entry {seq}: content does not match its hash (edited)")
            expected_prev, expected_seq = stored, seq + 1
            if runs_dir is not None and status == RAN:
                problems.extend(_results_problems(seq, payload_text, runs_dir))
        return problems + self.anchor_problems()

    def head(self) -> tuple[int, str] | None:
        """(entry number, hash) of the newest entry, or None for an empty ledger."""
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        return (row[0], row[1]) if row else None

    def anchor_problems(self) -> list[str]:
        """Check the chain against the anchor file: the anchored hash must still be in the chain at its entry
        number. No anchor file (or none configured) means nothing to check."""
        if self.anchor_path is None or not Path(self.anchor_path).exists():
            return []
        anchor = json.loads(Path(self.anchor_path).read_text(encoding="utf-8"))
        number, expected = anchor["entries"], anchor["head_hash"]
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT hash FROM ledger WHERE seq = ?", (number,)).fetchone()
            newest = db.execute("SELECT MAX(seq) FROM ledger").fetchone()[0] or 0
        if row is None:
            return [f"anchor: entry {number} (anchored {anchor['anchored_at']}) is missing; the ledger ends at entry "
                    f"{newest}, so entries were removed"]
        if row[0] != expected:
            return [f"anchor: entry {number} does not hold the anchored hash {expected[:12]}... (the chain was "
                    f"rewritten)"]
        return []


def write_anchor(led: Ledger, path: Path | None = None) -> dict:
    """Anchor the ledger's current head in `path` (default: the ledger's anchor file). Refuses a broken chain, so an
    anchor never vouches for damage. Writes only the anchor file; no ledger entry is touched."""
    path = path if path is not None else led.anchor_path
    if path is None:
        raise LedgerError("no anchor file for this ledger: pass a path")
    problems = led.verify()
    if problems:
        raise LedgerError(f"the chain has problems, so it is not anchored: {problems[0]}")
    head = led.head()
    if head is None:
        raise LedgerError("an empty ledger has nothing to anchor")
    anchor = {"entries": head[0], "head_hash": head[1], "anchored_at": datetime.now(timezone.utc).isoformat()}
    with Path(path).open("w", encoding="utf-8", newline="\n") as handle:  # LF on every platform, as git stores it
        handle.write(json.dumps(anchor, indent=1) + "\n")
    return anchor


def _results_problems(seq: int, payload_text: str, runs_dir: Path) -> list[str]:
    try:
        payload = json.loads(payload_text)
    except ValueError:
        return [f"entry {seq}: payload is not valid JSON"]
    problems = []
    # A failed run has no results hash, and entries written before script hashing have no script hash: both are skipped.
    for label, name, key in (("results", "results.json", "results_sha256"), ("script", "experiment.py", "script_sha256")):
        expected = payload.get(key)
        if expected is None:
            continue
        path = runs_dir / payload["run_id"] / name
        if not path.exists():
            problems.append(f"entry {seq}: {label} file is missing ({path})")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            problems.append(f"entry {seq}: {label} file does not match its stored hash (edited)")
    return problems


def main(argv: list[str] | None = None) -> int:
    """`python -m canary.ledger anchor` writes the anchor of the real ledger; `check` checks the chain and anchor."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m canary.ledger")
    parser.add_argument("action", choices=["anchor", "check"])
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--anchor", type=Path, default=None, help="anchor file (default: ledger_anchor.json)")
    args = parser.parse_args(argv)
    led = Ledger(args.db, anchor_path=args.anchor)
    if args.action == "anchor":
        anchor = write_anchor(led)
        print(f"Anchored entry {anchor['entries']} ({anchor['head_hash'][:12]}...) in {led.anchor_path}")
        return 0
    problems = led.verify()
    for problem in problems:
        print(f"[FAIL] {problem}")
    print(f"Ledger check: {'FAILED' if problems else 'OK'} ({len(led.entries())} entries, anchor "
          f"{led.anchor_path if led.anchor_path and Path(led.anchor_path).exists() else 'none'})")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
