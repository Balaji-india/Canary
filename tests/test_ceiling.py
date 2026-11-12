"""The ceiling check's frozen analysis (eval/ceiling.py): the rule, its outcomes, and the refusal on unfinished arms."""
import itertools
import json
import random

import numpy as np
import pytest

from canary import ledger, sealed, separation
from canary.ledger import Ledger
from eval import ceiling
from tests.test_skeptic import add_ran_run

DRAWS = 300  # tests check logic, not the third decimal


def test_the_interval_is_97_5_percent_two_sided():
    assert ceiling.PERCENTILES == pytest.approx((1.25, 98.75))


@pytest.mark.parametrize("j_low, auc_low, gap_low, t1, t2, t3", [
    (0.0, 0.50, 0.1, False, False, True),     # lower bound exactly at the bar fails
    (0.41, 0.705, 0.01, True, True, True),
    (0.40, 0.70, 0.2, True, False, True),     # AUC exactly 0.70 fails T2
    (0.5, 0.75, 0.0, True, True, False),      # a gap exactly 0 fails T3
    (0.5, 0.75, None, True, True, False),     # gap not computed: T3 not passed
])
def test_each_test_needs_its_lower_bound_strictly_above_the_bar(j_low, auc_low, gap_low, t1, t2, t3):
    tests = ceiling.cell_tests(j_low, auc_low, 0.9, gap_low, 0.0)
    assert (tests["T1"], tests["T2"], tests["T3"]) == (t1, t2, t3)
    assert tests["passes"] == (t1 and t2 and t3)


def test_more_than_ten_percent_failed_makes_a_cell_void():
    assert not ceiling.cell_tests(0.6, 0.8, 0.9, 0.1, 0.10)["void"]
    void = ceiling.cell_tests(0.6, 0.8, 0.9, 0.1, 0.11)
    assert void["void"] and not void["passes"]


def fake_tests(passes=False, below=False, t1=False, t2=False, void=False):
    return {"T1": t1, "T2": t2, "T3": passes, "void": void, "passes": passes, "below_bar": below}


def test_hard_needs_arm_r_every_cell_none_void_and_every_upper_bound_below():
    below = {f"c{i}": fake_tests(below=True) for i in range(4)}
    assert ceiling.outcome(below, arm_r_run=True, cells_expected=4)["outcome"] == ceiling.HARD
    assert ceiling.outcome(below, arm_r_run=False, cells_expected=4)["outcome"] == ceiling.INCONCLUSIVE
    assert ceiling.outcome(dict(list(below.items())[:3]), True, 4)["outcome"] == ceiling.INCONCLUSIVE
    assert ceiling.outcome({**below, "c3": fake_tests(below=True, void=True)}, True, 4)["outcome"] == ceiling.INCONCLUSIVE
    assert ceiling.outcome({**below, "c3": fake_tests(below=False)}, True, 4)["outcome"] == ceiling.INCONCLUSIVE


def test_the_locked_design_is_two_baseline_cells_at_97_5_on_120_runs():
    assert ceiling.ARMS == {"L": ("skeptic_d",), "R": ("skeptic_e",)} and ceiling.CELLS == 2
    assert ceiling.BATCHES == ("task-dev-2", "ceiling-ext") and ceiling.LEVEL == 0.975
    two = {"L": fake_tests(below=True), "R": fake_tests(below=True)}
    assert ceiling.outcome(two, arm_r_run=True)["outcome"] == ceiling.HARD  # 2 cells are the whole study now
    assert ceiling.outcome({"L": fake_tests(below=True)}, arm_r_run=True)["outcome"] == ceiling.INCONCLUSIVE


def test_one_passing_cell_is_solvable_and_the_subcase_is_named():
    assert ceiling.outcome({"a": fake_tests(passes=True, t1=True, t2=True), "b": fake_tests(below=True)},
                           False) == {"outcome": ceiling.SOLVABLE, "cells": ["a"], "subcase": None}
    works = ceiling.outcome({"a": fake_tests(t1=True), "b": fake_tests()}, False)
    assert works == {"outcome": ceiling.INCONCLUSIVE, "cells": ["a"], "subcase": ceiling.WORKS_STRENGTH_UNKNOWN}


