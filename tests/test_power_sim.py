"""eval/power_sim.py and eval/dev_compare.py: the statistics are checked against hand-computed values, and the fast
weighted base bootstrap against separation.base_bootstrap on the same draws. No LLM, no real data."""
import math

import numpy as np
import pytest

from canary import separation
from eval import dev_compare, power_sim


def test_icc_matches_hand_computed_anova():
    # groups [1,2] and [3,4]: MSB = 4, MSW = 0.5, n0 = 2, ICC = 3.5 / 4.5
    assert power_sim.icc([[1.0, 2.0], [3.0, 4.0]]) == pytest.approx(3.5 / 4.5)


def test_icc_is_zero_without_between_base_variance_and_never_negative():
    assert power_sim.icc([[1.0, 3.0], [1.0, 3.0]]) == 0.0
    assert power_sim.icc([[5.0]]) == 0.0


def test_weighted_draws_give_the_same_interval_as_separation_base_bootstrap():
    rng = np.random.default_rng(1)
    base = np.repeat(np.arange(6), 4)
    buggy = np.tile([True, False], 12)
    values = rng.normal(size=24) + buggy
    items = [(int(b), bool(g), float(v)) for b, g, v in zip(base, buggy, values)]
    expected = separation.base_bootstrap(items, separation.auc_stat, seed=0, draws=300)
    draw_rng = np.random.default_rng(0)
    counts = np.stack([np.bincount(draw_rng.integers(0, 6, 6), minlength=6) for _ in range(300)])
    w = counts[:, base].astype(float)
    ok = (w[:, buggy].sum(1) > 0) & (w[:, ~buggy].sum(1) > 0)
    aucs = power_sim.draw_aucs(power_sim.pair_matrix(values, buggy), w[ok][:, buggy], w[ok][:, ~buggy])
    assert list(np.percentile(aucs, [5, 95])) == pytest.approx(expected)


def test_pair_matrix_counts_ties_as_half():
    m = power_sim.pair_matrix(np.array([2.0, 1.0, 1.0]), np.array([True, True, False]))
    assert m.tolist() == [[1.0], [0.5]]


@pytest.mark.parametrize("auc", [0.6, 0.7])
def test_latent_shift_gives_the_target_auc(auc):
    rng = np.random.default_rng(0)
    n = 4000
    base, buggy = np.arange(n), np.arange(n) % 2 == 0
    z = power_sim.latent(rng, base, buggy, n, auc, 0.3)
    assert separation.auc(list(z[buggy]), list(z[~buggy])) == pytest.approx(auc, abs=0.02)


def test_runs_needed_picks_the_smallest_run_count_reaching_the_target():
    cells = {"100": {"H2": 0.5}, "200": {"H2": 0.81}, "300": {"H2": 0.9}}
    assert power_sim.runs_needed(cells, "H2") == 200
    assert power_sim.runs_needed({"100": {"H2": 0.79}}, "H2") is None


def test_measured_times_reads_runs_audits_and_pool_rate(tmp_path):
    log = tmp_path / "campaign.log"
    log.write_text("\n".join([
        "2026-11-01T09:00:00+00:00 pool 1/3 kept a / b / c (4 s trial)",
        "2026-11-01T09:00:20+00:00 pool 2/3 kept a / b / c (4 s trial)",
        "2026-11-01T09:00:40+00:00 pool 3/3 kept a / b / c (4 s trial)",
        "2026-11-10T12:00:00+00:00 batch b: 4 slots, 4 to run",
        "2026-11-10T12:00:40+00:00 batch b: length gate passed (...)",
        "2026-11-10T12:01:00+00:00 batch b: audit 1/4 pass [20 s so far]",
        "2026-11-10T12:01:00+00:00 batch b: audit 2/4 pass [30 s so far]",
        "2026-11-10T12:01:00+00:00 batch b: audit 3/4 pass [50 s so far]",
        "2026-11-10T12:01:00+00:00 batch b: audit 4/4 pass [60 s so far]",
    ]), encoding="utf-8")
    t = power_sim.measured_times(log, "b")
    assert (t["run_seconds_per_run"], t["audit_seconds_per_run"], t["pool_seconds_per_base"]) == (10.0, 15.0, 20.0)
    assert power_sim.laptop_minutes(6, 3, t) == pytest.approx((3 * 20 + 6 * 25) / 60)


def _row(base, buggy, score, decoy=False, code=False):
    return {"run_id": f"{base}-{buggy}-{score}", "base": base, "buggy": buggy, "score": score,
            "decoy": decoy, "decoy_has_code": code}


def test_dev_compare_splits_the_change_by_side():
    before = [_row("a", True, 0.6), _row("a", False, 0.3), _row("b", True, 0.4), _row("b", False, 0.5)]
    after = [_row("a", True, 0.7), _row("a", False, 0.5, True, True), _row("b", True, 0.5),
             _row("b", False, 0.6, True, False)]
    s = dev_compare.statistics_of(before, after)
    assert s["auc_before"] == pytest.approx(0.75)     # 0.6 beats 0.3 and 0.5; 0.4 beats 0.3 only: 3 of 4
    assert s["auc_after"] == pytest.approx(0.625)     # 0.7 beats both; 0.5 ties 0.5, loses to 0.6: 2.5 of 4
    assert s["auc_change"] == pytest.approx(-0.125)
    assert s["buggy_change"] == pytest.approx(0.1)    # mean 0.5 -> 0.6
    assert s["clean_change"] == pytest.approx(0.15)   # 0.4 -> 0.55
    assert s["decoy_with_code_minus_plain"] == pytest.approx(0.1)
    assert s["decoy_no_code_minus_plain"] == pytest.approx(0.2)
    assert s["decoy_with_minus_without_code"] == pytest.approx(-0.1)


def test_dev_compare_bootstrap_with_one_base_is_a_point():
    rows = [_row("a", True, 0.6), _row("a", False, 0.3)]
    iv = dev_compare.joint_base_bootstrap(rows, rows, draws=50)
    assert iv["auc_change"] == [0.0, 0.0]
    assert not math.isnan(iv["auc_before"][0])
