"""How big must the ceiling check's batch be? The outcome table of eval/ceiling.py's rule, simulated (no LLM).

Run with `python -m eval.ceiling_power` (a few minutes). Writes eval/results/ceiling/power_ceiling.json. Planning
numbers for the lock (docs/plans/cloud_ceiling_check_outline.md section 7), deciding nothing about any reviewer.
It extends eval/power_sim.py (same latent model of trivial features, same measured laptop rates) to verdict scores
and calls eval/ceiling.py's own functions for the bootstrap and the tests, so it simulates exactly the frozen rule.

Model of one simulated batch (all assumptions, written into the result file):
- Layout: task-dev-2 as planned (pool 1, seed 1110, 40 runs) plus, for larger sizes, an extension of fresh runs
  planned by the same mixer on a stand-in for pool 2 (pool 1's bases copied under new labels, i.e. an equally varied
  new pool; the real pool 2 does not exist yet). Bases of the two pools are separate clusters.
- Verdicts: recall (1 + J) / 2 and false-alarm rate (1 - J) / 2, the split with the widest intervals for a given J.
  Verdicts cluster by base through a latent normal with intra-base correlation `verdict ICC` (0, 0.2, 0.5; llama's
  score had 0.012, a cloud model's is unknown). No failed audits.
- Trivial features: line and character count are padded constant; statement count and helper characters are the
  dry plan's real values; effect spread, effect size and best arm's score are latent normals with the true AUCs of
  dry_proof.json and base ICCs estimated from task-dev-1 and task-dev-2. Features are independent of the verdicts.
- Analysis exactly as eval/ceiling.py: base-level percentile bootstrap at 97.5%, T1/T2/T3, `ceiling.cell_tests`.
  Simulation shortcuts: 2,000 bootstrap draws instead of 10,000; all simulated batches of one size share the same
  base-draw indices and a bank of feature realisations (common random numbers), which leaves each batch's interval
  correct and makes the grid cheaper. T3 is computed only where T1 and T2 pass (it cannot matter otherwise).
- Study-level outcomes treat the 4 cells as independent with the same true J (the arms are different models; their
  prompts share runs, so this is an approximation). Cells that agree more than chance make the study's P(SOLVABLE)
  here an upper bound and its P(HARD) a lower bound. The false-positive check uses the Bonferroni bound 4 x p, which
  holds under any dependence.
Batch-size criterion (Claude's proposal, approved by the student 2026-11-11): the smallest size at which one cell is
SOLVABLE with probability at least 0.80 at a true J of 0.70 (AUC 0.85), while the rule's false-positive rate over
4 cells is at most 0.05 at a true J of exactly 0.40 (AUC 0.70). It is applied at verdict ICC 0.2, fixed before this
simulation ran (0.2 is power_sim's sensitivity value; 0 and 0.5 are reported beside it). If no size up to 200 meets
it, 200 is used and the power reached is stated; if the false-positive part fails at every size, the interval level
changes before the lock, never the bars after it.
"""
from __future__ import annotations

import argparse
import copy
import json
import math

import numpy as np
from scipy import stats

from canary import config, ledger, mixer, sealed
from eval import ceiling, compare_tasks, power_sim

