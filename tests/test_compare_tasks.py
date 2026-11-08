"""The review-task screen's arithmetic: AUC, the paired delta J, the fixed pass rule, and the rq1-full refusal."""
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
