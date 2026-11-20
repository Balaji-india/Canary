"""eval/rq4_power.py: the design simulation as tested code (Mission 4.1 step 1). Synthetic data only, no ledger."""
import json

import numpy as np
import pytest

from canary import sealed, trust
from canary.saboteur import impact
from eval import rq4_power


def test_the_simulation_is_seeded_and_repeatable():
    args = ([0.9, 0.6, 0.95], [1, 1, 1], 0.97, 12, 60, 60, 0.1)
    one = rq4_power.simulate(*args, seed=5, reps=30, draws=300)
    assert one == rq4_power.simulate(*args, seed=5, reps=30, draws=300)
    assert one != rq4_power.simulate(*args, seed=6, reps=30, draws=300)


def test_a_perfect_reviewer_recovers_the_planted_prevalence():
    """Recall 1 and specificity 1: every buggy real run is flagged and no clean one, so the flag share is the
    prevalence. With huge counts the estimate equals it to 3 decimals, pooled and worst alike."""
    big = 10_000_000
    found = trust.estimate_from_posteriors({"c00": trust.Posterior(big, 0), "c01": trust.Posterior(big, 0)},
                                           trust.Posterior(big, 0), trust.Posterior(3 * big // 10, 7 * big // 10),
                                           draws=1000, rng=np.random.default_rng(0))
    for name in ("pooled", "worst"):
        assert round(found[name]["prevalence"]["median"], 3) == 0.3
        assert round(found[name]["contamination"]["median"], 3) == 0.0
    row = rq4_power.simulate([1.0, 1.0], [1, 1], 1.0, 100_000, 100_000, 100_000, 0.3, seed=1, reps=5, draws=500)
    assert row["se_mix"] == 1.0 and row["contamination_true"] == 0.0
    for name in ("pooled", "worst"):
        assert row[name]["median_estimate"] == pytest.approx(0.3, abs=0.005)  # the 5-95% interval covers 90%


def test_the_simulation_uses_the_estimator_itself(monkeypatch):
    calls = []
    real = trust.estimate_from_posteriors

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(trust, "estimate_from_posteriors", spy)
    rq4_power.simulate([0.9, 0.9], [1, 1], 0.98, 6, 60, 30, 0.0, seed=1, reps=7, draws=100)
    assert len(calls) == 7


def test_true_contamination_and_mix_recall_match_the_hand_calculation():
    """se (0.9, 0.5), all bugs in the second class, pi 0.3, sp 0.9: se_mix 0.5, contamination 0.15 / (0.15 + 0.63)."""
    row = rq4_power.simulate([0.9, 0.5], [0, 1], 0.9, 6, 60, 30, 0.3, seed=1, reps=3, draws=100)
    assert row["se_mix"] == pytest.approx(0.5)
    assert row["contamination_true"] == pytest.approx(0.15 / 0.78)


def test_a_reviewer_that_is_no_better_than_chance_never_opens_the_gate():
    row = rq4_power.simulate([0.05, 0.05], [1, 1], 0.5, 40, 120, 120, 0.0, seed=2, reps=50, draws=300)
    assert row["worst"]["gate_open"] == 0.0


def _obs(run_id, run_type, bug, tier, flagged):
    return trust.Observation(run_id, run_type, bug, tier, impact.HARMFUL if bug else None, flagged,
                             bug if flagged else None)


OBS = [_obs("a", sealed.CANARY_MEASURE, "B06", "obvious", True), _obs("b", sealed.CANARY_MEASURE, "B06", "subtle", False),
       _obs("c", sealed.CANARY_MEASURE, "B06", "subtle", True), _obs("d", sealed.CANARY_MEASURE, "B01", "obvious", True),
       _obs("e", sealed.CONTROL, None, None, False), _obs("f", sealed.SHAM, None, None, True),
       _obs("g", sealed.CANARY_PROBE, "B01", "subtle", False), _obs("h", sealed.REAL, None, None, True)]


def test_variant_counts_and_class_rates_by_hand():
    counts, clean = rq4_power.variant_counts(OBS)
    assert counts == {("B06", "obvious"): (1, 1), ("B06", "subtle"): (1, 2), ("B01", "obvious"): (1, 1)}
    assert clean == (1, 2)  # probes and real runs are neither recall nor specificity
    rates = rq4_power.class_rates(counts, [("B01", "obvious"), ("B01", "subtle"), ("B06", "subtle")])
    assert rates["B06"] == {"caught": 1, "n": 2, "variants": ["subtle"], "rate": 2 / 4}  # obvious left out
    assert rates["B01"]["rate"] == pytest.approx(2 / 3)  # Beta(2, 1) mean
    summary = rq4_power.pooled_and_worst(rates)
    assert summary == {"pooled": pytest.approx((2 / 3 + 0.5) / 2), "worst_class": "B06", "worst": 0.5}


def test_records_on_disk_become_observations_of_the_same_runs(tmp_path):
    version = "v1:abc"
    for run_id, verdict, record_version in (("a", "pass", version), ("b", "flag", version), ("c", "flag", "v1:other")):
        (tmp_path / f"{run_id}.json").write_text(json.dumps({
            "run_id": run_id, "verdict": verdict, "bug_class": "B03" if verdict == "flag" else None,
            "version": record_version, "tier": "replay"}), encoding="utf-8")
    llm = [OBS[0], OBS[1], OBS[2], _obs("z", sealed.CONTROL, None, None, False)]
    found, missing = rq4_power.records_as_observations(llm, tmp_path, version)
    assert [(o.run_id, o.flagged, o.named_class) for o in found] == [("a", False, None), ("b", True, "B03")]
    assert found[1].bug_id == "B06" and found[1].tier == "subtle"  # truth copied from the same run
    assert missing == ["c", "z"]  # c is another version, z has no record


def test_the_rates_table_labels_every_rate():
    measured = {name: {"counts": {("B01", "obvious"): (3, 3), ("B09", "subtle"): (0, 3)}, "clean": (5, 6),
                       "source": f"{name} source"} for name in ("skeptic_d", "tripwire_v1", "union")}
    rows = rq4_power.rates_table(measured)
    assert {r["status"] for r in rows} == {"measured", "assumed"}
    assert all(r["source"] for r in rows)
    b09 = [r for r in rows if r["reviewer"] == "union" and r["class"] == "B09"]
    assert [r["support"] for r in b09] == ["real_guard_untested"]  # B09 leaves only the tested-guard support
    assert any(r["class"] == "specificity" and r["rate"] == 6 / 8 for r in rows if r["reviewer"] == "skeptic_d")