SIZES = (40, 80, 120, 160, 200)
J_GRID = (0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
VERDICT_ICCS = (0.0, 0.2, 0.5)
PRIMARY_ICC = 0.2
POWER_J, FP_J, POWER_TARGET, FP_TARGET, CELLS = 0.70, 0.40, 0.80, 0.05, 4
SIMS, FP_SIMS, DRAWS, FEATURE_BANK, SEED = 1000, 4000, 2000, 250, 0
DEV_BATCH, DEV_SEED, DEV_RUNS, EXT_SEED = "task-dev-2", 1110, 40, 1111
REPEAT_PER_CELL, SMOKE_CALLS, PROMPTS_PER_ARM = 20, 4, 2
LAYOUT_FEATURES = ("line_count", "char_count", "statement_count", "helper_chars")
LATENT_FEATURES = ("effect_spread", "effect_size", "top_score")
OUT_PATH = ceiling.OUT_DIR / "power_ceiling.json"


# ---------- inputs ----------

def layout(size: int, pool: dict) -> dict:
    """task-dev-2's plan plus an extension of `size - 40` runs on a pool-2 stand-in: base, buggy, layout features."""
    rows = mixer.dry_rows(mixer.plan_batch(DEV_BATCH, DEV_RUNS, pool, DEV_SEED))
    if size > DEV_RUNS:
        stand_in = {**pool, "bases": copy.deepcopy(pool["bases"])}
        extra = mixer.dry_rows(mixer.plan_batch("ceiling-ext", size - DEV_RUNS, stand_in, EXT_SEED))
        rows += [{**r, "base": f"pool2-stand-in:{r['base']}"} for r in extra]
    labels = sorted({r["base"] for r in rows})
    return {"base": np.array([labels.index(r["base"]) for r in rows]), "buggy": np.array([bool(r["buggy"]) for r in rows]),
            "features": {f: np.array([float(r[f]) for r in rows]) for f in LAYOUT_FEATURES},
            "bases": len(labels), "runs": len(rows), "buggy_runs": int(sum(r["buggy"] for r in rows))}


def feature_inputs(table: sealed.SealedTable, led: ledger.Ledger) -> dict:
    """True AUCs (dry_proof.json, pool-1 runs) and base ICCs (task-dev-1 and -2 runs) of the latent features."""
    proof = json.loads(power_sim.PROOF_PATH.read_text(encoding="utf-8"))["result_features"]["features"]
    per_batch: dict[str, list] = {f: [] for f in LATENT_FEATURES}
    for batch in ("task-dev-1", "task-dev-2"):
        rows: dict[str, list] = {f: [] for f in LATENT_FEATURES}
        for truth in table.all():
            if truth.details.get("batch") != batch or truth.run_type not in (sealed.CANARY_MEASURE, *ceiling.CLEAN_TYPES):
                continue
            features = compare_tasks.run_features(truth.run_id)
            if features:
                for f in LATENT_FEATURES:
                    rows[f].append((truth.source or truth.run_id, truth.run_type == sealed.CANARY_MEASURE, features[f]))
        for f in LATENT_FEATURES:
            per_batch[f].append(rows[f])
    return {f: {"auc": float(proof[f]["auc"]), "icc": power_sim.residual_icc(per_batch[f])} for f in LATENT_FEATURES}


# ---------- simulation ----------

def strongest_bank(lay: dict, w: np.ndarray, features: dict, bank: int, rng) -> np.ndarray:
    """bank x draws: the strongest direction-free trivial-feature AUC in every draw, for `bank` feature realisations."""
    buggy = lay["buggy"]
    fixed = np.max([np.maximum(a, 1 - a) for a in
                    (ceiling.weighted_aucs(v, buggy, w) for v in lay["features"].values())], axis=0)
    out = np.empty((bank, len(w)))
    for i in range(bank):
        latent = [ceiling.weighted_aucs(power_sim.latent(rng, lay["base"], buggy, lay["bases"], p["auc"], p["icc"]),
                                        buggy, w) for p in features.values()]
        out[i] = np.maximum(fixed, np.max([np.maximum(a, 1 - a) for a in latent], axis=0))
    return out


def simulate(lay: dict, j: float, verdict_icc: float, w: np.ndarray, bank: np.ndarray, sims: int, rng) -> dict:
    """Share of simulated batches in which one cell is SOLVABLE, below the bar, or "works but strength unknown"."""
    base, buggy, k = lay["base"], lay["buggy"], lay["bases"]
    cut_bug, cut_clean = stats.norm.ppf(1 - (1 + j) / 2), stats.norm.ppf(1 - (1 - j) / 2)
    solvable = below = works = 0
    for s in range(sims):
        z = rng.normal(0, math.sqrt(verdict_icc), k)[base] + rng.normal(0, math.sqrt(1 - verdict_icc), len(base))
        flagged = np.where(buggy, z > cut_bug, z > cut_clean).astype(float)
        j_draws = ceiling.weighted_j(flagged, buggy, w)
        j_low, j_high = np.percentile(j_draws, ceiling.PERCENTILES)
        auc_low, auc_high = (1 + j_low) / 2, (1 + j_high) / 2  # verdict AUC is (1 + J) / 2 in every draw
        gap_low = None
        if j_low > ceiling.J_BAR and auc_low > ceiling.AUC_BAR:
            gap_low = float(np.percentile((1 + j_draws) / 2 - bank[s % len(bank)], ceiling.PERCENTILES[0]))
        tests = ceiling.cell_tests(j_low, auc_low, auc_high, gap_low, 0.0)
        solvable += tests["passes"]
        below += tests["below_bar"]
        works += tests["T1"] and not tests["T2"]
    p, q = solvable / sims, below / sims
    return {"p_solvable_cell": p, "p_below_bar_cell": q, "p_works_strength_unknown_cell": works / sims, "sims": sims,
            "mc_se_solvable": math.sqrt(p * (1 - p) / sims),
            "study_independent_cells": {"SOLVABLE": 1 - (1 - p) ** CELLS, "HARD": q ** CELLS,
                                        "INCONCLUSIVE": max(0.0, (1 - p) ** CELLS - q ** CELLS)}}


def criterion(grid: dict) -> dict:
    """Apply the batch-size criterion at the primary verdict ICC."""
    rows = []
    for size in SIZES:
        cells = grid[f"{PRIMARY_ICC:.1f}"][str(size)]
        power = cells[f"{POWER_J:.2f}"]["p_solvable_cell"]
        fp_cell = cells[f"{FP_J:.2f}"]["p_solvable_cell"]
        fp = min(1.0, CELLS * fp_cell)
        rows.append({"runs": size, "power_at_j_0_70": power, "fp_bonferroni_4_cells_at_j_0_40": fp,
                     "meets_power": power >= POWER_TARGET, "meets_fp": fp <= FP_TARGET})
    meets = [r["runs"] for r in rows if r["meets_power"] and r["meets_fp"]]
    if meets:
        chosen, why = min(meets), "smallest size meeting both parts"
    elif rows[-1]["meets_fp"]:  # power short even at the largest size, but its false-positive rate is acceptable
        chosen, why = max(SIZES), "no size up to 200 reaches the power: 200, with the power reached stated in the lock"
    else:  # a size is never chosen with a false-positive rate above the limit
        chosen, why = None, ("false-positive part fails at every size that reaches the power (and at 200): change the "
                             "interval level before the lock, never the bars after it")
    return {"rows": rows, "chosen_runs": chosen, "why": why, "verdict_icc": PRIMARY_ICC, "level": ceiling.LEVEL}


def cost(size: int | None, models_cfg: dict, times: dict, pool_bases: int) -> dict | None:
    """Extension runs, laptop minutes and calendar days per arm at each provider's daily call budget."""
    if size is None:
        return None
    extension = max(0, size - DEV_RUNS)
    laptop_s = (pool_bases * times["pool_seconds_per_base"] + extension * times["run_seconds_per_run"]) if extension else 0
    calls = PROMPTS_PER_ARM * size + PROMPTS_PER_ARM * REPEAT_PER_CELL + SMOKE_CALLS
    arms = {}
    for arm, roles in ceiling.ARMS.items():
        entry = models_cfg["providers"][models_cfg["roles"][roles[0]]["provider"]]
        budget = entry["max_calls_per_day"]
        arms[arm] = {"provider": models_cfg["roles"][roles[0]]["provider"], "daily_call_budget": budget,
                     "calls": calls, "days": math.ceil(calls / budget),
                     "minutes_per_daily_session": round(budget * entry.get("min_interval_s", 0) / 60, 1)}
    return {"runs": size, "task_dev_2_runs": min(size, DEV_RUNS), "fresh_pool_2_runs": extension,
            "pool_2_build_bases": pool_bases if extension else 0, "laptop_minutes": round(laptop_s / 60, 1),
            "calls_per_arm": calls, "arms": arms,
            "note": "laptop: pool-2 build by the Scientist plus the extension runs, no local audits (the reviewer is "
                    "in the cloud); calls: 2 prompts x runs + the repeat pass (20 per cell) + the smoke test; "
                    "invalid-reply retries would add calls; budgets are placeholders until read in the consoles"}


def build(sims: int = SIMS, fp_sims: int = FP_SIMS, draws: int = DRAWS, bank_size: int = FEATURE_BANK,
          features: dict | None = None, pool: dict | None = None, sizes: tuple[int, ...] = SIZES,
          j_grid: tuple[float, ...] = J_GRID, iccs: tuple[float, ...] = VERDICT_ICCS) -> dict:
    pool = pool or json.loads(mixer.POOL_PATH.read_text(encoding="utf-8"))
    features = features or feature_inputs(sealed.SealedTable(), ledger.Ledger())
    rng = np.random.default_rng(SEED)
    grid: dict = {}
    layouts = {}
    for size in sizes:
        lay = layout(size, pool)
        layouts[str(size)] = {k: lay[k] for k in ("runs", "buggy_runs", "bases")}
        w = ceiling.base_weights(lay["base"], lay["bases"], draws, SEED + size)
        w = w[ceiling.usable(w, lay["buggy"])]
        bank = strongest_bank(lay, w, features, bank_size, rng)
        for icc in iccs:
            for j in j_grid:
                n = fp_sims if math.isclose(j, FP_J) else sims
                cell = simulate(lay, j, icc, w, bank, n, rng)
                grid.setdefault(f"{icc:.1f}", {}).setdefault(str(size), {})[f"{j:.2f}"] = cell
                print(f"ICC {icc:.1f}, {size:3d} runs, J {j:.2f}: SOLVABLE {cell['p_solvable_cell']:.3f}  below "
                      f"{cell['p_below_bar_cell']:.3f}  works-unknown {cell['p_works_strength_unknown_cell']:.3f}",
                      flush=True)
    return {"sizes": list(sizes), "j_grid": list(j_grid), "verdict_iccs": list(iccs), "sims": sims, "fp_sims": fp_sims,
            "draws": draws, "feature_bank": bank_size, "level": ceiling.LEVEL, "features": features,
            "layouts": layouts, "grid": grid, "ceiling_code_sha256": ceiling.code_sha256(),
            "assumptions": __doc__.split("Model of one simulated batch")[1].split("Batch-size criterion")[0].strip(),
            "criterion_text": "Batch-size criterion" + __doc__.split("Batch-size criterion")[1].strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sims", type=int, default=SIMS)
    parser.add_argument("--fp-sims", type=int, default=FP_SIMS)
    parser.add_argument("--draws", type=int, default=DRAWS)
    parser.add_argument("--level", type=float, help="simulate another interval level (a proposal for the lock; "
                                                    "eval/ceiling.py keeps its own until the student changes it)")
    parser.add_argument("--quick", action="store_true", help="only what the criterion needs: ICC 0.2, J 0.40 and 0.70")
    args = parser.parse_args(argv)
    out_path = OUT_PATH
    if args.level:
        ceiling.LEVEL = args.level
        ceiling.PERCENTILES = (100 * (1 - args.level) / 2, 100 * (1 + args.level) / 2)
        out_path = OUT_PATH.with_name(f"power_ceiling_level_{args.level * 100:g}.json")
    grid_args = {"iccs": (PRIMARY_ICC,), "j_grid": (FP_J, POWER_J)} if args.quick else {}
    result = build(args.sims, args.fp_sims, args.draws, **grid_args)
    result["level_simulated"] = ceiling.LEVEL
    result["criterion"] = criterion(result["grid"])
    pool = json.loads(mixer.POOL_PATH.read_text(encoding="utf-8"))
    result["times"] = power_sim.measured_times()
    result["recommendation"] = cost(result["criterion"]["chosen_runs"], config.load_yaml("models.yaml"),
                                    result["times"], len(pool["bases"]))
    if result["criterion"]["chosen_runs"] is None:  # still cost the largest size, so the student sees the stakes
        result["cost_at_200"] = cost(max(SIZES), config.load_yaml("models.yaml"), result["times"], len(pool["bases"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    c = result["criterion"]
    print("\nCriterion at verdict ICC 0.2 (power at J 0.70 >= 0.80; 4-cell FP at J 0.40 <= 0.05):")
    for row in c["rows"]:
        print(f"  {row['runs']:3d} runs: power {row['power_at_j_0_70']:.3f}, FP bound {row['fp_bonferroni_4_cells_at_j_0_40']:.3f}")
    print(f"Chosen: {c['chosen_runs']} ({c['why']})")
    if result["recommendation"]:
        r = result["recommendation"]
        print(f"Batch: {r['task_dev_2_runs']} task-dev-2 runs + {r['fresh_pool_2_runs']} fresh pool-2 runs; laptop "
              f"{r['laptop_minutes']} min; {r['calls_per_arm']} calls per arm: " +
              ", ".join(f"arm {a} {v['days']} days at {v['daily_call_budget']}/day" for a, v in r["arms"].items()))
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
