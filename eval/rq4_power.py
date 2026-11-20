"""Mission 4.1 step 1: the trust-gate design simulation as tested code, re-run with measured reviewer rates.

Why: the design session (docs/plans/sims/trust_design_sim.py, 2026-11-15) sized the gate and the RQ4 bank with
ASSUMED reviewer rates. This module runs the same simulation through the estimator itself
(`trust.estimate_from_posteriors`), so the simulation cannot drift from the code that will make real decisions, and
re-runs it with the rates measured since:
  skeptic_d   the locked ceiling result, arm L (task-dev-2 + ceiling-ext, 120 runs),
  tripwire_v1 the locked tripwire test (tripwire-test-1, 360 runs, role tripwire_v1 in the ledger),
  union       per run, "flagged if either flags", on the runs both reviewers judged (ceiling-ext from the ledger;
              task-dev-2 with its tripwire records from the dev loop on disk). Never computed from the two rates.
Every count is read through `canary.trust` (the only module that joins with the sealed table) and checked against
the locked result files before it is used. Anything not measured is labelled "assumed".

This is design only: no threshold is chosen on these numbers and nothing is locked (plan section 6, trap 9).
In a simulated campaign the "true" recall of a class is the posterior mean of its measured counts, Beta(1 + s, 1 + f).

Run: python -m eval.rq4_power [--reps 1000] [--draws 1000]   (writes eval/results/rq4_power/design_rerun.json)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path

import numpy as np

from canary import ledger, sealed, tripwire_ledger, trust

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"
OUT_PATH = RESULTS / "rq4_power" / "design_rerun.json"
ARM_L = RESULTS / "ceiling" / "arm_L.json"
ARM_L_BREAKDOWN = RESULTS / "ceiling" / "arm_L_breakdown.json"
TRIPWIRE_TEST = RESULTS / "tripwires" / "test_tripwire-test-1.json"
TRIPWIRE_DEV_TASK_DEV_2 = RESULTS / "tripwires" / "dev_task-dev-2.json"
TRIPWIRE_TEST_CEILING_EXT = RESULTS / "tripwires" / "test_ceiling-ext.json"

TAU, GATE_PCT = 0.10, trust.GATE_PERCENTILE  # the plan's fixed values, used only to report how often a gate opens
SIZES = ((6, 60, 30), (12, 60, 60), (20, 120, 60), (20, 120, 120), (40, 120, 120))  # canaries/class, clean, real
PREVALENCES = (0.0, 0.1, 0.3)
RQ4_SIZES = (60, 100, 150, 200)
RQ4_PREVALENCES = (0.0, 0.1, 0.3, 0.5)

# The design session's assumed reviewers (trust_design_sim.py), kept for the side-by-side comparison.
ASSUMED = {
    "llm_all10": ([0.94] * 8 + [0.05, 0.17], 0.98),
    "union_all10_B09_in": ([0.97] * 9 + [0.17], 0.98),
    "union_B09_out": ([0.97] * 9, 0.98),
    "llm_B06_B09_out": ([0.94] * 8, 0.98),
}


# ---- The simulation ---------------------------------------------------------------------------------------------

def class_names(k: int) -> list[str]:
    return [f"c{i:02d}" for i in range(k)]


def simulate(se_true, mix, sp_true: float, n_c: int, n_clean: int, n_real: int, pi_true: float, seed: int,
             reps: int = 1000, draws: int = 1000, leak: tuple[int, int] | None = None) -> dict:
    """Simulated campaigns: draw calibration and real-run counts from true rates, estimate with the real estimator.

    `mix` is how real bugs spread over the classes (it sets the true recall on real bugs, se_mix). Returned per
    figure (pooled, worst): the share of campaigns whose gate figure at the 90th percentile is at most tau, whether
    the 5-95% prevalence interval covers the truth, its mean width and the mean median estimate.
    """
    rng = np.random.default_rng(seed)
    se_true, mix = np.asarray(se_true, float), np.asarray(mix, float) / np.sum(mix)
    se_mix = float(se_true @ mix)
    p_true = pi_true * se_mix + (1 - pi_true) * (1 - sp_true)
    denominator = pi_true * (1 - se_mix) + (1 - pi_true) * sp_true
    cont_true = pi_true * (1 - se_mix) / denominator if denominator > 0 else 1.0
    names = class_names(len(se_true))
    rows = {k: {"open": 0, "cover": 0, "upper_ok": 0, "width": [], "mid": []} for k in ("pooled", "worst")}
    leak_posterior = trust.Posterior(leak[0], leak[1] - leak[0]) if leak else None
    for _ in range(reps):
        caught = rng.binomial(n_c, se_true)
        per_class = {name: trust.Posterior(int(c), n_c - int(c)) for name, c in zip(names, caught)}
        passed = int(rng.binomial(n_clean, sp_true))
        flags = int(rng.binomial(n_real, p_true))
        found = trust.estimate_from_posteriors(per_class, trust.Posterior(passed, n_clean - passed),
                                               trust.Posterior(flags, n_real - flags), leak_posterior, draws, rng)
        for name in ("pooled", "worst"):
            prevalence = found[name]["prevalence"]
            low, high = prevalence["interval"]
            row = rows[name]
            row["cover"] += low <= pi_true <= high
            row["upper_ok"] += pi_true <= high
            row["width"].append(high - low)
            row["mid"].append(prevalence["median"])
        # Gate figures: the worst one is the plan's (with the leak); the pooled one is shown for contrast only.
        rows["worst"]["open"] += found["gate_figure"]["value"] <= TAU
        rows["pooled"]["open"] += _pooled_gate_value(found) <= TAU
    return {"se_mix": se_mix, "contamination_true": cont_true,
            **{name: {"gate_open": r["open"] / reps, "interval_covers": r["cover"] / reps,
                      "upper_end_above_truth": r["upper_ok"] / reps, "mean_width": float(np.mean(r["width"])),
                      "median_estimate": float(np.mean(r["mid"]))} for name, r in rows.items()}}


def _pooled_gate_value(found: dict) -> float:
    """The same figure on the pooled recall (the gate never uses it; shown for contrast, as in the design session)."""
    return found["pooled"]["contamination"][f"p{GATE_PCT}"]


def gate_grid(name: str, se, sp: float, reps: int, draws: int, seed: int, source: str) -> list[dict]:
    """The design session's gate rows for one reviewer: sizes x prevalence x mix (uniform, all bugs in the worst)."""
    rows = []
    worst_only = [0.0] * len(se)
    worst_only[int(np.argmin(se))] = 1.0
    for n_c, n_clean, n_real in SIZES:
        for pi in PREVALENCES:
            for mix_name, mix in (("uniform", [1.0] * len(se)), ("worst_class_only", worst_only)):
                if pi == 0.0 and mix_name != "uniform":
                    continue
                seed += 1
                rows.append({"reviewer": name, "rates": source, "n_per_class": n_c, "n_clean": n_clean,
                             "n_real": n_real, "pi_true": pi, "mix": mix_name,
                             **simulate(se, mix, sp, n_c, n_clean, n_real, pi, seed, reps, draws)})
    return rows


