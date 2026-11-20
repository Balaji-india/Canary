"""The decisive-share check (build-order row 5; docs/plans/roadmap_challenge_2026-11-15.md, section 8, as approved).

Why: a gate that has nothing decisive to accept shows nothing. Before pool 3 is built, the student fixes
`seeds_per_arm` and the campaign grid; this check measures, on clean runs already made, how often the code's verdict
is decisive (`supported` or `not_supported`) and how many inconclusive verdicts 10 seeds could decide.

Data: every control and sham with a finished (`ok`) run in the batches below, selected through `canary.trust`. The
verdict is the one stored in the run's `ran` ledger entry, recomputed with `prereg.compute_verdict` on its
`results.json`; any mismatch stops the check before D or G10 is computed. No audit and no reviewer output is read.
The runs are clones of the 35 bases of pools 1 and 2, so the base (the experiment without its seeds) is the unit
that decides; the run-level figures are printed beside it.

Run: python -m eval.decisive_share   (read-only; writes eval/results/decisive_share.json)
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

from canary import ledger, prereg, sandbox, sealed, trust

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "eval" / "results" / "decisive_share.json"
BATCHES = ("rq1-full", "task-dev-1", "task-dev-2", "ceiling-ext", "tripwire-test-1")
TARGET_SEEDS = 10
G10_BAR, D_BAR = 0.10, 0.20  # the rule's fixed values (section 8)
BOOTSTRAP, SEED, LEVEL = 5000, 2026, 90


class VerdictMismatch(RuntimeError):
    """A stored verdict differs from the one the verdict code gives on the same results: stop (section 8)."""


def seed_factor(n_seeds: int, ratio: float, target: int = TARGET_SEEDS) -> float:
    """How much the verdict's interval half-width would shrink at `target` seeds, the spread between seeds unchanged:
    [t(0.975, target - 1) sqrt(1/target + r)] / [t(0.975, n - 1) sqrt(1/n + r)], r = the run's n_test / n_train
    (the same ratio `prereg.compute_verdict` uses). At n 5 and r 1/3 it is 0.734."""
    return (stats.t.ppf(0.975, target - 1) * math.sqrt(1 / target + ratio)) / (
        stats.t.ppf(0.975, n_seeds - 1) * math.sqrt(1 / n_seeds + ratio))


def split_ratio(results: dict) -> float:
    train, test = results["split_sizes"]["train"], results["split_sizes"]["test"]
    return (sum(test) / len(test)) / (sum(train) / len(train))


def decisive(outcome: str) -> bool:
    return outcome in (prereg.SUPPORTED, prereg.NOT_SUPPORTED)


def projected_decisive(verdict: dict, factor: float) -> bool:
    """Would this verdict's interval, narrowed by `factor` around the same mean, be decisive? (A projection.)"""
    mean, low, high = verdict["mean_effect"], verdict["ci_low"], verdict["ci_high"]
    if low is None or high is None:
        return False
    half = factor * (high - low) / 2
    return bool((mean >= verdict["min_effect"] and mean - half > 0) or (mean + half < verdict["min_effect"]))


def base_key(locked: dict) -> str:
    """The experiment without its seeds: clones of one base share it."""
    config = prereg.to_run_config(locked)
    del config["seeds"]
    return prereg.canonical_json(config)


def collect(table: sealed.SealedTable, led: ledger.Ledger, runs_dir: Path, batches=BATCHES) -> tuple[list, dict]:
    """One row per clean run with an `ok` run: batch, base, verdict (checked), its projection at 10 seeds.

    Raises VerdictMismatch if a recomputed verdict differs from the stored one. Also returns what was left out."""
    ran = {e.payload["run_id"]: e for e in led.entries(ledger.RAN) if "run_id" in e.payload}
    locks = {e.hypothesis_id: e.payload["prereg"] for e in led.entries(ledger.PREREGISTERED) if "prereg" in e.payload}
    rows, left_out, mismatches = [], defaultdict(int), []
    for run_id, run_type, batch in trust.clean_runs(table, list(batches)):
        entry = ran.get(run_id)
        if entry is None:
            left_out["no_ran_entry"] += 1
            continue
        if entry.payload.get("run_status") != sandbox.STATUS_OK:
            left_out["run_not_ok"] += 1
            continue
        locked = locks[entry.hypothesis_id]
        results = json.loads((runs_dir / run_id / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))
        stored = entry.payload["verdict"]
        recomputed = prereg.compute_verdict(locked, results)
        if recomputed != stored:
            mismatches.append({"run_id": run_id, "batch": batch, "stored": stored, "recomputed": recomputed})
            continue
        ratio = split_ratio(results)
        factor = float(seed_factor(stored["n_seeds"], ratio))
        rows.append({"run_id": run_id, "run_type": run_type, "batch": batch, "base": base_key(locked),
                     "dataset": locked["dataset"], "metric": locked["metric"],
                     "model": locked["control_config"]["model"], "outcome": stored["outcome"],
                     "n_seeds": stored["n_seeds"], "ratio": ratio, "f10": factor,
                     "decisive": decisive(stored["outcome"]), "supported": stored["outcome"] == prereg.SUPPORTED,
                     "g10": not decisive(stored["outcome"]) and projected_decisive(stored, factor)})
    if mismatches:
        raise VerdictMismatch(f"{len(mismatches)} recomputed verdicts differ from the ledger: {mismatches[:3]}")
    return rows, dict(left_out)


