"""Design-time simulation for Mission 4.3 (control chart and drift alarms), written 2026-11-15 with the plan
`docs/plans/mission_4_3_drift.md`; not part of the package. Committed BEFORE its first run, so the rules below
were fixed before any simulated number existed.

Every reviewer rate here is an ASSUMPTION for sizing (the same ones as trust_design_sim.py): LLM alone 0.94 on
eight classes, 0.05 on B06, 0.17 on B09 (mean 0.774); specificity 0.98; union recall 0.97 on the supported
classes; a re-asked run repeats its verdict 19 times in 20. Opus rebuilds this as tested code (`eval/drift_power.py`)
and re-runs it with the rates measured in Mission 5.1 sitting D and on the RQ4 bank.

WHAT IS SIMULATED
-----------------
A. The sentinel chart (the LLM half, paired). A fixed set of N already-reviewed runs, half buggy (N/20 per class)
   and half clean. Once, right after calibration, all N are asked again with the cache bypassed (the opening pass):
   the number of verdicts that differ from the first stored verdict, per half, is the baseline. Then every review
   day starts with a slice of k sentinel runs (k/2 buggy, k/2 clean, in a fixed rotation). The chart counts
   "flips" (verdict now differs from the first stored verdict), separately for the buggy half (a recall chart)
   and the clean half (a specificity chart).
B. The fresh-run charts (the union). Windows of 20 fresh clean runs (false alarms) and windows of 20 fresh
   measuring canaries of the supported classes (misses), as in DESIGN.md section 9.

RULES (fixed here, before the first run)
----------------------------------------
Limits are exact, not normal approximations: for a slice or window of m runs, the limit at tail probability t is
the smallest count c with P(X >= c) <= t, X ~ BetaBinomial(m, 1 + f0, 1 + n0 - f0), where f0 of n0 is the baseline
count (opening pass for the sentinel, the calibration set for the fresh charts). So the limit already carries the
uncertainty of a small baseline. Westgard's sigma levels are kept as tail probabilities: "3 sigma" = 0.00135,
"2 sigma" = 0.0228 (set "standard"); a stricter set (0.0005, 0.01) exists only for the selection rule below.
  R1 (Westgard 1_3s): one slice or window at or beyond the 3-sigma limit.
  R2 (Westgard 2_2s): two slices or windows in a row, each at or beyond the 2-sigma limit.
  R3 (cumulative; stands in for 4_1s and 10_x, which need a centre line that small counts do not have): the count
     summed over the last W slices or windows at or beyond the 3-sigma limit for that many runs.
An alarm is any rule firing on either half.

Two models of how a re-asked run behaves, because the repeat pass (19 of 20) cannot tell them apart:
  "independent": every ask is a fresh draw at the class rate (the noisiest case the data allow).
  "sticky": a run keeps its verdict and each re-ask flips with probability 0.05.
A design must qualify under BOTH.

Changes simulated (from the first slice after 5 quiet days):
  drop          LLM recall 0.77 -> 0.60 (the eight good classes 0.94 -> 0.7225), specificity unchanged
  collapse_030  LLM recall 0.77 -> 0.30 (the eight good classes 0.94 -> 0.35)
  pass_all      the LLM passes everything
  flag_all      the LLM flags everything
  spec_drop     specificity 0.98 -> 0.90

SELECTION RULE FOR THE SENTINEL DESIGN (fixed here, before the first run)
------------------------------------------------------------------------
Candidates: N in {20, 40, 60}; k in {6, 10, 20}; W in {3, 5, 7}; tails standard or strict.
A candidate qualifies if, under both models:
  (a) P(any alarm in 30 quiet review days) <= 0.10;
  (b) P(alarm within 2 review days) >= 0.95 for pass_all and for flag_all;
  (c) P(alarm within 7 review days) >= 0.80 for drop.
Choice: among the candidates that qualify, the fewest sentinel calls a day (k); then the smallest N; then the
smallest W; then standard before strict. If none qualifies, (c) is dropped, the same order is applied to the
candidates meeting (a) and (b), and the plan must say that a drop to 0.60 is not seen reliably within a week. If
none meets (a) and (b), the choice is the candidate meeting (a) with the highest worst-case value of (b), and the
plan says so.

RULE FOR THE FRESH CHARTS (fixed here): window 20 (DESIGN.md section 9), W = 3, standard tails unless
P(any alarm in 30 quiet review days) > 0.05 for that chart, then strict. Pace ASSUMED: 15 fresh clean runs and 20
fresh measuring canaries a review day (the Mission 4.4 plan fixes the mix; re-run with it).

Run: python docs/plans/sims/drift_chart_sim.py   (writes drift_chart_sim.json beside this file)
"""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.stats import betabinom, binom