def test_the_outcomes_cannot_overlap_on_any_interval_ends():
    """From real interval ends (low <= high), SOLVABLE's cell has AUC low > 0.70 and so can never be below the bar."""
    rng = random.Random(0)
    for _ in range(3000):
        cells = {}
        for name in "abcd":
            auc_low = rng.uniform(0.4, 1.0)
            auc_high = rng.uniform(auc_low, 1.0)
            j_low = 2 * auc_low - 1
            cells[name] = ceiling.cell_tests(j_low, auc_low, auc_high, rng.uniform(-0.2, 0.2), rng.choice([0, 0.2]))
        result = ceiling.outcome(cells, arm_r_run=rng.random() < 0.5)
        solvable = any(t["passes"] for t in cells.values())
        hard = all(t["below_bar"] for t in cells.values())
        assert not (solvable and hard)
        assert result["outcome"] in (ceiling.SOLVABLE, ceiling.HARD, ceiling.INCONCLUSIVE)
        assert (result["outcome"] == ceiling.SOLVABLE) == solvable


def synthetic_rows(n_bases=12, per_base=4, recall=1.0, false_alarm=0.0, cue=False, seed=0):
    """Two buggy and two clean runs per base. Features flat (padded) or, with `cue`, one that gives buggy runs away."""
    rng = random.Random(seed)
    rows = []
    for b, i in itertools.product(range(n_bases), range(per_base)):
        buggy = i % 2 == 0
        flagged = rng.random() < (recall if buggy else false_alarm)
        features = {f: 1.0 for f in ceiling.FEATURES}
        features["effect_spread"] = rng.random()
        features["top_score"] = (1.0 if buggy else 0.0) if cue else rng.random()
        rows.append({"run_id": f"r{b}-{i}", "base": f"b{b}", "buggy": buggy, "flagged": flagged, "failed": False,
                     "run_type": sealed.CANARY_MEASURE if buggy else sealed.CONTROL, "tier": "obvious" if buggy else None,
                     "features": features})
    return rows


def test_a_perfect_reviewer_passes_and_its_auc_is_one_plus_j_over_two():
    cell = ceiling.analyse_cell(synthetic_rows(), DRAWS)
    assert cell["youden_j"]["value"] == 1.0 and cell["auc_verdict"]["value"] == 1.0
    assert cell["tests"]["passes"]


def test_verdict_auc_equals_one_plus_j_over_two_in_every_draw():
    rows = synthetic_rows(recall=0.7, false_alarm=0.3, seed=3)
    buggy = np.array([r["buggy"] for r in rows])
    flagged = np.array([r["flagged"] for r in rows], dtype=float)
    bases = sorted({r["base"] for r in rows})
    w = ceiling.base_weights(np.array([bases.index(r["base"]) for r in rows]), len(bases), 200, 1)
    w = w[ceiling.usable(w, buggy)]
    assert np.allclose(ceiling.weighted_aucs(flagged, buggy, w), (1 + ceiling.weighted_j(flagged, buggy, w)) / 2)


def test_weighted_auc_matches_the_plain_auc_on_the_observed_runs():
    rows = synthetic_rows(seed=5)
    values = np.array([r["features"]["effect_spread"] for r in rows])
    buggy = np.array([r["buggy"] for r in rows])
    expected = separation.auc(list(values[buggy]), list(values[~buggy]))
    assert ceiling.weighted_aucs(values, buggy, np.ones((1, len(rows))))[0] == pytest.approx(expected)


def test_a_reviewer_that_flags_everything_fails_t1():
    cell = ceiling.analyse_cell(synthetic_rows(recall=1.0, false_alarm=1.0), DRAWS)
    assert cell["youden_j"]["value"] == 0 and not cell["tests"]["T1"] and cell["tests"]["below_bar"]


def test_a_perfect_verdict_does_not_beat_a_perfect_cue():
    cell = ceiling.analyse_cell(synthetic_rows(cue=True), DRAWS)
    assert cell["tests"]["T1"] and cell["tests"]["T2"] and not cell["tests"]["T3"]
    assert cell["gap_vs_strongest_feature"]["strongest_observed"] == "top_score"


