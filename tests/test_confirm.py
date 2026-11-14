"""The confirmation's locks and rules: cut-off choice and lock, hash checks, H1-H3, and the power arithmetic."""
import json
import math

import pytest

from canary import ledger, sealed
from canary.ledger import Ledger
from eval import confirm, confirm_power, cutoff


def test_cutoff_maximises_j_and_takes_the_lowest_on_a_tie():
    best = cutoff.choose_cutoff([0.9, 0.8, 0.3], [0.2, 0.7, 0.1])
    assert best["j"] == pytest.approx(2 / 3)  # flag >= 0.75: 2 of 3 buggy, 0 of 3 clean
    assert best["cutoff"] == pytest.approx(0.25)  # ties with 0.75 (3/3 - 1/3); the lower one wins
    assert best["tied_candidates"] == 2 and best["recall"] == 1.0


def test_a_cutoff_is_locked_once(tmp_path):
    path = tmp_path / "cut.json"
    digest = cutoff.lock(path, {"cutoff": 0.5})
    assert digest == cutoff.sha256_file(path)
    with pytest.raises(cutoff.LockError):
        cutoff.lock(path, {"cutoff": 0.4})
    assert json.loads(path.read_text(encoding="utf-8")) == {"cutoff": 0.5}


def test_the_plan_and_cutoff_hashes_are_checked(tmp_path):
    cut = tmp_path / "cut.json"
    digest = cutoff.lock(cut, {"cutoff": 0.5})
    plan, plan_hash = tmp_path / "plan.md", tmp_path / "plan.md.sha256"
    plan.write_text(f"Cut-off file SHA-256: `{digest}`\n", encoding="utf-8")
    plan_hash.write_text(cutoff.sha256_file(plan) + "  plan.md\n", encoding="utf-8")
    assert confirm.verify_locks(plan, plan_hash, cut)["cutoff_sha256"] == digest
    plan.write_text(plan.read_text(encoding="utf-8") + "edited\n", encoding="utf-8")
    with pytest.raises(confirm.LockError, match="edited"):
        confirm.verify_locks(plan, plan_hash, cut)


def batch(tmp_path, bug_scores, clean_scores, bases=6, helper=lambda buggy: 21):
    """Sealed runs with one checklist audit each, a script and results per run (all the same length and numbers),
    spread over bases. `helper` gives each run's padding-helper size from whether it is buggy."""
    table, led, runs = sealed.SealedTable(tmp_path / "s.db"), Ledger(tmp_path / "l.db"), tmp_path / "runs"
    rows = [(sealed.CANARY_MEASURE, s) for s in bug_scores] + [(sealed.CONTROL, s) for s in clean_scores]
    for i, (run_type, score) in enumerate(rows):
        run, hyp = f"r{i:03d}", f"h{i:03d}"
        bug = ("B01", "obvious") if run_type == sealed.CANARY_MEASURE else (None, None)
        table.seal(run, run_type, *bug, source=f"pool:{i % bases}",
                   details={"batch": "c", "padding": {"statements": helper(run_type == sealed.CANARY_MEASURE)}})
        (runs / run).mkdir(parents=True)
        (runs / run / "experiment.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        (runs / run / "results.json").write_text(json.dumps({"control": [0.8, 0.9], "treatment": [0.85, 0.9]}),
                                                 encoding="utf-8")
        led.append(hyp, ledger.PROPOSED, {})
        led.append(hyp, ledger.PREREGISTERED, {})
        led.append(hyp, ledger.RAN, {"run_id": run, "run_status": "ok", "results_sha256": "x"})
        led.append(hyp, ledger.AUDITED, {
            "run_id": run, "role": confirm.ROLE, "model": "llama3.1:8b", "task": "checklist", "seconds": 1.0,
            "prompt_sha256": "p", "audit": {}, "score": {"p_flag": score},
            "decision": {"verdict": "pass", "bug_class": None}})
    return table, led, runs


