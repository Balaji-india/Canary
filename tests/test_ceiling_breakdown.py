"""The arm breakdown's tables, checked against values worked out by hand (no ledger, no network)."""
import json

import pytest

from eval import ceiling_breakdown as cb


def row(run_id, buggy, flagged, bug_id=None, tier=None, named=None, run_type=None, decoy=None, batch="b1",
        focus="wine|f1|svm"):
    run_type = run_type or ("canary_measure" if buggy else "control")
    return {"run_id": run_id, "buggy": buggy, "flagged": flagged, "bug_id": bug_id, "tier": tier, "named": named,
            "run_type": run_type, "decoy": decoy, "batch": batch, "focus": focus}


ROWS = [
    row("c1", True, True, "B01", "obvious", named="B01"),
    row("c2", True, True, "B01", "subtle", named="B03"),
    row("c3", True, False, "B06", "obvious", focus="pc1|f1|knn"),
    row("c4", True, False, "B06", "subtle", focus="pc1|f1|knn", batch="b2"),
    row("k1", False, False, decoy={"bug_id": "B01", "tier": "obvious"}),
    row("k2", False, True, decoy={"bug_id": "B02", "tier": "subtle"}),
    row("s1", False, False, run_type="sham", decoy={"bug_id": "B01", "tier": "subtle"}),
    row("s2", False, False, run_type="sham"),
]


def test_jeffreys_interval_matches_known_values_and_pins_the_ends():
    assert cb.jeffreys(0, 0) is None
    low, high = cb.jeffreys(5, 10)  # Beta(5.5, 5.5): symmetric about one half
    assert low == pytest.approx(1 - high) and low == pytest.approx(0.2235, abs=5e-4)
    assert cb.jeffreys(0, 6)[0] == 0.0 and cb.jeffreys(6, 6)[1] == 1.0
    assert cb.jeffreys(0, 6)[1] == pytest.approx(0.3303, abs=5e-4)  # Beta(0.5, 6.5) at 0.975


def test_recall_is_split_by_class_tier_batch_and_focus():
    recall = cb.recall_tables(ROWS)
    assert (recall["overall"]["hits"], recall["overall"]["of"]) == (2, 4)
    assert {k: (v["hits"], v["of"]) for k, v in recall["by_class"].items()} == {"B01": (2, 2), "B06": (0, 2)}
    assert {k: (v["hits"], v["of"]) for k, v in recall["by_tier"].items()} == {"obvious": (1, 2), "subtle": (1, 2)}
    assert recall["by_class_and_tier"]["B06 subtle"]["value"] == 0.0
    assert {k: (v["hits"], v["of"]) for k, v in recall["by_batch"].items()} == {"b1": (2, 3), "b2": (0, 1)}
    assert {k: (v["hits"], v["of"]) for k, v in recall["by_dataset"].items()} == {"pc1": (0, 2), "wine": (2, 2)}
    assert recall["missed_by_class_and_dataset"] == {"B06 obvious on pc1, f1": 1, "B06 subtle on pc1, f1": 1}


def test_class_naming_counts_only_caught_canaries():
    naming = cb.naming_tables(ROWS)
    assert (naming["overall"]["hits"], naming["overall"]["of"]) == (1, 2)
    assert naming["wrong_names"] == {"B01 named B03": 1} and "B06" not in naming["by_class"]


def test_specificity_is_split_by_type_and_by_decoy():
    spec = cb.specificity_tables(ROWS)
    assert (spec["overall"]["hits"], spec["overall"]["of"]) == (3, 4)
    assert {k: (v["hits"], v["of"]) for k, v in spec["by_type"].items()} == {"control": (1, 2), "sham": (2, 2)}
    assert (spec["with_decoy"]["hits"], spec["with_decoy"]["of"]) == (2, 3)
    assert (spec["without_decoy"]["hits"], spec["without_decoy"]["of"]) == (1, 1)
    assert {k: (v["hits"], v["of"]) for k, v in spec["by_decoy_class"].items()} == {"B01": (2, 2), "B02": (0, 1)}
    assert spec["by_type_and_decoy_tier"]["control subtle"]["value"] == 0.0


