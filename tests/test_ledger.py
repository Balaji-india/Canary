import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from canary import ledger
from canary.ledger import GENESIS_HASH, Ledger


@pytest.fixture
def led(tmp_path):
    return Ledger(tmp_path / "test.db")


def fill(led):
    led.append("h1", ledger.PROPOSED, {"n": 1})
    led.append("h1", ledger.PREREGISTERED, {"n": 2})
    led.append("h2", ledger.PROPOSED, {"n": 3})
    led.append("h1", ledger.RAN, {"n": 4})


def edit(led, sql):
    """A manual edit, going around the Ledger class just as someone with a database tool would."""
    with closing(sqlite3.connect(led.path)) as db, db:
        db.execute(sql)


def test_entries_chain_from_the_genesis_hash(led):
    first = led.append("h1", ledger.PROPOSED, {"n": 1})
    second = led.append("h1", ledger.PREREGISTERED, {"n": 2})
    assert first.prev_hash == GENESIS_HASH
    assert second.prev_hash == first.hash
    assert (first.seq, second.seq) == (1, 2)


def test_intact_ledger_verifies(led):
    fill(led)
    assert led.verify() == []


def test_empty_ledger_verifies(led):
    assert led.verify() == []


def test_entries_read_back_and_filter(led):
    fill(led)
    assert [e.payload["n"] for e in led.entries()] == [1, 2, 3, 4]
    assert [e.hypothesis_id for e in led.entries(ledger.PROPOSED)] == ["h1", "h2"]


def test_chain_survives_reopening(led):
    fill(led)
    Ledger(led.path).append("h2", ledger.PREREGISTERED, {"n": 5})
    assert led.verify() == []


@pytest.mark.parametrize("sql, expected", [
    ("UPDATE ledger SET payload = '{\"n\":99}' WHERE seq = 2", "entry 2: content does not match"),
    ("UPDATE ledger SET status = 'accepted' WHERE seq = 2", "entry 2: content does not match"),
    ("UPDATE ledger SET created_at = 'x' WHERE seq = 1", "entry 1: content does not match"),
    ("UPDATE ledger SET hash = 'x' WHERE seq = 2", "entry 2: content does not match"),
    ("DELETE FROM ledger WHERE seq = 2", "entry 3: expected number 2"),
])
def test_manual_edits_are_detected(led, sql, expected):
    fill(led)
    edit(led, sql)
    assert any(expected in problem for problem in led.verify())


def test_editing_a_hash_also_breaks_the_next_link(led):
    fill(led)
    edit(led, "UPDATE ledger SET hash = 'x' WHERE seq = 2")
    assert any("entry 3: does not link" in problem for problem in led.verify())


def test_corrupt_payload_is_reported_not_raised_when_checking_results(led, tmp_path):
    led.append("h1", ledger.PROPOSED, {})
    led.append("h1", ledger.PREREGISTERED, {})
    led.append("h1", ledger.RAN, {"run_id": "r", "results_sha256": None})
    edit(led, "UPDATE ledger SET payload = 'not json' WHERE seq = 3")
    assert any("not valid JSON" in problem for problem in led.verify(tmp_path))


def test_removing_the_newest_entry_is_a_known_limit(led):
    """Documents the limit stated in the module docstring: a shorter chain is still a valid chain."""
    fill(led)
    edit(led, "DELETE FROM ledger WHERE seq = 4")
    assert led.verify() == []


def test_illegal_transitions_are_refused_and_write_nothing(led):
    with pytest.raises(ledger.LedgerError):
        led.append("h1", ledger.RAN, {})
    led.append("h1", ledger.PROPOSED, {})
    with pytest.raises(ledger.LedgerError):
        led.append("h1", ledger.ACCEPTED, {})
    assert len(led.entries()) == 1
    assert led.verify() == []


def test_a_run_cannot_happen_before_the_lock(led):
    led.append("h1", ledger.PROPOSED, {})
    with pytest.raises(ledger.LedgerError, match="proposed to ran"):
        led.append("h1", ledger.RAN, {})


def test_finished_hypotheses_cannot_continue(led):
    led.append("h1", ledger.PROPOSED, {})
    led.append("h1", ledger.GRAVEYARD, {})
    with pytest.raises(ledger.LedgerError):
        led.append("h1", ledger.PREREGISTERED, {})


def test_ledger_has_no_way_to_change_an_entry():
    assert not [name for name in dir(Ledger) if name.startswith(("update", "delete", "remove", "edit"))]


def ran_entry(led, tmp_path, content=b'{"a":1}'):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "results.json").write_bytes(content)
    led.append("h1", ledger.PROPOSED, {})
    led.append("h1", ledger.PREREGISTERED, {})
    led.append("h1", ledger.RAN, {"run_id": "r1", "results_sha256": hashlib.sha256(content).hexdigest()})
    return run_dir, tmp_path / "runs"


def test_unchanged_results_file_verifies(led, tmp_path):
    _, runs = ran_entry(led, tmp_path)
    assert led.verify(runs) == []


def test_edited_results_file_is_detected(led, tmp_path):
    run_dir, runs = ran_entry(led, tmp_path)
    (run_dir / "results.json").write_text(json.dumps({"a": 2}), encoding="utf-8")
    assert "does not match its stored hash" in led.verify(runs)[0]


def test_missing_results_file_is_detected(led, tmp_path):
    run_dir, runs = ran_entry(led, tmp_path)
    (run_dir / "results.json").unlink()
    assert "missing" in led.verify(runs)[0]