@pytest.mark.slow  # 0.6-2.4 s (2026-11-11 durations); keeps the default run under 30 s
def test_a_separating_score_is_confirmed_and_a_flat_one_is_not(tmp_path):
    table, led, runs = batch(tmp_path / "a", [0.8, 0.7, 0.9, 0.6, 0.85, 0.75], [0.2, 0.3, 0.1, 0.4, 0.25, 0.35])
    result = confirm.build(table, led, "c", 0.5, ["B01"], 200, runs, tmp_path / "rescore")
    assert result["H1"]["j_at_cutoff"] == 1.0 and result["H2"]["value"] == 1.0
    # Every trivial feature is constant here (AUC 0.5), so H3 = 1.0 - 0.5.
    assert result["H3"]["value"] == pytest.approx(0.5) and result["H3"]["runs"] == 12
    assert all(result[h]["passes"] for h in ("H1", "H2", "H3")) and result["confirmed"]

    table, led, runs = batch(tmp_path / "b", [0.5] * 6, [0.5] * 6)
    flat = confirm.build(table, led, "c", 0.5, ["B01"], 200, runs, tmp_path / "rescore")
    assert flat["H2"]["value"] == 0.5 and not flat["confirmed"]


@pytest.mark.slow
def test_h3_fails_when_the_helper_size_separates_as_well_as_the_score(tmp_path):
    """The amended H3: a perfect score does not confirm if the helper's size alone separates just as well."""
    # Six bases, each with one canary and one control, so every bootstrap draw keeps both kinds.
    table, led, runs = batch(tmp_path, [0.8, 0.7, 0.9, 0.6, 0.85, 0.75], [0.2, 0.3, 0.1, 0.4, 0.25, 0.35],
                             helper=lambda buggy: 6 if buggy else 21)
    result = confirm.build(table, led, "c", 0.5, ["B01"], 200, runs, tmp_path / "rescore")
    assert result["H2"]["passes"]
    assert result["H3"]["strongest_feature"] == "helper_statements"
    assert result["H3"]["feature_auc"]["helper_statements"] == 0.0  # lower on buggy runs: direction-free 1.0
    assert result["H3"]["value"] == pytest.approx(0.0) and not result["H3"]["passes"] and not result["confirmed"]


def test_h3_power_is_the_one_sided_error_rate_when_the_score_only_ties_the_feature():
    assert confirm_power.h3_power(0.85, 0.85, 60, 40, 1.27) == pytest.approx(0.05)
    assert confirm_power.h3_power(0.95, 0.85, 60, 40, 1.0) > confirm_power.h3_power(0.90, 0.85, 60, 40, 1.0)


def test_power_uses_hanley_mcneil_and_rises_with_the_effect():
    # Hanley-McNeil at AUC 0.5: Q1 = 1/3, Q2 = 1/3, so SE^2 = (0.25 + 59/12 + 39/12) / 2400.
    assert confirm_power.auc_se(0.5, 60, 40) == pytest.approx(math.sqrt((0.25 + 59 / 12 + 39 / 12) / 2400))
    low, high = (confirm_power.power(a, 0.5, confirm_power.auc_se(a, 60, 40), 1.0) for a in (0.6, 0.75))
    assert 0 < low < high < 1
    assert confirm_power.power(0.5, 0.5, 0.05, 1.0) == pytest.approx(0.05)  # no effect: the one-sided 5% error rate


def test_the_superseded_batch_and_dev_batches_are_refused_and_cutoffs_come_from_dev_batches(capsys):
    assert confirm.main(["--batch", "confirm-llama-1"]) == 2  # the v1 plan's batch: superseded, never confirmable
    assert confirm.main(["--batch", "task-dev-2"]) == 2  # the batch that chose the cut-off cannot confirm it
    assert cutoff.main(["--batch", "confirm-llama-2"]) == 2  # a cut-off is never chosen on the batch that tests it
    assert cutoff.cutoff_path("task-dev-2").parent.name == "task_dev_2"
    assert confirm.PLAN_PATH.name == "llama_checklist_confirmation_v2.md"
