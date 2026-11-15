"""Design-time simulation for Missions 4.1 and 4.2 (written 2026-11-15 with the plans, not part of the package).

It answers two design questions with a synthetic reviewer whose true recall per class and specificity are set by hand:
  gate:  how often does the trust gate open, for a given set of classes the estimate must cover (the "support")?
  rq4:   how wide and how well covered is the prevalence interval, for a given number of audited runs per level?

The true rates below are ASSUMPTIONS for sizing, not measurements. Opus rebuilds this as tested code
(eval/rq4_power.py) and re-runs it with the measured union numbers before any plan is locked.
Run: python docs/plans/sims/trust_design_sim.py  (writes trust_design_sim.json beside this file)
"""
import json
from pathlib import Path

import numpy as np

DRAWS, REPS, TAU, GATE_PCT, LOW, HIGH = 1000, 1000, 0.10, 90, 5, 95


def estimate(rng, caught, n_c, clean_pass, n_clean, flags, n_real, leak=None):
    """Posterior draws of prevalence and contamination: pooled (mean of classes) and worst class."""
    se = rng.beta(1 + caught[:, None], 1 + (n_c - caught)[:, None], (len(caught), DRAWS))
    means = (1 + caught) / (2 + n_c)
    worst = se[int(np.argmin(means))]
    pooled = se.mean(axis=0)
    sp = rng.beta(1 + clean_pass, 1 + n_clean - clean_pass, DRAWS)
    p = rng.beta(1 + flags, 1 + n_real - flags, DRAWS)
    out = {}
    for name, s in (("pooled", pooled), ("worst", worst)):
        den = s + sp - 1
        pi = np.where(den > 0, np.clip((p + sp - 1) / np.where(den > 0, den, 1), 0, 1), 1.0)
        cont = pi * (1 - s) / np.maximum(pi * (1 - s) + (1 - pi) * sp, 1e-12)
        if leak is not None:
            cont = np.minimum(1.0, cont + leak / np.maximum(1 - p, 1e-12))
        out[name] = (pi, cont)
    return out


def simulate(se_true, mix, sp_true, n_c, n_clean, n_real, pi_true, seed, leak_k=None, leak_n=None):
    rng = np.random.default_rng(seed)
    se_true, mix = np.array(se_true), np.array(mix) / np.sum(mix)
    se_mix = float(se_true @ mix)
    p_true = pi_true * se_mix + (1 - pi_true) * (1 - sp_true)
    cont_true = pi_true * (1 - se_mix) / (pi_true * (1 - se_mix) + (1 - pi_true) * sp_true)
    rows = {k: {"open": 0, "cover": 0, "upper_ok": 0, "width": [], "mid": []} for k in ("pooled", "worst")}
    for _ in range(REPS):
        caught = rng.binomial(n_c, se_true)
        clean_pass = rng.binomial(n_clean, sp_true)
        flags = rng.binomial(n_real, p_true)
        leak = rng.beta(1 + leak_k, 1 + leak_n - leak_k, DRAWS) if leak_n else None
        for name, (pi, cont) in estimate(rng, caught, n_c, clean_pass, n_clean, flags, n_real, leak).items():
            lo, hi = np.percentile(pi, [LOW, HIGH])
            r = rows[name]
            r["open"] += np.percentile(cont, GATE_PCT) <= TAU
            r["cover"] += lo <= pi_true <= hi
            r["upper_ok"] += pi_true <= hi
            r["width"].append(hi - lo)
            r["mid"].append(float(np.median(pi)))
    return {"se_mix": se_mix, "contamination_true": cont_true,
            **{name: {"gate_open": r["open"] / REPS, "interval_covers": r["cover"] / REPS,
                      "upper_end_above_truth": r["upper_ok"] / REPS, "mean_width": float(np.mean(r["width"])),
                      "median_estimate": float(np.mean(r["mid"]))} for name, r in rows.items()}}


# Assumed true recalls. "llm": like arm L's counts (development data): 8 classes high, B06 and B09 low.
# "union": tripwires expected to catch the code-level classes and B06 (NOT measured until sitting D); B09 stays the LLM's.
REVIEWERS = {
    "llm_all10": [0.94] * 8 + [0.05, 0.17],
    "union_all10_B09_in": [0.97] * 9 + [0.17],
    "union_B09_out": [0.97] * 9,
    "llm_B06_B09_out": [0.94] * 8,
}
SP = 0.98


def main():
    results = {"settings": {"draws": DRAWS, "reps": REPS, "tau": TAU, "gate_percentile": GATE_PCT, "sp_true": SP,
                            "reviewers": REVIEWERS}, "gate": [], "rq4": []}
    seed = 0
    # Gate: uniform mix of bugs over the support; then the worst case (all bugs of the worst class).
    for name, se in REVIEWERS.items():
        for n_c, n_clean, n_real in ((6, 60, 30), (12, 60, 60), (20, 120, 60), (20, 120, 120), (40, 120, 120)):
            for pi in (0.0, 0.1, 0.3):
                for mix_name, mix in (("uniform", [1] * len(se)), ("worst_class_only", [0] * (len(se) - 1) + [1])):
                    if pi == 0.0 and mix_name != "uniform":
                        continue
                    seed += 1
                    row = simulate(se, mix, SP, n_c, n_clean, n_real, pi, seed)
                    results["gate"].append({"reviewer": name, "n_per_class": n_c, "n_clean": n_clean,
                                            "n_real": n_real, "pi_true": pi, "mix": mix_name, **row})
    # Leak term: B09 out of the support, plus a measured leak of 0 of 100 or 2 of 100 weak controls.
    for k in (0, 2):
        seed += 1
        row = simulate(REVIEWERS["union_B09_out"], [1] * 9, SP, 20, 120, 60, 0.0, seed, leak_k=k, leak_n=100)
        results["gate"].append({"reviewer": "union_B09_out", "n_per_class": 20, "n_clean": 120, "n_real": 60,
                                "pi_true": 0.0, "mix": "uniform", "leak": f"{k} of 100", **row})
    # RQ4 sizing: audited runs per level, calibration 10 or 20 per class and 100 clean.
    for name in ("union_all10_B09_in", "llm_all10"):
        se = REVIEWERS[name]
        for n_c in (10, 20):
            for n_aud in (60, 100, 150, 200):
                for pi in (0.0, 0.1, 0.3, 0.5):
                    for mix_name, mix in (("matched", [1] * 10), ("half_B09", [1] * 9 + [9])):
                        if pi == 0.0 and mix_name != "matched":
                            continue
                        seed += 1
                        row = simulate(se, mix, SP, n_c, 100, n_aud, pi, seed)
                        results["rq4"].append({"reviewer": name, "n_per_class": n_c, "n_clean": 100,
                                               "n_audited": n_aud, "pi_true": pi, "mix": mix_name, **row})
    path = Path(__file__).with_suffix(".json")
    path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print("wrote", path.name, len(results["gate"]), "gate rows,", len(results["rq4"]), "rq4 rows")


if __name__ == "__main__":
    main()
