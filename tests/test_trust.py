"""Expected values here are worked out by hand from the Beta formulas, not copied from the code's output.

Beta(a, b) has mean a / (a + b). Beta(a, 1) has CDF x^a, so its 5th percentile is 0.05^(1/a) and its 95th is 0.95^(1/a).
"""
import math

import numpy as np
import pytest

from canary import cli, ledger, sealed, trust
from canary.saboteur import impact

BUGS = [f"B{i:02d}" for i in range(1, 11)]
CLEAN_IMPACT = {"size": 0.0, "threshold": 0.005, "comparable": True}
HARM_IMPACT = {"size": 0.2, "threshold": 0.005, "comparable": True}
OTHER_METRIC_IMPACT = {"size": 0.2, "threshold": 0.005, "comparable": False}


def obs(run_type=sealed.CANARY_MEASURE, flagged=True, bug="B01", tier="obvious", group=impact.HARMFUL, named=None):
    named = named if named is not None else (bug if flagged else None)
    return trust.Observation("r", run_type, bug, tier, group, flagged, named)


def canaries(caught, missed, **kwargs):
    return [obs(flagged=True, **kwargs) for _ in range(caught)] + [obs(flagged=False, **kwargs) for _ in range(missed)]


def clean(run_type, passed, flagged):
    return [obs(run_type, False, None, None, None) for _ in range(passed)] + \
           [obs(run_type, True, None, None, None, named="B01") for _ in range(flagged)]


# Beta numbers against hand-computed values

def test_three_of_ten_caught_gives_beta_4_8_with_mean_one_third():
    p = trust.summarize(canaries(3, 7), BUGS).per_class["B01"]
    assert (p.alpha, p.beta, p.n) == (4, 8, 10)
    assert p.mean == pytest.approx(4 / 12)
    assert p.mean == pytest.approx(0.33, abs=0.01)


def test_flat_prior_with_no_data():
    p = trust.Posterior()
    assert (p.alpha, p.beta, p.mean) == (1, 1, 0.5)
    assert p.interval() == pytest.approx((0.05, 0.95))


def test_one_catch_interval_matches_the_closed_form():
    p = trust.Posterior(1, 0)  # Beta(2, 1): CDF x^2, so the percentiles are square roots
    assert p.mean == pytest.approx(2 / 3)
    assert p.interval() == pytest.approx((math.sqrt(0.05), math.sqrt(0.95)))
    assert p.interval() == pytest.approx((0.2236, 0.9747), abs=1e-4)


def test_one_miss_interval_matches_the_closed_form():
    p = trust.Posterior(0, 2)  # Beta(1, 3): CDF 1 - (1 - x)^3
    assert p.mean == pytest.approx(0.25)
    assert p.interval() == pytest.approx((1 - 0.95 ** (1 / 3), 1 - 0.05 ** (1 / 3)))


def test_eight_of_ten_has_mean_three_quarters():
    assert trust.Posterior(8, 2).mean == pytest.approx(0.75)


def test_more_data_narrows_the_interval_at_the_same_rate():
    def width(p):
        return p.interval()[1] - p.interval()[0]
    assert width(trust.Posterior(300, 700)) < width(trust.Posterior(3, 7))


# Only canary-measure runs count in recall

def test_probes_change_no_recall_figure():
    base = canaries(3, 7)
    probes = [obs(sealed.CANARY_PROBE, flagged=True) for _ in range(50)]
    without, with_probes = trust.summarize(base, BUGS), trust.summarize(base + probes, BUGS)
    assert without == with_probes


@pytest.mark.parametrize("run_type", [sealed.CONTROL, sealed.SHAM, sealed.REAL])
def test_other_run_types_are_not_recall(run_type):
    summary = trust.summarize([obs(run_type, flagged=True)], BUGS)
    assert summary.per_class["B01"].n == 0
    assert all(p.n == 0 for p in summary.by_impact.values())


def test_real_runs_are_not_specificity():
    assert trust.summarize(clean(sealed.REAL, 5, 5), BUGS).specificity.n == 0


# Recall by impact group

