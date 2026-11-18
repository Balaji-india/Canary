"""The locked test script `eval/tripwires_test.py` (Mission 5.1, plan step 9). Fast: a temporary plan, lock and sealed
table, fake records, no replay. Bars checked against Beta lower bounds computed by hand (scipy, 5th percentile)."""
import ast
import json
from pathlib import Path

import pytest
from scipy.stats import beta

from canary import sealed, tripwires
from eval import tripwires_test as tt
from tests.test_tripwires_dev import record


def world_plan(root: Path, draft: bool = False) -> Path:
    """A plan listing every required file (copies with known text) in section 3 and both slot-list locks in section 4
    (the hashes of `PLANS`, the stored batch plans the tests build)."""
    lines = []
    for name in tt.MUST_FREEZE:
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(f"# {name}\r\n".encode())  # CRLF on disk: hashed as LF
        lines.append(f"- `{name}` {tt.lf_sha256(file)}")
    plan = root / "docs" / "plans" / "tripwire_test.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    title = "# Pre-registration: tripwire test" + (" (DRAFT)" if draft else "")
    slots = "".join(f"- Slot list `{b}` {tt.slots_sha256(PLANS[b])}\n" for b in tt.TEST_BATCHES)
    plan.write_bytes((title + "\n\n## 3. Frozen inputs\n" + "\n".join(lines) + "\n\n## 4. Data\n" + slots).encode())
    return plan


def store_plan(root: Path, batch: str, batch_plan: dict, gate: bool | None = True) -> None:
    """The stored batch plan `calibrate` writes, and its length-gate file (None: the build has not finished)."""
    plans = root / tt.PLANS_SUBDIR
    plans.mkdir(parents=True, exist_ok=True)
    (plans / f"{batch}.json").write_text(json.dumps(batch_plan), encoding="utf-8")
    gate_file = plans / f"{batch}.length_check.json"
    if gate is None:
        gate_file.unlink(missing_ok=True)
    else:
        gate_file.write_text(json.dumps({"passes": gate}), encoding="utf-8")


