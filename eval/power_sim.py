"""Simulated power of confirm-llama-2 for H2 and H3, with the plan's own base-level resampling.

Run with `python -m eval.power_sim` (a few minutes, no LLM). Planning numbers, deciding nothing.

Why a simulation and not eval/confirm_power.py's normal approximation: that one widens a run-level standard error by
a fixed design effect and treats the strongest trivial feature as fixed at 0.521. Both hide what matters here:
- **Bases cap the information.** A pool has 18 bases; more runs on the same 18 bases mostly repeat the same
  experiments. Resampling whole bases, as the plan does, shows how little extra runs then buy.
- **H3 picks the strongest of several features in every draw**, and a maximum of noisy AUCs sits above 0.5 even
  when each feature's true AUC is 0.5.

Model of one simulated batch (all assumptions, written in the result file):
- Layout: the real mixer plans the batch (`mixer.plan_batch`, seed 1109) on pool 1 (pool 2 is built on the same
  grid and does not exist yet). "More bases" copies pool 1 under new indices, i.e. an equally varied larger pool.
- Size features (statement count, helper statements, helper characters) are the real dry-plan values of that layout,
  so their ties and decoys are as in the batch. Line and character count are padded constant (AUC exactly 0.5).
- llama's score and effect spread are latent normals: value = base effect + shift if buggy + noise, with the share of
  variance between bases (ICC) estimated from task-dev-1 and task-dev-2 on normal scores. The shift gives the true
  AUC between runs on independent bases: d = sqrt(2) * Phi^-1(AUC). Effect spread's true AUC is 0.521 (pool-1 runs,
  dry_proof.json). Score and features are drawn independently of each other.
- Each batch is analysed as the plan says: 90% percentile interval over base-level draws; H2 passes if AUC's lower
  bound is above 0.5, H3 if the lower bound of AUC minus the strongest direction-free feature AUC (picked again in
  each draw) is above 0. All simulated batches of one cell share the same base-draw indices (common random numbers),
  which leaves each batch's interval correct and makes the grid cheaper.
Laptop time comes from task-dev-2's measured rates in data/runs/campaign.log and pool 1's build rate.
Writes eval/results/confirm_llama_2/power_sim.json.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy import stats

from canary import ledger, mixer, sandbox, sealed, trust
from eval import compare_tasks, cutoff, dev_compare

AUC_GRID = (0.60, 0.64, 0.70)
RUNS_GRID = (100, 150, 200, 300, 400)
POOL_COPIES = (1, 2, 3)  # 18, 36, 54 bases
SIMS, DRAWS, SEED, PLAN_SEED = 300, 1000, 0, 1109
TARGET = 0.80
SENSITIVITY_SCORE_ICC = 0.20  # 18-base pool only
SIZE_FEATURES = ("statement_count", "helper_statements", "helper_chars")
EFFECT_SPREAD_AUC_KEY = "effect_spread"
PROOF_PATH = compare_tasks.RESULTS_DIR / "padding_v2" / "dry_proof.json"
LOG_PATH = sandbox.RUNS_DIR / "campaign.log"
OUT_PATH = compare_tasks.RESULTS_DIR / "confirm_llama_2" / "power_sim.json"
LOW, HIGH = trust.INTERVAL_PERCENTILES


# ---------- inputs estimated from data ----------

def normal_scores(values: list[float]) -> np.ndarray:
    """Rank-based inverse normal: the latent scale an AUC model lives on (AUC only sees ranks)."""
    ranks = stats.rankdata(values)
    return stats.norm.ppf((ranks - 0.5) / len(values))


def icc(groups: list[list[float]]) -> float:
    """One-way random-effects ICC (ANOVA estimator, unequal group sizes), clipped at 0."""
    groups = [g for g in groups if g]
    k, n = len(groups), sum(len(g) for g in groups)
    if k < 2 or n <= k:
        return 0.0
    grand = np.mean([x for g in groups for x in g])
    msb = sum(len(g) * (np.mean(g) - grand) ** 2 for g in groups) / (k - 1)
    msw = sum(((np.asarray(g) - np.mean(g)) ** 2).sum() for g in groups) / (n - k)
    n0 = (n - sum(len(g) ** 2 for g in groups) / n) / (k - 1)
    return float(max(0.0, (msb - msw) / (msb + (n0 - 1) * msw)))


def residual_icc(per_batch: list[list[tuple[str, bool, float]]]) -> float:
    """ICC by base of normal scores, after removing each batch's buggy/clean means (the type effect)."""
    by_base: dict[str, list[float]] = {}
    for rows in per_batch:
        z = normal_scores([v for _, _, v in rows])
        for flag in (True, False):
            idx = [i for i, (_, b, _) in enumerate(rows) if b == flag]
            if not idx:
                continue
            mean = z[idx].mean()
            for i in idx:
                by_base.setdefault(rows[i][0], []).append(float(z[i] - mean))
    return icc(list(by_base.values()))


