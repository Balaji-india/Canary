"""canary/drift.py: exact limits and chart rules (Mission 4.3 step 1), checked against hand-computed values."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import betabinom, binom

from canary import drift

ROOT = Path(__file__).resolve().parent.parent
T3, T2 = drift.TAILS["standard"]


# ---- Step 1: limits ------------------------------------------------------------------------------------------

def test_hand_computed_beta_binomial_for_zero_of_ten():
    """Baseline 0 flips in 10, slice of m = 2: X ~ BetaBinomial(2, 1, 11).
    P(X = 2) = (1/12)(2/13) = 2/156 = 0.0128;  P(X >= 1) = 1 - P(X = 0) = 1 - (11/12)(12/13) = 2/13 = 0.1538."""
    assert betabinom.pmf(2, 2, 1, 11) == pytest.approx(2 / 156)
    assert betabinom.sf(0, 2, 1, 11) == pytest.approx(2 / 13)
    assert drift.limit(10, 0, 2, T2) == 2          # 0.0128 <= 0.0228, but 0.1538 is not
    assert drift.limit(10, 0, 2, T3) == 3          # 0.0128 > 0.00135: no 3-sigma limit, so m + 1


def test_no_three_sigma_limit_means_r1_cannot_fire():
    fired = drift.rules([2, 2, 2, 2], n0=10, f0=0, m=2, span=3)
    assert fired["R1"] == []                       # even the largest possible count is not "rare enough"
    assert fired["R2"] == [1, 2, 3]                # but 2 of 2 is beyond the 2-sigma limit every time


def test_limit_is_the_smallest_rare_count():
    for n0, f0, m in ((30, 1, 10), (60, 3, 20), (160, 4, 20), (170, 5, 60)):
        for tail in (T3, T2):
            c = drift.limit(n0, f0, m, tail)
            assert betabinom.sf(c - 1, m, 1 + f0, 1 + n0 - f0) <= tail
            assert betabinom.sf(c - 2, m, 1 + f0, 1 + n0 - f0) > tail


def _never_falls(sizes, slices, tails):
    for n0 in sizes:
        for m in slices:
            for tail in tails:
                values = [drift.limit(n0, f0, m, tail) for f0 in range(n0 + 1)]
                assert values == sorted(values), (n0, m, tail)


def test_a_limit_never_falls_when_the_baseline_count_rises():
    _never_falls((10, 30), (2, 10, 20), (T3, T2))


@pytest.mark.slow
def test_a_limit_never_falls_when_the_baseline_count_rises_full_grid():
    _never_falls((10, 30, 60, 160), (2, 10, 20, 60), (T3, T2, 0.0005, 0.01))


def test_a_huge_baseline_reproduces_the_plain_binomial_limit():
    """With f0 of n0 at n0 = 10^7 the rate is known exactly, so the Beta-binomial becomes Binomial(m, f0 / n0)."""
    n0 = 10_000_000
    for p, m in ((0.05, 20), (0.02, 20), (0.03, 60), (0.30, 10)):
        f0 = round(p * n0)
        for tail in (T3, T2):
            c = next(c for c in range(m + 2) if c == m + 1 or binom.sf(c - 1, m, p) <= tail)
            assert drift.limit(n0, f0, m, tail) == c, (p, m, tail)


def _design_sim():
    path = ROOT / "docs" / "plans" / "sims" / "drift_chart_sim.py"
    spec = importlib.util.spec_from_file_location("drift_chart_sim_for_test", path)
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    return sim


def test_the_limit_table_matches_the_design_simulation():
    """The design session's script (committed before its first run) and this module agree on every limit."""
    _same_as_design(((30, 10), (30, 30)))


@pytest.mark.slow
def test_the_limit_table_matches_the_design_simulation_large_baselines():
    _same_as_design(((160, 20), (170, 60), (60, 60)))


