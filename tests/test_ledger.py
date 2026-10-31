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


def test_failed_run_has_no_results_to_check(led, tmp_path):
    led.append("h1", ledger.PROPOSED, {})
    led.append("h1", ledger.PREREGISTERED, {})
    led.append("h1", ledger.RAN, {"run_id": "r1", "results_sha256": None})
    assert led.verify(tmp_path) == []
