"""Dry proof that the decoy padding leaves no trivial feature separating buggy from clean runs (pool 1).

Run with `python -m eval.padding_proof`. No experiment and no model runs. Two kinds of evidence:
- Script features (line, character and statement count; the padding helper's size in statements and characters),
  from the dry plan of every slot's script exactly as it would be written: the 40-run development batch's own plan
  (task-dev-2, seed 1110) and a 100-run plan the size of the confirmation batch (seed 1109). Each also without decoys,
  to show what decoys change.
- Result features (effect spread; effect size and best arm's score as diagnostics), which padding and decoys cannot
  change (they never change a number: tests/test_decoys.py). So they are measured on the pool-1 runs that already
  exist (rq1-full and task-dev-1, 220 runs).
Rule, the same as the length gate: a feature passes when its base-level 90% AUC interval contains 0.5.
Writes eval/results/padding_v2/dry_proof.json.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from canary import mixer, sealed, separation
from eval import compare_tasks

PLANS = {"task-dev-2 (40 runs, seed 1110)": (40, 1110), "100 runs, seed 1109": (100, 1109)}
RESULT_FEATURES = ("effect_spread",)
RESULT_DIAGNOSTICS = ("effect_size", "top_score")
EXISTING_BATCHES = ("rq1-full", "task-dev-1")
OUT = compare_tasks.RESULTS_DIR / "padding_v2" / "dry_proof.json"


def _row(summary: dict) -> dict:
    interval = summary.get("interval_90_base")
    return {"auc": summary.get("value"), "interval_90_base": interval,
            "contains_half": bool(interval and interval[0] <= 0.5 <= interval[1])}


def script_features(pool: dict) -> dict:
    out = {}
    for name, (runs, seed) in PLANS.items():
        for decoys in (True, False):
            check = separation.length_check(mixer.dry_rows(mixer.plan_batch("proof", runs, pool, seed, decoys=decoys)))
            out[f"{name}, {'decoys' if decoys else 'no decoys (old design)'}"] = {
                "decoys": decoys, "passes": check["passes"], "runs": check["runs"], "buggy": check["buggy"],
                "features": {f: _row(s) for f, s in check["features"].items()}}
    return out


def result_features(table: sealed.SealedTable) -> dict:
    truths = [t for t in table.all() if t.details.get("batch") in EXISTING_BATCHES
              and t.run_type in (sealed.CANARY_MEASURE, sealed.CONTROL, sealed.SHAM)]
    features = {t.run_id: compare_tasks.run_features(t.run_id) for t in truths}
    buggy = {t.run_id for t in truths if t.known_buggy}
    base_of = {t.run_id: t.source or t.run_id for t in truths}
    out = {}
    for name in RESULT_FEATURES + RESULT_DIAGNOSTICS:
        summary = separation.auc_summary({r: (f or {}).get(name) for r, f in features.items()}, buggy, base_of)
        out[name] = {**_row(summary), "gating": name in RESULT_FEATURES, "buggy": summary["scored_buggy"],
                     "clean": summary["scored_clean"], "bases": summary["bases"]}
    return {"batches": list(EXISTING_BATCHES), "features": out}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    pool = json.loads(mixer.POOL_PATH.read_text(encoding="utf-8"))
    scripts, results = script_features(pool), result_features(sealed.SealedTable())
    with_decoys = [v for v in scripts.values() if v["decoys"]]
    gating_results = [v for v in results["features"].values() if v["gating"]]
    passes = all(v["passes"] for v in with_decoys) and all(v["contains_half"] for v in gating_results)
    result = {"rule": "base-level 90% AUC interval contains 0.5, for every script feature of every decoy plan and for "
                      "effect spread on existing pool-1 runs",
              "passes": passes, "script_features": scripts, "result_features": results,
              "generated_at": datetime.now(timezone.utc).isoformat()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for plan, v in scripts.items():
        cells = ", ".join(f"{f} {r['auc']:.3f} [{r['interval_90_base'][0]:.3f}, {r['interval_90_base'][1]:.3f}]"
                          for f, r in v["features"].items() if r["auc"] is not None)
        print(f"{plan}: {'PASS' if v['passes'] else 'FAIL'}: {cells}")
    for f, r in results["features"].items():
        print(f"existing pool-1 runs, {f}{'' if r['gating'] else ' (diagnostic)'}: {r['auc']:.3f} "
              f"[{r['interval_90_base'][0]:.3f}, {r['interval_90_base'][1]:.3f}] ({r['buggy']} buggy, {r['clean']} clean)")
    print(f"Overall: {'PASS' if passes else 'FAIL'}. Wrote {OUT}")
    return 0 if passes else 1


if __name__ == "__main__":
    raise SystemExit(main())
