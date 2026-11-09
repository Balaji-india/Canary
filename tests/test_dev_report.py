"""The development report's decoy diagnostic: flag rate and mean score on clean runs by decoy class, against plain
clean runs of the reference batch. Numbers are small and hand-checkable."""
import json

import pytest

from canary import ledger, sealed, separation
from canary.ledger import Ledger
from eval import cutoff, dev_report


def add_run(table, led, runs, run_id, batch, run_type, score, flagged, decoy=None, base="pool:0"):
    bug = ("B01", "obvious") if run_type == sealed.CANARY_MEASURE else (None, None)
    details = {"batch": batch, **({"decoy": {"bug_id": decoy[0], "tier": decoy[1]}} if decoy else {})}
    table.seal(run_id, run_type, *bug, source=base, details=details)
    (runs / run_id).mkdir(parents=True)
    (runs / run_id / "experiment.py").write_text("x = 1\n", encoding="utf-8")
    (runs / run_id / "results.json").write_text(json.dumps({"control": [0.8, 0.9], "treatment": [0.8, 0.9]}),
                                                encoding="utf-8")
    hyp = f"h-{run_id}"
    led.append(hyp, ledger.PROPOSED, {})
    led.append(hyp, ledger.PREREGISTERED, {})
    led.append(hyp, ledger.RAN, {"run_id": run_id, "run_status": "ok", "results_sha256": "x"})
    verdict = "flag" if flagged else "pass"
    led.append(hyp, ledger.AUDITED, {
        "run_id": run_id, "role": cutoff.ROLE, "model": "llama3.1:8b", "task": "checklist", "seconds": 1.0,
        "prompt_sha256": "p", "audit": {}, "score": {"p_flag": score},
        "decision": {"verdict": verdict, "bug_class": "B01" if flagged else None}})


@pytest.fixture
def stores(tmp_path):
    table, led, runs = sealed.SealedTable(tmp_path / "s.db"), Ledger(tmp_path / "l.db"), tmp_path / "runs"
    # Development batch: two canaries; clean runs with B10 decoys (code), a B03 pair (subtle has code, obvious none).
    add_run(table, led, runs, "k1", "dev", sealed.CANARY_MEASURE, 0.9, True, base="pool:0")
    add_run(table, led, runs, "k2", "dev", sealed.CANARY_MEASURE, 0.7, True, base="pool:1")
    add_run(table, led, runs, "c1", "dev", sealed.CONTROL, 0.8, True, ("B10", "obvious"), "pool:0")
    add_run(table, led, runs, "c2", "dev", sealed.SHAM, 0.6, False, ("B10", "subtle"), "pool:1")
    add_run(table, led, runs, "c3", "dev", sealed.CONTROL, 0.4, False, ("B03", "subtle"), "pool:0")
    add_run(table, led, runs, "c4", "dev", sealed.SHAM, 0.2, False, ("B03", "obvious"), "pool:1")
    # Reference batch: plain clean runs, no decoys.
    add_run(table, led, runs, "p1", "ref", sealed.CONTROL, 0.3, False)
    add_run(table, led, runs, "p2", "ref", sealed.SHAM, 0.5, True)
    return table, led, runs


def test_the_decoy_diagnostic_groups_clean_runs_by_decoy_class(stores, monkeypatch):
    monkeypatch.setattr(separation, "BOOTSTRAP_DRAWS", 50)  # no interval is checked here; the suite has a 30 s limit
    table, led, runs = stores
    result = dev_report.build(table, led, "dev", runs, {"cutoff": 0.65}, reference_batch="ref")
    d = result["decoy_diagnostic"]
    assert d["by_decoy_class"]["B10"]["flagged"] == 1 and d["by_decoy_class"]["B10"]["mean_p_flag"] == pytest.approx(0.7)
    assert d["by_decoy_class"]["B03"]["variants"] == ["obvious (no code)", "subtle"]
    assert d[dev_report.WITH_CODE] == {"runs": 3, "flagged": 1, "flag_rate": pytest.approx(1 / 3),
                                       "mean_p_flag": pytest.approx(0.6), "scored": 3}  # c1, c2, c3
    assert d[dev_report.NO_CODE]["runs"] == 1 and d[dev_report.NO_CODE]["mean_p_flag"] == pytest.approx(0.2)
    plain = d[f"{dev_report.PLAIN} (ref)"]
    assert plain["runs"] == 2 and plain["flag_rate"] == 0.5 and plain["mean_p_flag"] == pytest.approx(0.4)
    # Canaries 0.9 and 0.7 against clean 0.8, 0.6, 0.4, 0.2: 7 of 8 pairs in order.
    assert result["auc"]["value"] == pytest.approx(7 / 8)
    assert result["at_own_cutoff"] == {"cutoff": 0.65, "recall": 1.0, "false_alarm_rate": 0.25}


def test_the_report_refuses_a_confirmation_batch():
    assert dev_report.main(["--batch", "confirm-llama-2"]) == 2