SEED = 4303
CAMPAIGNS = 4000
QUIET_DAYS, LEAD, AFTER = 30, 5, 14
GOOD, B06, B09, SP = 0.94, 0.05, 0.17, 0.98      # assumed LLM-alone rates
EPS = 0.05                                        # sticky model: a re-ask flips 1 time in 20
UNION_MISS, CLEAN_PER_DAY, CANARY_PER_DAY, WINDOW = 0.03, 15, 20, 20
TAILS = {"standard": (0.00135, 0.0228), "strict": (0.0005, 0.01)}
SIZES, SLICES, SPANS = (20, 40, 60), (6, 10, 20), (3, 5, 7)
MODELS = ("independent", "sticky")
CHANGES = {  # name: (rate of the eight good classes, B06, B09, false-alarm rate), None = constant verdict
    "none": (GOOD, B06, B09, 1 - SP),
    "drop": (0.7225, B06, B09, 1 - SP),
    "collapse_030": (0.35, B06, B09, 1 - SP),
    "pass_all": (0.0, 0.0, 0.0, 0.0),
    "flag_all": (1.0, 1.0, 1.0, 1.0),
    "spec_drop": (GOOD, B06, B09, 0.10),
}


@lru_cache(maxsize=None)
def limits(n0: int, m: int, tail: float) -> np.ndarray:
    """For each baseline count f0 = 0..n0: the smallest c with P(X >= c) <= tail; m + 1 if no count is that rare."""
    out = np.empty(n0 + 1, dtype=int)
    counts = np.arange(m + 1)
    for f0 in range(n0 + 1):
        upper = betabinom.sf(counts - 1, m, 1 + f0, 1 + n0 - f0)  # P(X >= c)
        rare = np.nonzero(upper <= tail)[0]
        out[f0] = rare[0] if len(rare) else m + 1
    return out


def first_fire(counts: np.ndarray, f0: np.ndarray, n0: int, m: int, span: int, tails: tuple, start: int) -> dict:
    """First day (1 = the first slice from `start`) each rule fires; inf if never. `counts` is campaigns x days."""
    t3, t2 = tails
    r1 = counts >= limits(n0, m, t3)[f0][:, None]
    over2 = counts >= limits(n0, m, t2)[f0][:, None]
    r2 = np.zeros_like(r1)
    r2[:, 1:] = over2[:, 1:] & over2[:, :-1]
    total = np.cumsum(counts, axis=1)
    roll = total.copy()
    roll[:, span:] = total[:, span:] - total[:, :-span]
    r3 = roll >= limits(n0, m * span, t3)[f0][:, None]
    r3[:, :span - 1] = False
    out = {}
    for name, fired in (("R1", r1), ("R2", r2), ("R3", r3)):
        fired = fired[:, start:]
        out[name] = np.where(fired.any(axis=1), fired.argmax(axis=1) + 1.0, np.inf)
    return out


