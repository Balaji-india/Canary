"""Development-batch report for task-dev-2: what the batch shows about llama-checklist, deciding nothing.

Run with `python -m eval.dev_report --batch task-dev-2` after `python -m eval.cutoff --batch task-dev-2`. These are
development numbers: this batch chose the cut-off, so nothing here can confirm anything (that is confirm-llama-2's job,
on bases the reviewer has never seen). Reported, as listed in docs/plans/llama_checklist_confirmation_v2.md section 5:
- AUC of P(flag) with run-level and base-level 90% intervals, and each trivial feature's AUC;
- recall and false alarms at the batch's own cut-off, if it has been chosen;
- **the decoy diagnostic:** on clean runs, llama's flag rate (the code's checklist decision) and mean P(flag), by decoy
  class, against plain clean runs. Two references: task-dev-1's clean runs (no padding, no decoys) and this batch's
  clean runs whose decoy has no code (B03 obvious, B06 obvious, B09: padded, but nothing added). If decoys draw flags,
  specificity measured with decoys is pessimistic for real runs, which carry none (PROGRESS.md, Mission 4.1).
With one decoy per variant in a 40-run batch, each class has two clean runs: read the classes as anecdotes and the
pooled rows as the measurement. Writes eval/results/<batch>/dev_report.json.
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from canary import ledger, sandbox, sealed, separation, trust
from canary.saboteur import decoys
from eval import compare_tasks, cutoff

ROLE = cutoff.ROLE
REFERENCE_BATCH = "task-dev-1"
NO_CODE, WITH_CODE, PLAIN = "decoys without code (padded, nothing added)", "decoys with code", "plain clean runs"


def _group(rows: list[dict]) -> dict:
    """Count, flag rate (code decision) and mean P(flag) of a group of clean runs."""
    scores = [r["score"] for r in rows if r["score"] is not None]
    return {"runs": len(rows), "flagged": sum(r["flagged"] for r in rows),
            "flag_rate": sum(r["flagged"] for r in rows) / len(rows) if rows else None,
            "mean_p_flag": statistics.mean(scores) if scores else None, "scored": len(scores)}


def clean_rows(table: sealed.SealedTable, led: ledger.Ledger, batch: str, role: str = ROLE) -> list[dict]:
    """One row per reviewed clean run: its decoy (if any), the code's decision and the score."""
    observations, _ = trust.collect_observations(table, led, role, batch)
    scores = cutoff.role_scores(table, led, batch, role)
    rows = []
    for o in observations:
        if o.run_type not in (sealed.CONTROL, sealed.SHAM):
            continue
        decoy = table.get(o.run_id).details.get("decoy")
        variant = (decoy["bug_id"], decoy["tier"]) if decoy else None
        rows.append({"run_id": o.run_id, "run_type": o.run_type, "decoy": list(variant) if variant else None,
                     "decoy_has_code": bool(variant) and decoys.DECOYS[variant] is not decoys._no_code,
                     "flagged": o.flagged, "score": scores.get(o.run_id, (False, None))[1]})
    return rows


def decoy_diagnostic(rows: list[dict], reference: list[dict], reference_batch: str = REFERENCE_BATCH) -> dict:
    """Clean runs by decoy class, pooled with and without decoy code, and the plain clean runs of the reference."""
    by_class: dict[str, list[dict]] = {}
    for r in rows:
        if r["decoy"]:
            by_class.setdefault(r["decoy"][0], []).append(r)
    return {
        "by_decoy_class": {c: {**_group(rs), "variants": sorted(f"{r['decoy'][1]}{'' if r['decoy_has_code'] else ' (no code)'}"
                                                                 for r in rs)}
                           for c, rs in sorted(by_class.items())},
        WITH_CODE: _group([r for r in rows if r["decoy_has_code"]]),
        NO_CODE: _group([r for r in rows if r["decoy"] and not r["decoy_has_code"]]),
        f"{PLAIN} ({reference_batch})": _group(reference),
    }


def build(table: sealed.SealedTable, led: ledger.Ledger, batch: str, runs_dir: Path = sandbox.RUNS_DIR,
          cutoff_record: dict | None = None, reference_batch: str = REFERENCE_BATCH) -> dict:
    scores = cutoff.role_scores(table, led, batch, ROLE)
    truths = {r: table.get(r) for r in scores}
    base_of = {r: t.source or r for r, t in truths.items()}
    buggy = {r for r, (b, _) in scores.items() if b}
    values = {r: s for r, (_, s) in scores.items()}
    features = {r: compare_tasks.run_features(r, runs_dir) for r in scores}
    at_cutoff = None
    if cutoff_record:
        c = cutoff_record["cutoff"]
        bug = [s for r, s in values.items() if r in buggy and s is not None]
        clean = [s for r, s in values.items() if r not in buggy and s is not None]
        at_cutoff = {"cutoff": c, "recall": sum(s >= c for s in bug) / len(bug) if bug else None,
                     "false_alarm_rate": sum(s >= c for s in clean) / len(clean) if clean else None}
    return {
        "batch": batch, "role": ROLE, "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "development numbers: this batch chose the cut-off, so nothing here confirms anything",
        "runs": len(scores), "buggy": len(buggy), "auc": separation.auc_summary(values, buggy, base_of),
        "trivial_features": compare_tasks.feature_baselines(set(scores), buggy, base_of, features),
        "at_own_cutoff": at_cutoff,
        "decoy_diagnostic": decoy_diagnostic(clean_rows(table, led, batch), clean_rows(table, led, reference_batch),
                                             reference_batch),
    }


def _rate(g: dict) -> str:
    if not g["runs"]:
        return "no runs"
    mean = "n/a" if g["mean_p_flag"] is None else f"{g['mean_p_flag']:.3f}"
    return f"{g['flagged']}/{g['runs']} flagged ({g['flag_rate']:.0%}), mean P(flag) {mean}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", default=cutoff.DEV_BATCH)
    args = parser.parse_args(argv)
    if args.batch.startswith("confirm"):
        print("This report is for development batches; a confirmation batch is read only by eval.confirm.")
        return 2
    path = cutoff.cutoff_path(args.batch)
    record = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    result = build(sealed.SealedTable(), ledger.Ledger(), args.batch, cutoff_record=record)
    if not result["runs"]:
        print(f"Batch {args.batch} has no {ROLE} audits yet.")
        return 1
    auc = result["auc"]
    iv = auc["interval_90_base"]
    print(f"{args.batch}, {ROLE}: {result['runs']} runs ({result['buggy']} canaries). Development numbers only.")
    print(f"  AUC {auc['value']:.3f}, base 90% [{iv[0]:.3f}, {iv[1]:.3f}]" if auc["value"] is not None and iv else "  AUC n/a")
    for name, f in result["trivial_features"].items():
        if f["value"] is not None:
            print(f"  trivial {name}: AUC {f['value']:.3f}")
    if result["at_own_cutoff"]:
        c = result["at_own_cutoff"]
        print(f"  at its own cut-off {c['cutoff']:.4g}: recall {c['recall']:.2f}, false alarms {c['false_alarm_rate']:.2f}")
    d = result["decoy_diagnostic"]
    print("  Decoy diagnostic (clean runs only):")
    for cls, g in d["by_decoy_class"].items():
        print(f"    {cls} ({', '.join(g['variants'])}): {_rate(g)}")
    for key in (WITH_CODE, NO_CODE, f"{PLAIN} ({REFERENCE_BATCH})"):
        print(f"    {key}: {_rate(d[key])}")
    out = compare_tasks.RESULTS_DIR / args.batch.replace("-", "_") / "dev_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