def run_level(flags: list[bool]) -> dict:
    d, n = sum(flags), len(flags)
    low, high = stats.beta.ppf([(100 - LEVEL) / 200, 1 - (100 - LEVEL) / 200], 1 + d, 1 + n - d)
    return {"count": d, "n": n, "share": d / n if n else None, "interval_beta": [float(low), float(high)]}


def base_level(rows: list[dict], field: str, seed: int = SEED) -> dict:
    """Mean over bases of each base's share, with a 90% bootstrap over bases (bases resampled with replacement)."""
    by_base: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        by_base[row["base"]].append(row[field])
    shares = np.array([np.mean(v) for _, v in sorted(by_base.items())])
    rng = np.random.default_rng(seed)
    draws = rng.choice(shares, size=(BOOTSTRAP, len(shares)), replace=True).mean(axis=1)
    low, high = np.percentile(draws, [(100 - LEVEL) / 2, 100 - (100 - LEVEL) / 2])
    return {"bases": len(shares), "share": float(shares.mean()), "interval_bootstrap": [float(low), float(high)]}


def figures(rows: list[dict]) -> dict:
    return {"runs": len(rows), "bases": len({r["base"] for r in rows}),
            "D": {"base_level": base_level(rows, "decisive"), "run_level": run_level([r["decisive"] for r in rows])},
            "G10": {"base_level": base_level(rows, "g10"), "run_level": run_level([r["g10"] for r in rows])},
            # Descriptive, decides nothing: D counts `not_supported` as decisive too, but only `supported` verdicts
            # are findings a gate could accept.
            "supported_only": {"base_level": base_level(rows, "supported"),
                               "run_level": run_level([r["supported"] for r in rows])}}


def recommend(fig: dict, level: str) -> dict:
    """Section 8's rule on one level's figures."""
    g10 = fig["G10"][level]["share"]
    d = fig["D"][level]
    low, high = d["interval_bootstrap"] if level == "base_level" else d["interval_beta"]
    seeds = 10 if g10 >= G10_BAR else 5
    if low >= D_BAR:
        grid = "keep question q1 and the focus grid"
    elif high < D_BAR:
        grid = ("decisive verdicts are rare on this grid: amend mission_4_2_hidden_truth.md section 2a before pool 3, "
                "from the cells where decisive verdicts occurred, with a local pilot for cells the bases do not cover")
    else:
        grid = "the interval straddles 0.20: keep q1 and the grid, and report the per-cell table"
    return {"seeds_per_arm": seeds, "grid": grid, "g10": g10, "d_interval": [low, high]}


def by_cell(rows: list[dict], key: str) -> dict:
    found: dict[str, dict] = {}
    for row in rows:
        cell = found.setdefault(row[key], {"runs": 0, "decisive": 0, "g10": 0, "bases": set()})
        cell["runs"] += 1
        cell["decisive"] += row["decisive"]
        cell["g10"] += row["g10"]
        cell["bases"].add(row["base"])
    return {k: {**v, "bases": len(v["bases"])} for k, v in sorted(found.items())}


def analyse(rows: list[dict], left_out: dict) -> dict:
    pooled = figures(rows)
    per_batch = {b: figures([r for r in rows if r["batch"] == b]) for b in BATCHES if any(r["batch"] == b for r in rows)}
    base_rec, run_rec = recommend(pooled, "base_level"), recommend(pooled, "run_level")
    outcomes = defaultdict(int)
    for row in rows:
        outcomes[row["outcome"]] += 1
    return {
        "rule": "docs/plans/roadmap_challenge_2026-11-15.md section 8 (approved 2026-11-20); base level decides",
        "batches": list(BATCHES), "left_out": left_out, "outcomes": dict(outcomes),
        "n_seeds": sorted({r["n_seeds"] for r in rows}),
        "f10_range": [min(r["f10"] for r in rows), max(r["f10"] for r in rows)],
        "ratio_range": [min(r["ratio"] for r in rows), max(r["ratio"] for r in rows)],
        "pooled": pooled, "per_batch": per_batch,
        "recommendation": {"base_level (decides)": base_rec, "run_level (beside it)": run_rec,
                           "levels_agree": (base_rec["seeds_per_arm"], base_rec["grid"]) ==
                                           (run_rec["seeds_per_arm"], run_rec["grid"])},
        "by_dataset": by_cell(rows, "dataset"), "by_metric": by_cell(rows, "metric"), "by_model": by_cell(rows, "model"),
        "claim": "clean clones of the 35 pool-1 and pool-2 bases only; G10 is a projection, not a verdict",
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m eval.decisive_share", description=__doc__.split("\n")[0]).parse_args(argv)
    rows, left_out = collect(sealed.SealedTable(), ledger.Ledger(), sandbox.RUNS_DIR)
    result = analyse(rows, left_out)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("left_out", "outcomes", "n_seeds", "f10_range", "ratio_range",
                                             "pooled", "per_batch", "recommendation")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
