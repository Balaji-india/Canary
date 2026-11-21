"""Mission 4.3 step 2: the drift-chart design simulation as tested code, re-run with measured reviewer rates.

Why: the design session (docs/plans/sims/drift_chart_sim.py, 2026-11-15, committed before its first run) sized the
sentinel set and checked the fresh-run charts with ASSUMED reviewer rates. This module runs the same simulation
through `canary.drift.fire_matrix`, the one implementation of the chart rules, so the simulated operating
characteristics cannot differ from what the chart does. It then re-runs it under the rule written in
docs/plans/mission_4_3_drift.md, amendment 1 (measured rates, a base-level random effect at verdict ICC 0.1, 0.2 and
0.4, the Mission 4.4 pace), and prints what the plan needs and did not have.

Two parts, in this order:
  1. Reproduction. The assumed rates at ICC 0 give, draw for draw, the design script's numbers (same seed, same
     random-number order), so its choice (60 runs, 20 a day, W = 3, standard tails) must come out again. If it does
     not, nothing else is run and the command exits 1.
  2. Measured. Every rate comes from a locked or committed result, read through `eval.rq4_power.measured_counts`
     (which reads through `canary.trust`, the only module that joins with the sealed table, and checks every count
     against its locked result file). Only analysed batches are read: arm L (task-dev-2, ceiling-ext) and
     tripwire-test-1. Arm R (open) is never read. Anything not measured is labelled "assumed".

Design only: the selection rule decides the sentinel size by code, and the student is told if it differs from the
decided 60 runs and 20 a day before any sentinel call (plan step 2). No threshold is changed here (trap 10).

Run: python -m eval.drift_power [--campaigns 4000]   (writes eval/results/drift/power.json)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from scipy import integrate
from scipy.stats import beta as beta_dist
from scipy.stats import binom, norm

from canary import drift

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"
OUT_PATH = RESULTS / "drift" / "power.json"
DESIGN_JSON = ROOT / "docs" / "plans" / "sims" / "drift_chart_sim.json"
ARM_L = RESULTS / "ceiling" / "arm_L.json"
TRIPWIRE_ON = {"ceiling-ext": RESULTS / "tripwires" / "test_ceiling-ext.json",
               "task-dev-2": RESULTS / "tripwires" / "dev_task-dev-2.json"}

# The design script's settings, unchanged (drift_chart_sim.py).
SEED = 4303
CAMPAIGNS = 4000
QUIET_DAYS, LEAD, AFTER = 30, 5, 14
SIZES, SLICES, SPANS = (20, 40, 60), (6, 10, 20), (3, 5, 7)
MODELS = ("independent", "sticky")
CHANGE_NAMES = ("none", "drop", "collapse_030", "pass_all", "flag_all", "spec_drop")
FRESH_WINDOW = 20
DESIGN_CHOICE = {"N": 60, "k": 20, "W": 3, "tails": "standard"}

# Amendment 1 (mission_4_3_drift.md): the base effect and its layout.
STUDY_ICCS = (0.1, 0.2, 0.4)          # as the ceiling design (eval/ceiling_power.py STUDY_ICCS)
ALL_ICCS = (0.0,) + STUDY_ICCS        # a design qualifies only if it qualifies at every one of these
PER_BASE = 4                          # sentinel: at most 4 runs per base (plan 2.2); fresh: 4 clones per base (4.4)
BANK_BASES = 17                       # pool 3 has at least 17 bases (mission_4_2_hidden_truth.md section 2a)
BANK_RULE_RUNS, BANK_RULE_MORE_THAN = 20, 3   # mission_4_2_hidden_truth.md section 6: "more than 3 of 20 changed"


@dataclass(frozen=True)
class Reviewer:
    """What one simulation is run with. `class_rates` are the LLM's per-class flag rates on the sentinel's buggy half
    (N/20 runs per class, in this order); `sp` its specificity; `eps` the sticky model's flip rate per re-ask;
    `union_fa` and `union_miss` the fresh charts' rates; `changes` maps each change to (class rates, false-alarm
    rate) after it."""
    name: str
    status: str                      # "assumed" or "measured"
    classes: tuple[str, ...]
    class_rates: tuple[float, ...]
    sp: float
    eps: float
    union_fa: float
    union_miss: float
    supported_classes: int
    clean_per_day: int
    canaries_per_day: int
    changes: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)


def assumed_reviewer() -> Reviewer:
    """The design session's assumed rates and changes, exactly as drift_chart_sim.py wrote them."""
    good, b06, b09, sp = 0.94, 0.05, 0.17, 0.98
    rates = (good,) * 8 + (b06, b09)
    changes = {
        "none": (rates, 1 - sp),
        "drop": ((0.7225,) * 8 + (b06, b09), 1 - sp),
        "collapse_030": ((0.35,) * 8 + (b06, b09), 1 - sp),
        "pass_all": ((0.0,) * 10, 0.0),
        "flag_all": ((1.0,) * 10, 1.0),
        "spec_drop": (rates, 0.10),
    }
    return Reviewer("assumed", "assumed", tuple(f"c{i}" for i in range(8)) + ("B06", "B09"), rates, sp, 0.05,
                    1 - sp, 0.03, 9, 15, 20, changes, {"all": "docs/plans/sims/drift_chart_sim.py (2026-11-15)"})