def test_recall_is_separate_for_harmful_harmless_and_unmeasured():
    runs = (canaries(3, 7, group=impact.HARMFUL) + canaries(1, 0, group=impact.HARMLESS)
            + canaries(0, 2, group=impact.UNMEASURED))
    by = trust.summarize(runs, BUGS).by_impact
    assert (by[impact.HARMFUL].alpha, by[impact.HARMFUL].beta) == (4, 8)
    assert (by[impact.HARMLESS].alpha, by[impact.HARMLESS].beta) == (2, 1)
    assert (by[impact.UNMEASURED].alpha, by[impact.UNMEASURED].beta) == (1, 3)
    assert by[impact.UNMEASURED].mean == pytest.approx(0.25)


def test_harmless_canaries_still_count_in_the_main_recall():
    runs = canaries(1, 0, group=impact.HARMFUL) + canaries(0, 1, group=impact.HARMLESS)
    assert trust.summarize(runs, BUGS).per_class["B01"].n == 2


def test_all_impact_groups_appear_even_when_empty():
    assert set(trust.summarize([], BUGS).by_impact) == {impact.HARMFUL, impact.HARMLESS, impact.UNMEASURED}


def test_recall_is_separate_per_tier():
    runs = canaries(2, 0, tier="obvious") + canaries(0, 2, tier="subtle")
    by = trust.summarize(runs, BUGS).by_tier
    assert by["obvious"].mean == pytest.approx(3 / 4)
    assert by["subtle"].mean == pytest.approx(1 / 4)


# Specificity for controls, shams and combined

def test_specificity_is_separate_and_combined():
    summary = trust.summarize(clean(sealed.CONTROL, 9, 1) + clean(sealed.SHAM, 2, 3), BUGS)
    assert (summary.control_specificity.alpha, summary.control_specificity.beta) == (10, 2)
    assert summary.control_specificity.mean == pytest.approx(10 / 12)
    assert (summary.sham_specificity.alpha, summary.sham_specificity.beta) == (3, 4)
    assert summary.sham_specificity.mean == pytest.approx(3 / 7)
    assert (summary.specificity.alpha, summary.specificity.beta) == (12, 5)  # 11 passed and 4 flagged, of 15
    assert summary.specificity.mean == pytest.approx(12 / 17)


# What counts as a catch

def test_a_flag_naming_the_wrong_class_is_a_catch_but_not_named_right():
    summary = trust.summarize([obs(bug="B07", named="B01"), obs(bug="B07", named="B07")], BUGS)
    assert summary.per_class["B07"].successes == 2
    assert summary.named_right.successes == 1
    assert summary.named_right.n == 2


# Overall and worst recall

def test_overall_mean_is_the_exact_mean_of_class_means():
    runs = canaries(3, 7, bug="B01") + canaries(1, 0, bug="B02")
    expected = (4 / 12 + 2 / 3 + 8 * 0.5) / 10
    assert trust.summarize(runs, BUGS).overall_recall_mean == pytest.approx(expected)


def test_monte_carlo_draws_centre_on_the_exact_mean():
    per_class = {"B01": trust.Posterior(3, 7), "B02": trust.Posterior(1, 0)}
    draws = trust.overall_recall_draws(per_class, 20000, np.random.default_rng(1))
    assert draws.mean() == pytest.approx((4 / 12 + 2 / 3) / 2, abs=0.005)


def test_interval_with_no_data_matches_the_hand_calculation_and_marks_all_untested():
    """Ten flat priors: sd = sqrt((1/12)/10) = 0.0913, so about 0.5 +- 1.645 sd. Narrow, yet based on no data at all."""
    summary = trust.summarize([], BUGS, draws=20000)
    assert summary.overall_recall_mean == 0.5
    assert summary.overall_recall_interval == pytest.approx((0.35, 0.65), abs=0.01)
    assert summary.untested == BUGS


def test_the_same_seed_gives_the_same_interval_and_another_seed_does_not():
    runs = canaries(3, 7)
    assert trust.summarize(runs, BUGS, seed=5) == trust.summarize(runs, BUGS, seed=5)
    assert trust.summarize(runs, BUGS, seed=5) != trust.summarize(runs, BUGS, seed=6)


def test_worst_class_ignores_untested_classes():
    """An untested class has mean 0.5, which must not beat or hide a measured class."""
    summary = trust.summarize(canaries(9, 1, bug="B01") + canaries(8, 2, bug="B02"), BUGS)
    assert summary.worst_class == "B02"
    assert summary.worst_recall.mean == pytest.approx(9 / 12)


def test_no_worst_class_until_something_is_tested():
    summary = trust.summarize([], BUGS)
    assert summary.worst_class is None and summary.worst_recall is None


