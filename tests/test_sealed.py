import sqlite3
from contextlib import closing

import pytest

from canary import sealed


@pytest.fixture
def table(tmp_path):
    return sealed.SealedTable(tmp_path / "sealed.db")


def test_a_canary_reads_back_with_its_bug_twin_and_impact(table):
    table.seal("r1", sealed.CANARY_MEASURE, "B03", "subtle", "t1", "h1", {"impact": {"size": 0.2}})
    truth = table.get("r1")
    assert (truth.bug_id, truth.tier, truth.twin_run_id, truth.source) == ("B03", "subtle", "t1", "h1")
    assert truth.details["impact"]["size"] == 0.2
    assert truth.known_buggy and not truth.known_clean


@pytest.mark.parametrize("run_type, buggy, clean", [
    (sealed.CONTROL, False, True), (sealed.SHAM, False, True), (sealed.REAL, False, False),
])
def test_only_canaries_are_known_buggy_and_real_runs_are_unknown(table, run_type, buggy, clean):
    truth = table.seal("r1", run_type)
    assert (truth.known_buggy, truth.known_clean) == (buggy, clean)


def test_unknown_run_gives_none(table):
    assert table.get("nope") is None


def test_a_run_type_cannot_be_changed_later(table):
    """Otherwise a miss could be relabelled after the review."""
    table.seal("r1", sealed.CONTROL)
    with pytest.raises(sealed.SealedError, match="already"):
        table.seal("r1", sealed.CANARY_MEASURE, "B01", "obvious")
    assert table.get("r1").run_type == sealed.CONTROL


def test_the_table_offers_no_way_to_edit():
    assert not any(hasattr(sealed.SealedTable, name) for name in ("update", "delete", "remove", "set"))


@pytest.mark.parametrize("args", [
    ("r1", "mystery"),
    ("r1", sealed.CANARY_MEASURE),
    ("r1", sealed.CANARY_PROBE, "B01"),
    ("r1", sealed.CONTROL, "B01", "obvious"),
    ("r1", sealed.SHAM, None, None, "t1"),
])
def test_records_that_contradict_themselves_are_refused(table, args):
    with pytest.raises(sealed.SealedError):
        table.seal(*args)
    assert table.all() == []


def test_the_sealed_file_is_not_the_ledger_database():
    from canary.config import DB_PATH
    assert sealed.SEALED_DB_PATH != DB_PATH


def test_data_survives_reopening(tmp_path):
    sealed.SealedTable(tmp_path / "s.db").seal("r1", sealed.SHAM, details={"renames": {"a": "b"}})
    assert sealed.SealedTable(tmp_path / "s.db").get("r1").details == {"renames": {"a": "b"}}


def test_stored_row_is_plain_sqlite(table):
    table.seal("r1", sealed.CONTROL)
    with closing(sqlite3.connect(table.path)) as db:
        assert db.execute("SELECT run_type FROM run_types").fetchall() == [("control",)]