def proportional_factors() -> dict[str, float]:
    """Amendment 1: a measured reviewer's drop and collapse keep the design's size as a ratio of the mean recall
    (0.600 / 0.774 and 0.302 / 0.774), applied to every class."""
    a = assumed_reviewer()
    before = float(np.mean(a.class_rates))
    return {name: float(np.mean(a.changes[name][0])) / before for name in ("drop", "collapse_030")}


def measured_reviewer(llm_classes: dict[str, tuple[int, int]], llm_clean: tuple[int, int],
                      repeat: tuple[int, int], union_classes: dict[str, tuple[int, int]],
                      union_clean: tuple[int, int], sources: dict) -> Reviewer:
    """Amendment 1, from counts. Every rate is the posterior mean Beta(1 + successes, 1 + failures), as in
    eval/rq4_power.py. `llm_classes` {class: (caught, n)} over both tiers (the sentinel draws both);
    `llm_clean` (passed, n); `repeat` (verdicts changed, runs asked again); `union_classes` over the supported
    classes; `union_clean` (passed, n)."""
    def mean(s: int, n: int) -> float:
        return (1 + s) / (2 + n)

    classes = tuple(sorted(llm_classes))
    rates = tuple(mean(*llm_classes[c]) for c in classes)
    sp = mean(*llm_clean)
    eps = mean(*repeat)
    union_rates = [mean(*union_classes[c]) for c in sorted(union_classes)]
    union_fa = 1 - mean(*union_clean)
    f = proportional_factors()
    changes = {
        "none": (rates, 1 - sp),
        "drop": (tuple(r * f["drop"] for r in rates), 1 - sp),
        "collapse_030": (tuple(r * f["collapse_030"] for r in rates), 1 - sp),
        "pass_all": ((0.0,) * len(rates), 0.0),
        "flag_all": ((1.0,) * len(rates), 1.0),
        "spec_drop": (rates, 0.10),
    }
    return Reviewer("measured", "measured", classes, rates, sp, eps, union_fa, 1 - float(np.mean(union_rates)),
                    len(union_rates), 12, 18, changes, sources)


# ---- Draws: plain (ICC 0, the design script's exact random-number order) or with a base effect ------------------

def _draw(rng, shape, p, shift=None, scale=1.0):
    """Bernoulli(p). Without `shift`: rng.random(shape) < p, as the design script. With a base effect: a latent
    normal sqrt(icc) * u_base + sqrt(1 - icc) * e is below Phi^-1(p), so the marginal rate is still p and runs of one
    base move together (verdict ICC on the latent scale, as eval/ceiling_power.py)."""
    if shift is None:
        return rng.random(shape) < p
    threshold = norm.ppf(np.clip(p, 0.0, 1.0))
    return shift + scale * rng.standard_normal(shape) < threshold


def _base_shifts(rng, campaigns: int, runs: int, icc: float):
    """Two independent base effects per run (flag propensity, flip propensity), PER_BASE runs per base in a random
    layout; None at ICC 0 (no random numbers drawn, so ICC 0 is the design script draw for draw)."""
    if icc == 0.0:
        return None, None, 1.0
    bases = runs // PER_BASE + (runs % PER_BASE > 0)
    layout = np.argsort(rng.random((campaigns, runs)), axis=1) // PER_BASE
    rows = np.arange(campaigns)[:, None]
    u = rng.standard_normal((campaigns, bases))[rows, layout] * np.sqrt(icc)
    v = rng.standard_normal((campaigns, bases))[rows, layout] * np.sqrt(icc)
    return u, v, float(np.sqrt(1 - icc))


