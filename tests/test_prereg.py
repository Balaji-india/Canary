import pytest

from canary import prereg


def locked(direction="increase", min_effect=0.01):
    return {"direction": direction, "min_effect": min_effect, "alpha": 0.05}


def results(control, treatment, train=426, test=143):
    n = len(control)
    return {"control": control, "treatment": treatment, "split_sizes": {"train": [train] * n, "test": [test] * n}}


# Effects .02 .03 .01 .04 .02 worked out by hand:
#   mean = .024; squared deviations sum to 520e-6; sample variance = 130e-6
#   factor = 1/5 + 143/426 = .535681; corrected variance = 69.64e-6; standard error = .0083451
#   t(.975, df=4) = 2.776445; half width = .023170; interval = [.000830, .047170]
CONTROL = [0.80, 0.80, 0.80, 0.80, 0.80]
TREATMENT = [0.82, 0.83, 0.81, 0.84, 0.82]


def test_interval_matches_the_hand_computation():
    verdict = prereg.compute_verdict(locked(), results(CONTROL, TREATMENT))
    assert verdict["mean_effect"] == pytest.approx(0.024)
    assert verdict["ci_low"] == pytest.approx(0.000830, abs=2e-6)
    assert verdict["ci_high"] == pytest.approx(0.047170, abs=2e-6)
    assert verdict["outcome"] == prereg.SUPPORTED


def test_correction_changes_the_outcome_a_plain_t_interval_would_give():
    """Effects .005 .015 .005 .02 .005: mean .01, sample variance 50e-6.

    Corrected half width: 2.776445 * sqrt(.535681 * 50e-6) = .01437, so the interval reaches below 0: inconclusive.
    Plain t half width: 2.776445 * sqrt(.2 * 50e-6) = .00878, whose interval excludes 0.
    """
    treatment = [0.805, 0.815, 0.805, 0.82, 0.805]
    verdict = prereg.compute_verdict(locked(), results(CONTROL, treatment))
    assert verdict["outcome"] == prereg.INCONCLUSIVE
    assert verdict["ci_high"] - verdict["mean_effect"] == pytest.approx(0.01437, abs=2e-5)
    assert verdict["ci_low"] < 0 < verdict["mean_effect"] - 0.00878


def test_effect_below_min_with_narrow_interval_is_not_supported():
    verdict = prereg.compute_verdict(locked(min_effect=0.05), results(CONTROL, TREATMENT))
    assert verdict["outcome"] == prereg.NOT_SUPPORTED


def test_large_but_noisy_effect_is_inconclusive():
    noisy = [0.95, 0.70, 0.95, 0.70, 0.95]
    assert prereg.compute_verdict(locked(), results(CONTROL, noisy))["outcome"] == prereg.INCONCLUSIVE


def test_decrease_direction_flips_the_sign():
    assert prereg.compute_verdict(locked("decrease"), results(TREATMENT, CONTROL))["outcome"] == prereg.SUPPORTED
    assert prereg.compute_verdict(locked("decrease"), results(CONTROL, TREATMENT))["outcome"] == prereg.NOT_SUPPORTED


def test_effect_in_the_wrong_direction_is_not_supported():
    assert prereg.compute_verdict(locked(), results(TREATMENT, CONTROL))["outcome"] == prereg.NOT_SUPPORTED


def test_identical_arms_are_not_supported():
    verdict = prereg.compute_verdict(locked(), results(CONTROL, CONTROL))
    assert verdict["outcome"] == prereg.NOT_SUPPORTED
    assert verdict["ci_low"] == verdict["ci_high"] == 0


def test_constant_effect_above_min_is_supported():
    treatment = [0.85] * 5
    assert prereg.compute_verdict(locked(), results(CONTROL, treatment))["outcome"] == prereg.SUPPORTED


def test_one_seed_cannot_decide():
    verdict = prereg.compute_verdict(locked(), results([0.8], [0.9]))
    assert verdict["outcome"] == prereg.INCONCLUSIVE and verdict["ci_low"] is None


def test_verdict_is_decided_by_the_locked_thresholds():
    """The same results give a different verdict under different locked thresholds."""
    data = results(CONTROL, TREATMENT)
    assert prereg.compute_verdict(locked(min_effect=0.01), data)["outcome"] == prereg.SUPPORTED
    assert prereg.compute_verdict(locked(min_effect=0.03), data)["outcome"] == prereg.INCONCLUSIVE


def test_hash_ignores_key_order_but_not_values():
    assert prereg.prereg_hash({"a": 1, "b": 2}) == prereg.prereg_hash({"b": 2, "a": 1})
    assert prereg.prereg_hash({"a": 1}) != prereg.prereg_hash({"a": 2})


def test_hash_matches_a_known_value():
    # sha256 of the text {"a":1}
    assert prereg.prereg_hash({"a": 1}) == "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"


def test_canonical_json_refuses_nan():
    with pytest.raises(ValueError):
        prereg.canonical_json({"a": float("nan")})


def test_failed_run_is_inconclusive_with_the_reason():
    verdict = prereg.failed_run_verdict("crash", "exit code 1")
    assert verdict["outcome"] == prereg.INCONCLUSIVE and "crash" in verdict["reason"]
