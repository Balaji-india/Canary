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


def summarize(observations: list[Observation], bug_ids: list[str], draws: int = 5000, seed: int = 0) -> TrustSummary:
    """Compute every trust number. The seed is fixed by default so that a report can be reproduced exactly.

    An untested class stays in the overall figure at its prior and is listed in `untested`. Averaging 10 flat priors
    gives a narrow-looking interval around 0.5 that reflects no data, so anything printing it must show `untested`.
    """
    measured = [o for o in observations if o.run_type == sealed.CANARY_MEASURE]
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
    )


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