def sentinel_counts(rng, rev: Reviewer, model: str, change: str, n: int, k: int, icc: float = 0.0,
                    campaigns: int = CAMPAIGNS):
    """Flips per review day for the buggy and the clean half, and the opening-pass baselines (campaigns x days)."""
    half, per, kb = n // 2, n // 20, k // 2
    if len(rev.class_rates) != 10:
        raise ValueError(f"the sentinel's buggy half has N/20 runs for each of 10 classes; got "
                         f"{len(rev.class_rates)} class rates")
    base_rates = np.repeat(np.asarray(rev.class_rates, float), per)
    old_fa = 1 - rev.sp
    new_rates, new_fa = rev.changes[change]
    new_b = np.repeat(np.asarray(new_rates, float), per)
    days = QUIET_DAYS if change == "none" else LEAD + AFTER
    c = campaigns
    u, v, scale = _base_shifts(rng, c, n, icc)
    ub, uc = (None, None) if u is None else (u[:, :half], u[:, half:])
    vb, vc = (None, None) if v is None else (v[:, :half], v[:, half:])
    ref_b = _draw(rng, (c, half), base_rates, ub, scale)
    ref_c = _draw(rng, (c, half), old_fa, uc, scale)
    if model == "independent":
        f0_b = (_draw(rng, (c, half), base_rates, ub, scale) != ref_b).sum(axis=1)
        f0_c = (_draw(rng, (c, half), old_fa, uc, scale) != ref_c).sum(axis=1)
    else:
        f0_b = _draw(rng, (c, half), rev.eps, vb, scale).sum(axis=1)
        f0_c = _draw(rng, (c, half), rev.eps, vc, scale).sum(axis=1)
    order_b = np.argsort(rng.random((c, half)), axis=1)
    order_c = np.argsort(rng.random((c, half)), axis=1)
    rows = np.arange(c)[:, None]
    late_b, late_c = ref_b.copy(), ref_c.copy()          # sticky model: some runs change their verdict for good
    constant = change in ("pass_all", "flag_all")
    if constant:
        late_b[:], late_c[:] = bool(new_b.min() == 1.0), new_fa == 1.0
    else:
        if np.any(new_b != base_rates):
            loss = np.where(base_rates > 0, 1 - new_b / np.where(base_rates > 0, base_rates, 1.0), 0.0)
            late_b &= ~(rng.random((c, half)) < loss)
        if new_fa != old_fa:
            late_c |= rng.random((c, half)) < (new_fa - (1 - rev.sp)) / rev.sp
    flips_b, flips_c = np.zeros((c, days), dtype=int), np.zeros((c, days), dtype=int)
    for day in range(days):
        after = change != "none" and day >= LEAD
        pos = (day * kb + np.arange(kb)) % half
        ib, ic = order_b[:, pos], order_c[:, pos]
        sb = None if ub is None else ub[rows, ib]
        sc = None if uc is None else uc[rows, ic]
        if model == "independent":
            now_b = _draw(rng, (c, kb), (new_b if after else base_rates)[ib], sb, scale)
            now_c = _draw(rng, (c, kb), new_fa if after else old_fa, sc, scale)
        else:
            noise = 0.0 if (after and constant) else rev.eps
            fb = None if vb is None else vb[rows, ib]
            fc = None if vc is None else vc[rows, ic]
            now_b = (late_b if after else ref_b)[rows, ib] ^ _draw(rng, (c, kb), noise, fb, scale)
            now_c = (late_c if after else ref_c)[rows, ic] ^ _draw(rng, (c, kb), noise, fc, scale)
        flips_b[:, day] = (now_b != ref_b[rows, ib]).sum(axis=1)
        flips_c[:, day] = (now_c != ref_c[rows, ic]).sum(axis=1)
    return flips_b, flips_c, f0_b, f0_c


def first_fire(counts: np.ndarray, f0: np.ndarray, n0: int, m: int, span: int, tails, start: int) -> dict:
    """First day (1 = the first slice from `start`) each rule fires, inf if never; through `drift.fire_matrix`."""
    fired = drift.fire_matrix(counts, n0, f0, m, span, tails)
    out = {}
    for name in drift.RULES:
        f = fired[name][:, start:]
        out[name] = np.where(f.any(axis=1), f.argmax(axis=1) + 1.0, np.inf)
    return out


def share_by(first: np.ndarray, day: int) -> float:
    return float((first <= day).mean())