def rq4_grid(name: str, se, sp: float, b09_index: int | None, reps: int, draws: int, seed: int, source: str) -> list:
    """RQ4 sizing rows (audited runs per level), matched mix and half of the bugs B09 when B09 is a class."""
    rows = []
    for n_c in (10, 20):
        for n_aud in RQ4_SIZES:
            for pi in RQ4_PREVALENCES:
                mixes = [("matched", [1.0] * len(se))]
                if b09_index is not None and pi > 0:
                    half = [1.0] * len(se)
                    half[b09_index] = len(se) - 1.0
                    mixes.append(("half_B09", half))
                for mix_name, mix in mixes:
                    seed += 1
                    rows.append({"reviewer": name, "rates": source, "n_per_class": n_c, "n_clean": 100,
                                 "n_audited": n_aud, "pi_true": pi, "mix": mix_name,
                                 **simulate(se, mix, sp, n_c, 100, n_aud, pi, seed, reps, draws)})
    return rows


# ---- Measured counts, through trust -------------------------------------------------------------------------------

def variant_counts(observations: list[trust.Observation]) -> tuple[dict, tuple[int, int]]:
    """{(class, tier): (caught, canaries)} of measuring canaries, and (passed, clean runs) of controls and shams."""
    counts: dict = {}
    for o in observations:
        if o.run_type == sealed.CANARY_MEASURE:
            caught, n = counts.get((o.bug_id, o.tier), (0, 0))
            counts[(o.bug_id, o.tier)] = (caught + o.flagged, n + 1)
    clean = [o for o in observations if o.run_type in (sealed.CONTROL, sealed.SHAM)]
    return counts, (sum(not o.flagged for o in clean), len(clean))