def _same_as_design(cases):
    sim = _design_sim()
    for n0, m in cases:
        for tail in (T3, T2):
            ours = drift.limits(n0, np.arange(n0 + 1), m, tail)
            assert list(ours) == list(sim.limits(n0, m, tail)), (n0, m, tail)


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        drift.limit(10, 11, 2, T3)
    with pytest.raises(ValueError):
        drift.limit(10, 0, 0, T3)
    with pytest.raises(ValueError):
        drift.limit(10, 0, 2, 0.0)
    with pytest.raises(ValueError):
        drift.rules([3], n0=10, f0=0, m=2, span=3)      # a count above m
    with pytest.raises(ValueError):
        drift.rules([1], n0=10, f0=0, m=2, span=0)
    with pytest.raises(ValueError):
        drift.rules([1], n0=10, f0=0, m=2, span=3, tails="loose")


# ---- Step 1: rules ---------------------------------------------------------------------------------------------

BASE = dict(n0=30, f0=1, m=10, span=3)   # a sentinel half: 1 flip of 30 in the opening pass, 10 a slice


def test_the_example_chart_limits():
    """1 flip in 30, slices of 10, W = 3: R1 6, R2 4, R3 11 (of 30). Each value is checked from the Beta-binomial
    directly here, not through `limit`: the tail at the limit is small enough, one below it is not."""
    lim = drift.chart_limits(**BASE)
    assert (lim["R1"], lim["R2"], lim["R3"]) == (6, 4, 11)
    for m, c, t in ((10, 6, T3), (10, 4, T2), (30, 11, T3)):
        assert betabinom.sf(c - 1, m, 2, 30) <= t < betabinom.sf(c - 2, m, 2, 30)
    # the design plan's printed fresh-chart limits at the bank baseline (section 4): 5, 3, 9 and 6, 4, 10
    assert [drift.chart_limits(160, 3, 20, 3)[r] for r in drift.RULES] == [5, 3, 9]
    assert [drift.chart_limits(170, 5, 20, 3)[r] for r in drift.RULES] == [6, 4, 10]


def test_r1_fires_on_one_slice_at_or_beyond_the_three_sigma_limit():
    lim = drift.chart_limits(**BASE)
    counts = [0, lim["R1"] - 1, 0, lim["R1"], 0]
    fired = drift.rules(counts, **BASE)
    assert fired["R1"] == [3]


def test_r2_needs_two_neighbours():
    lim = drift.chart_limits(**BASE)
    c2 = lim["R2"]
    assert c2 < lim["R1"]                               # so these counts cannot fire R1
    apart = [c2, 0, c2, 0, c2]
    assert drift.rules(apart, **BASE)["R2"] == []       # three times over the 2-sigma limit, never twice in a row
    together = [0, c2, c2, 0]
    assert drift.rules(together, **BASE)["R2"] == [2]   # fires on the second of the two


def test_r3_ignores_the_first_w_minus_1_slices():
    lim = drift.chart_limits(**BASE)
    assert lim["R3"] == 11                              # 11 flips in 30 runs after 1 of 30 (printed limit)
    early = [10, 1, 0, 0]                               # the running sum is 11 already at index 1
    fired = drift.rules(early, **BASE)
    assert fired["R3"] == [2]                           # index 1 is ignored (fewer than W slices); 2 counts 0..2
    for span in (3, 5, 7):
        anywhere = drift.rules([5] * 12, n0=30, f0=1, m=10, span=span)["R3"]
        assert anywhere and min(anywhere) == span - 1


def test_r3_sums_exactly_the_last_w_slices():
    """Hand count: span 3, counts 1, 2, 3, 4 -> rolling sums at index 2 and 3 are 6 and 9."""
    counts = np.array([[1, 2, 3, 4]])
    n0, f0, m, span = 10, 0, 4, 3
    lim = drift.limit(n0, f0, m * span, T3)
    fired = drift.fire_matrix(counts, n0, f0, m, span)["R3"][0]
    assert list(fired) == [False, False, 6 >= lim, 9 >= lim]


def test_a_quiet_chart_raises_nothing():
    assert drift.rules([0] * 30, **BASE) == {"R1": [], "R2": [], "R3": []}


def test_fire_matrix_takes_one_baseline_per_campaign():
    counts = np.array([[4, 4], [4, 4]])
    rows = drift.fire_matrix(counts, 30, np.array([0, 15]), 10, 3)
    assert rows["R2"][0, 1] and not rows["R2"][1, 1]    # 4 of 10 is rare after 0 of 30, ordinary after 15 of 30
