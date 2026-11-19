"""`python -m canary.cli tripwires` (Mission 5.1 step 11): inspect, record (dry run unless --write), verify.

Fast: temporary ledger, sealed table and record folders, synthetic records, no replay, no model. The real ledger and
the real data folders are never opened (every default path is redirected to tmp_path).
"""
import json
import re

import pytest

from canary import cli, ledger, llm, sandbox, sealed, skeptic, tripwire_ledger as tl, tripwires
from tests.test_tripwire_ledger import _impact, ran, record, store


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A batch b1 (2 canaries, a control, a sham) and a run of batch b2, all in the ledger, with stored test records."""
    monkeypatch.setattr(sealed, "SEALED_DB_PATH", tmp_path / "sealed.db")
    monkeypatch.setattr(sealed.SealedTable.__init__, "__defaults__", (tmp_path / "sealed.db",))
    monkeypatch.setattr(ledger.Ledger.__init__, "__defaults__", (tmp_path / "ledger.db",))  # for `trust`
    monkeypatch.setattr(tl, "TEST_RECORDS_DIR", tmp_path / "tripwires" / "test")
    monkeypatch.setattr(tl, "RECORDS_DIR", tmp_path / "tripwires" / "v1")
    monkeypatch.setattr(sandbox, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(llm, "LLM", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model may be called")))
    table, led = sealed.SealedTable(), ledger.Ledger()
    rows = [("c1", sealed.CANARY_MEASURE, "B01", "obvious", record("c1", "flag", fired=("K1",), named="B01")),
            ("c2", sealed.CANARY_MEASURE, "B03", "subtle", record("c2")),
            ("k1", sealed.CONTROL, None, None, record("k1")),
            ("s1", sealed.SHAM, None, None, record("s1", "flag", unverifiable=("K0",)))]
    for number, (run_id, run_type, bug, tier, rec) in enumerate(rows):
        details = {"batch": "b1", "impact": _impact(0.01)} if bug else {"batch": "b1"}
        table.seal(run_id, run_type, bug, tier, f"t{number}" if bug else None, f"pool:{number}", details)
        ran(led, f"h{number}", run_id)
        store(tl.TEST_RECORDS_DIR / "b1", rec)
    table.seal("other", sealed.CONTROL, details={"batch": "b2"})
    ran(led, "h-other", "other")
    return tmp_path, led


def run(capsys, *argv):
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


def test_record_is_a_dry_run_unless_write(world, capsys):
    tmp_path, led = world
    before = len(led.entries())
    code, out = run(capsys, "tripwires", "record", "--batch", "b1", "--db", str(tmp_path / "ledger.db"))
    assert code == 0 and len(ledger.Ledger().entries()) == before
    assert "0 written; 4 ready (dry run, not written)" in out and "verdicts flag 2, pass 2" in out
    assert "DRY RUN: nothing written. To write: python -m canary.cli tripwires record --batch b1 --write" in out
    assert not tl.RECORDS_DIR.exists()  # nothing made, nothing stored


def test_write_records_the_batch_only_and_trust_reads_it_under_the_role(world, capsys):
    tmp_path, _ = world
    code, out = run(capsys, "tripwires", "record", "--batch", "b1", "--write", "--db", str(tmp_path / "ledger.db"))
    assert code == 0 and "4 written" in out and "DRY RUN" not in out
    audits = [e for e in ledger.Ledger().entries(ledger.AUDITED) if e.payload["role"] == tl.ROLE]
    assert sorted(e.payload["run_id"] for e in audits) == ["c1", "c2", "k1", "s1"]  # not b2's run
    code, out = run(capsys, "tripwires", "record", "--batch", "b1", "--write", "--db", str(tmp_path / "ledger.db"))
    assert "0 written" in out and "4 already recorded" in out
    code, out = run(capsys, "trust", "--role", tl.ROLE, "--batch", "b1")
    assert code == 0 and "4 audited runs with a sealed type" in out
    rows = dict(re.findall(r"^  (B01|B03|controls|shams|combined)\s+(\d+ of \d+)", out, re.M))
    assert rows == {"B01": "1 of 1", "B03": "0 of 1", "controls": "1 of 1", "shams": "0 of 1", "combined": "1 of 2"}


def test_verify_finds_an_edited_record_file(world, capsys):
    tmp_path, _ = world
    db = str(tmp_path / "ledger.db")
    run(capsys, "tripwires", "record", "--batch", "b1", "--write", "--db", db)
    code, out = run(capsys, "tripwires", "verify", "--db", db)
    assert code == 0 and "Tripwire records: OK (4 ledger entries under tripwire_v1" in out
    path = tl.TEST_RECORDS_DIR / "b1" / "k1.json"
    edited = json.loads(path.read_text(encoding="utf-8")) | {"verdict": "flag"}
    path.write_text(json.dumps(edited), encoding="utf-8")
    code, out = run(capsys, "tripwires", "verify", "--db", db)
    assert code == 1 and "the record file of k1 does not match its hash" in out


def test_bad_arguments_are_refused_without_writing(world, capsys):
    tmp_path, led = world
    before = len(led.entries())
    db = str(tmp_path / "ledger.db")
    assert run(capsys, "tripwires", "record", "--db", db)[0] == 2
    code, out = run(capsys, "tripwires", "record", "--batch", "nope", "--write", "--db", db)
    assert code == 2 and "Batch nope has no sealed runs." in out
    assert run(capsys, "tripwires", "inspect")[0] == 2
    code, out = run(capsys, "tripwires", "inspect", "no-such-run")
    assert code == 2 and "No run folder no-such-run" in out
    assert len(ledger.Ledger().entries()) == before


def test_another_tripwire_version_under_the_role_refuses_the_write(world, capsys):
    tmp_path, led = world
    led.append("h-other", ledger.AUDITED, tl.ledger_payload("other", record("other", version="v1:" + "0" * 64)))
    code, out = run(capsys, "tripwires", "record", "--batch", "b1", "--write", "--db", str(tmp_path / "ledger.db"))
    assert code == 1 and out.startswith("Refused: role tripwire_v1 already holds records of version")


def test_inspect_is_the_tripwires_module_on_the_run_folder(world, capsys, monkeypatch):
    tmp_path, _ = world
    (sandbox.RUNS_DIR / "c1").mkdir(parents=True)
    seen = []
    monkeypatch.setattr(tripwires, "main", lambda argv: seen.append(argv) or 0)
    assert run(capsys, "tripwires", "inspect", "c1", "--json")[0] == 0
    assert run(capsys, "tripwires", "inspect", str(sandbox.RUNS_DIR / "c1"))[0] == 0
    assert seen == [[str(sandbox.RUNS_DIR / "c1"), "--json"], [str(sandbox.RUNS_DIR / "c1")]]


# Guards added by the step 11 /challenge (2026-11-19)

def test_audit_leaves_out_no_audit_batches_and_the_never_reviewed_batch(world, monkeypatch, capsys):
    tmp_path, led = world
    plans = tmp_path / "sealed_plans"
    plans.mkdir()
    monkeypatch.setattr(sealed, "PLANS_DIR", plans)
    (plans / "b1.json").write_text(json.dumps({"batch": "b1", "no_audit": True}), encoding="utf-8")
    (plans / "b1.length_check.json").write_text(json.dumps({"passes": True}), encoding="utf-8")
    sealed.SealedTable().seal("t1", sealed.CONTROL, details={"batch": "tripwire-test-1"})  # no stored plan needed
    ran(led, "h-t1", "t1")
    ran(led, "h-real", "real-run")  # a run of no batch (a Scientist run) is still reviewed
    asked = {}
    monkeypatch.setattr(skeptic, "audit_pending", lambda client, l, **kw: asked.update(kw) or skeptic.AuditReport())
    assert cli._run_audits(object(), led) == 0
    assert asked["run_ids"] == {"other", "real-run"}  # b1 (no_audit) and tripwire-test-1 left out
    assert "Left out: the runs of no-audit batches (b1, tripwire-test-1)" in capsys.readouterr().out
    assert cli.no_audit_run_ids(plans) == ({"c1", "c2", "k1", "s1", "t1"}, ["b1", "tripwire-test-1"])


def test_reaudit_and_rescore_refuse_the_never_reviewed_batch_before_any_model(world, capsys):
    for argv in (["reaudit", "--batch", "tripwire-test-1", "--role", "skeptic_d"],
                 ["rescore", "--batch", "tripwire-test-1", "--reviewer", "skeptic_d", "--sample", "20"]):
        code, out = run(capsys, *argv)
        assert code == 2 and out.startswith("Refused: no LLM ever reviews tripwire-test-1")


def test_trust_says_when_a_crashed_run_holds_an_opinion_and_is_counted(world, capsys):
    tmp_path, led = world
    sealed.SealedTable().seal("k9", sealed.CONTROL, details={"batch": "b1"})
    ran(led, "h-k9", "k9", status="timeout")
    store(tl.TEST_RECORDS_DIR / "b1", record("k9", "flag", unverifiable=("K0",)))
    run(capsys, "tripwires", "record", "--batch", "b1", "--write", "--db", str(tmp_path / "ledger.db"))
    code, out = run(capsys, "trust", "--role", tl.ROLE, "--batch", "b1")
    assert "controls                1 of 2" in out
    assert "Note: 1 crashed or timed-out run(s) listed above as crashed hold an opinion from tripwire_v1 and ARE " \
           "counted in the figures above: k9" in out
