"""The review-task screen's arithmetic: AUC, the paired delta J, the fixed pass rule, and the rq1-full refusal."""
import json

import numpy as np
import pytest

from canary import ledger, sealed
from canary.ledger import Ledger
from eval import compare_tasks

BUG_IDS = ["B01", "B02"]


def test_auc_counts_ties_as_half_and_is_half_for_no_signal():
    assert compare_tasks.auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert compare_tasks.auc([0.1], [0.9]) == 0.0
    assert compare_tasks.auc([0.5, 0.5], [0.5]) == 0.5
    assert compare_tasks.auc([0.9, 0.3], [0.5, 0.1]) == pytest.approx(3 / 4)  # pairs: 9>5, 9>1, 3<5, 3>1
    assert compare_tasks.auc([], [0.1]) is None


def test_the_bootstrap_keeps_each_group_and_brackets_the_estimate():
    bug, clean = [1.0] * 8 + [0.0] * 2, [1.0] * 2 + [0.0] * 8
    low, high = compare_tasks.bootstrap(bug, clean, lambda b, c: b.mean() - c.mean())
    assert low < 0.6 < high and low > 0  # observed J 0.8 - 0.2 = 0.6


def seal_and_audit(table, led, role, flags, batch="b", task="baseline", **decision_extra):
    """Seal runs and store one audit each. `flags` lists (run type, bug or None, flagged)."""
    for i, (run_type, bug, flagged) in enumerate(flags):
        run, hyp = f"{batch}-r{i:03d}", f"{batch}-h{i:03d}"
        if table.get(run) is None:
            table.seal(run, run_type, bug, "obvious" if bug else None, source="pool:0", details={"batch": batch})
            led.append(hyp, ledger.PROPOSED, {})
            led.append(hyp, ledger.PREREGISTERED, {})
            led.append(hyp, ledger.RAN, {"run_id": run, "run_status": "ok", "results_sha256": "x"})
        verdict = "flag" if flagged else "pass"
        led.append(hyp, ledger.AUDITED, {
            "run_id": run, "role": role, "model": "m:1", "task": task, "seconds": 1.0,
            "audit": {"verdict": "flag", "bug_class": "B01", "evidence": "", "confidence": 0.9},
            "decision": {"verdict": verdict, "bug_class": bug if flagged else None, "raw_verdict": "flag", **decision_extra},
            "score": {"p_flag": 0.9 if flagged else 0.1},
        })


@pytest.fixture
def stores(tmp_path):
    return sealed.SealedTable(tmp_path / "sealed.db"), Ledger(tmp_path / "ledger.db")


def runs(bug_flags, clean_flags):
    bugs = [(sealed.CANARY_MEASURE, BUG_IDS[i % 2], f) for i, f in enumerate(bug_flags)]
    clean = [(sealed.CONTROL if i % 2 else sealed.SHAM, None, f) for i, f in enumerate(clean_flags)]
    return bugs + clean


@pytest.mark.slow  # 0.6-2.4 s (2026-11-11 durations); keeps the default run under 30 s
def test_a_reviewer_that_flags_everything_fails_and_a_discriminating_one_passes(stores):
    table, led = stores
    seal_and_audit(table, led, "skeptic_a", runs([True] * 20, [True] * 20))
    seal_and_audit(table, led, "skeptic_a_grounded", runs([True] * 18 + [False] * 2, [True] * 3 + [False] * 17),
                   task="grounded", line_verified=True)
    result = compare_tasks.build(table, led, "b", BUG_IDS, 4000)
    base, grounded = result["cells"]["skeptic_a"], result["cells"]["skeptic_a_grounded"]
    assert not base["passes_screen"] and base["youden_j"]["observed_j"] == 0
    assert grounded["passes_screen"] and grounded["youden_j"]["observed_j"] == pytest.approx(0.9 - 0.15)
    assert result["passing"] == ["skeptic_a_grounded"]
    # Raw verdicts were all "flag", so without the code's line check the variant would not discriminate.
    assert grounded["raw_verdict_youden_j"]["observed_j"] == 0
    assert grounded["auc"]["value"] == pytest.approx(compare_tasks.auc([0.9] * 18 + [0.1] * 2, [0.9] * 3 + [0.1] * 17))
    delta = grounded["delta_j_vs_baseline"]
    assert delta["runs"] == 40 and delta["observed"] == pytest.approx(0.75)
    assert delta["interval_90"][0] > 0
    assert base["delta_j_vs_baseline"] is None and grounded["line_verified_share"] == 1.0