def sentinel_counts(rng, model: str, change: str, n: int, k: int):
    """Flips per day for the buggy and the clean half, and the opening-pass baselines. Arrays: campaigns x days."""
    half, per, kb = n // 2, n // 20, k // 2
    base_b = np.array([GOOD] * (8 * per) + [B06] * per + [B09] * per)
    good = np.arange(half) < 8 * per
    new_good, new_b06, new_b09, new_fa = CHANGES[change]
    new_b = np.array([new_good] * (8 * per) + [new_b06] * per + [new_b09] * per)
    days = QUIET_DAYS if change == "none" else LEAD + AFTER
    c = CAMPAIGNS
    ref_b = rng.random((c, half)) < base_b
    ref_c = rng.random((c, half)) < 1 - SP
    if model == "independent":
        f0_b = ((rng.random((c, half)) < base_b) != ref_b).sum(axis=1)
        f0_c = ((rng.random((c, half)) < 1 - SP) != ref_c).sum(axis=1)
    else:
        f0_b = (rng.random((c, half)) < EPS).sum(axis=1)
        f0_c = (rng.random((c, half)) < EPS).sum(axis=1)
    order_b = np.argsort(rng.random((c, half)), axis=1)
    order_c = np.argsort(rng.random((c, half)), axis=1)
    rows = np.arange(c)[:, None]
    # sticky model after the change: some runs change their verdict for good
    late_b, late_c = ref_b.copy(), ref_c.copy()
    constant = change in ("pass_all", "flag_all")
    if change in ("drop", "collapse_030"):
        late_b &= ~(good & (rng.random((c, half)) < 1 - new_good / GOOD))
    elif change == "spec_drop":
        late_c |= rng.random((c, half)) < (new_fa - (1 - SP)) / SP
    elif constant:
        late_b[:], late_c[:] = new_good == 1.0, new_fa == 1.0
    flips_b, flips_c = np.zeros((c, days), dtype=int), np.zeros((c, days), dtype=int)
    for day in range(days):
        after = change != "none" and day >= LEAD
        pos = (day * kb + np.arange(kb)) % half
        ib, ic = order_b[:, pos], order_c[:, pos]
        if model == "independent":
            now_b = rng.random((c, kb)) < (new_b if after else base_b)[ib]
            now_c = rng.random((c, kb)) < (new_fa if after else 1 - SP)
        else:
            noise = 0.0 if (after and constant) else EPS
            now_b = (late_b if after else ref_b)[rows, ib] ^ (rng.random((c, kb)) < noise)
            now_c = (late_c if after else ref_c)[rows, ic] ^ (rng.random((c, kb)) < noise)
        flips_b[:, day] = (now_b != ref_b[rows, ib]).sum(axis=1)
        flips_c[:, day] = (now_c != ref_c[rows, ic]).sum(axis=1)
    return flips_b, flips_c, f0_b, f0_c


def share_by(first: np.ndarray, day: int) -> float:
    return float((first <= day).mean())


