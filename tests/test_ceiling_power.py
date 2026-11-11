"""The batch-size simulation (eval/ceiling_power.py) on small synthetic layouts: no pool file, no sealed data."""
import numpy as np
import pytest

from canary import config
from eval import ceiling, ceiling_power as cp

FEATURES = {f: {"auc": 0.5, "icc": 0.3} for f in cp.LATENT_FEATURES}


def synthetic_layout(bases=16, per_base=4):
    base = np.repeat(np.arange(bases), per_base)
    buggy = np.tile([True, False], bases * per_base // 2)
    return {"base": base, "buggy": buggy, "bases": bases, "runs": len(base),
            "features": {f: np.ones(len(base)) for f in cp.LAYOUT_FEATURES}}


def run_cell(j, sims=60, icc=0.0, bases=16):
    lay = synthetic_layout(bases)
    rng = np.random.default_rng(0)
    w = ceiling.base_weights(lay["base"], lay["bases"], 300, 0)
    w = w[ceiling.usable(w, lay["buggy"])]
    bank = cp.strongest_bank(lay, w, FEATURES, 5, rng)
    return cp.simulate(lay, j, icc, w, bank, sims, rng)


def test_a_chance_reviewer_is_never_solvable_and_usually_below_the_bar():
    cell = run_cell(0.0)
    assert cell["p_solvable_cell"] == 0 and cell["p_below_bar_cell"] > 0.6  # about 0.8 at 64 runs on 16 bases


def test_a_strong_reviewer_on_many_runs_is_usually_solvable():
    cell = run_cell(0.9, bases=40)
    assert cell["p_solvable_cell"] > 0.9 and cell["p_below_bar_cell"] == 0


def test_study_outcomes_add_up_to_one():
    study = run_cell(0.5)["study_independent_cells"]
    assert sum(study.values()) == pytest.approx(1.0)


def test_the_simulation_calls_the_frozen_rule(monkeypatch):
    calls = []
    real = ceiling.cell_tests
    monkeypatch.setattr(ceiling, "cell_tests", lambda *a: calls.append(a) or real(*a))
    run_cell(0.7, sims=10)
    assert len(calls) == 10


def test_a_clustered_verdict_gives_less_power():
    loose, clustered = run_cell(0.7, sims=150, icc=0.0), run_cell(0.7, sims=150, icc=0.6)
    assert clustered["p_solvable_cell"] < loose["p_solvable_cell"]


def grid(power: dict, fp: dict) -> dict:
    return {f"{cp.PRIMARY_ICC:.1f}": {str(n): {"0.70": {"p_solvable_cell": power[n]}, "0.40": {"p_solvable_cell": fp[n]}}
                                      for n in cp.SIZES}}


def test_the_criterion_takes_the_smallest_size_meeting_both_parts():
    power = dict(zip(cp.SIZES, (0.2, 0.7, 0.85, 0.95, 0.99)))
    fp = dict(zip(cp.SIZES, (0.0, 0.01, 0.02, 0.01, 0.01)))  # 4 x 0.02 = 0.08 fails at 120
    assert cp.criterion(grid(power, fp))["chosen_runs"] == 160


def test_the_criterion_says_so_when_it_cannot_be_met():
    power = dict(zip(cp.SIZES, (0.2, 0.3, 0.4, 0.5, 0.6)))
    ok_fp = dict(zip(cp.SIZES, (0.0,) * 5))
    assert cp.criterion(grid(power, ok_fp))["chosen_runs"] == 200
    bad_fp = dict(zip(cp.SIZES, (0.02,) * 5))
    result = cp.criterion(grid(dict(zip(cp.SIZES, (0.9,) * 5)), bad_fp))
    assert result["chosen_runs"] is None and "interval level" in result["why"]


def test_a_size_with_too_many_false_positives_is_never_chosen():
    """The real 97.5% result's shape: the FP part holds only at 40 runs, where power is far too low."""
    power = dict(zip(cp.SIZES, (0.25, 0.75, 0.93, 0.99, 1.0)))
    fp = dict(zip(cp.SIZES, (0.008, 0.016, 0.018, 0.019, 0.022)))
    result = cp.criterion(grid(power, fp))
    assert result["chosen_runs"] is None and "interval level" in result["why"]


def test_cost_counts_calls_days_and_laptop_time_from_the_config():
    models = config.load_yaml("models.yaml")
    times = {"pool_seconds_per_base": 30.0, "run_seconds_per_run": 6.0}
    c = cp.cost(80, models, times, 18)
    assert (c["task_dev_2_runs"], c["fresh_pool_2_runs"]) == (40, 40)
    assert c["calls_per_arm"] == 2 * 80 + 2 * 20 + 4
    assert c["laptop_minutes"] == pytest.approx((18 * 30 + 40 * 6) / 60, abs=0.05)
    groq = models["providers"]["groq"]
    per_day = min(groq["max_calls_per_day"], groq["max_tokens_per_day"] // groq["expected_tokens_per_call"])
    assert c["arms"]["L"]["calls_per_day"] == per_day and c["arms"]["L"]["days"] == -(-c["calls_per_arm"] // per_day)
    assert cp.cost(120, models, times, 18, prompts=1)["calls_per_arm"] == 120 + 20 + 3  # the 2-cell design
    assert cp.cost(40, models, times, 18)["laptop_minutes"] == 0 and cp.cost(None, models, times, 18) is None


def study_grid(power: dict, fp: dict) -> dict:
    """{level: grid} with the same numbers under every ICC: power[(level, size)], fp[(level, size)] per cell."""
    return {level: {f"{icc:.1f}": {str(size): {"0.70": {"p_solvable_cell": power[(level, size)]},
                                             "0.40": {"p_solvable_cell": fp[(level, size)], "mc_se_solvable": 0.0}}
                                  for size in cp.STUDY_SIZES} for icc in cp.STUDY_ICCS}
            for level in cp.STUDY_LEVELS}


def test_the_design_rule_takes_each_designs_least_strict_level_then_the_fewest_calls():
    keys = [(level, size) for level in cp.STUDY_LEVELS for size in cp.STUDY_SIZES]
    power = {k: 0.9 for k in keys}
    fp = {k: 0.02 for k in keys}  # 4 x 0.02 = 0.08 fails the 4-cell design; 2 x 0.02 = 0.04 passes the 2-cell one
    fp.update({(0.99, 120): 0.01, (0.99, 160): 0.01, (0.995, 120): 0.005, (0.995, 160): 0.005})
    study = cp.choose_design(study_grid(power, fp))
    picks = {p["design"]: (p["level"], p["runs"]) for p in study["per_design_picks"]}
    assert picks == {"4-cell": (0.99, 120), "2-cell": (0.975, 120)}
    assert (study["choice"]["design"], study["choice"]["calls_per_arm"]) == ("2-cell", 143)


def test_a_design_must_qualify_under_every_icc():
    keys = [(level, size) for level in cp.STUDY_LEVELS for size in cp.STUDY_SIZES]
    grid = study_grid({k: 0.9 for k in keys}, {k: 0.001 for k in keys})
    for level in cp.STUDY_LEVELS:
        for size in cp.STUDY_SIZES:
            grid[level]["0.4"][str(size)]["0.70"]["p_solvable_cell"] = 0.79  # one ICC short of power
    assert cp.choose_design(grid)["choice"] is None
