"""The development runner `eval/tripwires_dev.py` (Mission 5.1, plan step 7). Fast: synthetic records, a temporary
sealed table, no replay, no audit. Every printed number is checked against one computed by hand."""
import json

import pytest

from canary import sealed, tripwires
from eval import tripwires_dev as dev

BUGS = [f"B{i:02d}" for i in range(1, 11)]


def record(verdict="pass", fired=(), unverifiable=(), named=None, margin=0.2, seconds=1.0):
    checks = {name: {"status": tripwires.OK, "evidence": "fine", "bug_class": None} for name in tripwires.CHAIN}
    for name in fired:
        checks[name] = {"status": tripwires.FIRED, "evidence": f"{name} broke", "bug_class": named}
    for name in unverifiable:
        checks[name] = {"status": tripwires.UNVERIFIABLE, "evidence": f"{name} unseen", "bug_class": None}
    return {"verdict": verdict, "bug_class": named, "evidence": "x", "checks": checks,
            "advisory": {"no_skill_margin": margin}, "replay": {"status": "ok", "seconds": seconds},
            "version": "v1:test", "tier": "replay"}


def impact(control=0.0, treatment=0.0):
    return {"control": control, "treatment": treatment, "effect": treatment - control,
            "size": max(abs(control), abs(treatment)), "threshold": 0.005, "comparable": True}


@pytest.fixture
def world(tmp_path):
    """Five canaries and three clean runs of task-dev-2, one run of another batch."""
    table = sealed.SealedTable(tmp_path / "sealed.db")
    batch = {"batch": "task-dev-2"}
    table.seal("c1", sealed.CANARY_MEASURE, "B01", "obvious", "t1", "pool:0", {**batch, "impact": impact(0.01)})
    table.seal("c2", sealed.CANARY_MEASURE, "B01", "subtle", "t2", "pool:1", {**batch, "impact": impact()})
    table.seal("c3", sealed.CANARY_MEASURE, "B05", "subtle", "t3", "pool:2", {**batch, "impact": impact(0, 0.02)})
    table.seal("c4", sealed.CANARY_MEASURE, "B09", "obvious", "t4", "pool:3", {**batch, "impact": impact(-0.3)})
    table.seal("c5", sealed.CANARY_MEASURE, "B06", "obvious", "t5", "pool:4",
               {**batch, "impact": {**impact(0.1, 0.1), "comparable": False}})
    table.seal("k1", sealed.CONTROL, source="pool:0", details={**batch, "decoy": {"bug_id": "B01", "tier": "obvious"}})
    table.seal("k2", sealed.CONTROL, source="pool:1", details={**batch, "decoy": {"bug_id": "B01", "tier": "obvious"}})
    table.seal("s1", sealed.SHAM, source="pool:2", details={**batch, "decoy": {"bug_id": "B05", "tier": "subtle"}})
    table.seal("other", sealed.CONTROL, source="pool:0", details={"batch": "rq1-full"})
    records = {
        "c1": record("flag", fired=["K2"], named="B01"),
        "c2": record("flag", unverifiable=["K0"]),
        "c3": record("flag", fired=["K6"], named="B07"),  # caught, wrong class named
        "c4": record("pass", margin=0.05),
        "c5": record("flag", fired=["L1"], named="B06"),
        "k1": record("pass", margin=0.2),
        "k2": record("pass", margin=0.3),
        "s1": record("flag", fired=["K4"], named="B04", margin=0.05, seconds=3.0),
    }
    return table, records


def scored(world):
    table, records = world
    truths = dev.batch_truths(table, "task-dev-2")
    return dev.score(records, truths, {t.run_id: t.run_id for t in truths}, BUGS, draws=500)


@pytest.mark.parametrize("batch", ["ceiling-ext", "tripwire-test-1", "rq4-bank-1", "anything"])
def test_only_development_batches_are_accepted(batch, tmp_path):
    with pytest.raises(dev.RefusedBatch):
        dev.check_batch(batch)
    with pytest.raises(dev.RefusedBatch):
        dev.batch_truths(sealed.SealedTable(tmp_path / "s.db"), batch)
    with pytest.raises(dev.RefusedBatch):
        dev.inspect_batch(batch, ["r1"], runs_dir=tmp_path, records_dir=tmp_path / "rec", log_path=tmp_path / "log",
                          inspect=lambda path: pytest.fail("must not inspect"))
    assert dev.main(["--batch", batch]) == 2


