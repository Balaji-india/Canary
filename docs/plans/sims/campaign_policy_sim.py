"""Design-time simulation for Mission 4.4 (campaign agent loop), written 2026-11-15 with the plan
`docs/plans/mission_4_4_campaign.md`; not part of the package. Committed BEFORE its first run.

It plays the campaign policy of the plan, one block per review day, against a simulated reviewer, to forecast the
pace and to check that the policy cannot loop. Every rate is an ASSUMPTION (the same ones as trust_design_sim.py
and drift_chart_sim.py): union recall 0.97 on each of the 9 supported classes, specificity 0.98, the baseline
guard tested with 0 weak controls in 100 (leak Beta(1, 101)), about 65 reviews a day of which 20 are the sentinel
slice. Opus rebuilds this in `eval/campaign_power.py` and re-runs it with measured rates.

THE POLICY SIMULATED (plan section 3; first rule that applies, once per review day)
  thin   a supported class has fewer than 12 measuring canaries in the window, or fewer than 60 clean runs
         -> calibration block
  wide   the zero-flag test fails (the gate would stay closed even if 60 real runs were all passed) and the
         rolling window is not full (24 per class, 120 clean) -> calibration block
  weak   the zero-flag test fails and the window is full -> science block, nothing auto-accepted
  else   science block
A calibration block: the day's 45 LLM calls go to fresh clean runs; up to 60 fresh canaries (local, no LLM call
under the lazy union) go to the classes with the fewest in the window. A science block: 61 runs at the configured
mix (30 real, 18 canaries over the 10 classes, 12 clean; 45 LLM calls counting the canaries the tripwires pass).
The gate (Mission 4.1): minimum calibration, reviewer informative in 95% of draws, then the 90th percentile of
worst-class contamination plus the leak at most tau = 0.10. Real runs that pass on a day the gate is open count
as accepted. The sentinel is assumed in control (drift is Mission 4.3's simulation).

WORLDS: "clean" (no real run is buggy), "bugs_5pct" (5% of real runs carry a bug of a supported class),
"weak_class" (as clean, but the union's recall on one supported class is 0.60, not 0.97).
STARTS: "bank" (window filled from the RQ4 bank: 20 canaries per class, 160 clean), "cold" (empty window).

CHECKS FIXED BEFORE THE FIRST RUN (if one fails, the policy in the plan must change and the plan says so)
  C1 no loop: no simulated campaign has more than 4 calibration blocks in a row (4 = the blocks needed to fill
     the whole clean window from nothing at 45 clean reviews a day, plus one).
  C2 from the bank, world "clean": the gate is open on at least 90% of review days.
  C3 from cold, world "clean": the first science block starts by review day 3 in at least 90% of campaigns.
  C4 world "weak_class": the policy does not keep calibrating: on review day 10 at least 90% of campaigns are in
     a science block (with or without auto-accept). How often the "weak" state occurs is reported, not judged.
  C5 world "bugs_5pct", from the bank: the true share of buggy runs among accepted runs is at most tau in at
     least 90% of campaigns.

Run: python docs/plans/sims/campaign_policy_sim.py   (writes campaign_policy_sim.json beside this file)
"""
import json
from collections import deque
from pathlib import Path

import numpy as np

SEED = 4404
CAMPAIGNS, DAYS, DRAWS = 300, 30, 800
CLASSES = 9                        # supported classes (B09 is out of the support; its canaries are not simulated)
SE, SP, TAU = 0.97, 0.98, 0.10
MIN_CLASS, MIN_CLEAN, WIN_CLASS, WIN_CLEAN = 12, 60, 24, 120
LLM_CALLS, CAL_CANARIES = 45, 60   # per day after the sentinel slice; canaries a calibration block can run locally
SCI_REAL, SCI_CANARY, SCI_CLEAN = 30, 18, 12
ZERO_FLAG_REAL = 60
LEAK = (1, 101)                    # Beta parameters of the guard's measured leak (0 weak controls in 100)
WORLDS = {"clean": (0.0, None), "bugs_5pct": (0.05, None), "weak_class": (0.0, 0.60)}
STARTS = ("bank", "cold")