def test_a_run_without_features_is_refused_not_dropped():
    rows = synthetic_rows()
    rows[0]["features"] = {}
    with pytest.raises(ValueError, match="lack trivial features"):
        ceiling.analyse_cell(rows, DRAWS)


# ---------- data collection and the refusal on unfinished arms ----------

def batch(tmp_path, types):
    """Runs r0.. sealed in batch b with the given types (canaries named B01 obvious), on two bases."""
    led = Ledger(tmp_path / "ledger.db")
    table = sealed.SealedTable(tmp_path / "sealed.db")
    runs = tmp_path / "runs"
    for i, run_type in enumerate(types):
        add_ran_run(led, runs, f"h{i}", f"r{i}", script=f"x = {i}\n")
        bug = ("B01", "obvious") if run_type == sealed.CANARY_MEASURE else (None, None)
        table.seal(f"r{i}", run_type, *bug, source=f"base{i % 2}", details={"batch": "b"})
    return led, table, runs


def audit(led, i, verdict, role="skeptic_d"):
    led.append(f"h{i}", ledger.AUDITED, {"run_id": f"r{i}", "role": role, "model": "m",
                                         "audit": {"verdict": verdict, "bug_class": None},
                                         "decision": {"verdict": verdict, "bug_class": None}})


def fail(led, i, role="skeptic_d"):
    led.append(f"h{i}", ledger.AUDIT_FAILED, {"run_id": f"r{i}", "role": role, "kind": "invalid_reply"})


TYPES = [sealed.CANARY_MEASURE, sealed.CONTROL, sealed.CANARY_MEASURE, sealed.SHAM]


def test_an_unasked_or_once_failed_run_blocks_the_arm_with_counts_only(tmp_path):
    led, table, runs = batch(tmp_path, TYPES)
    audit(led, 0, "flag")
    audit(led, 1, "pass")
    fail(led, 2)
    collected = {"skeptic_d": ceiling.cell_rows(table, led, ("b",), "skeptic_d", runs)}
    with pytest.raises(ceiling.ArmNotFinished) as caught:
        ceiling.check_finished(collected)
    message = str(caught.value)
    assert "2 answered, 1 not asked yet, 1 failed once" in message
    assert "J" not in message.replace("skeptic_d", "") and "AUC" not in message


def test_runs_that_failed_twice_count_against_the_reviewer(tmp_path):
    led, table, runs = batch(tmp_path, TYPES)
    for i in (0, 0, 1, 1):
        fail(led, i)
    audit(led, 2, "flag")
    audit(led, 3, "pass")
    rows = {r["run_id"]: r for r in ceiling.cell_rows(table, led, ("b",), "skeptic_d", runs)["rows"]}
    assert (rows["r0"]["flagged"], rows["r0"]["failed"]) == (False, True)  # a canary counted as passed
    assert (rows["r1"]["flagged"], rows["r1"]["failed"]) == (True, True)   # a clean run counted as flagged
    assert rows["r2"]["flagged"] and not rows["r3"]["flagged"]
    assert rows["r0"]["features"]["line_count"] > 0 and rows["r0"]["base"] == "batch:b|base0"


def test_only_the_first_audit_counts_and_other_roles_and_batches_are_ignored(tmp_path):
    led, table, runs = batch(tmp_path, TYPES)
    for i in range(4):
        audit(led, i, "pass")
        audit(led, i, "flag")  # a later audit: ignored
        audit(led, i, "flag", role="skeptic_c")
    rows = ceiling.cell_rows(table, led, ("b",), "skeptic_d", runs)["rows"]
    assert [r["flagged"] for r in rows] == [False] * 4
    assert ceiling.cell_rows(table, led, ("other",), "skeptic_d", runs)["rows"] == []


