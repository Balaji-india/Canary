"""Mission 4.3: control chart and drift alarms (docs/plans/mission_4_3_drift.md).

Why this module exists: Mission 4.1 turns calibration counts into a gate, but those counts describe the reviewer on
the day it was measured. A cloud model can change without notice. This module holds the arithmetic that notices a
change: exact small-sample control limits and the three chart rules of plan section 4.

Limits are exact, not normal approximations. For a slice or window of m runs the limit at tail probability t is the
smallest count c with P(X >= c) <= t, where X ~ BetaBinomial(m, 1 + f0, 1 + n0 - f0) and f0 of n0 is the baseline
count (the sentinel's opening pass, or the epoch's calibration set for the fresh charts). The Beta-binomial is the
predictive distribution of a new count when the baseline rate is only known from f0 of n0 (flat prior), so a small
baseline gives wider limits instead of false alarms. When no count is that rare the limit is m + 1, so the rule
cannot fire. Westgard's sigma levels are kept as tail probabilities: "3 sigma" = 0.00135, "2 sigma" = 0.0228.

  R1 (Westgard 1_3s): one slice or window at or beyond the 3-sigma limit.
  R2 (Westgard 2_2s): two in a row, each at or beyond the 2-sigma limit (fires on the second of the two).
  R3 (stands in for 4_1s and 10_x): the count summed over the last W slices or windows at or beyond the 3-sigma
     limit for W * m runs; it needs W complete slices, so it never fires on the first W - 1.

All limits are one-sided (upper): a chart counts bad events (flips, false alarms, misses), and only "more than
expected" is a drift; "fewer" is good news and raises nothing.

Sitting 1 (plan steps 1-3) is arithmetic on records it is given: this module opens no database, no run folder and
no sealed table, and calls no model. No LLM decides anything here; the rules are code.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.stats import betabinom

TAILS: dict[str, tuple[float, float]] = {"standard": (0.00135, 0.0228), "strict": (0.0005, 0.01)}
RULES = ("R1", "R2", "R3")


def _tails(tails: str | tuple[float, float]) -> tuple[float, float]:
    if isinstance(tails, str):
        if tails not in TAILS:
            raise ValueError(f"unknown tails {tails!r}; use one of {sorted(TAILS)}")
        return TAILS[tails]
    t3, t2 = tails
    return float(t3), float(t2)


@lru_cache(maxsize=None)
def limit(n0: int, f0: int, m: int, tail: float) -> int:
    """The smallest count c in 0..m with P(X >= c) <= tail, X ~ BetaBinomial(m, 1 + f0, 1 + n0 - f0); m + 1 if none.

    Example (plan step 1): baseline 0 flips in 10, m = 2: P(X = 2) = (1/12)(2/13) = 0.0128 and P(X >= 1) = 2/13 =
    0.154, so the 2-sigma limit (0.0228) is 2 and no 3-sigma limit (0.00135) exists: the function returns 3.
    """
    n0, f0, m = int(n0), int(f0), int(m)
    if n0 < 0 or not 0 <= f0 <= n0:
        raise ValueError(f"baseline must be 0 <= f0 <= n0, got f0={f0}, n0={n0}")
    if m < 1:
        raise ValueError(f"a slice or window needs at least one run, got m={m}")
    if not 0.0 < tail < 1.0:
        raise ValueError(f"tail must be a probability in (0, 1), got {tail}")
    counts = np.arange(m + 1)
    upper = betabinom.sf(counts - 1, m, 1 + f0, 1 + n0 - f0)  # P(X >= c) for c = 0..m
    rare = np.nonzero(upper <= tail)[0]
    return int(rare[0]) if len(rare) else m + 1


def limits(n0: int, f0, m: int, tail: float) -> np.ndarray:
    """`limit` for an array of baseline counts (one per simulated campaign); each distinct f0 is computed once."""
    f0 = np.asarray(f0, dtype=int)
    values, inverse = np.unique(f0, return_inverse=True)
    table = np.array([limit(n0, int(v), m, tail) for v in values], dtype=int)
    return table[inverse].reshape(f0.shape)


def fire_matrix(counts, n0: int, f0, m: int, span: int, tails: str | tuple[float, float] = "standard"
                ) -> dict[str, np.ndarray]:
    """Where each rule fires. `counts` is campaigns x slices (each slice exactly m runs), `f0` one baseline count
    per campaign (or one for all). Returns {"R1": bool array, "R2": ..., "R3": ...} of the same shape.

    This is the only implementation of the rules: `rules` (the chart) and eval/drift_power.py (the simulation) both
    call it, so the simulated operating characteristics cannot drift from what the chart does.
    """
    counts = np.asarray(counts, dtype=int)
    if counts.ndim != 2:
        raise ValueError("counts must be 2-D: campaigns x slices")
    if counts.size and (counts.min() < 0 or counts.max() > m):
        raise ValueError(f"every count must be between 0 and m = {m}")
    if span < 1:
        raise ValueError(f"W must be at least 1, got {span}")
    t3, t2 = _tails(tails)
    f0 = np.broadcast_to(np.asarray(f0, dtype=int), counts.shape[:1])
    r1 = counts >= limits(n0, f0, m, t3)[:, None]
    over2 = counts >= limits(n0, f0, m, t2)[:, None]
    r2 = np.zeros_like(r1)
    r2[:, 1:] = over2[:, 1:] & over2[:, :-1]
    total = np.cumsum(counts, axis=1)
    roll = total.copy()
    roll[:, span:] = total[:, span:] - total[:, :-span]          # sum of the last `span` slices, this one included
    r3 = roll >= limits(n0, f0, m * span, t3)[:, None]
    r3[:, :span - 1] = False                                     # fewer than W complete slices: R3 cannot fire
    return {"R1": r1, "R2": r2, "R3": r3}


def rules(counts, n0: int, f0: int, m: int, span: int, tails: str | tuple[float, float] = "standard"
          ) -> dict[str, list[int]]:
    """One chart: which of R1, R2, R3 fire at which slice index (0-based, in review order).

    `counts` are the counts of complete slices or windows of exactly m runs each, oldest first.
    """
    counts = np.asarray(counts, dtype=int).reshape(1, -1)
    fired = fire_matrix(counts, n0, f0, m, span, tails)
    return {name: [int(i) for i in np.nonzero(fired[name][0])[0]] for name in RULES}


def chart_limits(n0: int, f0: int, m: int, span: int, tails: str | tuple[float, float] = "standard") -> dict:
    """The three limits a chart shows: R1 (per slice), R2 (per slice, twice in a row), R3 (over W slices)."""
    t3, t2 = _tails(tails)
    return {"R1": limit(n0, f0, m, t3), "R2": limit(n0, f0, m, t2), "R3": limit(n0, f0, m * span, t3),
            "m": m, "W": span, "baseline": [f0, n0], "tails": [t3, t2]}