def test_edited_script_is_detected(led, tmp_path):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "experiment.py").write_text("x = 1", encoding="utf-8")
    digest = hashlib.sha256((run_dir / "experiment.py").read_bytes()).hexdigest()
    led.append("h1", ledger.PROPOSED, {})
    led.append("h1", ledger.PREREGISTERED, {})
    led.append("h1", ledger.RAN, {"run_id": "r1", "results_sha256": None, "script_sha256": digest})
    assert led.verify(tmp_path / "runs") == []
    (run_dir / "experiment.py").write_text("x = 2", encoding="utf-8")
    assert "script file does not match" in led.verify(tmp_path / "runs")[0]


def test_failed_run_has_no_results_to_check(led, tmp_path):
    led.append("h1", ledger.PROPOSED, {})
    led.append("h1", ledger.PREREGISTERED, {})
    led.append("h1", ledger.RAN, {"run_id": "r1", "results_sha256": None})
    assert led.verify(tmp_path) == []


# ---- The anchor (roadmap findings 14 and 26): a tracked copy of the head's number and hash ----------------------

@pytest.fixture
def anchored(tmp_path):
    led = Ledger(tmp_path / "anchored.db", anchor_path=tmp_path / "anchor.json")
    fill(led)
    ledger.write_anchor(led)
    return led


def test_an_honest_append_after_the_anchor_verifies(anchored):
    anchored.append("h2", ledger.PREREGISTERED, {"n": 5})
    anchored.append("h3", ledger.PROPOSED, {"n": 6})
    assert anchored.verify() == []
    assert json.loads(anchored.anchor_path.read_text(encoding="utf-8"))["entries"] == 4  # the anchor did not move


def test_removing_the_newest_entries_is_detected_by_the_anchor(anchored):
    edit(anchored, "DELETE FROM ledger WHERE seq >= 3")
    unanchored = Ledger(anchored.path, anchor_path=None)
    unanchored.anchor_path = None
    assert unanchored.verify() == []  # the chain alone cannot see it (the known limit above)
    problems = anchored.verify()
    assert len(problems) == 1 and "entry 4" in problems[0] and "removed" in problems[0]


def test_removing_only_the_anchored_entry_is_detected(anchored):
    anchored.append("h2", ledger.PREREGISTERED, {"n": 5})
    edit(anchored, "DELETE FROM ledger WHERE seq >= 4")
    assert any("entry 4" in p and "removed" in p for p in anchored.verify())


def test_a_rewritten_chain_is_detected_by_the_anchor(anchored):
    """Rewrite entry 2 and recompute every hash after it: the chain is valid again, but not the anchored one."""
    rows = anchored._rows()
    edit(anchored, "DELETE FROM ledger")
    prev = GENESIS_HASH
    with closing(sqlite3.connect(anchored.path)) as db, db:
        for seq, hypothesis_id, status, payload_text, created_at, _, _ in rows:
            if seq == 2:
                payload_text = '{"n":99}'
            new_hash = ledger._entry_hash(seq, hypothesis_id, status, payload_text, created_at, prev)
            db.execute("INSERT INTO ledger VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (seq, hypothesis_id, status, payload_text, created_at, prev, new_hash))
            prev = new_hash
    problems = anchored.verify()
    assert len(problems) == 1 and "rewritten" in problems[0]


def test_anchoring_changes_no_ledger_entry(tmp_path):
    led = Ledger(tmp_path / "l.db", anchor_path=tmp_path / "anchor.json")
    fill(led)
    before = hashlib.sha256(led.path.read_bytes()).hexdigest()
    anchor = ledger.write_anchor(led)
    assert hashlib.sha256(led.path.read_bytes()).hexdigest() == before
    assert anchor["entries"] == 4 and anchor["head_hash"] == led.entries()[-1].hash
    assert (tmp_path / "anchor.json").read_bytes().count(b"\r\n") == 0  # LF, as git stores it


def test_a_broken_or_empty_chain_is_never_anchored(tmp_path):
    led = Ledger(tmp_path / "l.db", anchor_path=tmp_path / "anchor.json")
    with pytest.raises(ledger.LedgerError, match="empty"):
        ledger.write_anchor(led)
    fill(led)
    edit(led, "UPDATE ledger SET payload = '{\"n\":9}' WHERE seq = 2")
    with pytest.raises(ledger.LedgerError, match="not anchored"):
        ledger.write_anchor(led)
    assert not (tmp_path / "anchor.json").exists()


def test_only_the_real_ledger_uses_the_tracked_anchor_by_default(tmp_path):
    assert Ledger(tmp_path / "x.db").anchor_path is None
    # keyword-only, so the positional defaults stay (DB_PATH,): tests redirect the default ledger through them
    assert ledger.Ledger.__init__.__defaults__ == (ledger.DB_PATH,)
    assert ledger.ANCHOR_PATH.name == "ledger_anchor.json" and ledger.ANCHOR_PATH.parent == ledger.ROOT


def test_no_anchor_file_means_nothing_to_check(tmp_path):
    led = Ledger(tmp_path / "l.db", anchor_path=tmp_path / "missing.json")
    fill(led)
    assert led.verify() == [] and led.anchor_problems() == []


def test_the_module_command_anchors_and_checks(tmp_path, capsys):
    led = Ledger(tmp_path / "l.db")
    fill(led)
    args = ["--db", str(led.path), "--anchor", str(tmp_path / "a.json")]
    assert ledger.main(["anchor", *args]) == 0
    assert ledger.main(["check", *args]) == 0
    edit(led, "DELETE FROM ledger WHERE seq = 4")
    assert ledger.main(["check", *args]) == 1
    out = capsys.readouterr().out
    assert "Anchored entry 4" in out and "Ledger check: OK" in out and "Ledger check: FAILED" in out