def test_an_arm_is_analysed_once_and_arm_r_only_after_arm_l(tmp_path, monkeypatch):
    led, table, runs = batch(tmp_path, TYPES * 3)
    for i in range(12):
        for role in ceiling.ARMS["L"]:
            audit(led, i, "flag" if i % 2 == 0 else "pass", role)  # canaries are the even runs
    out = tmp_path / "out"
    paths = {"runs_dir": runs, "rescore_dir": tmp_path / "rescore"}
    with pytest.raises(FileNotFoundError, match="after arm L"):
        ceiling.run_arm("R", table, led, ("b",), out, DRAWS, **paths)
    result = ceiling.run_arm("L", table, led, ("b",), out, DRAWS, **paths)
    assert set(result["cells"]) == set(ceiling.ARMS["L"]) and result["code_sha256"] == ceiling.code_sha256()
    assert json.loads((out / "arm_L.json").read_text())["outcome"] == result["outcome"]
    # no pool here, so focus clusters equal base clusters and the sensitivity outcome must agree
    assert result["sensitivity_focus_level"] == {**result["sensitivity_focus_level"], "outcome": result["outcome"],
                                                 "agrees": True}
    with pytest.raises(FileExistsError, match="once per arm"):
        ceiling.run_arm("L", table, led, ("b",), out, DRAWS, **paths)
    if result["outcome"]["outcome"] == ceiling.SOLVABLE:
        with pytest.raises(RuntimeError, match="does not run arm R"):
            ceiling.run_arm("R", table, led, ("b",), out, DRAWS, **paths)


def test_arm_r_may_not_use_other_batches_than_arm_l(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "arm_L.json").write_text(json.dumps({"batches": ["task-dev-2"], "cells": {},
                                                "outcome": {"outcome": ceiling.INCONCLUSIVE}}))
    with pytest.raises(RuntimeError, match="mix two sets of runs"):
        ceiling.run_arm("R", None, None, ("task-dev-2", "ceiling-ext"), out, DRAWS)


# ---------- clusters: what the bootstraps resample ----------

def pool_base(dataset="wine", model="knn", scaler="robust_scaler", params=None, metric="f1"):
    """One pool entry: `scaler` against no scaling on one model. `params` are the model's hyperparameters."""
    params = params or {"n_neighbors": 5}
    return {"focus": {"dataset": dataset, "metric": metric, "model": model},
            "prereg": {"hypothesis": "h", "dataset": dataset, "metric": metric, "test_size": 0.25, "seeds": [1, 2],
                       "control_config": {"model": model, "params": params, "preprocessing": []},
                       "treatment_config": {"model": model, "params": params, "preprocessing": [scaler]}}}


def two_pools(tmp_path, pool_1, pool_2, sources=(("b1", "pool:0"), ("b1", "pool:1"), ("b2", "pool:0"), ("b2", "pool:1"))):
    """Batch b1 on pool 1 and b2 on pool 2 (plans store a Windows-style relative path), one audited run per source."""
    led, table, runs = Ledger(tmp_path / "ledger.db"), sealed.SealedTable(tmp_path / "sealed.db"), tmp_path / "runs"
    plans = tmp_path / "plans"
    plans.mkdir()
    for batch_name, name, bases in (("b1", "pool.json", pool_1), ("b2", "pool-2.json", pool_2)):
        (tmp_path / name).write_text(json.dumps({"bases": bases, "dropped": []}), encoding="utf-8")
        (plans / f"{batch_name}.json").write_text(json.dumps({"batch": batch_name, "pool": name}), encoding="utf-8")
    for i, (batch_name, source) in enumerate(sources):
        add_ran_run(led, runs, f"h{i}", f"r{i}", script=f"x = {i}\n")
        bug = ("B01", "obvious") if i % 2 == 0 else (None, None)
        table.seal(f"r{i}", sealed.CANARY_MEASURE if i % 2 == 0 else sealed.CONTROL, *bug, source=source,
                   details={"batch": batch_name})
        audit(led, i, "flag")
    return led, table, runs, plans


