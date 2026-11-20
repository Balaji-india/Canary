"""eval/decisive_share.py (roadmap section 8): synthetic ledgers and run folders only, hand-computed values."""
import json
import math

import pytest

from canary import ledger, prereg, sandbox, sealed, trust
from eval import decisive_share as ds
from tests.test_scientist import lock


def test_the_ten_seed_factor_matches_the_hand_calculation():
    from scipy import stats
    by_hand = (stats.t.ppf(0.975, 9) * math.sqrt(0.1 + 1 / 3)) / (stats.t.ppf(0.975, 4) * math.sqrt(0.2 + 1 / 3))
    assert ds.seed_factor(5, 1 / 3) == pytest.approx(by_hand) and round(by_hand, 3) == 0.734
    assert ds.seed_factor(10, 0.5) == pytest.approx(1.0)
    assert ds.seed_factor(5, 0.1) < ds.seed_factor(5, 1 / 3)  # a smaller test share narrows more


def test_the_split_ratio_is_the_runs_own():
    assert ds.split_ratio({"split_sizes": {"train": [300, 300], "test": [100, 100]}}) == pytest.approx(1 / 3)
    assert ds.split_ratio({"split_sizes": {"train": [400], "test": [100]}}) == pytest.approx(0.25)


@pytest.mark.parametrize("mean, low, high, factor, expected", [
    (0.02, -0.01, 0.05, 0.5, True),     # narrowed to [0.005, 0.035]: above 0, mean >= min_effect -> supported
    (0.02, -0.01, 0.05, 0.9, False),    # narrowed to [-0.007, 0.047]: still crosses 0
    (0.0, -0.01, 0.01, 0.4, True),      # narrowed to [-0.004, 0.004]: below min_effect 0.005 -> not_supported
    (0.0, -0.01, 0.01, 0.6, False),     # narrowed to [-0.006, 0.006]: still reaches the floor
    (0.003, -0.002, 0.008, 1.0, False),
])
def test_the_projection_by_hand(mean, low, high, factor, expected):
    verdict = {"mean_effect": mean, "ci_low": low, "ci_high": high, "min_effect": 0.005}
    assert ds.projected_decisive(verdict, factor) is expected


def test_a_verdict_without_an_interval_is_never_projected_decisive():
    assert not ds.projected_decisive({"mean_effect": 0.5, "ci_low": None, "ci_high": None, "min_effect": 0.005}, 0.1)


def _world(tmp_path, runs):
    """A temporary sealed table, ledger and run folders. `runs`: (run_id, run_type, batch, base hypothesis, scores)."""
    table, led = sealed.SealedTable(tmp_path / "sealed.db"), ledger.Ledger(tmp_path / "ledger.db")
    runs_dir = tmp_path / "runs"
    for run_id, run_type, batch, hypothesis, (control, treatment) in runs:
        locked = lock(hypothesis=hypothesis, dataset="wine" if hypothesis == "B" else "breast_cancer")
        n = len(locked["seeds"])
        results = {"control": [control] * (n - 1) + [control + 0.001], "treatment": [treatment] * n,
                   "split_sizes": {"train": [426] * n, "test": [143] * n}}
        (runs_dir / run_id).mkdir(parents=True)
        (runs_dir / run_id / sandbox.RESULTS_NAME).write_text(json.dumps(results), encoding="utf-8")
        table.seal(run_id, run_type, details={"batch": batch})
        led.append(run_id, ledger.PROPOSED, {})
        led.append(run_id, ledger.PREREGISTERED, {"prereg": locked})
        led.append(run_id, ledger.RAN, {"run_id": run_id, "run_status": "ok",
                                        "verdict": prereg.compute_verdict(locked, results)})
    return table, led, runs_dir


def test_the_check_selects_clean_runs_of_the_batches_through_trust(tmp_path):
    table, led, runs_dir = _world(tmp_path, [
        ("c1", sealed.CONTROL, "rq1-full", "A", (0.80, 0.90)), ("s1", sealed.SHAM, "rq1-full", "A", (0.80, 0.80)),
        ("c2", sealed.CONTROL, "other", "B", (0.80, 0.90)), ("r1", sealed.REAL, "rq1-full", "B", (0.8, 0.9))])
    assert [r[0] for r in trust.clean_runs(table, ["rq1-full"])] == ["c1", "s1"]
    rows, left_out = ds.collect(table, led, runs_dir, ["rq1-full"])
    assert [r["run_id"] for r in rows] == ["c1", "s1"] and left_out == {}
    assert rows[0]["decisive"] and rows[0]["outcome"] == prereg.SUPPORTED


def test_a_verdict_that_does_not_match_the_ledger_stops_the_check(tmp_path):
    table, led, runs_dir = _world(tmp_path, [("c1", sealed.CONTROL, "rq1-full", "A", (0.80, 0.90))])
    (runs_dir / "c1" / sandbox.RESULTS_NAME).write_text(json.dumps(
        {"control": [0.9] * 5, "treatment": [0.8] * 5, "split_sizes": {"train": [426] * 5, "test": [143] * 5}}),
        encoding="utf-8")
    with pytest.raises(ds.VerdictMismatch, match="1 recomputed"):
        ds.collect(table, led, runs_dir, ["rq1-full"])


def test_base_level_and_run_level_by_hand():
    rows = [{"base": "A", "decisive": True, "g10": False}, {"base": "A", "decisive": False, "g10": True},
            {"base": "B", "decisive": True, "g10": False}]
    base = ds.base_level(rows, "decisive")
    assert base["bases"] == 2 and base["share"] == pytest.approx((0.5 + 1.0) / 2)
    assert 0.5 <= base["interval_bootstrap"][0] <= base["interval_bootstrap"][1] <= 1.0
    run = ds.run_level([r["decisive"] for r in rows])
    assert (run["count"], run["n"]) == (2, 3) and run["share"] == pytest.approx(2 / 3)
    from scipy import stats
    assert run["interval_beta"] == pytest.approx(list(stats.beta.ppf([0.05, 0.95], 3, 2)))
    assert ds.base_level(rows, "decisive") == base  # seeded


def _fig(g10, low, high):
    level = {"share": g10, "interval_bootstrap": [low, high], "interval_beta": [low, high]}
    return {"G10": {"base_level": level, "run_level": level}, "D": {"base_level": level, "run_level": level}}


@pytest.mark.parametrize("g10, low, high, seeds, grid", [
    (0.10, 0.25, 0.40, 10, "keep question q1"), (0.09, 0.20, 0.40, 5, "keep question q1"),
    (0.02, 0.05, 0.19, 5, "rare"), (0.02, 0.15, 0.30, 5, "straddles")])
def test_the_rule_by_its_fixed_values(g10, low, high, seeds, grid):
    found = ds.recommend(_fig(g10, low, high), "base_level")
    assert found["seeds_per_arm"] == seeds and grid in found["grid"]
