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
from pathlib import Path

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


def calls_per_arm(size: int, prompts: int = PROMPTS_PER_ARM) -> int:
    """One call per run and prompt, the repeat pass (20 per cell), and the smoke test (toy, one per prompt, a repeat)."""
    return prompts * size + prompts * REPEAT_PER_CELL + (2 + prompts)


def calls_per_day(entry: dict) -> int:
    """Calls a day inside our budget: the call cap, or the token budget at the expected tokens per call if lower."""
    by_calls = entry["max_calls_per_day"]
    if entry.get("max_tokens_per_day") and entry.get("expected_tokens_per_call"):
        return min(by_calls, entry["max_tokens_per_day"] // entry["expected_tokens_per_call"])
    return by_calls


def cost(size: int | None, models_cfg: dict, times: dict, pool_bases: int, prompts: int = PROMPTS_PER_ARM) -> dict | None:
    """Extension runs, laptop minutes and calendar days per arm at each provider's daily budget."""
    if size is None:
        return None
    extension = max(0, size - DEV_RUNS)
    laptop_s = (pool_bases * times["pool_seconds_per_base"] + extension * times["run_seconds_per_run"]) if extension else 0
    calls = calls_per_arm(size, prompts)
    arms = {}
    for arm, roles in ceiling.ARMS.items():
        provider = models_cfg["roles"][roles[0]]["provider"]
        entry = models_cfg["providers"][provider]
        per_day = calls_per_day(entry)
        arms[arm] = {"provider": provider, "calls_per_day": per_day, "calls": calls, "days": math.ceil(calls / per_day),
                     "minutes_per_daily_session": round(per_day * entry.get("min_interval_s", 0) / 60, 1)}
    return {"runs": size, "prompts_per_arm": prompts, "task_dev_2_runs": min(size, DEV_RUNS),
            "fresh_pool_2_runs": extension, "pool_2_build_bases": pool_bases if extension else 0,
            "laptop_minutes": round(laptop_s / 60, 1), "calls_per_arm": calls, "arms": arms,
            "note": "laptop: pool-2 build by the Scientist plus the extension runs, no local audits (the reviewer is "
                    "in the cloud); calls: prompts x runs + the repeat pass (20 per cell) + the smoke test; "
                    "invalid-reply retries would add calls; tokens per call are an estimate until the smoke test"}


# ---------- the design study (student's rule, 2026-11-11, fixed before these simulations ran) ----------
# Candidates: a 4-cell design (2 arms x 2 prompts) and a 2-cell design (one prompt per arm: baseline only), at
# interval levels 97.5% (the approved one; with 2 cells there are only 2 chances), 99% and 99.5%, for 120 and 160 runs,
# under verdict ICC 0.1, 0.2 and 0.4. A cell's simulation does not depend on the design: the design only sets how many
# cells share the false-positive budget (Bonferroni bound = cells x p) and how many calls an arm costs.
# Rule (Claude's reading of the student's wording, written before any result): a (design, level, size) qualifies if,
# under EVERY ICC, power at true J 0.70 is at least 0.80 and the false-positive bound at J 0.40 is at most 0.05. For each
# design keep its least strict qualifying level, at its smallest qualifying size. Among those, the fewest calls per arm.
DESIGNS = {"4-cell": 2, "2-cell": 1}  # prompts per arm
STUDY_LEVELS = (0.975, 0.99, 0.995)
STUDY_ICCS = (0.1, 0.2, 0.4)
STUDY_SIZES = (120, 160)
STUDY_PATH = ceiling.OUT_DIR / "design_study.json"


def set_level(level: float) -> None:
    """Simulate at another interval level (this process only; eval/ceiling.py's file is not touched)."""
    ceiling.LEVEL = level
    ceiling.PERCENTILES = (100 * (1 - level) / 2, 100 * (1 + level) / 2)


def level_path(level: float) -> Path:
    return ceiling.OUT_DIR / f"design_level_{level * 100:g}.json"


def choose_design(per_level: dict[float, dict]) -> dict:
    """Apply the rule above to {level: grid} (grid as built by `build`). Returns every row and the choice."""
    rows = []
    for design, prompts in DESIGNS.items():
        cells = 2 * prompts
        for level in sorted(per_level):
            for size in STUDY_SIZES:
                by_icc = {}
                for icc in STUDY_ICCS:
                    c = per_level[level][f"{icc:.1f}"][str(size)]
                    power, p_fp = c[f"{POWER_J:.2f}"]["p_solvable_cell"], c[f"{FP_J:.2f}"]["p_solvable_cell"]
                    by_icc[f"{icc:.1f}"] = {"power": power, "fp_bound": min(1.0, cells * p_fp),
                                            "fp_bound_mc_se": cells * c[f"{FP_J:.2f}"]["mc_se_solvable"]}
                ok = all(v["power"] >= POWER_TARGET and v["fp_bound"] <= FP_TARGET for v in by_icc.values())
                rows.append({"design": design, "cells": cells, "level": level, "runs": size,
                             "calls_per_arm": calls_per_arm(size, prompts), "qualifies": ok, "by_icc": by_icc})
    picks = []
    for design in DESIGNS:
        ok = [r for r in rows if r["design"] == design and r["qualifies"]]
        if ok:
            least = min(r["level"] for r in ok)
            picks.append(min((r for r in ok if r["level"] == least), key=lambda r: r["runs"]))
    choice = min(picks, key=lambda r: (r["calls_per_arm"], -r["cells"])) if picks else None
    return {"rows": rows, "per_design_picks": picks, "choice": choice,
            "rule": "qualifies under every ICC (power >= 0.80 at J 0.70, cells x p <= 0.05 at J 0.40); per design the "
                    "least strict qualifying level at its smallest size; then the fewest calls per arm"}


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
    parser.add_argument("--design-study", action="store_true",
                        help="with --level: 120 and 160 runs, ICC 0.1/0.2/0.4, J 0.40 and 0.70, full thoroughness")
    parser.add_argument("--choose", action="store_true", help="merge the design-study levels and apply the rule")
    args = parser.parse_args(argv)
    if args.design_study:
        set_level(args.level)
        result = build(args.sims, args.fp_sims, args.draws, sizes=STUDY_SIZES, j_grid=(FP_J, POWER_J), iccs=STUDY_ICCS)
        result["level_simulated"] = args.level
        level_path(args.level).write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"Wrote {level_path(args.level)}")
        return 0
    if args.choose:
        files = {level: json.loads(level_path(level).read_text(encoding="utf-8")) for level in STUDY_LEVELS}
        study = choose_design({level: f["grid"] for level, f in files.items()})
        pool = json.loads(mixer.POOL_PATH.read_text(encoding="utf-8"))
        times, models = power_sim.measured_times(), config.load_yaml("models.yaml")
        if study["choice"]:
            c = study["choice"]
            study["cost"] = cost(c["runs"], models, times, len(pool["bases"]), DESIGNS[c["design"]])
        study["costs_of_picks"] = [cost(p["runs"], models, times, len(pool["bases"]), DESIGNS[p["design"]])
                                   for p in study["per_design_picks"]]
        study.update(times=times, sims=files[STUDY_LEVELS[0]]["sims"], fp_sims=files[STUDY_LEVELS[0]]["fp_sims"],
                     draws=files[STUDY_LEVELS[0]]["draws"], level_files=[str(level_path(l)) for l in STUDY_LEVELS])
        STUDY_PATH.write_text(json.dumps(study, indent=1), encoding="utf-8")
        for r in study["rows"]:
            print(f"{r['design']} {r['level']:.3f} {r['runs']} runs, {r['calls_per_arm']} calls: " + "  ".join(
                f"ICC {i} pow {v['power']:.3f} fp {v['fp_bound']:.3f}" for i, v in r["by_icc"].items()) +
                ("  QUALIFIES" if r["qualifies"] else ""))
        print(f"Choice: {study['choice'] and {k: study['choice'][k] for k in ('design', 'level', 'runs', 'calls_per_arm')}}")
        print(f"Wrote {STUDY_PATH}")
        return 0
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
              ", ".join(f"arm {a} {v['days']} days at {v['calls_per_day']}/day" for a, v in r["arms"].items()))
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