def test_the_same_pool_index_in_two_pools_is_two_clusters(tmp_path):
    """task-dev-2 (pool 1) and ceiling-ext (pool 2) both have a `pool:0`; the bootstrap must not merge them."""
    pool_1 = [pool_base(scaler="robust_scaler"), pool_base(dataset="digits")]
    pool_2 = [pool_base(scaler="standard_scaler"), pool_base(dataset="pc1")]
    led, table, runs, plans = two_pools(tmp_path, pool_1, pool_2)
    rows = {r["run_id"]: r for r in ceiling.cell_rows(table, led, ("b1", "b2"), "skeptic_d", runs, plans, tmp_path)["rows"]}
    assert len({r["base"] for r in rows.values()}) == 4
    assert rows["r0"]["base"] != rows["r2"]["base"]  # same index, another comparison


def test_near_twins_across_pools_are_one_cluster(tmp_path):
    """The student's rule: bases that differ only in a model hyperparameter (and seeds, wording) are one cluster."""
    twin_1 = pool_base(dataset="blood", model="decision_tree", params={"max_depth": 5, "min_samples_leaf": 2})
    twin_2 = pool_base(dataset="blood", model="decision_tree", params={"max_depth": 5, "min_samples_leaf": 1})
    twin_2["prereg"].update(seeds=[8, 9], hypothesis="other words")
    led, table, runs, plans = two_pools(tmp_path, [pool_base(), twin_1], [pool_base(scaler="minmax_scaler"), twin_2])
    rows = {r["run_id"]: r for r in ceiling.cell_rows(table, led, ("b1", "b2"), "skeptic_d", runs, plans, tmp_path)["rows"]}
    assert rows["r1"]["base"] == rows["r3"]["base"]            # the twins: pool 1 index 1 and pool 2 index 1
    assert len({r["base"] for r in rows.values()}) == 3        # 4 bases, 3 clusters
    assert ceiling.analyse_cell(list(rows.values()), DRAWS)["bases"] == 3  # and the bootstrap resamples 3


def test_the_comparison_key_keeps_everything_but_hyperparameters_seeds_and_wording():
    key = ceiling.comparison_key(pool_base()["prereg"])
    assert key == ceiling.comparison_key(pool_base(params={"n_neighbors": 9})["prereg"])
    for other in (pool_base(dataset="digits"), pool_base(model="svm"), pool_base(scaler="minmax_scaler"),
                  pool_base(metric="accuracy")):
        assert ceiling.comparison_key(other["prereg"]) != key
    changed = pool_base()
    changed["prereg"]["test_size"] = 0.3
    assert ceiling.comparison_key(changed["prereg"]) != key
    changed = pool_base()
    changed["prereg"]["control_config"]["preprocessing"] = ["minmax_scaler"]
    assert ceiling.comparison_key(changed["prereg"]) != key


def test_focus_clusters_join_the_two_pools_bases_on_one_grid_cell(tmp_path):
    """Pool 2 is asked on pool 1's grid: the sensitivity bootstrap treats one dataset | metric | model as one cluster."""
    pool_1 = [pool_base(scaler="robust_scaler"), pool_base(dataset="digits")]
    pool_2 = [pool_base(scaler="standard_scaler"), pool_base(dataset="digits", scaler="minmax_scaler")]
    led, table, runs, plans = two_pools(tmp_path, pool_1, pool_2)
    rows = ceiling.cell_rows(table, led, ("b1", "b2"), "skeptic_d", runs, plans, tmp_path)["rows"]
    assert len({r["base"] for r in rows}) == 4 and sorted({r["focus"] for r in rows}) == ["digits|f1|knn", "wine|f1|knn"]
    for r in rows:
        r["features"] = {f: 1.0 for f in ceiling.FEATURES}
    assert ceiling.focus_sensitivity(rows, DRAWS)["clusters"] == 2 and ceiling.analyse_cell(rows, DRAWS)["bases"] == 4


def test_a_missing_pool_file_is_refused_not_guessed(tmp_path):
    led, table, runs, plans = two_pools(tmp_path, [pool_base(), pool_base(dataset="digits")],
                                        [pool_base(scaler="minmax_scaler"), pool_base(dataset="pc1")])
    (tmp_path / "pool-2.json").unlink()
    ceiling._pool_bases.cache_clear()
    with pytest.raises(ValueError, match="pool file .* is missing"):
        ceiling.cell_rows(table, led, ("b1", "b2"), "skeptic_d", runs, plans, tmp_path)