def gate(rng, win_class, win_clean, flags, n_real):
    """Mission 4.1's gate on window counts. Returns (state, 90th percentile of the gate figure or None)."""
    caught = np.array([sum(w) for w in win_class])
    size = np.array([len(w) for w in win_class])
    if size.min() < MIN_CLASS or len(win_clean) < MIN_CLEAN:
        return "thin", None
    worst = int(np.argmin((1 + caught) / (2 + size)))
    se = rng.beta(1 + caught[worst], 1 + size[worst] - caught[worst], DRAWS)
    passed = sum(win_clean)
    sp = rng.beta(1 + passed, 1 + len(win_clean) - passed, DRAWS)
    if (se + sp - 1 > 0).mean() < 0.95:
        return "uninformative", None
    p = rng.beta(1 + flags, 1 + n_real - flags, DRAWS)
    den = se + sp - 1
    prev = np.where(den > 0, np.clip((p + sp - 1) / np.where(den > 0, den, 1), 0, 1), 1.0)
    bad = prev * (1 - se)
    cont = np.where(prev > 0, bad / np.where(bad + (1 - prev) * sp > 0, bad + (1 - prev) * sp, 1), 0.0)
    total = np.minimum(1, cont + rng.beta(*LEAK, DRAWS) / (1 - p))
    q90 = float(np.percentile(total, 90))
    return ("open" if q90 <= TAU else "closed"), q90


def one_campaign(rng, start, prevalence, weak):
    rates = np.full(CLASSES, SE)
    if weak is not None:
        rates[0] = weak
    win_class = [deque(maxlen=WIN_CLASS) for _ in range(CLASSES)]
    win_clean = deque(maxlen=WIN_CLEAN)
    if start == "bank":
        for c in range(CLASSES):
            win_class[c].extend(rng.random(20) < rates[c])
        win_clean.extend(rng.random(160) < SP)
    flags = n_real = accepted = accepted_buggy = 0
    actions, open_days, pointer = [], 0, 0
    for _ in range(DAYS):
        thin = min(len(w) for w in win_class) < MIN_CLASS or len(win_clean) < MIN_CLEAN
        full = min(len(w) for w in win_class) >= WIN_CLASS and len(win_clean) >= WIN_CLEAN
        zero_ok = (not thin) and gate(rng, win_class, win_clean, 0, max(n_real, ZERO_FLAG_REAL))[0] == "open"
        if thin:
            action = "calibrate_thin"
        elif not zero_ok and not full:
            action = "calibrate_wide"
        elif not zero_ok:
            action = "science_weak"
        else:
            action = "science"
        actions.append(action)
        if action.startswith("calibrate"):
            win_clean.extend(rng.random(LLM_CALLS) < SP)
            for _ in range(CAL_CANARIES):
                c = int(np.argmin([len(w) for w in win_class]))      # the class with the fewest in the window
                if all(len(w) >= WIN_CLASS for w in win_class):
                    c = pointer % CLASSES
                win_class[c].append(rng.random() < rates[c])
                pointer += 1
            continue
        win_clean.extend(rng.random(SCI_CLEAN) < SP)
        for _ in range(SCI_CANARY):
            c = pointer % (CLASSES + 1)          # the tenth slot is a B09 canary: outside the support
            pointer += 1
            if c < CLASSES:
                win_class[c].append(rng.random() < rates[c])
        buggy = rng.random(SCI_REAL) < prevalence
        bug_class = rng.integers(0, CLASSES, SCI_REAL)
        flagged = np.where(buggy, rng.random(SCI_REAL) < rates[bug_class], rng.random(SCI_REAL) < 1 - SP)
        flags += int(flagged.sum())
        n_real += SCI_REAL
        state, _ = gate(rng, win_class, win_clean, flags, n_real)
        if state == "open" and action == "science":
            open_days += 1
            accepted += int((~flagged).sum())
            accepted_buggy += int((buggy & ~flagged).sum())
    longest = run = 0
    for a in actions:
        run = run + 1 if a.startswith("calibrate") else 0
        longest = max(longest, run)
    science_days = [i + 1 for i, a in enumerate(actions) if a.startswith("science")]
    weak_days = [i + 1 for i, a in enumerate(actions) if a == "science_weak"]
    return {"longest_calibration_run": longest, "calibration_blocks": sum(a.startswith("calibrate") for a in actions),
            "science_on_day_10": actions[9].startswith("science"), "ever_weak": "science_weak" in actions,
            "first_science_day": science_days[0] if science_days else None,
            "first_weak_day": weak_days[0] if weak_days else None,
            "open_days": open_days, "real_reviewed": n_real, "accepted": accepted, "accepted_buggy": accepted_buggy}


