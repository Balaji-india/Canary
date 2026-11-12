"""The cloud ceiling check's analysis: is the review task solvable from a blinded run, for the named cloud reviewer?

Run once per arm, after every audit of the arm is stored: `python -m eval.ceiling --arm L` (then `--arm R` only if arm
L is not SOLVABLE). Development check on existing local audits: `python -m eval.ceiling --dev skeptic_c_checklist`.
Plan: docs/plans/cloud_ceiling_check_outline.md (sections 5 and 6; rule approved by the student 2026-11-11). This file
is frozen before the first cloud call: its SHA-256 goes in the lock, and it is not changed after any cloud reply exists.

Design (student's rule, applied to eval/results/ceiling/design_study.json on 2026-11-11): **2 cells**, one per arm, the
baseline prompt only (the checklist cells were dropped), on **120 runs** (the 40 task-dev-2 runs + 80 fresh pool-2 runs
in `ceiling-ext`), at the **97.5%** level: the least strict level at which power at a true J of 0.70 is at least 0.80
and the 2-cell false-positive bound at J 0.40 is at most 0.05 under verdict ICC 0.1, 0.2 and 0.4, with the fewest calls.
The rule, per **cell** (one arm with one prompt), each test on the lower end of a 97.5% two-sided base-level percentile
interval (bases resampled because clones of a base are not independent; a base is the comparison it makes, so two
bases that differ only in a model hyperparameter are one cluster: `cluster_labels`, the student's rule of 2026-11-12):
- T1, the verdict works: Youden's J > 0 (recall + specificity > 1, where Rogan-Gladen is defined).
- T2, strong enough: AUC > 0.70. No cloud cell has token probabilities, so the score is the code's verdict as 0/1, and
  its AUC is exactly (1 + J) / 2 (ties count half): T2 reads "J above 0.40", and T1 follows from it.
- T3, not a cue: AUC minus the direction-free AUC of the strongest of the seven trivial features
  (`compare_tasks.FEATURES`), re-picked in every draw, is above 0.
Outcomes, which cannot overlap (SOLVABLE needs one lower bound above 0.70, HARD every upper bound below it):
- SOLVABLE (for the named model): at least one non-void cell passes T1, T2 and T3.
- HARD (for these two models): arm R was run, both cells exist, none is void, and every AUC upper bound is below 0.70.
- INCONCLUSIVE: anything else; sub-case "works but strength unknown" when a non-void cell passes T1 but not T2.
Failed audits: a run whose audits all failed, after the command was run again (two or more failure records), counts
against the reviewer (a canary as passed, a clean run as flagged); a cell with more than 10% of its runs like that is
void. A run with one failure record (not retried yet) or no record at all means the arm is unfinished: nothing is
computed, only counts are printed (no looking at partial results). A daily-limit stop leaves no record, so such runs
simply count as not asked yet.
Sensitivity, deciding nothing: the same tests with the bootstrap over focus-level clusters (dataset | metric | model),
because pool 2 was asked on pool 1's grid; a different outcome there is reported beside the outcome.
No LLM is called here; every number comes from the ledger, the sealed table, the run files and the call log.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from canary import ledger, llm, mixer, sandbox, sealed
from canary.config import ROOT
from eval import compare_tasks

ARMS = {"L": ("skeptic_d",), "R": ("skeptic_e",)}  # the 2-cell design: baseline prompt only (design_study.json)
CELLS = sum(len(roles) for roles in ARMS.values())
BATCHES = ("task-dev-2", "ceiling-ext")  # 40 + 80 runs; ceiling-ext is planned with calibrate --no-audit on pool 2
LEVEL = 0.975  # the least strict qualifying level for the 2-cell design (design_study.json)
PERCENTILES = (100 * (1 - LEVEL) / 2, 100 * (1 + LEVEL) / 2)  # 1.25 and 98.75
DRAWS = 10_000
SEED = 0
J_BAR, AUC_BAR, GAP_BAR = 0.0, 0.70, 0.0
VOID_SHARE = 0.10  # more than this share of runs without any reply makes a cell void
FEATURES = compare_tasks.FEATURES
LLAMA_ROLE, LLAMA_BATCH = "skeptic_c_checklist", "task-dev-2"  # secondary paired comparison only
REPEAT_KIND = "repeat"
SOLVABLE, HARD, INCONCLUSIVE = "SOLVABLE", "HARD", "INCONCLUSIVE"
WORKS_STRENGTH_UNKNOWN = "works but strength unknown"
OUT_DIR = compare_tasks.RESULTS_DIR / "ceiling"
CLEAN_TYPES = (sealed.CONTROL, sealed.SHAM)


class ArmNotFinished(RuntimeError):
    """Some runs of the arm have no final answer yet. Carries counts only, never a metric."""


# ---------- the rule, as pure functions (the power simulation calls these same functions) ----------

def cell_tests(j_low: float, auc_low: float, auc_high: float, gap_low: float | None, failed_share: float) -> dict:
    """The three tests of one cell from its interval ends. `gap_low` may be None when T1 or T2 already failed."""
    void = failed_share > VOID_SHARE
    t1, t2 = j_low > J_BAR, auc_low > AUC_BAR
    t3 = gap_low is not None and gap_low > GAP_BAR
    return {"T1": bool(t1), "T2": bool(t2), "T3": bool(t3), "void": bool(void),
            "passes": bool(t1 and t2 and t3 and not void), "below_bar": bool(auc_high < AUC_BAR)}


def outcome(tests: dict[str, dict], arm_r_run: bool, cells_expected: int = CELLS) -> dict:
    """SOLVABLE, HARD or INCONCLUSIVE from the cells' tests. Exactly one is returned, by construction."""
    passing = sorted(name for name, t in tests.items() if t["passes"])
    if passing:
        return {"outcome": SOLVABLE, "cells": passing, "subcase": None}
    if (arm_r_run and len(tests) == cells_expected and not any(t["void"] for t in tests.values())
            and all(t["below_bar"] for t in tests.values())):
        return {"outcome": HARD, "cells": sorted(tests), "subcase": None}
    works = sorted(n for n, t in tests.items() if t["T1"] and not t["T2"] and not t["void"])
    return {"outcome": INCONCLUSIVE, "cells": works, "subcase": WORKS_STRENGTH_UNKNOWN if works else None}


