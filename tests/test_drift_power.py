"""eval/drift_power.py: the drift design simulation as tested code (Mission 4.3 step 2). Synthetic inputs only:
no ledger, no sealed table, no result file is opened by these tests (the reproduction test reads the committed
design JSON only)."""
import json

import numpy as np
import pytest
from scipy.stats import binom

from canary import drift
from eval import drift_power as dp

SMALL = dict(campaigns=200, sizes=(60,), slices=(20,), spans=(3,))


def _perfect(sp: float = 1.0, eps: float = 0.0) -> dp.Reviewer:
    """A reviewer with no noise: every canary always flagged, every clean run always passed, no flip on a re-ask."""
    rates = (1.0,) * 10
    a = dp.assumed_reviewer()
    changes = dict(a.changes)
    changes["none"] = (rates, 1 - sp)
    changes["drop"] = (tuple(r * 0.775 for r in rates), 1 - sp)
    changes["collapse_030"] = (tuple(r * 0.39 for r in rates), 1 - sp)
    changes["spec_drop"] = (rates, 0.10)
    return dp.Reviewer("perfect", "assumed", a.classes, rates, sp, eps, 0.0, 0.0, 9, 15, 20, changes, {})


def test_the_simulation_is_seeded_and_repeatable():
    rev = dp.assumed_reviewer()
    for icc in (0.0, 0.2):
        one = dp.sentinel_counts(np.random.default_rng(5), rev, "independent", "drop", 60, 20, icc, 300)
        two = dp.sentinel_counts(np.random.default_rng(5), rev, "independent", "drop", 60, 20, icc, 300)
        other = dp.sentinel_counts(np.random.default_rng(6), rev, "independent", "drop", 60, 20, icc, 300)
        assert all(np.array_equal(a, b) for a, b in zip(one, two))
        assert not all(np.array_equal(a, b) for a, b in zip(one, other))


def test_no_noise_and_no_change_never_fires():
    """Deterministic verdicts and no flips: every flip count is 0, the baseline is 0, and no rule ever fires."""
    rev = _perfect()
    for icc in (0.0, 0.4):
        for model in dp.MODELS:
            fb, fc, f0b, f0c = dp.sentinel_counts(np.random.default_rng(1), rev, model, "none", 60, 20, icc, 200)
            assert fb.sum() == fc.sum() == f0b.sum() == f0c.sum() == 0
        rows, table = dp.sentinel_study(np.random.default_rng(2), rev, icc, **SMALL)
        assert all(row["alarm_by_day"]["30"] == 0.0 for row in rows if row["change"] == "none")
        assert table[(60, 20, 3, "standard")]["quiet_30"] == 0.0


def test_flags_everything_always_fires_on_the_first_slice():
    rev = _perfect()
    for icc in (0.0, 0.2):
        rows, _ = dp.sentinel_study(np.random.default_rng(3), rev, icc, **SMALL)
        for row in rows:
            if row["change"] == "flag_all":
                assert row["alarm_by_day"]["1"] == 1.0, row
                assert row["by_rule_day2"]["clean_R1"] == 1.0         # 10 of 10 clean runs flip on day 1


def test_passes_everything_with_the_design_rates_fires_within_two_days_mostly():
    rows, _ = dp.sentinel_study(np.random.default_rng(4), dp.assumed_reviewer(), 0.0, **SMALL)
    shares = [row["alarm_by_day"]["2"] for row in rows if row["change"] == "pass_all" and row["tails"] == "standard"]
    assert min(shares) > 0.9                                          # design JSON: 0.9715 worst case


def test_the_simulation_uses_the_chart_rules(monkeypatch):
    calls = []
    real = drift.fire_matrix

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(drift, "fire_matrix", spy)
    dp.sentinel_study(np.random.default_rng(0), dp.assumed_reviewer(), 0.0, **SMALL)
    assert calls


def test_a_base_effect_keeps_the_rate_and_adds_spread():
    """The latent draw keeps the marginal rate p; at ICC 0.4 window counts vary more than Binomial(20, p)."""
    rng = np.random.default_rng(7)
    p, c, windows = 0.1, 4000, 30
    u = rng.standard_normal((c, dp.BANK_BASES)) * np.sqrt(0.4)
    counts = dp._fresh_counts(rng, p, (c, windows), 0.4, u)
    assert counts.mean() / dp.FRESH_WINDOW == pytest.approx(p, abs=0.01)
    assert counts.var() > 1.5 * dp.FRESH_WINDOW * p * (1 - p)
    plain = dp._fresh_counts(np.random.default_rng(7), p, (c, windows), 0.0, None)
    assert plain.var() == pytest.approx(dp.FRESH_WINDOW * p * (1 - p), rel=0.1)


def test_choose_applies_the_selection_rule_in_order():
    def w(q, pa, fa, d):
        return {"quiet_30": q, "pass_all_2": pa, "flag_all_2": fa, "drop_7": d}
    table = {(60, 20, 3, "standard"): w(0.01, 0.97, 1.0, 0.1),
             (40, 10, 3, "standard"): w(0.01, 0.80, 1.0, 0.1),      # fails (b)
             (60, 20, 3, "strict"): w(0.01, 0.96, 1.0, 0.1),
             (60, 20, 5, "standard"): w(0.20, 0.99, 1.0, 0.9)}      # fails (a)
    got = dp.choose(table)
    assert (got["N"], got["k"], got["W"], got["tails"]) == (60, 20, 3, "standard")
    assert got["how"].startswith("no candidate meets (c)")
    table[(60, 20, 7, "strict")] = w(0.05, 0.99, 1.0, 0.85)         # meets everything
    assert dp.choose(table)["W"] == 7


