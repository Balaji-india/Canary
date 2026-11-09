"""Choose and lock the llama-checklist score cut-off on a development batch, before the confirmation batch exists.

Run once per development batch: `python -m eval.cutoff --batch task-dev-2`. It reads each run's score for
`skeptic_c_checklist` (the one stored with its first audit; for older batches, the matched rescore or the fresh pass),
picks the cut-off with the highest Youden's J, and writes it to a file that is never overwritten. The confirmation
plan records that file's SHA-256, and eval/confirm.py refuses to run if the two disagree.

History: the first cut-off (task-dev-1, 2026-11-08) was chosen on length-confounded data (line-count AUC 0.85), and on
padded clean runs it flagged 14-17 of 20 (cue probe). It is kept, superseded, at its old path. The second is chosen on
task-dev-2: pool 1, padded, with decoys (canary/saboteur/decoys.py), so no size feature separates the run types.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from canary import ledger, mixer, sealed, trust
from eval import compare_tasks

ROLE = "skeptic_c_checklist"
DEV_BATCH = "task-dev-2"
CAVEATS = {
    "task-dev-1": "chosen on task-dev-1, whose canaries were longer than its clean runs (line-count AUC 0.85): "
                  "length-confounded data, so the cut-off may not transfer to a length-matched batch",
    "task-dev-2": "chosen on task-dev-2: 40 runs on pool 1 (bases also used by rq1-full and task-dev-1), padded and "
                  "with decoys; the confirmation batch uses new bases (pool 2)",
}


def cutoff_path(batch: str) -> Path:
    return compare_tasks.RESULTS_DIR / batch.replace("-", "_") / "llama_checklist_cutoff.json"


CUTOFF_PATH = cutoff_path(DEV_BATCH)  # the cut-off the current confirmation plan uses
SUPERSEDED_CUTOFF_PATH = cutoff_path("task-dev-1")
TIE_RULE = "highest J; on a tie, the lowest cut-off"


class LockError(RuntimeError):
    """A locked file exists already, or does not match the hash it was locked with."""


def choose_cutoff(bug: list[float], clean: list[float]) -> dict:
    """The cut-off c with the highest J = P(score >= c | buggy) - P(score >= c | clean).

    Candidates are the midpoints between neighbouring distinct scores, plus one below all (flag everything) and one
    above all (flag nothing): any c between two neighbours flags the same runs. Ties go to the lowest c.
    """
    if not bug or not clean:
        raise ValueError("need buggy and clean scores")
    values = sorted(set(bug) | set(clean))
    candidates = [values[0] - 1e-9] + [(a + b) / 2 for a, b in zip(values, values[1:])] + [values[-1] + 1e-9]
    best = None
    for c in candidates:  # ascending, and only a strictly higher J replaces the best: ties keep the lowest c
        recall = sum(s >= c for s in bug) / len(bug)
        false_alarms = sum(s >= c for s in clean) / len(clean)
        if best is None or recall - false_alarms > best["j"]:
            best = {"cutoff": c, "j": recall - false_alarms, "recall": recall, "false_alarm_rate": false_alarms}
    best["tied_candidates"] = sum(
        1 for c in candidates
        if abs(sum(s >= c for s in bug) / len(bug) - sum(s >= c for s in clean) / len(clean) - best["j"]) < 1e-12)
    return best


def role_scores(table: sealed.SealedTable, led: ledger.Ledger, batch: str, role: str,
                rescore_dir: Path = mixer.RESCORE_DIR) -> dict[str, tuple[bool, float | None]]:
    """Run ID -> (buggy, fresh score), by the same rule as compare_tasks' fresh AUC."""
    rescores = {(r["role"], r["run_id"]): r for r in mixer.read_rescores(batch, rescore_dir)}
    fresh = {(r["role"], r["run_id"]): r for r in mixer.read_rescores(batch, rescore_dir, mixer.FRESH)}
    observations, _ = trust.collect_observations(table, led, role, batch)
    observations = [o for o in observations if o.run_type in (sealed.CANARY_MEASURE, sealed.CONTROL, sealed.SHAM)]
    audits = compare_tasks.first_audits(led, role, {o.run_id for o in observations})
    out = {}
    for o in observations:
        prompt = audits[o.run_id]["prompt_sha256"]
        score = audits[o.run_id].get("score")
        first, again = rescores.get((role, o.run_id)), fresh.get((role, o.run_id))
        if not score and first and first["outcome"] == "matched" and first["prompt_sha256"] == prompt:
            score = first["score"]
        if not score and again and again.get("score") and again["prompt_sha256"] == prompt:
            score = again["score"]
        out[o.run_id] = (o.run_type == sealed.CANARY_MEASURE, score["p_flag"] if score else None)
    return out


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lock(path: Path, record: dict) -> str:
    """Write the record once and return its SHA-256. Refuses to overwrite: a cut-off chosen twice is not locked."""
    if path.exists():
        raise LockError(f"{path} is already locked (SHA-256 {sha256_file(path)})")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return sha256_file(path)


def build_record(scores: dict[str, tuple[bool, float | None]], batch: str = DEV_BATCH) -> dict:
    bug = [s for b, s in scores.values() if b and s is not None]
    clean = [s for b, s in scores.values() if not b and s is not None]
    missing = sum(s is None for _, s in scores.values())
    if missing:
        raise ValueError(f"{missing} runs have no score; run `rescore --batch {batch} --reviewer skeptic_c --fresh` first")
    return {"role": ROLE, "batch": batch, "rule": TIE_RULE, "scored_buggy": len(bug), "scored_clean": len(clean),
            "auc_on_these_scores": compare_tasks.auc(bug, clean), **choose_cutoff(bug, clean),
            "caveat": CAVEATS.get(batch, f"chosen on {batch}"),
            "chosen_at": datetime.now(timezone.utc).isoformat()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", default=DEV_BATCH, help="the development batch (never a confirmation batch)")
    args = parser.parse_args(argv)
    if args.batch.startswith("confirm"):
        print("A cut-off is chosen on a development batch, never on the batch that tests it.")
        return 2
    scores = role_scores(sealed.SealedTable(), ledger.Ledger(), args.batch, ROLE)
    if not scores:
        print(f"Batch {args.batch} has no {ROLE} audits yet.")
        return 1
    record = build_record(scores, args.batch)
    path = cutoff_path(args.batch)
    try:
        digest = lock(path, record)
    except LockError as exc:
        print(exc)
        return 1
    print(f"Cut-off {record['cutoff']:.6g}: J {record['j']:+.3f} (recall {record['recall']:.2f}, false alarms "
          f"{record['false_alarm_rate']:.2f}) on {record['scored_buggy']}+{record['scored_clean']} runs.")
    print(f"Locked {path} SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