def test_repeat_pass_counts_decisions_not_wording():
    truth = {r["run_id"]: r for r in ROWS}
    first = {"c1": {"verdict": "flag", "bug_class": "B01"}, "c2": {"verdict": "flag", "bug_class": "B03"},
             "c3": {"verdict": "pass", "bug_class": None}, "k1": {"verdict": "pass", "bug_class": None}}
    records = [
        {"run_id": "c1", "outcome": "matched"},  # identical reply: no new decision is stored
        {"run_id": "c2", "outcome": "reply_differs", "fields_changed": ["bug_class", "evidence"],
         "new_decision": {"verdict": "flag", "bug_class": "B01"}},
        {"run_id": "c3", "outcome": "reply_differs", "fields_changed": ["verdict", "bug_class", "evidence"],
         "new_decision": {"verdict": "flag", "bug_class": "B06"}},
        {"run_id": "k1", "outcome": "reply_differs", "fields_changed": ["evidence"],
         "new_decision": {"verdict": "pass", "bug_class": None}},
        {"run_id": "zz", "outcome": "reply_differs", "new_decision": {"verdict": "flag", "bug_class": "B01"}},
    ]
    rep = cb.repeat_tables(records, first, truth)
    assert (rep["asked"], rep["buggy_asked"], rep["clean_asked"]) == (4, 3, 1)  # `zz` has no first audit
    assert (rep["verdict_same"]["hits"], rep["bug_class_same"]["hits"]) == (3, 2)
    twice = rep["bug_class_same_when_flagged_twice"]
    assert (twice["hits"], twice["of"]) == (1, 2)
    assert rep["wording_differs"] == 3 and rep["fields_changed"] == {"bug_class": 2, "evidence": 3, "verdict": 1}
    assert rep["verdict_changes"] == {"buggy run: pass then flag": 1}


def test_verdict_summary_gives_j_and_the_verdict_auc():
    summary = cb.verdict_summary(ROWS)  # recall 2/4, false alarms 1/4
    assert summary["youden_j"] == pytest.approx(0.25) and summary["auc_verdict"] == pytest.approx(0.625)
    assert cb.verdict_summary([r for r in ROWS if r["buggy"]])["youden_j"] is None


def test_build_refuses_without_the_locked_arm_file(tmp_path):
    with pytest.raises(SystemExit, match="missing"):
        cb.build("L", table=None, led=None, out_dir=tmp_path)


def test_build_refuses_rows_that_do_not_add_up_to_the_arm_file(tmp_path, monkeypatch):
    locked = {"cells": {"skeptic_d": {"runs": 8, "flagged_buggy": 3, "flagged_clean": 1, "models": ["m"]}},
              "outcome": {"outcome": "SOLVABLE"}}
    (tmp_path / "arm_L.json").write_text(json.dumps(locked), encoding="utf-8")
    monkeypatch.setattr(cb, "detailed_rows", lambda *args: ROWS)  # 2 flagged buggy, not 3
    with pytest.raises(SystemExit, match="do not add up"):
        cb.build("L", table=None, led=None, out_dir=tmp_path)


def test_render_marks_the_side_comparison_and_names_no_run():
    b = {"arm": "L", "role": "skeptic_d", "models": ["m"], "arm_file_outcome": "SOLVABLE", "interval": "i",
         "recall": cb.recall_tables(ROWS), "class_named": cb.naming_tables(ROWS),
         "specificity": cb.specificity_tables(ROWS),
         "repeat_pass": cb.repeat_tables([], {}, {}),
         "side_comparison": {"paired_auc_difference_from_arm_file": None,
                             "same_runs": {"batch": "x", "note": "n", "reviewers": {
                                 "skeptic_d": {"models": ["m"], **cb.verdict_summary(ROWS)}}},
                             "other_runs": {"batch": "y", "note": "n", "reviewers": {}}}}
    text = cb.render(b)
    assert "SIDE COMPARISON, same runs" in text and "Exploratory, decides nothing" in text
    assert not any(r["run_id"] in text.split() for r in ROWS)
