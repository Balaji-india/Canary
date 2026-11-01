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
        specificity=passes(clean),
        control_specificity=passes([o for o in clean if o.run_type == sealed.CONTROL]),
        sham_specificity=passes([o for o in clean if o.run_type == sealed.SHAM]),
        untested=[b for b in per_class if b not in tested],
    )


def collect_observations(table: sealed.SealedTable, led: ledger.Ledger,
                         role: str = DEFAULT_ROLE) -> tuple[list[Observation], dict[str, int]]:
    """Join the ledger's audits to the sealed table by run ID.

    `excluded` counts what was left out and why, so nothing vanishes silently. A run with no audit (for example a
    failed LLM reply) is not a miss and is not an observation: the reviewer never gave an opinion on it.
    """
    observations: list[Observation] = []
    excluded = {"other_role": 0, "repeat_audit": 0, "unsealed": 0, "canary_probe": 0, "real": 0}
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
        if truth.run_type == sealed.CANARY_PROBE:
            excluded["canary_probe"] += 1
        elif truth.run_type == sealed.REAL:
            excluded["real"] += 1
        impact = impact_module.impact_class(truth.details.get("impact")) if truth.known_buggy else None
        audit = payload["audit"]
        observations.append(Observation(run_id, truth.run_type, truth.bug_id, truth.tier, impact,
                                        audit["verdict"] == FLAG, audit["bug_class"]))
    return observations, excluded