def test_a_canary_with_an_unconfigured_class_is_refused():
    with pytest.raises(ValueError, match="B99"):
        trust.summarize([obs(bug="B99")], BUGS)


# The join between the ledger and the sealed table

@pytest.fixture
def stores(tmp_path):
    return sealed.SealedTable(tmp_path / "sealed.db"), ledger.Ledger(tmp_path / "ledger.db")


def audit(led, hypothesis, run_id, verdict="flag", bug="B01", role="skeptic_a"):
    for status in (ledger.PROPOSED, ledger.PREREGISTERED, ledger.RAN):
        led.append(hypothesis, status, {})
    led.append(hypothesis, ledger.AUDITED, {"run_id": run_id, "role": role, "audit": {
        "verdict": verdict, "bug_class": bug if verdict == "flag" else None, "evidence": "x", "confidence": 0.5}})


def test_join_carries_truth_verdict_and_impact_group(stores):
    table, led = stores
    table.seal("r1", sealed.CANARY_MEASURE, "B03", "subtle", details={"impact": HARM_IMPACT})
    table.seal("r2", sealed.CANARY_MEASURE, "B03", "subtle", details={"impact": CLEAN_IMPACT})
    table.seal("r3", sealed.CANARY_MEASURE, "B06", "obvious", details={"impact": OTHER_METRIC_IMPACT})
    table.seal("r4", sealed.CANARY_MEASURE, "B06", "obvious", details={"impact": None})
    table.seal("r5", sealed.CONTROL)
    audit(led, "h1", "r1", bug="B03")
    audit(led, "h2", "r2", verdict="pass")
    audit(led, "h3", "r3")
    audit(led, "h4", "r4")
    audit(led, "h5", "r5", verdict="pass")
    found, excluded = trust.collect_observations(table, led)
    assert [o.impact for o in found] == [impact.HARMFUL, impact.HARMLESS, impact.UNMEASURED, impact.UNMEASURED, None]
    assert [o.flagged for o in found] == [True, False, True, True, False]
    assert found[0].named_class == "B03" and found[0].tier == "subtle"
    assert not any(excluded.values())


def test_unsealed_probe_and_real_runs_are_counted_as_excluded(stores):
    table, led = stores
    table.seal("probe", sealed.CANARY_PROBE, "B01", "obvious")
    table.seal("real", sealed.REAL)
    audit(led, "h1", "probe")
    audit(led, "h2", "real")
    audit(led, "h3", "not-sealed")
    found, excluded = trust.collect_observations(table, led)
    assert (excluded["canary_probe"], excluded["real"], excluded["unsealed"]) == (1, 1, 1)
    assert sorted(o.run_type for o in found) == [sealed.CANARY_PROBE, sealed.REAL]  # kept for Missions 4.1 and 6.1
    summary = trust.summarize(found, BUGS)
    assert summary.per_class["B01"].n == 0 and summary.specificity.n == 0


def test_other_roles_are_ignored(stores):
    table, led = stores
    table.seal("r1", sealed.CONTROL)
    audit(led, "h1", "r1", role="skeptic_b")
    found, excluded = trust.collect_observations(table, led)
    assert found == [] and excluded["other_role"] == 1


def test_the_first_audit_of_a_run_stands(stores):
    """Otherwise re-reviewing a miss until it is caught would raise recall."""
    table, led = stores
    table.seal("r1", sealed.CANARY_MEASURE, "B01", "obvious")
    audit(led, "h1", "r1", verdict="pass")
    audit(led, "h2", "r1", verdict="flag")
    found, excluded = trust.collect_observations(table, led)
    assert [o.flagged for o in found] == [False] and excluded["repeat_audit"] == 1


# The command

def test_trust_command_does_not_create_the_sealed_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "sealed.db"
    monkeypatch.setattr(sealed, "SEALED_DB_PATH", path)
    assert cli.main(["trust"]) == 0
    assert not path.exists()
    assert "No sealed table yet" in capsys.readouterr().out


def test_demo_is_labelled_synthetic_and_shows_every_group(capsys):
    assert cli.main(["trust", "--demo"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("SYNTHETIC DEMO")
    for word in ("harmful", "harmless", "unmeasured", "controls", "shams", "combined", "tested 2 of 10", "UNTESTED"):
        assert word in out
    assert "Beta(9, 3)" in out and "Beta(4, 8)" in out  # B01 8 of 10, B02 3 of 10