def test_lf_hash_ignores_line_endings_only(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    a.write_bytes(b"x\r\ny\r\n")
    b.write_bytes(b"x\ny\n")
    c.write_bytes(b"x\ny \n")
    assert tt.lf_sha256(a) == tt.lf_sha256(b) != tt.lf_sha256(c)


def test_lock_cycle_draft_refused_then_locked_then_edits_caught(tmp_path):
    plan = world_plan(tmp_path, draft=True)
    assert tt.lock_problems(plan, tmp_path) == [tt.NOT_LOCKED]
    with pytest.raises(tt.Refused, match="DRAFT"):
        tt.write_lock(plan, tmp_path)
    plan = world_plan(tmp_path)
    digest = tt.write_lock(plan, tmp_path)
    assert tt.lock_problems(plan, tmp_path) == [] and digest == tt.lf_sha256(plan)
    with pytest.raises(tt.Refused, match="exists already"):
        tt.write_lock(plan, tmp_path)
    (tmp_path / "canary" / "tripwires.py").write_bytes(b"# changed\n")
    assert tt.lock_problems(plan, tmp_path) == ["canary/tripwires.py: hash differs from the plan"]
    plan.write_bytes(plan.read_bytes() + b"edit\n")
    assert any("edited after it was locked" in p for p in tt.lock_problems(plan, tmp_path))


def test_a_required_file_left_out_of_the_plan_is_a_problem(tmp_path):
    plan = world_plan(tmp_path)
    text = plan.read_text(encoding="utf-8")
    plan.write_text("\n".join(l for l in text.splitlines() if "eval/tripwires_dev.py" not in l) + "\n", encoding="utf-8")
    assert "eval/tripwires_dev.py: not listed in section 3" in tt.file_problems(plan, tmp_path)


def test_chain_classes_leave_out_b09_and_b06_obvious_only():
    variants = [(f"B{i:02d}", t) for i in range(1, 11) for t in ("obvious", "subtle")]
    chain = [v for v in variants if tt.in_chain(*v)]
    assert len(chain) == 17
    assert ("B09", "obvious") not in chain and ("B09", "subtle") not in chain and ("B06", "obvious") not in chain
    assert ("B06", "subtle") in chain


def truths_of(canaries: list[tuple[str, str]], clean: int, batch: str = tt.PRIMARY) -> list[sealed.Truth]:
    """Truth rows as the sealed table returns them (built directly: sealing 360 rows per test is too slow). Slot
    numbers run over the canaries first, then the clean runs."""
    rows = [sealed.Truth(f"c{i:03d}", sealed.CANARY_MEASURE, bug, tier, f"t{i}", f"pool:{i % 17}",
                         {"batch": batch, "slot": i}, "2026-11-20T00:00:00") for i, (bug, tier) in enumerate(canaries)]
    rows += [sealed.Truth(f"k{i:03d}", sealed.CONTROL if i % 2 else sealed.SHAM, None, None, None, f"pool:{i % 17}",
                          {"batch": batch, "slot": len(canaries) + i}, "2026-11-20T00:00:00") for i in range(clean)]
    return rows


def full_batch():
    """The planned test batch: 10 per variant (200 canaries), 160 clean runs."""
    return truths_of([(f"B{i:02d}", t) for i in range(1, 11) for t in ("obvious", "subtle") for _ in range(10)], 160)


def secondary_batch():
    """The ceiling-ext shape: 2 per variant (40 canaries), 40 clean runs."""
    return truths_of([(f"B{i:02d}", t) for i in range(1, 11) for t in ("obvious", "subtle") for _ in range(2)], 40,
                     batch=tt.SECONDARY)


def batch_plan_of(truths: list[sealed.Truth], no_audit: bool = True) -> dict:
    """A stored batch plan whose slots are exactly these runs."""
    slots = [{"slot": t.details["slot"], "run_type": t.run_type, "bug_id": t.bug_id, "tier": t.tier,
              "candidates": [int(t.source.split(":")[1])]} for t in truths]
    return {"batch": truths[0].details["batch"], "seed": 7, "runs": len(truths), "role": "skeptic_a",
            "slots": sorted(slots, key=lambda s: s["slot"]), "no_audit": no_audit}


PLANS = {tt.PRIMARY: batch_plan_of(full_batch()), tt.SECONDARY: batch_plan_of(secondary_batch())}


class FakeTable:
    def __init__(self, truths):
        self.truths = truths

    def all(self):
        return list(self.truths)


@pytest.mark.parametrize("misses, false_alarms, recall_ok, spec_ok", [(10, 3, True, True), (11, 3, False, True),
                                                                      (10, 4, True, False), (0, 0, True, True)])
def test_bars_against_hand_computed_beta_bounds(tmp_path, misses, false_alarms, recall_ok, spec_ok):
    truths = full_batch()
    chain = [t for t in truths if t.run_type == sealed.CANARY_MEASURE and tt.in_chain(t.bug_id, t.tier)]
    clean = [t for t in truths if t.run_type != sealed.CANARY_MEASURE]
    records = {t.run_id: record("flag", fired=["K2"]) for t in truths if t.run_type == sealed.CANARY_MEASURE}
    for t in chain[:misses]:
        records[t.run_id] = record("pass")
    records.update({t.run_id: record("pass") for t in clean})
    for t in clean[:false_alarms]:
        records[t.run_id] = record("flag", unverifiable=["K0"])  # unverifiable is a false alarm too
    b = tt.bars(records, truths, {}, decides=True, draws=100)
    assert b["chain_canaries"] == 170 and len(clean) == 160
    assert set(b["chain_by_variant"].values()) == {10} and len(b["chain_by_variant"]) == 17
    assert b["recall_fired_chain"]["beta_90"][0] == pytest.approx(beta.ppf(0.05, 1 + 170 - misses, 1 + misses))
    assert b["specificity"]["beta_90"][0] == pytest.approx(beta.ppf(0.05, 1 + 160 - false_alarms, 1 + false_alarms))
    assert b["recall_fired_chain"]["meets_bar"] is recall_ok and b["specificity"]["meets_bar"] is spec_ok
    assert b["outcome"] == ("PASSED" if recall_ok and spec_ok else "FAILED")
    assert len(b["recall_fired_chain"]["missed_runs"]) == misses
    assert len(b["specificity"]["false_alarm_runs"]) == false_alarms


def test_hand_values_at_the_edges():
    """The numbers quoted in the lock draft: 10 misses of 170 clear 0.90, 11 do not; 3 false alarms of 160 clear 0.95,
    4 do not."""
    assert round(beta.ppf(0.05, 161, 11), 4) == 0.9028 and round(beta.ppf(0.05, 160, 12), 4) == 0.8958
    assert round(beta.ppf(0.05, 158, 4), 4) == 0.9525 and round(beta.ppf(0.05, 157, 5), 4) == 0.9441


def test_unverifiable_canary_is_not_fired_and_missing_records_count_against(tmp_path):
    truths = full_batch()
    records = {t.run_id: record("flag", fired=["K2"]) for t in truths if t.run_type == sealed.CANARY_MEASURE}
    records.update({t.run_id: record("pass") for t in truths if t.run_type != sealed.CANARY_MEASURE})
    chain = [t for t in truths if t.run_type == sealed.CANARY_MEASURE and tt.in_chain(t.bug_id, t.tier)]
    clean = [t for t in truths if t.run_type != sealed.CANARY_MEASURE]
    records[chain[0].run_id] = record("flag", unverifiable=["K5"])
    del records[chain[1].run_id], records[clean[0].run_id]
    b = tt.bars(records, truths, {}, decides=True, draws=100)
    assert b["recall_fired_chain"]["successes"] == 168 and b["specificity"]["successes"] == 159


def test_b09_and_b06_obvious_misses_do_not_touch_the_recall_bar(tmp_path):
    truths = full_batch()
    records = {t.run_id: record("pass" if t.bug_id == "B09" or (t.bug_id, t.tier) == ("B06", "obvious")
                                else "flag", fired=() if t.bug_id == "B09" else ["K2"])
               for t in truths if t.run_type == sealed.CANARY_MEASURE}
    records.update({t.run_id: record("pass") for t in truths if t.run_type != sealed.CANARY_MEASURE})
    b = tt.bars(records, truths, {}, decides=True, draws=100)
    assert b["recall_fired_chain"]["successes"] == 170 and b["outcome"] == "PASSED"


def test_secondary_batch_decides_nothing(tmp_path):
    truths = full_batch()
    b = tt.bars({}, truths, {}, decides=False, draws=100)
    assert b["outcome"] == "reported only" and "decides nothing" in tt.format_bars(b)


def test_preflight_refusals_in_order(tmp_path):
    plan = world_plan(tmp_path)
    table = FakeTable(truths_of([("B01", "obvious")] * 10, 10))  # slots 10-19 clean, but planned as B01 subtle
    out, arm_l = tmp_path / "out", tmp_path / "arm_L.json"
    with pytest.raises(tt.Refused, match="not a test batch"):
        tt.preflight("task-dev-2", table, plan, tmp_path, out, arm_l)
    with pytest.raises(tt.Refused, match="NOT LOCKED"):
        tt.preflight(tt.PRIMARY, table, plan, tmp_path, out, arm_l)
    tt.write_lock(plan, tmp_path)
    with pytest.raises(tt.Refused, match="no stored batch plan"):
        tt.preflight(tt.PRIMARY, table, plan, tmp_path, out, arm_l)
    other = {**PLANS[tt.PRIMARY], "slots": list(reversed(PLANS[tt.PRIMARY]["slots"]))}
    store_plan(tmp_path, tt.PRIMARY, other)
    with pytest.raises(tt.Refused, match="stored batch plan differs from the locked one"):
        tt.preflight(tt.PRIMARY, table, plan, tmp_path, out, arm_l)
    store_plan(tmp_path, tt.PRIMARY, {**PLANS[tt.PRIMARY], "no_audit": False})  # no_audit is outside the slot hash
    with pytest.raises(tt.Refused, match="planned with audits"):
        tt.preflight(tt.PRIMARY, table, plan, tmp_path, out, arm_l)
    store_plan(tmp_path, tt.PRIMARY, PLANS[tt.PRIMARY], gate=None)
    with pytest.raises(tt.Refused, match="has not finished.*--resume --no-audit"):
        tt.preflight(tt.PRIMARY, table, plan, tmp_path, out, arm_l)
    store_plan(tmp_path, tt.PRIMARY, PLANS[tt.PRIMARY], gate=False)
    with pytest.raises(tt.Refused, match="length gate failed"):
        tt.preflight(tt.PRIMARY, table, plan, tmp_path, out, arm_l)
    store_plan(tmp_path, tt.PRIMARY, PLANS[tt.PRIMARY])
    with pytest.raises(tt.Refused, match="not the slot's planned type"):
        tt.preflight(tt.PRIMARY, table, plan, tmp_path, out, arm_l)
    with pytest.raises(tt.Refused, match="arm L"):
        tt.preflight(tt.SECONDARY, table, plan, tmp_path, out, arm_l)
    out.mkdir()
    tt.out_path(tt.PRIMARY, out).write_text("{}", encoding="utf-8")
    with pytest.raises(tt.Refused, match="runs once"):
        tt.preflight(tt.PRIMARY, table, plan, tmp_path, out, arm_l)
    assert tt.main(["--batch", "rq1-full"]) == 2


@pytest.mark.parametrize("batch", [tt.PRIMARY, tt.SECONDARY])
def test_the_run_once_writes_the_result_and_refuses_a_second(tmp_path, monkeypatch, batch):
    """Write-once for both test batches: the second call is refused and writes nothing."""
    plan = world_plan(tmp_path)
    tt.write_lock(plan, tmp_path)
    truths = full_batch() if batch == tt.PRIMARY else secondary_batch()
    store_plan(tmp_path, batch, PLANS[batch])
    arm_l = tmp_path / "arm_L.json"
    arm_l.write_text("{}", encoding="utf-8")
    runs = tmp_path / "runs"
    for t in truths:
        (runs / t.run_id).mkdir(parents=True)
    monkeypatch.setattr(tt.ceiling, "cluster_labels", lambda batch, source, run_id: (f"base:{source}", "f"))

    def fake(path):
        canary = path.name.startswith("c")
        return {**record("flag" if canary else "pass", fired=["K2"] if canary else ()),
                "version": tripwires.source_version()}

    kwargs = dict(table=FakeTable(truths), inspect=fake, runs_dir=runs, records_dir=tmp_path / "rec", log_path=tmp_path / "log",
                  plan=plan, root=tmp_path, out_dir=tmp_path / "out", arm_l=arm_l, workers=2, draws=100)
    result = tt.run_test(batch, **kwargs)
    assert result["label"] == "known shapes, fresh bases"
    assert result["bars"]["outcome"] == ("PASSED" if batch == tt.PRIMARY else "reported only")
    assert result["bars"]["base_level_beside"]["clusters"] == 17
    assert result["slot_list_sha256"] == tt.slots_sha256(PLANS[batch]) and result["not_built_slots"] == []
    written = tt.out_path(batch, tmp_path / "out")
    assert json.loads(written.read_text(encoding="utf-8"))["runs"] == tt.EXPECTED_RUNS[batch]
    assert not any(any(p.iterdir()) for p in runs.iterdir())  # nothing written inside run folders
    before = written.read_bytes()
    with pytest.raises(tt.Refused, match="runs once"):
        tt.run_test(batch, **kwargs)
    assert written.read_bytes() == before  # the refused second call wrote nothing


def test_the_test_script_loads_no_audit_never_opens_the_ledger_and_calls_no_model():
    source = Path(tt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.attr if isinstance(n, ast.Attribute) else n.id for n in ast.walk(tree)
             if isinstance(n, (ast.Attribute, ast.Name))}
    assert not names & {"Ledger", "ledger", "AUDITED", "collect_observations", "skeptic_d", "audit", "llm", "skeptic"}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not imported & {"llm", "skeptic", "ledger", "blinding", "prompts"}


def test_the_batch_listing_keeps_only_that_batch_s_scored_runs():
    rows = truths_of([("B01", "obvious")], 1) + truths_of([("B02", "subtle")], 0, batch="ceiling-ext")
    rows.append(sealed.Truth("r1", sealed.REAL, None, None, None, None, {"batch": tt.PRIMARY}, ""))
    assert [t.run_id for t in tt.batch_truths(FakeTable(rows), tt.PRIMARY)] == ["c000", "k000"]


def test_slot_hash_covers_the_runs_not_the_name_role_or_audit_flag():
    base = PLANS[tt.PRIMARY]
    same = {**base, "batch": "dry-check", "role": "skeptic_d", "no_audit": False, "pool": "elsewhere.json"}
    assert tt.slots_sha256(same) == tt.slots_sha256(base)
    moved = {**base, "slots": [{**base["slots"][0], "candidates": [16]}] + base["slots"][1:]}
    assert tt.slots_sha256(moved) != tt.slots_sha256(base)
    assert tt.slots_sha256({**base, "seed": 8}) != tt.slots_sha256(base)


def test_slot_locks_must_be_listed_for_both_batches(tmp_path):
    plan = world_plan(tmp_path)
    text = plan.read_text(encoding="utf-8")
    plan.write_text("\n".join(l for l in text.splitlines() if f"`{tt.SECONDARY}`" not in l) + "\n", encoding="utf-8")
    assert f"slot list of {tt.SECONDARY}: not listed in section 4" in tt.lock_problems(plan, tmp_path)
    with pytest.raises(tt.Refused, match="not listed in section 4"):
        tt.write_lock(plan, tmp_path)


def test_unbuilt_slots_count_against_and_a_crash_leftover_is_superseded():
    truths = full_batch()
    chain = [t for t in truths if t.run_type == sealed.CANARY_MEASURE and tt.in_chain(t.bug_id, t.tier)]
    clean = [t for t in truths if t.run_type != sealed.CANARY_MEASURE]
    gone = {chain[0].run_id, chain[1].run_id, clean[0].run_id}
    leftover = sealed.Truth("old", clean[1].run_type, None, None, None, clean[1].source, dict(clean[1].details),
                            "2026-11-19T00:00:00")  # sealed earlier, before a crash; the slot ran again later
    table = FakeTable([t for t in truths if t.run_id not in gone] + [leftover])
    scored, not_built, superseded = tt.slot_truths(tt.PRIMARY, table, PLANS[tt.PRIMARY])
    assert len(scored) == 360 and len(not_built) == 3 and superseded == ["old"]
    assert clean[1].run_id in {t.run_id for t in scored} and "old" not in {t.run_id for t in scored}
    records = {t.run_id: record("flag", fired=["K2"]) for t in scored if t.run_type == sealed.CANARY_MEASURE}
    records.update({t.run_id: record("pass") for t in scored if t.run_type != sealed.CANARY_MEASURE})
    records.update({run_id: None for run_id in not_built})
    b = tt.bars(records, scored, {}, decides=True, draws=100)
    assert b["recall_fired_chain"]["successes"] == 168 and b["recall_fired_chain"]["n"] == 170
    assert b["specificity"]["successes"] == 159 and b["specificity"]["n"] == 160
    stray = sealed.Truth("stray", sealed.SHAM, None, None, None, "pool:0", {"batch": tt.PRIMARY, "slot": 999}, "x")
    with pytest.raises(tt.Refused, match="no planned slot"):
        tt.slot_truths(tt.PRIMARY, FakeTable(truths + [stray]), PLANS[tt.PRIMARY])


def test_line_endings_report_and_sync_against_the_git_blob(tmp_path):
    plan = world_plan(tmp_path)  # writes each frozen file with CRLF; the "blob" is its LF form
    blobs = {name: (tmp_path / name).read_bytes().replace(b"\r\n", b"\n") for name in tt.MUST_FREEZE}

    def blob(name, root):
        return blobs.get(name)

    rows = tt.line_ending_rows(plan, tmp_path, blob=blob, attr=lambda name, root: "unspecified")
    assert all(r["in_git"] and not r["minus_text"] and not r["working_is_blob"] and r["hash_is_blob"] for r in rows)
    assert not tt.line_endings_ok(rows)
    assert sorted(tt.sync_lf(plan, tmp_path, blob=blob)) == sorted(tt.MUST_FREEZE)
    rows = tt.line_ending_rows(plan, tmp_path, blob=blob, attr=lambda name, root: "unset")
    assert tt.line_endings_ok(rows) and tt.sync_lf(plan, tmp_path, blob=blob) == []
    outside = tt.line_ending_rows(plan, tmp_path, blob=lambda n, r: None, attr=lambda n, r: "unset")
    assert all(not r["in_git"] for r in outside) and tt.line_endings_ok(outside)


def test_sync_lf_refuses_a_content_change_and_writes_nothing(tmp_path):
    plan = world_plan(tmp_path)
    blobs = {name: (tmp_path / name).read_bytes().replace(b"\r\n", b"\n") for name in tt.MUST_FREEZE}
    (tmp_path / "canary" / "probe.py").write_bytes(b"# edited\r\n")
    before = {name: (tmp_path / name).read_bytes() for name in tt.MUST_FREEZE}
    with pytest.raises(tt.Refused, match="canary/probe.py: differs from HEAD in content"):
        tt.sync_lf(plan, tmp_path, blob=lambda name, root: blobs.get(name))
    assert {name: (tmp_path / name).read_bytes() for name in tt.MUST_FREEZE} == before