def sentinel_study(rng) -> tuple[list[dict], dict]:
    """Every candidate under both models and every change; then the selection rule."""
    rows, table = [], {}
    for n in SIZES:
        for k in SLICES:
            data = {(model, change): sentinel_counts(rng, model, change, n, k)
                    for model in MODELS for change in CHANGES}
            for span in SPANS:
                for tails_name, tails in TAILS.items():
                    cand = {"N": n, "k": k, "W": span, "tails": tails_name}
                    worst = {"quiet_30": 0.0, "pass_all_2": 1.0, "flag_all_2": 1.0, "drop_7": 1.0}
                    for (model, change), (fb, fc, f0b, f0c) in data.items():
                        start = 0 if change == "none" else LEAD
                        per_rule = {}
                        for half, counts, f0 in (("buggy", fb, f0b), ("clean", fc, f0c)):
                            for rule, first in first_fire(counts, f0, n // 2, k // 2, span, tails, start).items():
                                per_rule[f"{half}_{rule}"] = first
                        any_rule = np.minimum.reduce(list(per_rule.values()))
                        row = {**cand, "model": model, "change": change,
                               "alarm_by_day": {str(d): share_by(any_rule, d) for d in (1, 2, 3, 5, 7, 14, 30)
                                                if d <= (QUIET_DAYS if change == "none" else AFTER)},
                               "median_day": (float(np.median(any_rule)) if np.isfinite(np.median(any_rule))
                                              else None),
                               "by_rule_day7": {name: share_by(first, 7) for name, first in per_rule.items()},
                               "by_rule_day2": {name: share_by(first, 2) for name, first in per_rule.items()},
                               "by_rule_day30": ({name: share_by(first, 30) for name, first in per_rule.items()}
                                                 if change == "none" else None)}
                        rows.append(row)
                        if change == "none":
                            worst["quiet_30"] = max(worst["quiet_30"], share_by(any_rule, 30))
                        elif change in ("pass_all", "flag_all"):
                            worst[f"{change}_2"] = min(worst[f"{change}_2"], share_by(any_rule, 2))
                        elif change == "drop":
                            worst["drop_7"] = min(worst["drop_7"], share_by(any_rule, 7))
                    table[(n, k, span, tails_name)] = worst
    return rows, choose(table)


def choose(table: dict) -> dict:
    """The selection rule of the docstring, applied by code."""
    def order(key):
        n, k, span, tails_name = key
        return (k, n, span, tails_name != "standard")

    def a(w): return w["quiet_30"] <= 0.10
    def b(w): return min(w["pass_all_2"], w["flag_all_2"]) >= 0.95
    def c(w): return w["drop_7"] >= 0.80

    full = sorted((key for key, w in table.items() if a(w) and b(w) and c(w)), key=order)
    ab = sorted((key for key, w in table.items() if a(w) and b(w)), key=order)
    if full:
        key, how = full[0], "qualifies on (a), (b) and (c)"
    elif ab:
        key, how = ab[0], "no candidate meets (c); chosen among those meeting (a) and (b)"
    else:
        only_a = [key for key, w in table.items() if a(w)]
        key = max(only_a, key=lambda q: (min(table[q]["pass_all_2"], table[q]["flag_all_2"]), [-x for x in order(q)]))
        how = "no candidate meets (a) and (b); highest worst-case (b) among those meeting (a)"
    n, k, span, tails_name = key
    return {"N": n, "k": k, "W": span, "tails": tails_name, "how": how, "worst_case": table[key],
            "qualify_abc": len(full), "qualify_ab": len(ab), "candidates": len(table),
            "all_worst_cases": [{"N": q[0], "k": q[1], "W": q[2], "tails": q[3], **w} for q, w in sorted(table.items())]}


def fresh_chart(rng, base: float, changed: dict, n0: int, per_day: int) -> dict:
    """A p-chart on windows of 20 fresh runs (clean: false alarms; canaries: misses), W = 3."""
    out = {}
    c = CAMPAIGNS
    f0 = rng.binomial(n0, base, c)
    quiet_windows = QUIET_DAYS * per_day // WINDOW
    for tails_name, tails in TAILS.items():
        res = {}
        quiet = rng.binomial(WINDOW, base, (c, quiet_windows))
        fires = first_fire(quiet, f0, n0, WINDOW, 3, tails, 0)
        res["quiet_30_days"] = share_by(np.minimum.reduce(list(fires.values())), quiet_windows)
        res["quiet_by_rule"] = {name: share_by(first, quiet_windows) for name, first in fires.items()}
        for name, rate in changed.items():
            counts = np.concatenate([rng.binomial(WINDOW, base, (c, LEAD)), rng.binomial(WINDOW, rate, (c, 20))], axis=1)
            fires = first_fire(counts, f0, n0, WINDOW, 3, tails, LEAD)
            first = np.minimum.reduce(list(fires.values()))  # in windows
            days = np.ceil(first * WINDOW / per_day)
            res[name] = {"alarm_by_day": {str(d): share_by(days, d) for d in (1, 2, 3, 5, 7, 14)},
                         "median_day": float(np.median(days)) if np.isfinite(np.median(days)) else None,
                         "by_rule_day7": {rule: share_by(np.ceil(f * WINDOW / per_day), 7) for rule, f in fires.items()}}
        res["limits_at_expected_baseline"] = {
            "R1": int(limits(n0, WINDOW, tails[0])[round(n0 * base)]),
            "R2": int(limits(n0, WINDOW, tails[1])[round(n0 * base)]),
            "R3_over_60": int(limits(n0, WINDOW * 3, tails[0])[round(n0 * base)])}
        out[tails_name] = res
    out["chosen_tails"] = "standard" if out["standard"]["quiet_30_days"] <= 0.05 else "strict"
    return out


def main() -> None:
    rng = np.random.default_rng(SEED)
    rows, choice = sentinel_study(rng)
    fresh = {
        "clean_bank_160": fresh_chart(rng, 1 - SP, {"spec_drop": 0.10, "flag_all": 1.0}, 160, CLEAN_PER_DAY),
        "clean_recal_60": fresh_chart(rng, 1 - SP, {"spec_drop": 0.10, "flag_all": 1.0}, 60, CLEAN_PER_DAY),
        # one supported class lost by the tripwires: union recall 0.97 -> 0.97 * 8 / 9
        "canary_bank_170": fresh_chart(rng, UNION_MISS, {"class_lost": 1 - (1 - UNION_MISS) * 8 / 9}, 170, CANARY_PER_DAY),
        "canary_recal_108": fresh_chart(rng, UNION_MISS, {"class_lost": 1 - (1 - UNION_MISS) * 8 / 9}, 108, CANARY_PER_DAY),
    }
    # The normal-approximation limit of DESIGN.md section 9 at recall 0.97, window 20: what its real tail is.
    p, n = 1 - UNION_MISS, WINDOW
    sigma = (p * (1 - p) / n) ** 0.5
    normal = {}
    for label, z in (("3_sigma", 3), ("2_sigma", 2)):
        max_catches = int(np.floor((p - z * sigma) * n + 1e-9))        # "below the limit" = catches under it
        if (p - z * sigma) * n == max_catches:
            max_catches -= 1
        normal[label] = {"limit": p - z * sigma, "alarm_at_catches_at_most": max_catches,
                         "true_tail": float(binom.cdf(max_catches, n, p))}
    # The ceiling repeat pass as a baseline (1 flip in 20): limits for a 20-run pass, for the plan's cross-check.
    s0 = {tails_name: {"R1_limit_of_20": int(limits(20, 20, tails[0])[1]), "R2_limit_of_20": int(limits(20, 20, tails[1])[1])}
          for tails_name, tails in TAILS.items()}
    out = {"assumed": {"llm_alone": {"eight_classes": GOOD, "B06": B06, "B09": B09}, "specificity": SP,
                       "union_miss_supported": UNION_MISS, "sticky_flip": EPS,
                       "clean_per_day": CLEAN_PER_DAY, "canaries_per_day": CANARY_PER_DAY},
           "campaigns": CAMPAIGNS, "seed": SEED, "tails": TAILS,
           "sentinel_choice": choice, "fresh_charts": fresh,
           "normal_approximation_at_0.97": normal, "repeat_pass_baseline_1_of_20": s0,
           "sentinel_rows": rows}
    path = Path(__file__).with_suffix(".json")
    path.write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in choice.items() if k != "all_worst_cases"}, indent=1))
    for name, chart in fresh.items():
        print(name, "tails:", chart["chosen_tails"], "quiet 30 days:", chart[chart["chosen_tails"]]["quiet_30_days"])
    print("wrote", path)


if __name__ == "__main__":
    main()