def estimate_iccs(table: sealed.SealedTable, led: ledger.Ledger) -> dict:
    score_rows, spread_rows = [], []
    for batch in (dev_compare.BEFORE, dev_compare.AFTER):
        rows = dev_compare.batch_rows(table, led, batch)
        score_rows.append([(r["base"], r["buggy"], r["score"]) for r in rows])
        feats = {r["run_id"]: compare_tasks.run_features(r["run_id"]) for r in rows}
        spread_rows.append([(r["base"], r["buggy"], feats[r["run_id"]][EFFECT_SPREAD_AUC_KEY])
                            for r in rows if feats[r["run_id"]]])
    return {"score": residual_icc(score_rows), "effect_spread": residual_icc(spread_rows),
            "source": f"{dev_compare.BEFORE} and {dev_compare.AFTER}, residuals after type means, bases pooled"}


def measured_times(log_path: Path = LOG_PATH, batch: str = dev_compare.AFTER) -> dict:
    """Seconds per run (incl. canary twins) and per audit for `batch`, and seconds per pool base, from the log."""
    lines = log_path.read_text(encoding="utf-8").splitlines()
    stamp = lambda line: datetime.fromisoformat(line.split(" ", 1)[0])  # noqa: E731
    mine = [l for l in lines if f"batch {batch}:" in l]
    start = next(l for l in mine if "slots," in l)
    gate = next(l for l in mine if "length gate passed" in l)
    audits = [l for l in mine if re.search(r"audit \d+/\d+ .*s so far\]", l)]
    total_runs = int(re.search(r"(\d+) slots", start).group(1))
    audit_seconds = int(re.search(r"\[(\d+) s so far\]", audits[-1]).group(1))
    pool = [l for l in lines if re.search(r"^\S+ pool \d+/\d+ kept", l)]
    per_base = (stamp(pool[-1]) - stamp(pool[0])).total_seconds() / max(1, len(pool) - 1)
    return {"batch": batch, "runs": total_runs,
            "run_seconds_per_run": (stamp(gate) - stamp(start)).total_seconds() / total_runs,
            "audit_seconds_per_run": audit_seconds / len(audits),
            "pool_seconds_per_base": per_base, "pool_1_bases_logged": len(pool)}


def laptop_minutes(runs: int, bases: int, t: dict) -> float:
    """Build the pool, run the batch, audit it (the optional rescore would add about the audit time again)."""
    return (bases * t["pool_seconds_per_base"] + runs * (t["run_seconds_per_run"] + t["audit_seconds_per_run"])) / 60


# ---------- layout and simulation ----------

def layout(runs: int, copies: int, pool: dict, seed: int = PLAN_SEED) -> dict:
    """The real mixer's plan on `copies` copies of the pool: base index, buggy flag and size features per run."""
    bigger = {**pool, "bases": [copy.deepcopy(b) for _ in range(copies) for b in pool["bases"]]}
    rows = mixer.dry_rows(mixer.plan_batch("power-sim", runs, bigger, seed))
    labels = sorted({r["base"] for r in rows})
    return {"base": np.array([labels.index(r["base"]) for r in rows]), "buggy": np.array([r["buggy"] for r in rows]),
            "features": {f: np.array([float(r[f]) for r in rows]) for f in SIZE_FEATURES},
            "bases": len(labels), "pool_bases": len(bigger["bases"])}


def pair_matrix(values: np.ndarray, buggy: np.ndarray) -> np.ndarray:
    b, c = values[buggy][:, None], values[~buggy][None, :]
    return (b > c) + 0.5 * (b == c)


def draw_aucs(matrix: np.ndarray, w_bug: np.ndarray, w_clean: np.ndarray) -> np.ndarray:
    """AUC in every base-level draw, from per-run weights (how often the run's base was drawn)."""
    return np.einsum("db,bc,dc->d", w_bug, matrix, w_clean) / (w_bug.sum(1) * w_clean.sum(1))


def latent(rng, base: np.ndarray, buggy: np.ndarray, bases: int, auc: float, icc_: float) -> np.ndarray:
    shift = math.sqrt(2) * stats.norm.ppf(auc)
    u = rng.normal(0, math.sqrt(icc_), bases)
    return u[base] + shift * buggy + rng.normal(0, math.sqrt(1 - icc_), len(base))