def test_the_batch_listing_keeps_its_own_scored_runs(world):
    table, _ = world
    assert [t.run_id for t in dev.batch_truths(table, "task-dev-2")] == ["c1", "c2", "c3", "c4", "c5", "k1", "k2", "s1"]


def test_inspection_gets_the_folder_path_only_stores_records_and_resumes(tmp_path):
    runs, stored, log = tmp_path / "runs", tmp_path / "records", tmp_path / "dev.log"
    for run_id in ("a", "b"):
        (runs / run_id).mkdir(parents=True)
    seen = []

    def fake(path):
        seen.append(path)
        return {**record(), "version": tripwires.source_version()}

    first = dev.inspect_batch("task-dev-2", ["a", "b", "gone"], runs, stored, log, workers=2, inspect=fake)
    assert sorted(seen) == [runs / "a", runs / "b"] and first["gone"] is None
    assert json.loads((stored / "a.json").read_text(encoding="utf-8"))["run_id"] == "a"
    again = dev.inspect_batch("task-dev-2", ["a", "b"], runs, stored, log, inspect=fake)
    assert len(seen) == 2 and again["a"]["run_id"] == "a"  # same version: reused, not replayed
    text = log.read_text(encoding="utf-8")
    assert "MISSING gone" in text and "reused=2" in text and not any(any((runs / r).iterdir()) for r in ("a", "b"))


def test_per_class_counts_split_fired_and_unverifiable(world):
    result = scored(world)
    b01 = result["per_class"]["B01"]
    assert (b01["canaries"], b01["fired"], b01["unverifiable_only"], b01["missed"], b01["named_right"]) == (2, 1, 1, 0, 1)
    assert b01["headline_fired"]["successes"] == 1 and b01["headline_fired"]["n"] == 2
    assert b01["any_flag"]["successes"] == 2
    b09 = result["per_class"]["B09"]
    assert (b09["canaries"], b09["missed"]) == (1, 1)
    assert result["per_class"]["B05"]["named_right"] == 0  # caught, but B07 named


def test_headline_leaves_out_b06_obvious_and_counts_fired_only(world):
    h = scored(world)["headline"]
    # B01 obvious, B01 subtle (unverifiable only), B05 subtle, B09 obvious: 2 fired of 4.
    assert (h["canaries"], h["fired"]) == (4, 2)
    assert h["recall_fired"]["raw"] == 0.5 and h["recall_fired"]["beta_mean"] == pytest.approx(3 / 6)
    assert (h["specificity"]["successes"], h["specificity"]["n"]) == (2, 3)
    assert h["control_specificity"]["raw"] == 1.0 and h["sham_specificity"]["raw"] == 0.0
    assert h["youden_j"]["observed_j"] == pytest.approx(0.5 + 2 / 3 - 1)
    assert (h["named_right"]["successes"], h["named_right"]["n"]) == (1, 4)
    assert h["by_tier"]["obvious"]["successes"] == 1 and h["by_tier"]["obvious"]["n"] == 2  # B01 caught, B09 not


def test_rule_row_any_flag_and_specificity_by_decoy(world):
    result = scored(world)
    assert result["rule_b06_obvious"]["canaries"] == 1 and result["rule_b06_obvious"]["caught_by_rule"] == 1
    assert result["any_flag"]["recall"]["successes"] == 4 and result["any_flag"]["recall"]["n"] == 5
    assert result["any_flag"]["unverifiable_only"] == 1
    assert result["specificity_by_decoy"] == {"B01 obvious": {"runs": 2, "passed": 2},
                                              "B05 subtle": {"runs": 1, "passed": 0}}


