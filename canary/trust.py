"""Trust statistics: how often the reviewer catches planted bugs and how often it wrongly flags clean runs.

Why Beta posteriors: "3 of 10 caught" and "300 of 1000 caught" are the same rate but not the same knowledge. Starting
from a flat Beta(1, 1), s successes and f failures give Beta(1 + s, 1 + f), whose width shows how much is really known.

Why "caught" means any flag, whichever class it names: Rogan-Gladen (Mission 4.1) corrects the flag rate on real runs,
so recall must be P(flag | bug) for that formula to hold. A flag naming the wrong class may be luck, so `named_right`
is always reported beside it.

Why probes are left out: the adaptive saboteur aims probes at weak spots, so counting them would bias recall downward.

This module reads the sealed table, so it must never be on the reviewer's code path (tests/test_skeptic.py checks).
Code computes every number here; no LLM is involved.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from canary import ledger, sealed
from canary.config import load_yaml
from canary.saboteur import classes as classes_module
from canary.saboteur import impact as impact_module

FLAG = "flag"  # the Skeptic's verdict word. Not imported, so that this module does not depend on the reviewer's code.
DEFAULT_ROLE = "skeptic_a"
INTERVAL_PERCENTILES = (5.0, 95.0)  # docs/DESIGN.md section 7
IMPACT_GROUPS = (impact_module.HARMFUL, impact_module.HARMLESS, impact_module.UNMEASURED)


@dataclass(frozen=True)
class Observation:
    """One reviewed run with its sealed truth. `impact` is set for canaries only."""
    run_id: str
    run_type: str
    bug_id: str | None
    tier: str | None
    impact: str | None
    flagged: bool
    named_class: str | None


@dataclass(frozen=True)
class Posterior:
    """Beta(1 + successes, 1 + failures), starting from a flat prior."""
    successes: int = 0
    failures: int = 0

    @property
    def alpha(self) -> int:
        return 1 + self.successes

    @property
    def beta(self) -> int:
        return 1 + self.failures

    @property
    def n(self) -> int:
        return self.successes + self.failures

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    def interval(self) -> tuple[float, float]:
        low, high = stats.beta.ppf([p / 100 for p in INTERVAL_PERCENTILES], self.alpha, self.beta)
        return float(low), float(high)


@dataclass(frozen=True)
class TrustSummary:
    per_class: dict[str, Posterior]
    overall_recall_mean: float
    overall_recall_interval: tuple[float, float]
    worst_class: str | None  # None until at least one class has been tested
    by_tier: dict[str, Posterior]
    by_impact: dict[str, Posterior]
    named_right: Posterior
    per_class_named_right: dict[str, Posterior]
    specificity: Posterior
    control_specificity: Posterior
    sham_specificity: Posterior
    untested: list[str]
    outside_support: int = 0  # canaries of variants left out by `variants` (counted, not scored)

    @property
    def worst_recall(self) -> Posterior | None:
        return self.per_class[self.worst_class] if self.worst_class else None


def _tally(values: list[bool]) -> Posterior:
    return Posterior(sum(values), len(values) - sum(values))


def overall_recall_draws(per_class: dict[str, Posterior], draws: int, rng: np.random.Generator) -> np.ndarray:
    """Draws of the recall averaged over classes (uniform class mix). Kept separate so Mission 4.1 can reuse them."""
    if not per_class:
        raise ValueError("no bug classes given")
    samples = [rng.beta(p.alpha, p.beta, draws) for p in per_class.values()]
    return np.mean(samples, axis=0)


def prevalence_draws(se: np.ndarray, sp: np.ndarray, flag_rate: np.ndarray) -> np.ndarray:
    """Rogan-Gladen per draw: the share of runs that are buggy, from the flag rate p on them (Mission 4.1).

    prevalence = (p + Sp - 1) / (Se + Sp - 1), clipped to [0, 1]. A draw where Se + Sp - 1 <= 0 (the reviewer is no
    better than chance there) gives 1, the worst case; it is never dropped, since dropping it would hide exactly the
    draws where the reviewer cannot be trusted.
    """
    se, sp, flag_rate = np.broadcast_arrays(np.asarray(se, float), np.asarray(sp, float), np.asarray(flag_rate, float))
    den = se + sp - 1
    safe = np.where(den > 0, den, 1.0)
    return np.where(den > 0, np.clip((flag_rate + sp - 1) / safe, 0.0, 1.0), 1.0)


def contamination_draws(prevalence: np.ndarray, se: np.ndarray, sp: np.ndarray) -> np.ndarray:
    """Per draw, the share of PASSED runs that are buggy (bugs of the catalogued kinds): Bayes on the reviewer's pass.

    contamination = prevalence (1 - Se) / (prevalence (1 - Se) + (1 - prevalence) Sp). It is 0 when the prevalence is
    0, and 1 when nothing can pass (the denominator is 0 with bugs present): no passed run then vouches for anything.
    """
    prevalence, se, sp = np.broadcast_arrays(np.asarray(prevalence, float), np.asarray(se, float),
                                             np.asarray(sp, float))
    buggy_pass = prevalence * (1 - se)
    passed = buggy_pass + (1 - prevalence) * sp
    safe = np.where(passed > 0, passed, 1.0)
    return np.where(prevalence <= 0, 0.0, np.where(passed > 0, buggy_pass / safe, 1.0))


Variant = tuple[str, str]  # (bug class, tier)


def all_variants() -> list[Variant]:
    """Every (class, tier) the bug catalog defines: 10 classes x 2 tiers."""
    return [(bug, tier) for bug in sorted(classes_module.catalog()) for tier in classes_module.TIERS]


def support_exclusions(population: str) -> dict[Variant, str]:
    """The variants a population cannot carry, each with the rule or test that excludes it (config/campaign.yaml,
    trust.support; docs/plans/mission_4_1_trust.md section 2). A variant left out without a named reason is refused."""
    table = load_yaml("campaign.yaml")["trust"]["support"]
    if population not in table:
        raise KeyError(f"no support defined for population {population!r}; known: {sorted(table)}")
    known = set(all_variants())
    found: dict[Variant, str] = {}
    for name, reason in (table[population] or {}).items():
        bug, tier = name.split()
        if (bug, tier) not in known:
            raise ValueError(f"{population}: {name!r} is not a variant of the catalog")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{population}: {name} is left out with no named rule")
        found[(bug, tier)] = reason
    return found


def support_variants(population: str) -> list[Variant]:
    """The (class, tier) variants a population can carry: the catalog minus the named exclusions."""
    excluded = support_exclusions(population)
    return [v for v in all_variants() if v not in excluded]


def real_population(guard_on: bool, guard_tested: bool) -> str:
    """Which support applies to real runs. B09 leaves the support only once the guard is on AND has passed its test
    (decision 2 of the Mission 4.1 plan, confirmed by the student 2026-11-20); until then nothing is auto-accepted."""
    if not guard_on:
        return "real_guard_off"
    return "real_guard_tested" if guard_tested else "real_guard_untested"


def summarize(observations: list[Observation], bug_ids: list[str], draws: int = 5000, seed: int = 0,
              variants: list[Variant] | None = None) -> TrustSummary:
    """Compute every trust number. The seed is fixed by default so that a report can be reproduced exactly.

    An untested class stays in the overall figure at its prior and is listed in `untested`. Averaging 10 flat priors
    gives a narrow-looking interval around 0.5 that reflects no data, so anything printing it must show `untested`.

    `variants` (a support) keeps only canaries of those (class, tier) variants, so for example B06's recall in the
    real-run support comes from subtle canaries alone; the others are counted in `outside_support`.
    """
    measured = [o for o in observations if o.run_type == sealed.CANARY_MEASURE]
    outside = 0
    if variants is not None:
        allowed = set(variants)
        kept = [o for o in measured if (o.bug_id, o.tier) in allowed]
        outside, measured = len(measured) - len(kept), kept
    clean = [o for o in observations if o.run_type in (sealed.CONTROL, sealed.SHAM)]
    unknown = sorted({o.bug_id for o in measured} - set(bug_ids))
    if unknown:
        raise ValueError(f"canaries with bug classes that are not configured: {unknown}")

    per_class = {b: _tally([o.flagged for o in measured if o.bug_id == b]) for b in sorted(bug_ids)}
    tested = [b for b, p in per_class.items() if p.n > 0]
    samples = overall_recall_draws(per_class, draws, np.random.default_rng(seed))
    low, high = np.percentile(samples, INTERVAL_PERCENTILES)

    def passes(kept: list[Observation]) -> Posterior:
        return _tally([not o.flagged for o in kept])

    return TrustSummary(
        per_class=per_class,
        overall_recall_mean=float(np.mean([p.mean for p in per_class.values()])),  # exact, no sampling noise
        overall_recall_interval=(float(low), float(high)),
        worst_class=min(tested, key=lambda b: (per_class[b].mean, b)) if tested else None,
        by_tier={t: _tally([o.flagged for o in measured if o.tier == t]) for t in sorted({o.tier for o in measured})},
        by_impact={g: _tally([o.flagged for o in measured if o.impact == g]) for g in IMPACT_GROUPS},
        named_right=_tally([o.flagged and o.named_class == o.bug_id for o in measured]),
        per_class_named_right={b: _tally([o.flagged and o.named_class == b for o in measured if o.bug_id == b])
                               for b in sorted(bug_ids)},
        specificity=passes(clean),
        control_specificity=passes([o for o in clean if o.run_type == sealed.CONTROL]),
        sham_specificity=passes([o for o in clean if o.run_type == sealed.SHAM]),
        untested=[b for b in per_class if b not in tested],
        outside_support=outside,
    )


GATE_PERCENTILE = 90  # the gate reads the 90th percentile of its figure (mission_4_1_trust.md, section 3; fixed)


def _spread(values: np.ndarray) -> dict:
    low, median, high = np.percentile(values, [INTERVAL_PERCENTILES[0], 50.0, INTERVAL_PERCENTILES[1]])
    return {"mean": float(np.mean(values)), "median": float(median), "interval": [float(low), float(high)]}


def _counts(posterior: Posterior) -> dict:
    return {"successes": posterior.successes, "n": posterior.n, "mean": posterior.mean,
            "interval": list(posterior.interval())}


def estimate_from_posteriors(per_class: dict[str, Posterior], specificity: Posterior, real: Posterior,
                             leak: Posterior | None = None, draws: int = 5000,
                             rng: np.random.Generator | None = None) -> dict:
    """Prevalence and contamination, pooled and worst class, from posteriors alone (Mission 4.1, section 3).

    pooled Se = the mean of the per-class recall draws over the support (untested classes at their flat prior);
    worst Se = the draws of the tested class with the lowest posterior mean, ties by ID. `real` is the flag-rate
    posterior on real runs. The gate figure is min(1, contamination_worst + leak / (1 - p)). The simulation in
    eval/rq4_power.py calls this same function, so the simulation cannot drift from the estimator.
    """
    rng = rng if rng is not None else np.random.default_rng(0)
    if not per_class:
        raise ValueError("no bug classes in the support")
    names = sorted(per_class)
    class_draws = {b: rng.beta(per_class[b].alpha, per_class[b].beta, draws) for b in names}
    sp = rng.beta(specificity.alpha, specificity.beta, draws)
    p = rng.beta(real.alpha, real.beta, draws)
    leak_draws = rng.beta(leak.alpha, leak.beta, draws) if leak is not None else None
    tested = [b for b in names if per_class[b].n > 0]
    worst = min(tested, key=lambda b: (per_class[b].mean, b)) if tested else None
    found: dict = {"worst_class": worst, "untested": [b for b in names if per_class[b].n == 0]}
    for name, se in (("pooled", np.mean([class_draws[b] for b in names], axis=0)),
                     ("worst", class_draws[worst] if worst else None)):
        if se is None:
            found[name] = None
            continue
        prevalence = prevalence_draws(se, sp, p)
        contamination = contamination_draws(prevalence, se, sp)
        found[name] = {"recall": _spread(se), "prevalence": _spread(prevalence),
                       "contamination": {**_spread(contamination),
                                         f"p{GATE_PERCENTILE}": float(np.percentile(contamination, GATE_PERCENTILE))},
                       "p_informative": float(np.mean(se + sp - 1 > 0))}
        found[f"_{name}_contamination"] = contamination
    gate = None
    if worst:
        total = found["_worst_contamination"]
        if leak_draws is not None:
            total = np.minimum(1.0, total + leak_draws / np.maximum(1 - p, 1e-12))
        gate = {"figure": "min(1, contamination_worst + leak / (1 - p))", "percentile": GATE_PERCENTILE,
                "value": float(np.percentile(total, GATE_PERCENTILE)), **_spread(total)}
    found.pop("_pooled_contamination", None)
    found.pop("_worst_contamination", None)
    found["gate_figure"] = gate
    return found


def estimate(observations: list[Observation], real_flags: list[bool], support: list[Variant],
             leak: tuple[int, int] | None = None, draws: int = 5000, seed: int = 0) -> dict:
    """Everything Mission 4.1 section 3 reports, as one record. No threshold is applied here (the gate is sitting 2).

    `observations` are calibration runs (canaries of the support's variants, controls and shams; probes and real runs
    are ignored, as in `summarize`). `real_flags` are the reviewer's verdicts on real runs (True = flagged): flags
    only, never the sealed table, so this side of the estimate cannot see a run's type. `leak` is (weak, of) from the
    guard's test, or None while the guard is untested. Every figure is a draw-based mean, median and 5-95% interval;
    the pooled one is never reported without the worst-class one, the support and the counts (plan trap 1).
    """
    classes = sorted({bug for bug, _ in support})
    summary = summarize(observations, classes, draws, seed, variants=support)
    real = _tally(list(real_flags))
    leak_posterior = Posterior(leak[0], leak[1] - leak[0]) if leak is not None else None
    found = estimate_from_posteriors(summary.per_class, summary.specificity, real, leak_posterior, draws,
                                     np.random.default_rng(seed))
    return {
        "support": [f"{bug} {tier}" for bug, tier in support],
        "per_class": {b: _counts(p) for b, p in summary.per_class.items()},
        "outside_support": summary.outside_support,
        "specificity": _counts(summary.specificity),
        "real_runs": {"flagged": real.successes, "reviewed": real.n},
        "leak": None if leak is None else {"weak": leak[0], "of": leak[1]},
        "draws": draws, "seed": seed,
        "claim": "bugs of the catalogued kinds only",
        **found,
    }


def _measured_only(observations: list[Observation]) -> list[Observation]:
    return [o for o in observations if o.run_type in (sealed.CANARY_MEASURE, sealed.CONTROL, sealed.SHAM)]


def chance_baseline(observations: list[Observation], bug_ids: list[str], draws: int = 5000, seed: int = 0) -> dict:
    """What a reviewer flagging at random, at this reviewer's overall flag rate f, would score.

    Such a reviewer catches each canary with probability f, so any-flag recall alone proves nothing: a reviewer that
    flags everything has recall 1. Right-type chance is given two ways. "Uniform" names one of the classes evenly: f/k.
    "Matched" names classes as often as this reviewer does: f * q_b. Matched is the harder test, since a reviewer that
    always says B01 is automatically "right" on every B01. Intervals draw f from its Beta, then the counts actually
    observed per class, so they show the noise a chance reviewer would have at this sample size.
    """
    measured = _measured_only(observations)
    flagged = [o for o in measured if o.flagged]
    flag_rate = _tally([o.flagged for o in measured])
    named = {b: sum(o.named_class == b for o in flagged) for b in sorted(bug_ids)}
    shares = {b: (named[b] / len(flagged) if flagged else 0.0) for b in named}
    counts = {b: sum(o.run_type == sealed.CANARY_MEASURE and o.bug_id == b for o in measured) for b in named}
    f = len(flagged) / len(measured) if measured else 0.0
    rng = np.random.default_rng(seed)
    f_draws = rng.beta(flag_rate.alpha, flag_rate.beta, draws)
    total = sum(counts.values())
    uniform = 1 / len(named) if named else 0.0

    def interval(hits: np.ndarray) -> list[float]:
        return [float(v) for v in np.percentile(hits, INTERVAL_PERCENTILES)]

    per_class = {}
    any_hits, uniform_hits, matched_hits = np.zeros(draws), np.zeros(draws), np.zeros(draws)
    for bug, n in counts.items():
        any_b = rng.binomial(n, f_draws)
        uniform_b = rng.binomial(n, f_draws * uniform)
        matched_b = rng.binomial(n, f_draws * shares[bug])
        any_hits, uniform_hits, matched_hits = any_hits + any_b, uniform_hits + uniform_b, matched_hits + matched_b
        per_class[bug] = {
            "n": n, "any_flag": f, "right_type_uniform": f * uniform, "right_type_matched": f * shares[bug],
            "any_flag_interval": interval(any_b / n) if n else None,
            "right_type_matched_interval": interval(matched_b / n) if n else None,
        }
    # The expected pooled rate weights each class by its canaries, like the observed pooled rate it sits beside.
    matched_pooled = sum(counts[b] * f * shares[b] for b in counts) / total if total else 0.0
    return {
        "flag_rate": f, "flagged": len(flagged), "reviewed": len(measured), "named_share": shares,
        "per_class": per_class,
        "overall": {
            "any_flag": f, "right_type_uniform": f * uniform, "right_type_matched": matched_pooled,
            "any_flag_interval": interval(any_hits / total) if total else None,
            "right_type_uniform_interval": interval(uniform_hits / total) if total else None,
            "right_type_matched_interval": interval(matched_hits / total) if total else None,
        },
    }


def discrimination(summary: TrustSummary, draws: int = 5000, seed: int = 0) -> dict | None:
    """Does the reviewer flag buggy runs more than clean ones? Unlike the flag rate, this ignores the batch's mix.

    Youden's J = recall + specificity - 1 = recall - false-alarm rate. It is 0 for any reviewer that cannot tell the
    two apart, however often it flags. Tested classes only, since an untested class would add a made-up 0.5.

    Recall is pooled here, one Beta over all canaries, so both sides have one prior. Averaging ten per-class posteriors
    shrinks recall ten times against specificity's once: a flag-everything reviewer then scored -0.07, looking worse
    than chance purely because of the priors. `observed` is the same figure from the raw counts.
    """
    tested = [p for p in summary.per_class.values() if p.n > 0]
    if not tested or summary.specificity.n == 0:
        return None
    recall = Posterior(sum(p.successes for p in tested), sum(p.failures for p in tested))
    rng = np.random.default_rng(seed)
    j = rng.beta(recall.alpha, recall.beta, draws) + rng.beta(summary.specificity.alpha, summary.specificity.beta, draws) - 1
    low, high = np.percentile(j, INTERVAL_PERCENTILES)
    observed = recall.successes / recall.n + summary.specificity.successes / summary.specificity.n - 1
    return {"observed_j": observed, "youden_j": float(np.mean(j)), "interval": [float(low), float(high)],
            "p_recall_above_false_alarm": float(np.mean(j > 0))}


def collect_failures(table: sealed.SealedTable, led: ledger.Ledger, role: str = DEFAULT_ROLE,
                     batch: str | None = None) -> dict:
    """Where each sealed run ended up, per type. Audit failures are kept apart from crashed experiments.

    This exists because a failed reply is not an observation: if the reviewer failed more often on canaries, recall
    would be measured on the easier remainder and nothing in the recall figures would show it.
    Returns {run type: counts} and `unreviewed`, the canaries per bug class with no opinion despite a working run.
    """
    entries = led.entries()
    ran = {e.payload["run_id"]: e.payload.get("run_status") for e in entries if e.status == ledger.RAN and "run_id" in e.payload}
    audited = {e.payload["run_id"] for e in entries if e.status == ledger.AUDITED and e.payload.get("role") == role}
    failed: dict[str, list[str]] = {}
    for e in entries:
        if e.status == ledger.AUDIT_FAILED and e.payload.get("role") == role:
            failed.setdefault(e.payload["run_id"], []).append(e.payload["kind"])
    groups: dict[str, dict] = {}
    unreviewed: dict[str, int] = {}
    for truth in table.all():
        if batch is not None and truth.details.get("batch") != batch:
            continue
        row = groups.setdefault(truth.run_type, {"sealed": 0, "crashed": 0, "not_recorded": 0, "audited": 0,
                                                 "failed_then_recovered": 0, "never_reviewed_failed": 0,
                                                 "not_reached": 0, "failure_kinds": {}})
        row["sealed"] += 1
        for kind in failed.get(truth.run_id, []):
            row["failure_kinds"][kind] = row["failure_kinds"].get(kind, 0) + 1
        if truth.run_id not in ran:
            row["not_recorded"] += 1  # the process stopped between sealing and the ledger; a resume re-ran this slot
        elif ran[truth.run_id] != "ok":
            row["crashed"] += 1
        elif truth.run_id in audited:
            row["audited"] += 1
            row["failed_then_recovered"] += truth.run_id in failed
        else:
            row["never_reviewed_failed" if truth.run_id in failed else "not_reached"] += 1
            if truth.bug_id:
                unreviewed[truth.bug_id] = unreviewed.get(truth.bug_id, 0) + 1
    return {"by_type": groups, "unreviewed_canaries": unreviewed}


def recall_bounds(observations: list[Observation], unreviewed: int) -> tuple[float, float] | None:
    """Pooled any-flag recall if every unreviewed canary were a miss, and if every one were a catch."""
    canaries = [o for o in observations if o.run_type == sealed.CANARY_MEASURE]
    total = len(canaries) + unreviewed
    if total == 0:
        return None
    caught = sum(o.flagged for o in canaries)
    return caught / total, (caught + unreviewed) / total


def collect_observations(table: sealed.SealedTable, led: ledger.Ledger, role: str = DEFAULT_ROLE,
                         batch: str | None = None) -> tuple[list[Observation], dict[str, int]]:
    """Join the ledger's audits to the sealed table by run ID. `batch` keeps one batch only.

    `excluded` counts what was left out and why, so nothing vanishes silently. A run with no audit (for example a
    failed LLM reply) is not a miss and is not an observation: the reviewer never gave an opinion on it. Those are
    counted by `collect_failures`.
    """
    observations: list[Observation] = []
    excluded = {"other_role": 0, "repeat_audit": 0, "unsealed": 0, "canary_probe": 0, "real": 0, "other_batch": 0}
    seen: set[str] = set()
    for entry in led.entries(ledger.AUDITED):
        payload = entry.payload
        run_id = payload["run_id"]
        if payload["role"] != role:
            excluded["other_role"] += 1
            continue
        if run_id in seen:  # the first opinion stands: a later one could be picked for looking better
            excluded["repeat_audit"] += 1
            continue
        seen.add(run_id)
        truth = table.get(run_id)
        if truth is None:
            excluded["unsealed"] += 1
            continue
        if batch is not None and truth.details.get("batch") != batch:
            excluded["other_batch"] += 1
            continue
        if truth.run_type == sealed.CANARY_PROBE:
            excluded["canary_probe"] += 1
        elif truth.run_type == sealed.REAL:
            excluded["real"] += 1
        impact = impact_module.impact_class(truth.details.get("impact")) if truth.known_buggy else None
        # The code's decision when the audit has one (every review task since the task screen); older audits only
        # have the reply, whose verdict is the baseline task's decision.
        audit = payload.get("decision") or payload["audit"]
        observations.append(Observation(run_id, truth.run_type, truth.bug_id, truth.tier, impact,
                                        audit["verdict"] == FLAG, audit["bug_class"]))
    return observations, excluded


def union_observations(first: list[Observation], second: list[Observation]) -> tuple[list[Observation], dict]:
    """The union reviewer, run by run: "flag" if either reviewer flagged (mission_5_1_tripwires.md section 8).

    Only runs that both reviewers judged get a union verdict; a run one of them has no opinion on (for example a
    failed LLM reply) is counted in `first_only` / `second_only`, never scored. Union numbers come from these per-run
    verdicts, never from the two reviewers' rates. The named class is the first reviewer's when it flagged, else the
    second's. Both lists must agree on each run's truth (they come from the same sealed row).
    """
    theirs = {o.run_id: o for o in second}
    ours = {o.run_id: o for o in first}
    if len(ours) != len(first) or len(theirs) != len(second):
        raise ValueError("a reviewer has two observations of one run")
    union = []
    for run_id, a in ours.items():
        b = theirs.get(run_id)
        if b is None:
            continue
        if (a.run_type, a.bug_id, a.tier, a.impact) != (b.run_type, b.bug_id, b.tier, b.impact):
            raise ValueError(f"run {run_id}: the two reviewers' observations disagree on its truth")
        named = a.named_class if a.flagged else (b.named_class if b.flagged else None)
        union.append(Observation(run_id, a.run_type, a.bug_id, a.tier, a.impact, a.flagged or b.flagged, named))
    counts = {"both": len(union), "first_only": len(set(ours) - set(theirs)),
              "second_only": len(set(theirs) - set(ours))}
    return union, counts


def collect_union_observations(table: sealed.SealedTable, led: ledger.Ledger, first_role: str, second_role: str,
                               batch: str | None = None) -> tuple[list[Observation], dict]:
    """Union observations from two roles' ledger audits (for example `tripwire_v1` and `skeptic_d`), joined by run."""
    first, _ = collect_observations(table, led, first_role, batch)
    second, _ = collect_observations(table, led, second_role, batch)
    return union_observations(first, second)


def clean_runs(table: sealed.SealedTable, batches: list[str]) -> list[tuple[str, str, str]]:
    """(run_id, run type, batch) of every control and sham sealed in these batches, in table order.

    For checks that read clean runs' own results (the decisive-share check, roadmap section 8): the run type and the
    batch come from the sealed table, so the selection goes through this module like every other join with truth.
    """
    wanted = set(batches)
    return [(truth.run_id, truth.run_type, truth.details.get("batch")) for truth in table.all()
            if truth.run_type in (sealed.CONTROL, sealed.SHAM) and truth.details.get("batch") in wanted]