def simulate_cell(lay: dict, auc: float, spread_auc: float, iccs: dict, sims: int = SIMS, draws: int = DRAWS,
                  seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    base, buggy, k = lay["base"], lay["buggy"], lay["bases"]
    counts = np.stack([np.bincount(rng.integers(0, k, k), minlength=k) for _ in range(draws)])
    weights = counts[:, base].astype(float)
    w_bug, w_clean = weights[:, buggy], weights[:, ~buggy]
    keep = (w_bug.sum(1) > 0) & (w_clean.sum(1) > 0)
    w_bug, w_clean = w_bug[keep], w_clean[keep]
    size_free = np.max([np.maximum(a, 1 - a) for a in
                        (draw_aucs(pair_matrix(v, buggy), w_bug, w_clean) for v in lay["features"].values())], axis=0)
    h2 = h3 = both = 0
    for _ in range(sims):
        score = draw_aucs(pair_matrix(latent(rng, base, buggy, k, auc, iccs["score"]), buggy), w_bug, w_clean)
        spread = draw_aucs(pair_matrix(latent(rng, base, buggy, k, spread_auc, iccs["effect_spread"]), buggy),
                           w_bug, w_clean)
        strongest = np.maximum(size_free, np.maximum(spread, 1 - spread))
        p2 = np.percentile(score, LOW) > 0.5
        p3 = np.percentile(score - strongest, LOW) > 0
        h2, h3, both = h2 + p2, h3 + p3, both + (p2 and p3)
    return {"H2": h2 / sims, "H3": h3 / sims, "H2_and_H3": both / sims, "sims": sims, "draws": int(keep.sum())}


def runs_needed(cells: dict, key: str) -> int | None:
    """Smallest run count in the grid whose power reaches TARGET (None: not within the grid)."""
    hits = [int(r) for r, c in cells.items() if c[key] >= TARGET]
    return min(hits) if hits else None


def build(sims: int = SIMS, draws: int = DRAWS) -> dict:
    table, led = sealed.SealedTable(), ledger.Ledger()
    iccs = estimate_iccs(table, led)
    spread_auc = json.loads(PROOF_PATH.read_text(encoding="utf-8"))["result_features"]["features"]["effect_spread"]["auc"]
    times = measured_times()
    pool = json.loads(mixer.POOL_PATH.read_text(encoding="utf-8"))
    grid: dict = {}
    for copies in POOL_COPIES:
        for runs in RUNS_GRID:
            lay = layout(runs, copies, pool)
            for auc in AUC_GRID:
                cell = simulate_cell(lay, auc, spread_auc, iccs, sims, draws)
                cell.update(bases_used=lay["bases"], laptop_minutes=laptop_minutes(runs, lay["pool_bases"], times))
                grid.setdefault(str(lay["pool_bases"]), {}).setdefault(f"{auc:.2f}", {})[str(runs)] = cell
                print(f"pool {lay['pool_bases']:3d} bases, {runs:3d} runs, AUC {auc:.2f}: H2 {cell['H2']:.2f}  "
                      f"H3 {cell['H3']:.2f}  both {cell['H2_and_H3']:.2f}", flush=True)
    # The score's ICC comes from 80 runs and may be too low; check what a clearly clustered score would cost.
    sensitivity = {}
    for runs in RUNS_GRID:
        lay = layout(runs, POOL_COPIES[0], pool)
        for auc in AUC_GRID:
            cell = simulate_cell(lay, auc, spread_auc, {**iccs, "score": SENSITIVITY_SCORE_ICC}, sims, draws)
            sensitivity.setdefault(f"{auc:.2f}", {})[str(runs)] = cell
    summary = {pool_size: {auc: {k: {"runs": runs_needed(cells, k),
                                     "laptop_minutes": (cells[str(runs_needed(cells, k))]["laptop_minutes"]
                                                        if runs_needed(cells, k) else None)}
                                 for k in ("H2", "H3", "H2_and_H3")}
                           for auc, cells in by_auc.items()} for pool_size, by_auc in grid.items()}
    return {"target_power": TARGET, "auc_grid": AUC_GRID, "runs_grid": RUNS_GRID, "sims": sims, "draws": draws,
            "plan_seed": PLAN_SEED, "icc": iccs, "effect_spread_true_auc": spread_auc, "times": times,
            "assumptions": __doc__.split("Model of one simulated batch")[1].split("Writes")[0].strip(),
            "grid": grid, "runs_needed": summary,
            "sensitivity_score_icc": {"icc": SENSITIVITY_SCORE_ICC, "pool_bases": len(pool["bases"]), "grid": sensitivity}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sims", type=int, default=SIMS)
    parser.add_argument("--draws", type=int, default=DRAWS)
    args = parser.parse_args(argv)
    result = build(args.sims, args.draws)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"ICC score {result['icc']['score']:.3f}, effect spread {result['icc']['effect_spread']:.3f}")
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
