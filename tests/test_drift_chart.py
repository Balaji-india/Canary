"""canary/drift.py chart state (Mission 4.3 step 3): fresh charts, the sentinel chart, alarms, look-back, layer C.
Synthetic records only."""
import ast
from pathlib import Path

import pytest

from canary import drift, sealed
from canary.drift import AcceptedRun, ChartObservation, SentinelRecord

ROOT = Path(__file__).resolve().parent.parent


def clean_run(i, epoch="e1", flagged=False, **kw):
    return ChartObservation(f"{epoch}-c{i:03d}", epoch, i, "control" if i % 2 else "sham", None, None, flagged, **kw)


def canary(i, bug, tier, epoch="e1", flagged=True, **kw):
    return ChartObservation(f"{epoch}-{bug}-{tier}-{i:03d}", epoch, i, sealed.CANARY_MEASURE, bug, tier, flagged, **kw)


# ---- module boundaries -------------------------------------------------------------------------------------------

def test_run_type_names_match_the_sealed_table():
    assert drift.MEASURE_TYPE == sealed.CANARY_MEASURE and drift.PROBE_TYPE == sealed.CANARY_PROBE
    assert set(drift.CLEAN_TYPES) == {sealed.CONTROL, sealed.SHAM}


def test_drift_opens_nothing():
    """Sitting 1 is arithmetic on given records: no database, ledger, sealed table, run folder or model."""
    tree = ast.parse((ROOT / "canary" / "drift.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
            if node.module == "canary" or (node.module or "").startswith("canary."):
                names |= {f"canary.{a.name}" for a in node.names}
    assert names <= {"__future__", "dataclasses", "functools", "numpy", "scipy", "argparse"}, names
    source = (ROOT / "canary" / "drift.py").read_text(encoding="utf-8")
    assert "open(" not in source and "sqlite" not in source


# ---- fresh charts ------------------------------------------------------------------------------------------------

def test_a_window_never_crosses_an_epoch():
    obs = [clean_run(i, "e1" if i % 3 else "e2", flagged=i % 7 == 0) for i in range(120)]
    state = drift.chart(obs, (2, 160), "clean", "e1")
    for w in state["windows"]:
        assert all(run.startswith("e1-") for run in w["runs"])
    used = sum(len(w["runs"]) for w in state["windows"]) + state["partial"]["runs"]
    assert used == sum(o.epoch == "e1" for o in obs) and state["left_out"]["other_epoch"] == 40
    assert len(state["windows"]) == 80 // 20 and state["partial"]["runs"] == 0


def test_windows_follow_review_order_and_count_false_alarms():
    obs = [clean_run(i, flagged=i in (3, 5, 21)) for i in reversed(range(45))]   # given newest first
    state = drift.chart(obs, (2, 160), "clean", "e1")
    assert state["counts"] == [2, 1] and state["partial"] == {"runs": 5, "count": 0}
    assert state["windows"][0]["first_order"] == 0 and state["windows"][1]["last_order"] == 39


def test_probes_and_failed_audits_are_left_out():
    obs = [clean_run(i) for i in range(20)]
    obs += [ChartObservation("probe", "e1", 50, sealed.CANARY_PROBE, "B01", "obvious", False),
            clean_run(60, flagged=True, failed=True)]
    state = drift.chart(obs, (2, 160), "clean", "e1")
    assert state["counts"] == [0] and state["left_out"]["probe"] == 1 and state["left_out"]["failed"] == 1
    support = [("B01", "obvious")]
    cans = [canary(i, "B01", "obvious", flagged=i != 4) for i in range(20)]
    cans += [ChartObservation("p2", "e1", 70, sealed.CANARY_PROBE, "B01", "obvious", False),
             canary(71, "B01", "obvious", flagged=False, failed=True), canary(72, "B06", "obvious", flagged=False)]
    state = drift.chart(cans, (3, 170), "canary", "e1", support)
    assert state["counts"] == [1]                                       # misses, measuring canaries only
    assert state["left_out"] == {"other_epoch": 0, "probe": 1, "failed": 1, "other_type": 0, "outside_support": 1}


def test_unverifiable_counts_as_a_flag_and_is_listed():
    obs = [clean_run(i, unverifiable=(i == 7)) for i in range(20)]
    state = drift.chart(obs, (2, 160), "clean", "e1")
    assert state["counts"] == [1] and state["windows"][0]["unverifiable"] == ["e1-c007"]


def test_the_canary_chart_needs_a_support():
    with pytest.raises(ValueError):
        drift.chart([], (0, 10), "canary", "e1")
    with pytest.raises(ValueError):
        drift.chart([], (0, 10), "probes", "e1")


# ---- the sentinel chart ------------------------------------------------------------------------------------------

def sentinel(buggy, clean, opening=(1, 0)):
    return drift._demo_sentinel("e1", buggy, clean, opening)


def test_sentinel_baseline_flips_and_directions():
    records, refs, _ = sentinel([2, 0], [0, 1], opening=(1, 2))
    state = drift.sentinel_chart(records, refs, "e1")
    assert state["baseline"] == {"buggy": [1, 30], "clean": [2, 30]}
    assert state["halves"]["buggy"]["counts"] == [2, 0] and state["halves"]["clean"]["counts"] == [0, 1]
    # slice 0 asks buggy runs 0..9: runs 0 and 1 have reference "flag", so their flips are flag -> pass
    assert state["halves"]["buggy"]["directions"][0] == {"flag_to_pass": 2, "pass_to_flag": 0}
    assert state["halves"]["clean"]["directions"][1] == {"flag_to_pass": 0, "pass_to_flag": 1}
    assert state["halves"]["buggy"]["limits"]["baseline"] == [1, 30]


def test_a_reference_verdict_pass_that_turns_into_flag_is_a_flip():
    """Buggy run s-b03 has reference "pass" (a miss in its first audit); a re-ask that flags it is a flip too."""
    records, refs, _ = sentinel([0], [0])
    assert refs["s-b03"] == ("buggy", "pass")
    changed = [SentinelRecord(r.run_id, r.epoch, r.order, r.slice_index, "flag", r.response_id)
               if r.run_id == "s-b03" and r.slice_index == 0 else r for r in records]
    state = drift.sentinel_chart(changed, refs, "e1")
    assert state["halves"]["buggy"]["counts"] == [1]
    assert state["halves"]["buggy"]["directions"][0] == {"flag_to_pass": 0, "pass_to_flag": 1}


def test_an_unfinished_slice_enters_no_rule_and_is_reported():
    records, refs, _ = sentinel([0, 10], [0, 10])
    state = drift.sentinel_chart(records[:-1], refs, "e1")
    assert state["unfinished_slice"] == 1 and state["halves"]["buggy"]["counts"] == [0]
    assert state["in_control"]


def test_slices_must_finish_in_order():
    records, refs, _ = sentinel([0, 0, 0], [0, 0, 0])
    gap = [r for r in records if r.slice_index != 1]
    with pytest.raises(ValueError, match="without gaps"):
        drift.sentinel_chart(gap, refs, "e1")
    hole = [r for r in records if not (r.slice_index == 0 and r.run_id == "s-b00")]
    with pytest.raises(ValueError, match="unfinished but a later slice"):
        drift.sentinel_chart(hole, refs, "e1")


def test_a_response_served_twice_is_refused():
    records, refs, _ = sentinel([0], [0])
    twice = records[:-1] + [SentinelRecord(records[-1].run_id, "e1", 999, 0, records[-1].verdict,
                                           records[0].response_id)]
    with pytest.raises(ValueError, match="served twice"):
        drift.sentinel_chart(twice, refs, "e1")


def test_no_opening_pass_means_no_baseline_and_not_in_control():
    records, refs, _ = sentinel([0], [0])
    state = drift.sentinel_chart([r for r in records if r.slice_index is not None], refs, "e1")
    assert state["baseline"] is None and not state["in_control"] and state["status"].startswith("no baseline")


def test_other_epochs_records_are_ignored():
    records, refs, _ = sentinel([0], [0])
    other = [SentinelRecord(r.run_id, "e0", r.order, r.slice_index, "flag", "old-" + r.response_id) for r in records]
    state = drift.sentinel_chart(records + other, refs, "e1")
    assert state["halves"]["clean"]["counts"] == [0]


# ---- alarms and the look-back -----------------------------------------------------------------------------------

def test_each_rule_fires_once_in_the_demo():
    found = {expected: drift.fired_list(state) for expected, _, state, _ in drift.demo_scenarios()}
    assert {k: [f[0] for f in v] for k, v in found.items()} == {"R1": ["R1"], "R2": ["R2"], "R3": ["R3"]}


def test_the_look_back_of_each_rule():
    """R1: since the previous in-control slice; R2: since the slice before the first of the two; R3: since the
    slice before its W (plan section 5, item 2)."""
    alarms = {expected: drift.first_alarm(state) for expected, _, state, _ in drift.demo_scenarios()}
    assert (alarms["R1"]["slice_index"], alarms["R1"]["hold_after_slice"]) == (3, 2)
    assert (alarms["R2"]["slice_index"], alarms["R2"]["hold_after_slice"]) == (3, 1)
    assert (alarms["R3"]["slice_index"], alarms["R3"]["hold_after_slice"]) == (4, 1)
    assert alarms["R2"]["counts"] == [4, 4] and alarms["R3"]["counts"] == [4, 2, 4]
    for expected, _, state, accepted in drift.demo_scenarios():
        alarm = alarms[expected]
        held = drift.hold_list(alarm, accepted)
        boundary = state["slice_last_order"][alarm["hold_after_slice"]]
        assert held == [a.run_id for a in accepted if a.order > boundary]
        assert held and len(held) < len(accepted)


def test_evidence_reaching_the_start_holds_everything_of_the_epoch_only():
    records, refs, accepted = sentinel([4, 4], [0, 0])
    state = drift.sentinel_chart(records, refs, "e1")
    alarm = drift.first_alarm(state)
    assert alarm["rule"] == "R2" and alarm["hold_after_slice"] == -1 and alarm["hold_after_order"] is None
    other = AcceptedRun("elsewhere", "e0", 5)
    assert drift.hold_list(alarm, accepted + [other]) == [a.run_id for a in accepted]


def test_no_alarm_when_in_control():
    records, refs, _ = sentinel([0, 1, 0], [0, 0, 1])
    assert drift.first_alarm(drift.sentinel_chart(records, refs, "e1")) is None


# ---- layer C: the rolling calibration window --------------------------------------------------------------------

SUPPORT = [("B01", "obvious"), ("B01", "subtle"), ("B02", "subtle")]


def test_the_rolling_window_keeps_exactly_24_per_class_and_120_clean_newest_first():
    obs = [canary(i, "B01", "obvious" if i % 2 else "subtle") for i in range(40)]
    obs += [canary(100 + i, "B02", "subtle") for i in range(30)]
    obs += [clean_run(200 + i) for i in range(150)]
    found = drift.calibration_window(obs, SUPPORT, "e1")
    assert found["per_class"] == {"B01": 24, "B02": 24} and found["clean"] == 120 and found["short"] == {}
    orders = [o.order for o in found["window"]]
    assert orders == sorted(orders, reverse=True)
    b01 = [o.order for o in found["window"] if o.bug_id == "B01"]
    assert b01 == list(range(39, 15, -1))                               # the newest 24 of 0..39
    clean = [o.order for o in found["window"] if o.bug_id is None]
    assert min(clean) == 200 + 30                                       # the oldest 30 clean runs are outside


def test_observations_outside_the_window_still_appear_in_the_report():
    obs = [canary(i, "B01", "obvious") for i in range(30)]
    obs += [clean_run(100 + i) for i in range(125)]
    obs += [clean_run(300, epoch="e0"), ChartObservation("pr", "e1", 400, sealed.CANARY_PROBE, "B01", "obvious", True),
            canary(401, "B01", "obvious", failed=True), canary(402, "B06", "obvious")]
    found = drift.calibration_window(obs, SUPPORT, "e1")
    reported = [o.run_id for o in found["window"]] + found["outside"] + found["other_epochs"]
    reported += [r for ids in found["left_out"].values() for r in ids]
    assert sorted(reported) == sorted(o.run_id for o in obs)            # every observation exactly once
    assert len(found["outside"]) == 6 + 5 and found["other_epochs"] == ["e0-c300"]
    assert found["short"] == {"B02": 24}


def test_the_window_never_crosses_an_epoch():
    obs = [canary(i, "B01", "obvious", epoch="e1") for i in range(10)]
    obs += [canary(100 + i, "B01", "obvious", epoch="e2") for i in range(30)]   # newer, but another epoch
    found = drift.calibration_window(obs, SUPPORT, "e1")
    assert found["per_class"]["B01"] == 10 and len(found["other_epochs"]) == 30
    assert all(o.epoch == "e1" for o in found["window"])


def test_the_demo_command_runs(capsys):
    assert drift.main(["--demo"]) == 0
    out = capsys.readouterr().out
    for rule in ("[R1]", "[R2]", "[R3]", "alarm record", "hold list"):
        assert rule in out
