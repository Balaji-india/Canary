"""task-dev-1 vs task-dev-2: how much of llama-checklist's AUC went away with the length cue, and what decoys did.

Run with `python -m eval.dev_compare`. Development numbers only: it decides nothing and changes no plan.

The two batches differ in three ways at once, so no single number is "the length share":
1. **The length cue:** task-dev-1 canaries were longer than clean runs (blinded line count alone: AUC 0.85);
   task-dev-2 is padded, so every size feature sits at 0.5.
2. **Decoys:** task-dev-2's clean runs carry harmless bug-shaped code (hard controls); task-dev-1's were plain.
3. **Different runs:** other variants on other bases, so part of any difference is luck.
Both batches use pool-1 bases, so the intervals here resample **bases jointly across the two batches** (a base drawn
brings its runs from both), the honest choice when the same experiments appear on both sides.

To separate (1) from (2) as far as the data allows, the AUC change is split by side: did canaries score lower once
the cue was gone (consistent with length), or did clean runs score higher once they carried decoys (decoys)?
Writes eval/results/task_dev_2/dev_compare.json.
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone

import numpy as np

from canary import ledger, sealed, separation, trust
from eval import compare_tasks, cutoff, dev_report

BEFORE, AFTER = "task-dev-1", "task-dev-2"
OUT_PATH = compare_tasks.RESULTS_DIR / "task_dev_2" / "dev_compare.json"


def batch_rows(table: sealed.SealedTable, led: ledger.Ledger, batch: str) -> list[dict]:
    """One row per scored run: base, buggy, P(flag), and for clean runs whether its decoy has code."""
    scores = cutoff.role_scores(table, led, batch, cutoff.ROLE)
    decoy_code = {r["run_id"]: r["decoy_has_code"] for r in dev_report.clean_rows(table, led, batch)}
    has_decoy = {r["run_id"]: bool(r["decoy"]) for r in dev_report.clean_rows(table, led, batch)}
    return [{"run_id": r, "base": table.get(r).source or r, "buggy": buggy, "score": s,
             "decoy": has_decoy.get(r, False), "decoy_has_code": decoy_code.get(r, False)}
            for r, (buggy, s) in sorted(scores.items()) if s is not None]


def _mean(rows: list[dict]) -> float | None:
    return statistics.mean(r["score"] for r in rows) if rows else None


def _auc(rows: list[dict]) -> float | None:
    return separation.auc([r["score"] for r in rows if r["buggy"]], [r["score"] for r in rows if not r["buggy"]])


def statistics_of(before: list[dict], after: list[dict]) -> dict[str, float | None]:
    """Every compared quantity, on one draw (or on the observed data)."""
    def diff(a, b):
        return None if a is None or b is None else a - b
    bug_b, bug_a = [r for r in before if r["buggy"]], [r for r in after if r["buggy"]]
    clean_b, clean_a = [r for r in before if not r["buggy"]], [r for r in after if not r["buggy"]]
    with_code = [r for r in clean_a if r["decoy_has_code"]]
    no_code = [r for r in clean_a if r["decoy"] and not r["decoy_has_code"]]
    auc_b, auc_a = _auc(before), _auc(after)
    return {
        "auc_before": auc_b, "auc_after": auc_a, "auc_change": diff(auc_a, auc_b),
        "mean_buggy_before": _mean(bug_b), "mean_buggy_after": _mean(bug_a),
        "buggy_change": diff(_mean(bug_a), _mean(bug_b)),
        "mean_clean_before": _mean(clean_b), "mean_clean_after": _mean(clean_a),
        "clean_change": diff(_mean(clean_a), _mean(clean_b)),
        "decoy_with_code_minus_plain": diff(_mean(with_code), _mean(clean_b)),
        "decoy_no_code_minus_plain": diff(_mean(no_code), _mean(clean_b)),
        "decoy_with_minus_without_code": diff(_mean(with_code), _mean(no_code)),
        "gap_before": diff(_mean(bug_b), _mean(clean_b)), "gap_after": diff(_mean(bug_a), _mean(clean_a)),
    }


def joint_base_bootstrap(before: list[dict], after: list[dict], seed: int = 0,
                         draws: int | None = None) -> dict[str, list[float] | None]:
    """90% intervals, resampling bases jointly: a drawn base brings its runs from both batches."""
    rng, draws = np.random.default_rng(seed), draws or separation.BOOTSTRAP_DRAWS
    bases = sorted({r["base"] for r in before} | {r["base"] for r in after})
    by_b = {b: [r for r in before if r["base"] == b] for b in bases}
    by_a = {b: [r for r in after if r["base"] == b] for b in bases}
    collected: dict[str, list[float]] = {}
    for _ in range(draws):
        picked = [bases[i] for i in rng.integers(0, len(bases), len(bases))]
        stats_ = statistics_of([r for b in picked for r in by_b[b]], [r for b in picked for r in by_a[b]])
        for k, v in stats_.items():
            if v is not None:
                collected.setdefault(k, []).append(v)
    return {k: [float(x) for x in np.percentile(v, trust.INTERVAL_PERCENTILES)] for k, v in collected.items()}


def build(table: sealed.SealedTable, led: ledger.Ledger) -> dict:
    before, after = batch_rows(table, led, BEFORE), batch_rows(table, led, AFTER)
    observed, intervals = statistics_of(before, after), joint_base_bootstrap(before, after)
    reference = json.loads((compare_tasks.RESULTS_DIR / "task_dev_1" / "compare_tasks.json").read_text(encoding="utf-8"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "role": cutoff.ROLE, "batches": [BEFORE, AFTER],
        "note": "development numbers; both batches are on pool-1 bases, intervals resample bases jointly",
        "runs": {BEFORE: len(before), AFTER: len(after)},
        "bases": {BEFORE: len({r["base"] for r in before}), AFTER: len({r["base"] for r in after}),
                  "shared": len({r["base"] for r in before} & {r["base"] for r in after})},
        "observed": observed, "interval_90_joint_base": intervals,
        "share_of_above_chance_lost": (None if observed["auc_before"] in (None, 0.5) else
                                       (observed["auc_before"] - observed["auc_after"]) / (observed["auc_before"] - 0.5)),
        "task_dev_1_line_count_auc": reference["feature_baselines"]["line_count"],
        "task_dev_1_score_vs_line_count_rho": reference["cells"][cutoff.ROLE]["score_vs_line_count_rho"],
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    result = build(sealed.SealedTable(), ledger.Ledger())
    o, iv = result["observed"], result["interval_90_joint_base"]
    for key in ("auc_before", "auc_after", "auc_change", "buggy_change", "clean_change", "decoy_with_code_minus_plain",
                "decoy_no_code_minus_plain", "decoy_with_minus_without_code"):
        lo, hi = iv.get(key, [float("nan")] * 2)
        print(f"{key:32s} {o[key]:+.3f}  joint-base 90% [{lo:+.3f}, {hi:+.3f}]")
    print(f"share of above-chance AUC lost: {result['share_of_above_chance_lost']:.2f}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