def class_rates(counts: dict, support: list[tuple[str, str]]) -> dict[str, dict]:
    """Per class over a support: the pooled counts of its variants and the posterior mean Beta(1 + s, 1 + f)."""
    found: dict[str, dict] = {}
    for bug, tier in support:
        caught, n = counts.get((bug, tier), (0, 0))
        row = found.setdefault(bug, {"caught": 0, "n": 0, "variants": []})
        row["caught"] += caught
        row["n"] += n
        row["variants"].append(tier)
    for row in found.values():
        row["rate"] = (1 + row["caught"]) / (2 + row["n"])
    return dict(sorted(found.items()))


def records_as_observations(llm_observations: list[trust.Observation], folder: Path,
                            version: str) -> tuple[list[trust.Observation], list[str]]:
    """Tripwire verdicts stored on disk (a dev batch's records, not in the ledger) on the runs an LLM judged.

    The truth fields are copied from the LLM's observation of the same run (which came through trust's join); only
    the verdict and the named class come from the record. `version` is the full tripwire version (`v1:<sha256>`);
    a record of any other version is not used. Returns the observations and the runs with no record.
    """
    found, missing = [], []
    for o in llm_observations:
        record = tripwire_ledger.find_record(o.run_id, version, [folder])
        if record is None:
            missing.append(o.run_id)
            continue
        found.append(dataclasses.replace(o, flagged=record["verdict"] == trust.FLAG, named_class=record["bug_class"]))
    return found, missing


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def measured_counts(led: ledger.Ledger, table: sealed.SealedTable, records_folder: Path) -> dict:
    """Per-variant counts for skeptic_d, tripwire_v1 and their union, each checked against its locked result."""
    checks = []

    def check(label: str, ours, theirs):
        if ours != theirs:
            raise ValueError(f"parity failed for {label}: ours {ours}, result file {theirs}")
        checks.append(f"{label}: {ours} (matches)")

    # skeptic_d: the arm L runs from the ledger, against the locked arm file and its breakdown.
    arm, breakdown = _load(ARM_L), _load(ARM_L_BREAKDOWN)
    batches = arm["batches"]
    llm = {b: trust.collect_observations(table, led, "skeptic_d", b)[0] for b in batches}
    llm_all = [o for b in batches for o in llm[b]]
    d_counts, d_clean = variant_counts(llm_all)
    cell = arm["cells"]["skeptic_d"]
    check("skeptic_d canaries flagged", sum(c for c, _ in d_counts.values()), cell["flagged_buggy"])
    check("skeptic_d canaries", sum(n for _, n in d_counts.values()), cell["buggy"])
    check("skeptic_d clean passed", d_clean, (cell["clean"] - cell["flagged_clean"], cell["clean"]))
    check("skeptic_d per variant", {f"{b} {t}": [c, n] for (b, t), (c, n) in sorted(d_counts.items())},
          {k: [v["hits"], v["of"]] for k, v in sorted(breakdown["recall"]["by_class_and_tier"].items())})

    # tripwire_v1: the locked test's records in the ledger, against the locked result file.
    test = _load(TRIPWIRE_TEST)
    t_obs, _ = trust.collect_observations(table, led, tripwire_ledger.ROLE, test["batch"])
    t_counts, t_clean = variant_counts(t_obs)
    per_class = {}
    for (bug, _), (c, n) in t_counts.items():
        a, b = per_class.get(bug, (0, 0))
        per_class[bug] = (a + c, b + n)
    check("tripwire_v1 per class (any flag)", {b: list(v) for b, v in sorted(per_class.items())},
          {b: [v["any_flag"]["successes"], v["any_flag"]["n"]] for b, v in sorted(test["per_class"].items())})
    check("tripwire_v1 clean passed", list(t_clean),
          [test["headline"]["specificity"]["successes"], test["headline"]["specificity"]["n"]])

    # union, per run: ceiling-ext from the ledger (both roles); task-dev-2 with the dev records from disk.
    union_all, union_counts = [], {}
    for batch in batches:
        if batch == "ceiling-ext":
            tripwire_obs, _ = trust.collect_observations(table, led, tripwire_ledger.ROLE, batch)
            source = TRIPWIRE_TEST_CEILING_EXT
        else:
            source = TRIPWIRE_DEV_TASK_DEV_2
            check(f"tripwire version of the {batch} dev records", _load(source)["tripwire_version"],
                  test["tripwire_version"])
            tripwire_obs, missing = records_as_observations(llm[batch], records_folder, test["tripwire_version"])
            if missing:
                raise ValueError(f"{batch}: {len(missing)} runs have no tripwire record")
        result = _load(source)
        tw_counts, tw_clean = variant_counts(tripwire_obs)
        check(f"tripwire on {batch} (any flag)", [sum(c for c, _ in tw_counts.values()),
                                                  sum(n for _, n in tw_counts.values())],
              [result["any_flag"]["recall"]["successes"], result["any_flag"]["recall"]["n"]])
        check(f"tripwire on {batch} clean passed", list(tw_clean),
              [result["headline"]["specificity"]["successes"], result["headline"]["specificity"]["n"]])
        union, counts = trust.union_observations(tripwire_obs, llm[batch])
        union_counts[batch] = counts
        union_all += union
    u_counts, u_clean = variant_counts(union_all)
    return {
        "checks": checks,
        "skeptic_d": {"counts": d_counts, "clean": d_clean,
                      "source": f"locked ceiling result, arm L ({', '.join(batches)}; {ARM_L.name}, "
                                f"{ARM_L_BREAKDOWN.name}), first audit per run from the ledger"},
        "tripwire_v1": {"counts": t_counts, "clean": t_clean,
                        "source": f"locked tripwire test ({test['batch']}, {TRIPWIRE_TEST.name}), role "
                                  f"{tripwire_ledger.ROLE} in the ledger"},
        "union": {"counts": u_counts, "clean": u_clean, "joined": union_counts,
                  "source": "per run, flag if either: ceiling-ext (both from the ledger) and task-dev-2 (skeptic_d "
                            "from the ledger, tripwire records of the dev loop on disk; tripwire development data)"},
    }