def test_worst_over_takes_the_worst_of_each_criterion():
    key = (60, 20, 3, "standard")
    one = {key: {"quiet_30": 0.01, "pass_all_2": 0.99, "flag_all_2": 1.0, "drop_7": 0.2}}
    two = {key: {"quiet_30": 0.04, "pass_all_2": 0.90, "flag_all_2": 1.0, "drop_7": 0.3}}
    assert dp.worst_over([one, two])[key] == {"quiet_30": 0.04, "pass_all_2": 0.90, "flag_all_2": 1.0, "drop_7": 0.2}


def test_measured_reviewer_uses_posterior_means_and_proportional_changes():
    llm = {f"B{i:02d}": (3, 6) for i in range(1, 11)}
    rev = dp.measured_reviewer(llm, (60, 60), (1, 20), {f"B{i:02d}": (6, 6) for i in range(1, 10)}, (60, 60), {})
    assert rev.class_rates == (4 / 8,) * 10                     # Beta(1 + 3, 1 + 3) mean
    assert rev.sp == pytest.approx(61 / 62) and rev.eps == pytest.approx(2 / 22)
    assert rev.union_miss == pytest.approx(1 - 7 / 8) and rev.union_fa == pytest.approx(1 - 61 / 62)
    assert (rev.clean_per_day, rev.canaries_per_day, rev.supported_classes) == (12, 18, 9)
    f = dp.proportional_factors()
    assert f["drop"] == pytest.approx(0.600 / 0.774) and f["collapse_030"] == pytest.approx(0.302 / 0.774)
    assert rev.changes["drop"][0] == tuple(0.5 * f["drop"] for _ in range(10))
    assert rev.changes["spec_drop"] == (rev.class_rates, 0.10)


def test_the_sentinel_needs_ten_class_rates():
    rev = dp.measured_reviewer({f"B{i:02d}": (3, 6) for i in range(1, 10)}, (60, 60), (1, 20),
                               {"B01": (6, 6)}, (60, 60), {})
    with pytest.raises(ValueError, match="10 classes"):
        dp.sentinel_counts(np.random.default_rng(0), rev, "sticky", "none", 60, 20, 0.0, 10)


def test_bank_rule_hand_values():
    """eps 0.05: a run differs between two passes with 2(0.05)(0.95) = 0.095; P(X >= 4 of 20) written out as
    1 - sum over k = 0..3 of C(20, k) q^k (1 - q)^(20 - k) = 1 - (0.1358 + 0.2851 + 0.2844 + 0.1791) = 0.1156."""
    from math import comb
    q = 0.095
    by_hand = 1 - sum(comb(20, k) * q ** k * (1 - q) ** (20 - k) for k in range(4))
    assert dp.bank_rule_exact(0.05) == pytest.approx(by_hand)
    assert round(by_hand, 4) == 0.1156
    assert dp.bank_rule_exact(0.05) == pytest.approx(binom.sf(3, 20, q))
    assert dp.bank_rule_exact(0.0) == 0.0
    # The predictive value averages over eps ~ Beta(2, 20); its mean 1/11 is above 1/20, so it is larger.
    assert dp.bank_rule_predictive(1, 20) > dp.bank_rule_exact(0.05)
    sim = dp.bank_rule_simulated(np.random.default_rng(0), _perfect(eps=0.05), "sticky", 0.0, 40_000)
    assert sim == pytest.approx(dp.bank_rule_exact(0.05), abs=0.01)


def test_day_to_day_waits_for_three_passes():
    out = dp.day_to_day((1, 20))
    assert out["status"].startswith("not computable")
    assert out["limit_95_if_the_other_two_repeat_this_rate"] == drift.limit(40, 2, 20, 0.05)
    with pytest.raises(ValueError):
        dp.spread_above([(1, 20)])


def test_spread_rule_compares_each_pass_with_the_other_two():
    """Amendment 1 item 7: pass i against drift.limit(40, f_others, 20, 0.05)."""
    calm = dp.spread_above([(1, 20), (1, 20), (2, 20)])
    assert [r["others"] for r in calm["rows"]] == [[3, 40], [3, 40], [2, 40]]
    assert [r["limit_95"] for r in calm["rows"]] == [drift.limit(40, 3, 20, 0.05)] * 2 + [drift.limit(40, 2, 20, 0.05)]
    assert not calm["split_opening_pass"]
    jumpy = dp.spread_above([(0, 20), (0, 20), (8, 20)])
    assert jumpy["rows"][2]["at_or_beyond"] and jumpy["split_opening_pass"]


@pytest.mark.slow
def test_reproduces_the_design_simulation_draw_for_draw():
    """Plan step 2, done when (first half): the assumed rates at ICC 0 give the design JSON's worst-case table for
    every one of the 54 candidates, hence its choice, and the same fresh-chart tails."""
    rep = dp.reproduce()
    assert rep["same_choice_as_design"], rep["choice"]
    assert rep["same_worst_case_table_as_design"]
    assert all(rep["same_fresh_charts_as_design"].values())
    design = json.loads(dp.DESIGN_JSON.read_text(encoding="utf-8"))
    assert rep["choice"]["worst_case"] == design["sentinel_choice"]["worst_case"]