def sentinel_study(rng, rev: Reviewer, icc: float = 0.0, campaigns: int = CAMPAIGNS,
                   sizes=SIZES, slices=SLICES, spans=SPANS) -> tuple[list[dict], dict]:
    """Every candidate under both models and every change, at one ICC: (rows, worst case per candidate)."""
    rows, table = [], {}
    for n in sizes:
        for k in slices:
            data = {(model, change): sentinel_counts(rng, rev, model, change, n, k, icc, campaigns)
                    for model in MODELS for change in CHANGE_NAMES}
            for span in spans:
                for tails_name, tails in drift.TAILS.items():
                    cand = {"N": n, "k": k, "W": span, "tails": tails_name}
                    worst = {"quiet_30": 0.0, "pass_all_2": 1.0, "flag_all_2": 1.0, "drop_7": 1.0}
                    for (model, change), (fb, fc, f0b, f0c) in data.items():
                        start = 0 if change == "none" else LEAD
                        per_rule = {}
                        for half_name, counts, f0 in (("buggy", fb, f0b), ("clean", fc, f0c)):
                            for rule, first in first_fire(counts, f0, n // 2, k // 2, span, tails, start).items():
                                per_rule[f"{half_name}_{rule}"] = first
                        any_rule = np.minimum.reduce(list(per_rule.values()))
                        rows.append({**cand, "icc": icc, "model": model, "change": change,
                                     "alarm_by_day": {str(d): share_by(any_rule, d) for d in (1, 2, 3, 5, 7, 14, 30)
                                                      if d <= (QUIET_DAYS if change == "none" else AFTER)},
                                     "by_rule_day2": {name: share_by(f, 2) for name, f in per_rule.items()},
                                     "by_rule_day7": {name: share_by(f, 7) for name, f in per_rule.items()}})
                        if change == "none":
                            worst["quiet_30"] = max(worst["quiet_30"], share_by(any_rule, 30))
                        elif change in ("pass_all", "flag_all"):
                            worst[f"{change}_2"] = min(worst[f"{change}_2"], share_by(any_rule, 2))
                        elif change == "drop":
                            worst["drop_7"] = min(worst["drop_7"], share_by(any_rule, 7))
                    table[(n, k, span, tails_name)] = worst
    return rows, table


def worst_over(tables: list[dict]) -> dict:
    """The worst case of each criterion over several tables (models are already inside each; this adds ICCs)."""
    out = {}
    for key in tables[0]:
        out[key] = {"quiet_30": max(t[key]["quiet_30"] for t in tables),
                    **{m: min(t[key][m] for t in tables) for m in ("pass_all_2", "flag_all_2", "drop_7")}}
    return out


def choose(table: dict) -> dict:
    """The selection rule of plan section 4 (the design script's docstring), applied by code."""
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
        if not only_a:
            return {"N": None, "how": "no candidate meets (a)", "candidates": len(table)}
        key = max(only_a, key=lambda q: (min(table[q]["pass_all_2"], table[q]["flag_all_2"]), [-x for x in order(q)]))
        how = "no candidate meets (a) and (b); highest worst-case (b) among those meeting (a)"
    n, k, span, tails_name = key
    return {"N": n, "k": k, "W": span, "tails": tails_name, "how": how, "worst_case": table[key],
            "qualify_abc": len(full), "qualify_ab": len(ab), "candidates": len(table),
            "all_worst_cases": [{"N": q[0], "k": q[1], "W": q[2], "tails": q[3], **w} for q, w in sorted(table.items())]}


# ---- The fresh-run charts (the union) ----------------------------------------------------------------------------

def _fresh_counts(rng, rate, shape: tuple[int, int], icc: float, u):
    """Counts of windows of 20 fresh runs. ICC 0: Binomial(20, rate) (the design script). Otherwise runs come in
    blocks of PER_BASE clones of one of the BANK_BASES bases (drawn at random), sharing that base's effect."""
    if icc == 0.0:
        return rng.binomial(FRESH_WINDOW, rate, shape)
    c, windows = shape
    blocks = FRESH_WINDOW // PER_BASE
    pick = rng.integers(0, BANK_BASES, (c, windows, blocks))
    shift = np.repeat(u[np.arange(c)[:, None, None], pick], PER_BASE, axis=2)
    flags = _draw(rng, (c, windows, FRESH_WINDOW), rate, shift, np.sqrt(1 - icc))
    return flags.sum(axis=2)


def fresh_chart(rng, base: float, changed: dict, n0: int, per_day: int, icc: float = 0.0,
                campaigns: int = CAMPAIGNS) -> dict:
    """Windows of 20 fresh runs (clean: false alarms; canaries: misses), W = 3, against a baseline of n0 runs."""
    out = {}
    c = campaigns
    if icc == 0.0:
        u = None
        f0 = rng.binomial(n0, base, c)
    else:   # the baseline: n0 runs spread evenly over the same BANK_BASES bases the fresh clones copy
        u = rng.standard_normal((c, BANK_BASES)) * np.sqrt(icc)
        layout = np.arange(n0) % BANK_BASES
        f0 = _draw(rng, (c, n0), base, u[:, layout], np.sqrt(1 - icc)).sum(axis=1)
    quiet_windows = QUIET_DAYS * per_day // FRESH_WINDOW
    for tails_name, tails in drift.TAILS.items():
        res = {}
        quiet = _fresh_counts(rng, base, (c, quiet_windows), icc, u)
        fires = first_fire(quiet, f0, n0, FRESH_WINDOW, 3, tails, 0)
        res["quiet_30_days"] = share_by(np.minimum.reduce(list(fires.values())), quiet_windows)
        res["quiet_by_rule"] = {name: share_by(first, quiet_windows) for name, first in fires.items()}
        for name, rate in changed.items():
            counts = np.concatenate([_fresh_counts(rng, base, (c, LEAD), icc, u),
                                     _fresh_counts(rng, rate, (c, 20), icc, u)], axis=1)
            fires = first_fire(counts, f0, n0, FRESH_WINDOW, 3, tails, LEAD)
            first = np.minimum.reduce(list(fires.values()))   # in windows
            days = np.ceil(first * FRESH_WINDOW / per_day)
            res[name] = {"alarm_by_day": {str(d): share_by(days, d) for d in (1, 2, 3, 5, 7, 14)},
                         "by_rule_day7": {rule: share_by(np.ceil(f * FRESH_WINDOW / per_day), 7)
                                          for rule, f in fires.items()}}
        res["limits_at_expected_baseline"] = {
            "R1": drift.limit(n0, round(n0 * base), FRESH_WINDOW, tails[0]),
            "R2": drift.limit(n0, round(n0 * base), FRESH_WINDOW, tails[1]),
            "R3_over_60": drift.limit(n0, round(n0 * base), FRESH_WINDOW * 3, tails[0])}
        out[tails_name] = res
    out["chosen_tails"] = "standard" if out["standard"]["quiet_30_days"] <= 0.05 else "strict"
    return out


def fresh_charts(rng, rev: Reviewer, icc: float = 0.0, campaigns: int = CAMPAIGNS) -> dict:
    """The design script's four fresh charts (bank and recalibration baselines), in its order."""
    lost = 1 - (1 - rev.union_miss) * (rev.supported_classes - 1) / rev.supported_classes
    return {
        "clean_bank_160": fresh_chart(rng, rev.union_fa, {"spec_drop": 0.10, "flag_all": 1.0}, 160,
                                      rev.clean_per_day, icc, campaigns),
        "clean_recal_60": fresh_chart(rng, rev.union_fa, {"spec_drop": 0.10, "flag_all": 1.0}, 60,
                                      rev.clean_per_day, icc, campaigns),
        "canary_bank_170": fresh_chart(rng, rev.union_miss, {"class_lost": lost}, 170, rev.canaries_per_day, icc,
                                       campaigns),
        "canary_recal_108": fresh_chart(rng, rev.union_miss, {"class_lost": lost}, 108, rev.canaries_per_day, icc,
                                        campaigns),
    }


# ---- What the plan needs and did not have -----------------------------------------------------------------------

def bank_rule_exact(eps: float, runs: int = BANK_RULE_RUNS, more_than: int = BANK_RULE_MORE_THAN) -> float:
    """Sticky model, no base effect: a run differs between the opening and the closing pass when exactly one of
    the two asks flips, probability 2 eps (1 - eps); P(more than `more_than` of `runs` differ)."""
    return float(binom.sf(more_than, runs, 2 * eps * (1 - eps)))


def bank_rule_predictive(changed: int, asked: int, runs: int = BANK_RULE_RUNS,
                         more_than: int = BANK_RULE_MORE_THAN) -> float:
    """The same, with eps uncertain: averaged over eps ~ Beta(1 + changed, 1 + asked - changed)."""
    a, b = 1 + changed, 1 + asked - changed
    value, _ = integrate.quad(lambda e: bank_rule_exact(e, runs, more_than) * beta_dist.pdf(e, a, b), 0, 1,
                              limit=200)
    return float(value)


def bank_rule_simulated(rng, rev: Reviewer, model: str, icc: float, campaigns: int = CAMPAIGNS) -> float:
    """P(more than 3 of 20 differ between two passes) when nothing changed, with a base effect. The 20 runs: one
    canary per class and 10 clean (amendment 1: the repeat pass's own mix is not read), PER_BASE per base."""
    per_class = np.asarray(rev.class_rates, float)
    rates = np.concatenate([per_class, np.full(BANK_RULE_RUNS - len(per_class), 1 - rev.sp)])
    c = campaigns
    u, v, scale = _base_shifts(rng, c, BANK_RULE_RUNS, icc)
    shape = (c, BANK_RULE_RUNS)
    if model == "independent":
        one, two = _draw(rng, shape, rates, u, scale), _draw(rng, shape, rates, u, scale)
    else:
        one, two = _draw(rng, shape, rev.eps, v, scale), _draw(rng, shape, rev.eps, v, scale)
    return float(((one != two).sum(axis=1) > BANK_RULE_MORE_THAN).mean())


def spread_above(passes: list[tuple[int, int]]) -> dict:
    """Amendment 1, item 7 (finding 14): each pass's changed-verdict count against the 95% Beta-binomial limit for
    its size, from the other passes pooled. Any pass at or beyond its limit: the opening pass is split over two days.
    `passes` are (changed, asked) pairs; the rule needs all three."""
    if len(passes) != 3:
        raise ValueError(f"the rule compares three passes, got {len(passes)}")
    rows = []
    for i, (changed, asked) in enumerate(passes):
        others = [p for j, p in enumerate(passes) if j != i]
        f, n = sum(p[0] for p in others), sum(p[1] for p in others)
        lim = drift.limit(n, f, asked, 0.05)
        rows.append({"pass": i, "changed": changed, "asked": asked, "others": [f, n], "limit_95": lim,
                     "at_or_beyond": changed >= lim})
    return {"rows": rows, "split_opening_pass": any(r["at_or_beyond"] for r in rows)}


def day_to_day(repeat: tuple[int, int]) -> dict:
    """Finding 14: the spread of the flip count over the ceiling-ext sentinel's three passes. Only the ceiling
    repeat pass exists until the RQ4 review week, so `spread_above` waits; the limit a pass of 20 would face if the
    other two passes repeat the ceiling pass's rate is printed for orientation."""
    changed, asked = repeat
    return {"passes": [{"pass": "ceiling repeat pass (arm L)", "runs": asked, "verdict_changed": changed},
                       {"pass": "RQ4 opening", "runs": None, "verdict_changed": None},
                       {"pass": "RQ4 closing", "runs": None, "verdict_changed": None}],
            "status": "not computable: 1 of 3 passes exists (the RQ4 opening and closing passes come in the review "
                      "week); the rule is amendment 1, item 7 (spread_above)",
            "limit_95_if_the_other_two_repeat_this_rate": drift.limit(2 * asked, 2 * changed, asked, 0.05)}


def union_minus_tripwires(union_classes: dict[str, tuple[int, int]]) -> dict:
    """Finding 3: on the runs both reviewers judged (arm L's batches), the union's catches minus the tripwires'
    alone, per class. The tripwire counts come from the committed result files; the runs must be the same."""
    tw: dict[str, list[int]] = {}
    for path in TRIPWIRE_ON.values():
        for bug, row in json.loads(path.read_text(encoding="utf-8"))["per_class"].items():
            got = tw.setdefault(bug, [0, 0])
            got[0] += row["any_flag"]["successes"]
            got[1] += row["any_flag"]["n"]
    out = {}
    for bug, (caught, n) in sorted(union_classes.items()):
        t_caught, t_n = tw.get(bug, (0, 0))
        if t_n != n:
            raise ValueError(f"{bug}: union judged {n} canaries, the tripwire files {t_n}; not the same runs")
        out[bug] = {"union": [caught, n], "tripwires_alone": [t_caught, t_n], "llm_adds": caught - t_caught}
    return out


# ---- Measured inputs ----------------------------------------------------------------------------------------------

def per_class(counts: dict, support: list | None = None) -> dict[str, tuple[int, int]]:
    """{(class, tier): (caught, n)} -> {class: (caught, n)}, over a support of (class, tier) or every variant."""
    out: dict[str, list[int]] = {}
    for (bug, tier), (caught, n) in counts.items():
        if support is not None and (bug, tier) not in support:
            continue
        row = out.setdefault(bug, [0, 0])
        row[0] += caught
        row[1] += n
    return {b: (c, n) for b, (c, n) in sorted(out.items())}


def load_measured() -> tuple[Reviewer, dict]:
    """The measured reviewer of amendment 1 and the counts behind it (read-only; parity-checked by rq4_power)."""
    from canary import ledger, sealed, tripwire_ledger, trust
    from eval import rq4_power

    measured = rq4_power.measured_counts(ledger.Ledger(), sealed.SealedTable(), tripwire_ledger.RECORDS_DIR)
    repeat_cell = json.loads(ARM_L.read_text(encoding="utf-8"))["cells"]["skeptic_d"]["repeat_pass"]
    repeat = (int(repeat_cell["verdict_changed"]), int(repeat_cell["runs"]))
    support = [tuple(v) for v in trust.support_variants("real_guard_tested")]
    llm = per_class(measured["skeptic_d"]["counts"])
    union_supported = per_class(measured["union"]["counts"], support)
    union_all = per_class(measured["union"]["counts"])
    sources = {"llm": measured["skeptic_d"]["source"], "union": measured["union"]["source"],
               "repeat": f"{ARM_L.relative_to(ROOT)} cells.skeptic_d.repeat_pass",
               "pace": "mission_4_4_campaign.md section 9: about 12 fresh clean runs and 18 fresh canaries a day",
               "parity_checks": measured["checks"]}
    rev = measured_reviewer(llm, tuple(measured["skeptic_d"]["clean"]), repeat, union_supported,
                            tuple(measured["union"]["clean"]), sources)
    return rev, {"llm_per_class": llm, "llm_clean": measured["skeptic_d"]["clean"], "repeat": repeat,
                 "union_supported": union_supported, "union_all": union_all, "union_clean": measured["union"]["clean"],
                 "support": support, "union_spec": measured["union"]}


def gate_with_window(union_spec: dict, support: list, reps: int, draws: int) -> list[dict]:
    """Finding 10: how often the gate opens with the rolling window (24 per class, 120 clean), measured union."""
    from eval import rq4_power
    rates = rq4_power.class_rates(union_spec["counts"], support)
    passed, n = union_spec["clean"]
    se, sp = [r["rate"] for r in rates.values()], (1 + passed) / (2 + n)
    rows = []
    for n_real in (60, 120):
        for pi in (0.0, 0.1):
            rows.append({"n_per_class": 24, "n_clean": 120, "n_real": n_real, "pi_true": pi, "mix": "uniform",
                         **rq4_power.simulate(se, [1.0] * len(se), sp, 24, 120, n_real, pi, 43_000 + len(rows),
                                              reps, draws)})
    return rows


# ---- The command ----------------------------------------------------------------------------------------------

def reproduce(campaigns: int = CAMPAIGNS) -> dict:
    """Part 1: the assumed rates at ICC 0, in the design script's random-number order."""
    rng = np.random.default_rng(SEED)
    rev = assumed_reviewer()
    _, table = sentinel_study(rng, rev, 0.0, campaigns)
    choice = choose(table)
    fresh = fresh_charts(rng, rev, 0.0, campaigns)
    design = json.loads(DESIGN_JSON.read_text(encoding="utf-8"))
    same_table = choice["all_worst_cases"] == design["sentinel_choice"]["all_worst_cases"]
    same_fresh = {name: (chart["chosen_tails"], chart["standard"]["quiet_30_days"]) ==
                  (design["fresh_charts"][name]["chosen_tails"], design["fresh_charts"][name]["standard"]["quiet_30_days"])
                  for name, chart in fresh.items()}
    picked = {key: choice.get(key) for key in DESIGN_CHOICE}
    return {"choice": {k: v for k, v in choice.items() if k != "all_worst_cases"},
            "same_choice_as_design": picked == DESIGN_CHOICE and campaigns == CAMPAIGNS,
            "same_worst_case_table_as_design": same_table, "same_fresh_charts_as_design": same_fresh,
            "fresh_chosen_tails": {name: chart["chosen_tails"] for name, chart in fresh.items()}}


def measured_run(rev: Reviewer, inputs: dict, campaigns: int = CAMPAIGNS, reps: int = 1000,
                 draws: int = 1000) -> dict:
    """Part 2: the measured reviewer at every ICC of amendment 1; the choice is the worst case over all of them."""
    rng = np.random.default_rng(SEED + 1)
    tables, rows, fresh = {}, [], {}
    for icc in ALL_ICCS:
        r, tables[icc] = sentinel_study(rng, rev, icc, campaigns)
        rows += r
        fresh[f"{icc:.1f}"] = fresh_charts(rng, rev, icc, campaigns)
    choice = choose(worst_over(list(tables.values())))
    per_icc_choice = {f"{icc:.1f}": {k: v for k, v in choose(t).items() if k != "all_worst_cases"}
                      for icc, t in tables.items()}
    fresh_tails = {name: ("strict" if any(fresh[i][name]["standard"]["quiet_30_days"] > 0.05 for i in fresh)
                          else "standard") for name in fresh["0.0"]}
    chosen = {key: choice.get(key) for key in DESIGN_CHOICE}
    decided = {"N": 60, "k": 20, "W": 3, "tails": "standard"}
    bank = {"exact_sticky_eps_point": bank_rule_exact(inputs["repeat"][0] / inputs["repeat"][1]),
            "exact_sticky_eps_posterior_mean": bank_rule_exact(rev.eps),
            "predictive_sticky_eps_uncertain": bank_rule_predictive(*inputs["repeat"]),
            "simulated": {f"{model} ICC {icc:.1f}": bank_rule_simulated(rng, rev, model, icc, campaigns)
                          for model in MODELS for icc in ALL_ICCS}}
    return {"reviewer": asdict(rev), "inputs": {k: v for k, v in inputs.items() if k != "union_spec"},
            "sentinel_choice": choice, "sentinel_choice_per_icc": per_icc_choice,
            "differs_from_decided_60_20": chosen != decided, "fresh_charts": fresh, "fresh_chosen_tails": fresh_tails,
            "bank_rule_more_than_3_of_20_when_nothing_changed": bank,
            "day_to_day_spread": day_to_day(inputs["repeat"]),
            "union_minus_tripwires_arm_L": union_minus_tripwires(inputs["union_all"]),
            "gate_with_rolling_window": gate_with_window(inputs["union_spec"], inputs["support"], reps, draws),
            "sentinel_rows": rows}


def database_hashes() -> dict[str, str]:
    """SHA-256 of the ledger and the sealed table (amendment 1, item 8: read-only, checked before and after)."""
    from canary import config, sealed
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (config.DB_PATH, sealed.SEALED_DB_PATH) if path.exists()}