def rates_table(measured: dict) -> list[dict]:
    """One row per reviewer x support x class (plus specificity), with its counts, rate and where it comes from."""
    rows = []
    for name in ("skeptic_d", "tripwire_v1", "union"):
        entry = measured[name]
        for population in ("real_guard_untested", "real_guard_tested"):
            for bug, row in class_rates(entry["counts"], trust.support_variants(population)).items():
                rows.append({"reviewer": name, "support": population, "class": bug,
                             "variants": row["variants"], "caught": row["caught"], "n": row["n"],
                             "rate": row["rate"], "status": "measured", "source": entry["source"]})
        passed, n = entry["clean"]
        rows.append({"reviewer": name, "support": "all", "class": "specificity", "variants": None, "caught": passed,
                     "n": n, "rate": (1 + passed) / (2 + n), "status": "measured", "source": entry["source"]})
    for name, (se, sp) in ASSUMED.items():
        rows.append({"reviewer": name, "support": "design session", "class": "per class", "variants": None,
                     "caught": None, "n": None, "rate": se, "status": "assumed",
                     "source": "docs/plans/sims/trust_design_sim.py (2026-11-15)"})
        rows.append({"reviewer": name, "support": "design session", "class": "specificity", "variants": None,
                     "caught": None, "n": None, "rate": sp, "status": "assumed",
                     "source": "docs/plans/sims/trust_design_sim.py (2026-11-15)"})
    return rows


def pooled_and_worst(rates: dict[str, dict]) -> dict:
    """The pooled recall (mean of class rates) always beside the worst class (plan trap 1)."""
    worst = min(rates, key=lambda b: (rates[b]["rate"], b))
    return {"pooled": float(np.mean([r["rate"] for r in rates.values()])), "worst_class": worst,
            "worst": rates[worst]["rate"]}