# ---------- base-level bootstrap with per-run weights (vectorised; the simulation uses it too) ----------

def base_weights(base_index: np.ndarray, n_bases: int, draws: int, seed: int) -> np.ndarray:
    """draws x runs: how often each run's base was drawn in each base-level resample."""
    rng = np.random.default_rng(seed)
    counts = np.stack([np.bincount(rng.integers(0, n_bases, n_bases), minlength=n_bases) for _ in range(draws)])
    return counts[:, base_index].astype(float)


def weighted_aucs(values: np.ndarray, buggy: np.ndarray, w: np.ndarray) -> np.ndarray:
    """AUC (ties count half) in every draw: sum over buggy-clean pairs of weight products times the pair's outcome."""
    b, c = values[buggy][:, None], values[~buggy][None, :]
    pairs = (b > c) + 0.5 * (b == c)
    w_bug, w_clean = w[:, buggy], w[:, ~buggy]
    return np.einsum("dc,dc->d", w_bug @ pairs, w_clean) / (w_bug.sum(1) * w_clean.sum(1))


def weighted_j(flagged: np.ndarray, buggy: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Recall minus false-alarm rate in every draw."""
    w_bug, w_clean = w[:, buggy], w[:, ~buggy]
    return w_bug @ flagged[buggy] / w_bug.sum(1) - w_clean @ flagged[~buggy] / w_clean.sum(1)


def usable(w: np.ndarray, buggy: np.ndarray) -> np.ndarray:
    """Draws with at least one buggy and one clean run (others are skipped, as in separation.base_bootstrap)."""
    return (w[:, buggy].sum(1) > 0) & (w[:, ~buggy].sum(1) > 0)


def interval(values: np.ndarray) -> list[float]:
    return [float(v) for v in np.percentile(values, PERCENTILES)]


def analyse_cell(rows: list[dict], draws: int = DRAWS, seed: int = SEED) -> dict:
    """J, AUC and the trivial-feature gap of one cell, with 97.5% base-level intervals, and its three tests.

    `rows`: one dict per run with base, buggy, flagged, failed (no reply, counted against the reviewer) and every
    feature in FEATURES. A missing feature raises: the frozen analysis never drops runs silently.
    """
    missing = [r["run_id"] for r in rows if any(r["features"].get(f) is None for f in FEATURES)]
    if missing:
        raise ValueError(f"{len(missing)} runs lack trivial features (run files missing?): {missing[:3]}")
    bases = sorted({r["base"] for r in rows})
    base_index = np.array([bases.index(r["base"]) for r in rows])
    buggy = np.array([r["buggy"] for r in rows])
    flagged = np.array([r["flagged"] for r in rows], dtype=float)
    w = base_weights(base_index, len(bases), draws, seed)
    w = w[usable(w, buggy)]
    one = np.ones((1, len(rows)))  # the observed data: every run once
    j = weighted_j(flagged, buggy, w)
    auc = weighted_aucs(flagged, buggy, w)
    feature_values = {f: np.array([r["features"][f] for r in rows], dtype=float) for f in FEATURES}
    feature_draws = {f: weighted_aucs(v, buggy, w) for f, v in feature_values.items()}
    strongest = np.max([np.maximum(a, 1 - a) for a in feature_draws.values()], axis=0)
    gap = auc - strongest
    observed_features = {f: float(weighted_aucs(v, buggy, one)[0]) for f, v in feature_values.items()}
    observed_auc = float(weighted_aucs(flagged, buggy, one)[0])
    observed_strongest = max(observed_features, key=lambda f: max(observed_features[f], 1 - observed_features[f]))
    failed = sum(r["failed"] for r in rows)
    j_iv, auc_iv, gap_iv = interval(j), interval(auc), interval(gap)
    return {
        "runs": len(rows), "buggy": int(buggy.sum()), "clean": int((~buggy).sum()), "bases": len(bases),
        "flagged_buggy": int(flagged[buggy].sum()), "flagged_clean": int(flagged[~buggy].sum()),
        "failed_counted_against": failed, "failed_share": failed / len(rows),
        "youden_j": {"value": float(weighted_j(flagged, buggy, one)[0]), "interval_975_base": j_iv},
        "auc_verdict": {"value": observed_auc, "interval_975_base": auc_iv},
        "gap_vs_strongest_feature": {"value": observed_auc - max(observed_features[observed_strongest],
                                                                 1 - observed_features[observed_strongest]),
                                     "interval_975_base": gap_iv, "strongest_observed": observed_strongest},
        "feature_auc": observed_features, "draws_used": int(len(w)),
        "tests": cell_tests(j_iv[0], auc_iv[0], auc_iv[1], gap_iv[0], failed / len(rows)),
    }


# ---------- data: which runs, and what each role said ----------

def comparison_key(locked: dict) -> str:
    """What a base compares: dataset, metric, test size, and each arm's model and preprocessing.

    Model hyperparameters, seeds and the hypothesis wording are left out on purpose, so two bases that differ only in
    a hyperparameter (near-twins) get the same key.
    """
    def arm(config: dict) -> dict:
        return {"model": config["model"], "preprocessing": list(config.get("preprocessing") or [])}
    return json.dumps({"dataset": locked["dataset"], "metric": locked["metric"], "test_size": locked["test_size"],
                       "control": arm(locked["control_config"]), "treatment": arm(locked["treatment_config"])},
                      sort_keys=True)


@functools.lru_cache(maxsize=None)
def _pool_bases(path: str) -> list[dict]:
    file = Path(path)
    if not file.exists():
        raise ValueError(f"pool file {file} is missing: the clusters of its runs cannot be told")
    return json.loads(file.read_text(encoding="utf-8"))["bases"]


def cluster_labels(batch: str, source: str | None, run_id: str, plans_dir: Path = sealed.PLANS_DIR,
                   root: Path = ROOT) -> tuple[str, str]:
    """(base-level cluster, focus-level cluster) of a run: the units the bootstraps resample.

    Base level (decides): the comparison its base makes (`comparison_key`), read from the pool file the batch's plan
    names. Why not the run's `source`: it is only `pool:<index>` and every pool counts from 0, so pool-1 base 0 and
    pool-2 base 0 would be one cluster by accident. Why not one cluster per base: a pool-2 base that differs from a
    pool-1 base only in a hyperparameter is a near-twin, and the student's rule (2026-11-12) is that near-twins are
    ONE cluster in every base-level bootstrap.
    Focus level (sensitivity only): the base's grid cell, dataset | metric | model. Pool 2 was asked on the same grid
    as pool 1, so every pool-2 base shares its focus with a pool-1 base.
    A plan that names a pool file which is missing raises: the frozen analysis never guesses a cluster. A batch with
    no stored plan or no pool (old batches, tests) keeps one cluster per source, named by the batch.
    """
    if not source:
        return run_id, run_id
    plan = mixer.plan_path(batch, plans_dir)
    pool = json.loads(plan.read_text(encoding="utf-8")).get("pool") if plan.exists() else None
    if not pool or not source.startswith("pool:"):
        return f"batch:{batch}|{source}", f"batch:{batch}|{source}"
    path = Path(pool.replace("\\", "/"))  # the plan stores a Windows path, relative to the project folder
    base = _pool_bases(str(path if path.is_absolute() else root / path))[int(source.split(":", 1)[1])]
    focus = base["focus"]
    return comparison_key(base["prereg"]), f"{focus['dataset']}|{focus['metric']}|{focus['model']}"


def cell_rows(table: sealed.SealedTable, led: ledger.Ledger, batches: tuple[str, ...], role: str,
              runs_dir: Path = sandbox.RUNS_DIR, plans_dir: Path = sealed.PLANS_DIR, root: Path = ROOT) -> dict:
    """Every finished calibration run of the batches with the role's final answer, or the counts that block analysis.

    Returns {"rows": [...], "waiting": n, "failed_once": n, "crashed": n}. Only the first audit counts. Each row
    carries its base-level cluster (`base`) and its focus-level cluster (`focus`), from `cluster_labels`.
    """
    entries = led.entries()
    finished = {e.payload["run_id"] for e in entries if e.status == ledger.RAN and e.payload.get("results_sha256")}
    first: dict[str, dict] = {}
    failures: dict[str, int] = {}
    for e in entries:
        if e.payload.get("role") != role:
            continue
        if e.status == ledger.AUDITED:
            first.setdefault(e.payload["run_id"], e.payload)
        elif e.status == ledger.AUDIT_FAILED:
            failures[e.payload["run_id"]] = failures.get(e.payload["run_id"], 0) + 1
    rows, waiting, failed_once, crashed = [], 0, 0, 0
    for truth in sorted(table.all(), key=lambda t: t.run_id):
        if truth.details.get("batch") not in batches or truth.run_type not in (sealed.CANARY_MEASURE, *CLEAN_TYPES):
            continue
        if truth.run_id not in finished:
            crashed += 1
            continue
        buggy = truth.run_type == sealed.CANARY_MEASURE
        if truth.run_id in first:
            audit = first[truth.run_id]
            flagged, failed = (audit.get("decision") or audit["audit"])["verdict"] == "flag", False
        elif failures.get(truth.run_id, 0) >= 2:
            flagged, failed = not buggy, True  # counted against the reviewer
        else:
            failed_once += truth.run_id in failures
            waiting += truth.run_id not in failures
            continue
        base, focus = cluster_labels(truth.details["batch"], truth.source, truth.run_id, plans_dir, root)
        rows.append({"run_id": truth.run_id, "base": base, "focus": focus, "buggy": buggy, "flagged": flagged,
                     "failed": failed, "run_type": truth.run_type, "tier": truth.tier,
                     "features": compare_tasks.run_features(truth.run_id, runs_dir) or {}})
    return {"rows": rows, "waiting": waiting, "failed_once": failed_once, "crashed": crashed}


def check_finished(collected: dict[str, dict]) -> None:
    """Refuse to compute anything on a partly finished arm. The message carries counts only."""
    open_ = {role: (c["waiting"], c["failed_once"]) for role, c in collected.items() if c["waiting"] or c["failed_once"]}
    if open_:
        detail = "; ".join(f"{role}: {len(collected[role]['rows'])} answered, {w} not asked yet, {f} failed once "
                           f"(run the same reaudit command again)" for role, (w, f) in open_.items())
        raise ArmNotFinished(f"arm not finished, nothing computed: {detail}")


# ---------- reported, deciding nothing ----------

def secondary(rows: list[dict]) -> dict:
    def rate(group: list[dict], flag: bool) -> dict:
        hits = sum(r["flagged"] == flag for r in group)
        return {"value": hits / len(group) if group else None, "of": len(group)}
    canaries = [r for r in rows if r["buggy"]]
    return {"recall": rate(canaries, True),
            "specificity": {t: rate([r for r in rows if r["run_type"] == t], False) for t in CLEAN_TYPES},
            "recall_by_tier": {tier: rate([r for r in canaries if r["tier"] == tier], True)
                               for tier in sorted({r["tier"] for r in canaries if r["tier"]})}}


def focus_sensitivity(rows: list[dict], draws: int = DRAWS, seed: int = SEED) -> dict:
    """The same cell with the bootstrap resampling focus-level clusters (dataset | metric | model). Deciding nothing.

    Why: both pools were asked on one grid, so runs of the two pools on the same focus may not be independent. If the
    three tests come out differently here, the report must say so beside the outcome (plan section 5).
    """
    cell = analyse_cell([{**r, "base": r["focus"]} for r in rows], draws, seed)
    return {"clusters": cell["bases"], "youden_j": cell["youden_j"], "auc_verdict": cell["auc_verdict"],
            "gap_vs_strongest_feature": cell["gap_vs_strongest_feature"], "tests": cell["tests"]}


def paired_vs_llama(rows: list[dict], llama: dict[str, tuple[bool, float | None]], draws: int = DRAWS,
                    seed: int = SEED) -> dict | None:
    """Cloud verdict-AUC minus llama's P(flag) AUC on the same runs (handicaps the cloud model). Deciding nothing."""
    common = [r for r in rows if llama.get(r["run_id"], (None, None))[1] is not None]
    if not common:
        return None
    bases = sorted({r["base"] for r in common})
    buggy = np.array([r["buggy"] for r in common])
    w = base_weights(np.array([bases.index(r["base"]) for r in common]), len(bases), draws, seed)
    w = w[usable(w, buggy)]
    cloud = np.array([r["flagged"] for r in common], dtype=float)
    other = np.array([llama[r["run_id"]][1] for r in common], dtype=float)
    one = np.ones((1, len(common)))
    diff = weighted_aucs(cloud, buggy, w) - weighted_aucs(other, buggy, w)
    return {"runs": len(common), "llama_role": LLAMA_ROLE,
            "value": float(weighted_aucs(cloud, buggy, one)[0] - weighted_aucs(other, buggy, one)[0]),
            "interval_975_base": interval(diff)}


def repeat_summary(batches: tuple[str, ...], role: str, directory: Path = mixer.RESCORE_DIR) -> dict:
    records = [r for b in batches for r in mixer.read_rescores(b, directory, REPEAT_KIND) if r["role"] == role]
    asked = [r for r in records if r["outcome"] in ("matched", "reply_differs")]
    return {"runs": len(asked), "reply_differs": sum(r["outcome"] == "reply_differs" for r in asked),
            "verdict_changed": sum(bool(r.get("verdict_changed")) for r in asked)}


def call_log_summary(roles: tuple[str, ...], path: Path | None = None) -> dict:
    path = path or llm.CALL_LOG_PATH
    if not path.exists():
        return {"calls": 0, "file_sha256": None}
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    mine = [r for r in records if r.get("role") in roles]
    return {"calls": len(mine), "status": {str(s): sum(r.get("status") == s for r in mine)
                                          for s in sorted({r.get("status") for r in mine}, key=str)},
            "total_tokens": sum(r.get("total_tokens") or 0 for r in mine),
            "reasoning_tokens": sum(r.get("reasoning_tokens") or 0 for r in mine),
            "server_models": sorted({r["server_model"] for r in mine if r.get("server_model")}),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def code_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# ---------- the command ----------

def analyse_roles(table, led, roles: tuple[str, ...], batches: tuple[str, ...], draws: int = DRAWS,
                  runs_dir: Path = sandbox.RUNS_DIR, rescore_dir: Path = mixer.RESCORE_DIR,
                  plans_dir: Path = sealed.PLANS_DIR, root: Path = ROOT) -> dict[str, dict]:
    collected = {role: cell_rows(table, led, batches, role, runs_dir, plans_dir, root) for role in roles}
    check_finished(collected)  # before any metric exists
    llama = {}
    if LLAMA_BATCH in batches:
        from eval import cutoff
        llama = cutoff.role_scores(table, led, LLAMA_BATCH, LLAMA_ROLE, rescore_dir)
    cells = {}
    for role, c in collected.items():
        if not c["rows"]:
            raise ArmNotFinished(f"{role}: no runs to analyse in {batches}")
        cell = analyse_cell(c["rows"], draws)
        cell.update(crashed_runs_left_out=c["crashed"], secondary=secondary(c["rows"]),
                    focus_level=focus_sensitivity(c["rows"], draws),
                    paired_vs_llama=paired_vs_llama(c["rows"], llama, draws) if role != LLAMA_ROLE else None,
                    repeat_pass=repeat_summary(batches, role, rescore_dir),
                    models=sorted({e.payload["model"] for e in led.entries(ledger.AUDITED)
                                   if e.payload.get("role") == role}))
        cells[role] = cell
    return cells


def run_arm(arm: str, table, led, batches: tuple[str, ...] = BATCHES, out_dir: Path = OUT_DIR,
            draws: int = DRAWS, **paths) -> dict:
    """Analyse one arm once and write `arm_<X>.json`. Refuses a second run, and arm R before arm L."""
    out = out_dir / f"arm_{arm}.json"
    if out.exists():
        raise FileExistsError(f"{out} exists: the analysis runs once per arm")
    earlier = {}
    if arm == "R":
        first = out_dir / "arm_L.json"
        if not first.exists():
            raise FileNotFoundError("arm R is analysed after arm L")
        arm_l = json.loads(first.read_text(encoding="utf-8"))
        if arm_l["outcome"]["outcome"] == SOLVABLE:
            raise RuntimeError("arm L is SOLVABLE: the plan does not run arm R")
        if tuple(arm_l["batches"]) != tuple(batches):
            raise RuntimeError(f"arm L used batches {arm_l['batches']}, arm R would use {list(batches)}: one outcome "
                               f"may not mix two sets of runs")
        earlier = arm_l["cells"]
    roles = ARMS[arm]
    cells = analyse_roles(table, led, roles, batches, draws, **paths)
    all_cells = {**earlier, **cells}
    primary = outcome({n: c["tests"] for n, c in all_cells.items()}, arm_r_run=arm == "R")
    by_focus = outcome({n: c["focus_level"]["tests"] for n, c in all_cells.items()}, arm_r_run=arm == "R")
    result = {"arm": arm, "roles": list(roles), "batches": list(batches), "generated_at": datetime.now(timezone.utc).isoformat(),
              "level": LEVEL, "draws": draws, "bars": {"J": J_BAR, "AUC": AUC_BAR, "gap": GAP_BAR, "void_share": VOID_SHARE},
              "features": list(FEATURES), "code_sha256": code_sha256(), "cells": cells,
              "outcome": primary,
              "sensitivity_focus_level": {"outcome": by_focus, "agrees": by_focus["outcome"] == primary["outcome"],
                                          "note": "bootstrap over dataset|metric|model clusters; decides nothing, but a "
                                                  "disagreement is reported beside the outcome"},
              "call_log": call_log_summary(roles), "claim": "for these models, at these settings, on Canary's canaries"}
    out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def print_cells(cells: dict[str, dict]) -> None:
    for name, c in cells.items():
        j, a, g, t = c["youden_j"], c["auc_verdict"], c["gap_vs_strongest_feature"], c["tests"]
        print(f"{name}: {c['runs']} runs ({c['buggy']} buggy) on {c['bases']} bases; flagged {c['flagged_buggy']}/"
              f"{c['buggy']} buggy, {c['flagged_clean']}/{c['clean']} clean; {c['failed_counted_against']} failed")
        print(f"  J {j['value']:+.3f} [{j['interval_975_base'][0]:+.3f}, {j['interval_975_base'][1]:+.3f}]  "
              f"AUC {a['value']:.3f} [{a['interval_975_base'][0]:.3f}, {a['interval_975_base'][1]:.3f}]  "
              f"gap {g['value']:+.3f} [{g['interval_975_base'][0]:+.3f}, {g['interval_975_base'][1]:+.3f}] "
              f"(strongest observed: {g['strongest_observed']})")
        print(f"  T1 {t['T1']}  T2 {t['T2']}  T3 {t['T3']}  void {t['void']}  passes {t['passes']}  "
              f"below 0.70 {t['below_bar']}")
        f = c["focus_level"]
        print(f"  sensitivity, {f['clusters']} focus-level clusters: J [{f['youden_j']['interval_975_base'][0]:+.3f}, "
              f"{f['youden_j']['interval_975_base'][1]:+.3f}]  AUC [{f['auc_verdict']['interval_975_base'][0]:.3f}, "
              f"{f['auc_verdict']['interval_975_base'][1]:.3f}]  passes {f['tests']['passes']}  "
              f"below 0.70 {f['tests']['below_bar']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--arm", choices=sorted(ARMS), help="the ceiling check: run once per arm")
    group.add_argument("--dev", metavar="ROLE", help="development check on any role's existing audits (decides nothing)")
    parser.add_argument("--batch", action="append", help="with --dev: batches (default task-dev-2)")
    args = parser.parse_args(argv)
    table, led = sealed.SealedTable(), ledger.Ledger()
    try:
        if args.dev:
            batches = tuple(args.batch or [LLAMA_BATCH])
            cells = analyse_roles(table, led, (args.dev,), batches)
            print(f"DEVELOPMENT check (not the ceiling result): {args.dev} on {', '.join(batches)}, code "
                  f"{code_sha256()[:16]}")
            print_cells(cells)
            out = OUT_DIR / f"dev_{args.dev}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"development": True, "batches": list(batches), "code_sha256": code_sha256(),
                                       "cells": cells}, indent=1), encoding="utf-8")
            print(f"Wrote {out}")
            return 0
        result = run_arm(args.arm, table, led)
    except (ArmNotFinished, FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Not computed: {exc}")
        return 1
    print_cells(result["cells"])
    o = result["outcome"]
    print(f"\nOutcome after arm {args.arm}: {o['outcome']}" + (f" ({o['subcase']})" if o["subcase"] else "") +
          f", cells {o['cells']}. Claim: {result['claim']}.")
    sens = result["sensitivity_focus_level"]
    print(f"Sensitivity (focus-level clusters, decides nothing): {sens['outcome']['outcome']}, "
          f"{'agrees' if sens['agrees'] else 'DIFFERS: report both'}.")
    print(f"Wrote {OUT_DIR / f'arm_{args.arm}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