@pytest.mark.slow  # 0.6-2.4 s (2026-11-11 durations); keeps the default run under 30 s
def test_the_pass_rule_is_the_lower_bound_above_zero_and_nothing_else(stores):
    table, led = stores
    # Observed J 0.6 - 0.4 = 0.2 on 20 + 20 runs: positive, but the interval reaches below 0, so it does not pass.
    seal_and_audit(table, led, "skeptic_b", runs([True] * 12 + [False] * 8, [True] * 8 + [False] * 12))
    c = compare_tasks.build(table, led, "b", BUG_IDS, 4000)["cells"]["skeptic_b"]
    assert c["youden_j"]["observed_j"] == pytest.approx(0.2) and c["youden_j"]["interval"][0] < 0
    assert c["passes_screen"] is False


def test_other_batches_and_other_roles_are_left_out(stores):
    table, led = stores
    seal_and_audit(table, led, "skeptic_a", runs([True] * 4, [False] * 4), batch="other")
    seal_and_audit(table, led, "skeptic_x", runs([True] * 4, [False] * 4), batch="b")
    assert compare_tasks.build(table, led, "b", BUG_IDS, 1000)["cells"] == {}


def test_the_screen_refuses_the_baseline_batch():
    assert compare_tasks.main(["--batch", "rq1-full"]) == 2


def test_the_base_bootstrap_resamples_whole_bases():
    # Two bases, each perfectly separated inside but in opposite directions: pooled AUC 0.5, base draws swing widely.
    items = [("a", True, 0.9), ("a", False, 0.1), ("b", True, 0.1), ("b", False, 0.9)]
    low, high = compare_tasks.base_bootstrap(items, compare_tasks._auc_stat, draws=300)
    assert low <= 0.0 + 1e-9 and high >= 1.0 - 1e-9  # a draw of only "a" gives 1, only "b" gives 0
    # One base cannot be resampled into anything else, so the interval is one value.
    one = compare_tasks.base_bootstrap([("a", True, 0.9), ("a", False, 0.1)], compare_tasks._auc_stat, draws=50)
    assert one == [1.0, 1.0]
    assert compare_tasks.base_bootstrap([], compare_tasks._auc_stat) is None


def test_run_features_read_only_what_the_reviewer_sees(tmp_path):
    run = tmp_path / "r1"
    run.mkdir()
    (run / "experiment.py").write_text("# a comment\nx = 1\n\n\ny = 2\n", encoding="utf-8")
    (run / "results.json").write_text(json.dumps({"control": [0.5, 0.6, 0.7], "treatment": [0.6, 0.8, 0.7]}),
                                      encoding="utf-8")
    f = compare_tasks.run_features("r1", tmp_path)
    assert f["line_count"] == 2  # blinded: the comment and blank lines are gone
    assert f["effect_size"] == pytest.approx(0.1) and f["top_score"] == pytest.approx(0.7)
    assert f["effect_spread"] == pytest.approx(np.std([0.1, 0.2, 0.0], ddof=1))
    assert compare_tasks.run_features("missing", tmp_path) is None


def test_a_feature_that_tracks_the_truth_scores_one_and_rho_needs_variation():
    buggy, base_of = {"b1", "b2"}, {"b1": "x", "b2": "y", "c1": "x", "c2": "y"}
    feats = {"b1": {n: 9.0 for n in compare_tasks.FEATURES}, "b2": {n: 8.0 for n in compare_tasks.FEATURES},
             "c1": {n: 1.0 for n in compare_tasks.FEATURES}, "c2": None}
    fb = compare_tasks.feature_baselines({"b1", "b2", "c1", "c2"}, buggy, base_of, feats)
    assert fb["line_count"]["value"] == 1.0 and fb["line_count"]["scored_clean"] == 1  # c2 has no files
    assert compare_tasks._spearman([(0.1, {"line_count": 3})] * 6) is None  # no variation, no rho
    rho = compare_tasks._spearman([(i / 10, {"line_count": i}) for i in range(6)])
    assert rho["rho"] == pytest.approx(1.0) and rho["n"] == 6