def test_gold_twin_reference_row_and_no_op_canaries(world):
    result = scored(world)
    ref = result["reference_gold_twin"]
    # Numbers changed: B01 obvious, B05 subtle, B09 obvious; unchanged: B01 subtle.
    assert (ref["recall"]["successes"], ref["recall"]["n"]) == (3, 4)
    assert ref["tripwires_only"] == 0 and ref["reference_only"] == 1  # B09: numbers moved, no tripwire fired
    assert [n["run_id"] for n in result["no_op_canaries"]] == ["c2"]


def test_misses_false_alarms_replays_and_a1(world):
    result = scored(world)
    assert [m["run_id"] for m in result["misses"]] == ["c4"]
    assert [f["run_id"] for f in result["false_alarms"]] == ["s1"]
    assert result["false_alarms"][0]["not_ok"] == {"K4": "fired: K4 broke"}
    assert [u["run_id"] for u in result["unverifiable_canaries"]] == ["c2"]
    assert result["replays"]["reproduced"] == 7 and result["replays"]["runs"] == 8  # c2's K0 was unverifiable
    assert result["replays"]["seconds_mean"] == pytest.approx((7 * 1.0 + 3.0) / 8) and result["replays"]["seconds_max"] == 3.0
    # B09 margin 0.05 against clean 0.2, 0.3, 0.05: below, below, tie -> (1 + 1 + 0.5) / 3.
    assert result["advisory_a1"]["auc_low_margin_picks_b09"] == pytest.approx(2.5 / 3)
    assert result["label"] == "known shapes (development)" and "not measured" in result["held_out_shapes"]


def test_base_level_interval_collapses_when_every_cluster_agrees():
    rows = [{"cluster": f"c{i}", "buggy": True, "flagged": True} for i in range(5)]
    rows += [{"cluster": f"k{i}", "buggy": False, "flagged": False} for i in range(5)]
    out = dev.base_bootstrap(rows, draws=200)
    assert out["recall_90"] == [1.0, 1.0] and out["specificity_90"] == [1.0, 1.0] and out["youden_j_90"] == [1.0, 1.0]
    assert out["clusters"] == 10
    mixed = dev.base_bootstrap(rows[:4] + [{"cluster": "c4", "buggy": True, "flagged": False}] + rows[5:], draws=500)
    assert mixed["recall_90"][0] < 0.8 <= mixed["recall_90"][1]


def test_missing_records_are_listed_not_scored(world):
    table, records = world
    del records["k2"]
    truths = dev.batch_truths(table, "task-dev-2")
    result = dev.score(records, truths, {}, BUGS, draws=200)
    assert result["missing_records"] == ["k2"] and result["clean"] == 2


def test_the_printed_table_carries_the_numbers(world):
    result = {"batch": "task-dev-2", "tripwire_version": "v1:abcdef0123456789abc", **scored(world)}
    text = dev.format_table(result)
    assert "known shapes (development)" in text and "held-out shapes: not measured (Mission 6.2)" in text
    b01 = next(line.split() for line in text.splitlines() if line.startswith("B01 "))
    assert b01[1:6] == ["2", "1", "1", "0", "1"]  # canaries, fired, unverifiable only, missed, right class named
    assert "headline recall (fired): 2/4" in text and "specificity: 2/3" in text
    assert "Youden's J: +0.167" in text and "B06 obvious (L1 rule, outside the headline): 1/1" in text
    assert "gold-twin reference recall: 3/4" in text and "miss c4 B09 obvious" in text
    assert "false alarm s1 sham (decoy B05 subtle)" in text and "AUC 0.833" in text


def test_the_runner_loads_no_audit_and_never_opens_the_ledger():
    """Mission 5.1 loads no reviewer output (plan section 2.5): the runner's source never touches the ledger."""
    import ast
    from pathlib import Path

    source = (Path(dev.__file__)).read_text(encoding="utf-8")
    names = {n.attr if isinstance(n, ast.Attribute) else n.id for n in ast.walk(ast.parse(source))
             if isinstance(n, (ast.Attribute, ast.Name))}
    assert not names & {"Ledger", "ledger", "AUDITED", "collect_observations", "skeptic_d", "audit"}
    assert "ceiling-ext" not in dev.DEV_BATCHES and "tripwire-test-1" not in dev.DEV_BATCHES