def summarize(rows):
    def col(name):
        return np.array([r[name] if r[name] is not None else np.inf for r in rows], dtype=float)

    accepted, buggy = col("accepted"), col("accepted_buggy")
    share = np.where(accepted > 0, buggy / np.where(accepted > 0, accepted, 1), 0.0)
    q = lambda x, p: float(np.percentile(x, p))
    return {
        "longest_calibration_run_max": int(col("longest_calibration_run").max()),
        "calibration_blocks_mean": float(col("calibration_blocks").mean()),
        "first_science_day": {"median": q(col("first_science_day"), 50), "by_day_3": float((col("first_science_day") <= 3).mean())},
        "science_on_day_10": float(col("science_on_day_10").mean()),
        "ever_in_weak_state": float(col("ever_weak").mean()),
        "gate_open_share_of_days": {"mean": float(col("open_days").mean() / DAYS), "p10": q(col("open_days"), 10) / DAYS},
        "campaigns_open_on_90pct_of_days": float((col("open_days") >= 0.9 * DAYS).mean()),
        "real_reviewed_30_days": {"median": q(col("real_reviewed"), 50)},
        "accepted_30_days": {"p10": q(accepted, 10), "median": q(accepted, 50), "p90": q(accepted, 90)},
        "true_contamination_of_accepted": {"mean": float(share.mean()), "p90": q(share, 90),
                                           "campaigns_at_most_tau": float((share <= TAU).mean())},
    }


def main() -> None:
    rng = np.random.default_rng(SEED)
    out = {"assumed": {"union_recall_supported": SE, "specificity": SP, "leak_beta": LEAK, "llm_calls_after_sentinel": LLM_CALLS,
                       "science_block": [SCI_REAL, SCI_CANARY, SCI_CLEAN], "calibration_canaries": CAL_CANARIES},
           "campaigns": CAMPAIGNS, "days": DAYS, "seed": SEED, "cells": {}}
    for world, (prevalence, weak) in WORLDS.items():
        for start in STARTS:
            rows = [one_campaign(rng, start, prevalence, weak) for _ in range(CAMPAIGNS)]
            out["cells"][f"{world}|{start}"] = summarize(rows)
    cells = out["cells"]
    out["checks"] = {
        "C1_no_loop": max(c["longest_calibration_run_max"] for c in cells.values()) <= 4,
        "C2_bank_clean_open_90pct_of_days": cells["clean|bank"]["gate_open_share_of_days"]["mean"] >= 0.90,
        "C3_cold_science_by_day_3": cells["clean|cold"]["first_science_day"]["by_day_3"] >= 0.90,
        "C4_weak_class_leaves_calibration": min(cells["weak_class|bank"]["science_on_day_10"],
                                                cells["weak_class|cold"]["science_on_day_10"]) >= 0.90,
        "C5_bugs_contamination_at_most_tau": cells["bugs_5pct|bank"]["true_contamination_of_accepted"]["campaigns_at_most_tau"] >= 0.90,
    }
    path = Path(__file__).with_suffix(".json")
    path.write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(out["checks"], indent=1))
    for name, cell in cells.items():
        print(name, json.dumps(cell))
    print("wrote", path)


if __name__ == "__main__":
    main()