def run(campaigns: int = CAMPAIGNS, out: Path = OUT_PATH, reps: int = 1000, draws: int = 1000) -> dict:
    started = time.perf_counter()
    result = {"status": "design only (mission_4_3_drift.md step 2, amendment 1); no threshold changed; the measured "
                        "part is PROVISIONAL, dev rates (arm L), replaced by the rq4-bank-1 run (row 16), never "
                        "the final design choice (amendment 1, item 9)",
              "settings": {"campaigns": campaigns, "seed": SEED, "iccs": list(ALL_ICCS), "per_base": PER_BASE,
                           "bank_bases": BANK_BASES, "tails": drift.TAILS},
              "reproduction": reproduce(campaigns)}
    if result["reproduction"]["same_choice_as_design"]:
        before = database_hashes()
        rev, inputs = load_measured()
        result["measured"] = measured_run(rev, inputs, campaigns, reps, draws)
        after = database_hashes()
        if before != after:
            raise RuntimeError(f"a database changed during a read-only run: {before} -> {after}")
        result["database_sha256_unchanged"] = after
    result["seconds"] = time.perf_counter() - started
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=list), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.drift_power", description=__doc__.split("\n")[0])
    parser.add_argument("--campaigns", type=int, default=CAMPAIGNS)
    parser.add_argument("--reps", type=int, default=1000, help="gate rows (finding 10)")
    parser.add_argument("--draws", type=int, default=1000, help="gate rows (finding 10)")
    args = parser.parse_args(argv)
    result = run(args.campaigns, reps=args.reps, draws=args.draws)
    rep = result["reproduction"]
    print("reproduction (assumed rates, ICC 0):", {k: rep["choice"][k] for k in ("N", "k", "W", "tails", "how")})
    print("  same choice as the design:", rep["same_choice_as_design"], "| same worst-case table:",
          rep["same_worst_case_table_as_design"], "| fresh charts:", rep["same_fresh_charts_as_design"])
    if "measured" not in result:
        print("reproduction FAILED: the measured run was not started")
        return 1
    m = result["measured"]
    ch = m["sentinel_choice"]
    print("measured choice (worst over models and ICC 0, 0.1, 0.2, 0.4):",
          {k: ch.get(k) for k in ("N", "k", "W", "tails", "how", "qualify_ab", "qualify_abc")})
    print("  worst case of the choice:", ch.get("worst_case"))
    print("  differs from the decided 60 runs / 20 a day:", m["differs_from_decided_60_20"])
    print("  fresh charts' tails:", m["fresh_chosen_tails"])
    print("  bank rule P(more than 3 of 20 differ | nothing changed):",
          json.dumps(m["bank_rule_more_than_3_of_20_when_nothing_changed"]))
    print("  day-to-day spread:", m["day_to_day_spread"]["status"])
    print(f"wrote {OUT_PATH.relative_to(ROOT)} in {result['seconds']:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