def run(reps: int, draws: int, out: Path = OUT_PATH, rq4: bool = True) -> dict:
    started = time.perf_counter()
    led, table = ledger.Ledger(), sealed.SealedTable()
    measured = measured_counts(led, table, tripwire_ledger.RECORDS_DIR)
    reviewers = {}
    for name in ("skeptic_d", "tripwire_v1", "union"):
        sp_passed, sp_n = measured[name]["clean"]
        sp = (1 + sp_passed) / (2 + sp_n)
        for population, label in (("real_guard_untested", "B09_in"), ("real_guard_tested", "B09_out")):
            rates = class_rates(measured[name]["counts"], trust.support_variants(population))
            reviewers[f"{name}_{label}"] = {
                "se": [r["rate"] for r in rates.values()], "classes": list(rates), "sp": sp,
                "status": "measured", "source": measured[name]["source"], **pooled_and_worst(rates)}
    for name, (se, sp) in ASSUMED.items():
        reviewers[name] = {"se": se, "classes": None, "sp": sp, "status": "assumed",
                           "source": "docs/plans/sims/trust_design_sim.py"}
    gate, seed = [], 0
    for name, spec in reviewers.items():
        gate += gate_grid(name, spec["se"], spec["sp"], reps, draws, seed, spec["status"])
        seed += 1000
    for name, k in (("union_B09_out", 0), ("union_B09_out", 2)):
        spec = reviewers[name]
        gate.append({"reviewer": name, "rates": spec["status"], "n_per_class": 20, "n_clean": 120, "n_real": 60,
                     "pi_true": 0.0, "mix": "uniform", "leak": f"{k} of 100",
                     **simulate(spec["se"], [1.0] * len(spec["se"]), spec["sp"], 20, 120, 60, 0.0, 50_000 + k,
                                reps, draws, leak=(k, 100))})
    rq4_rows = []
    if rq4:
        hidden = trust.support_variants("hidden_truth")
        for name in ("union", "skeptic_d"):
            rates = class_rates(measured[name]["counts"], hidden)
            sp_passed, sp_n = measured[name]["clean"]
            rq4_rows += rq4_grid(f"{name}_hidden_truth", [r["rate"] for r in rates.values()],
                                 (1 + sp_passed) / (2 + sp_n), list(rates).index("B09"), reps, draws,
                                 60_000 + 1000 * len(rq4_rows), "measured")
        for name in ("union_all10_B09_in", "llm_all10"):
            se, sp = ASSUMED[name]
            rq4_rows += rq4_grid(name, se, sp, 9, reps, draws, 90_000 + 1000 * len(rq4_rows), "assumed")
    result = {
        "status": "design only: no threshold chosen on these numbers, nothing locked (mission_4_1_trust.md trap 9)",
        "settings": {"reps": reps, "draws": draws, "tau": TAU, "gate_percentile": GATE_PCT,
                     "true_rate": "posterior mean Beta(1 + caught, 1 + missed) of the measured counts"},
        "parity_checks": measured["checks"],
        "union_joined": measured["union"]["joined"],
        "reviewers": {k: {key: v for key, v in spec.items()} for k, spec in reviewers.items()},
        "rates": rates_table(measured),
        "gate": gate, "rq4": rq4_rows,
        "seconds": time.perf_counter() - started,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=list), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.rq4_power", description=__doc__.split("\n")[0])
    parser.add_argument("--reps", type=int, default=1000)
    parser.add_argument("--draws", type=int, default=1000)
    parser.add_argument("--no-rq4", action="store_true", help="gate rows only")
    args = parser.parse_args(argv)
    result = run(args.reps, args.draws, rq4=not args.no_rq4)
    for line in result["parity_checks"]:
        print("parity", line)
    for name, spec in result["reviewers"].items():
        if spec["status"] == "measured":
            print(f"{name}: pooled {spec['pooled']:.3f}, worst {spec['worst_class']} {spec['worst']:.3f}, "
                  f"specificity {spec['sp']:.3f} ({spec['status']})")
    print(f"wrote {OUT_PATH.relative_to(ROOT)}: {len(result['gate'])} gate rows, {len(result['rq4'])} rq4 rows, "
          f"{result['seconds']:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
