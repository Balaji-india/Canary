"""Tripwire records in the ledger (Mission 5.1 step 11). Fast: temporary ledger and sealed table, synthetic records,
no replay. The real ledger is never opened."""
import json

import pytest

from canary import config, ledger, sealed, skeptic, tripwire_ledger as tl, tripwires, trust
from eval import tripwires_dev as dev
from tests.test_skeptic import canary_imports, reachable_modules, PACKAGE

BUGS = [f"B{i:02d}" for i in range(1, 11)]
VERSION = tripwires.source_version()


def record(run_id, verdict="pass", fired=(), unverifiable=(), named=None, version=VERSION, tier="replay"):
    checks = {name: {"status": tripwires.OK, "evidence": "fine", "bug_class": None} for name in tripwires.CHAIN}
    for name in fired:
        checks[name] = {"status": tripwires.FIRED, "evidence": f"{name} broke", "bug_class": named}
    for name in unverifiable:
        checks[name] = {"status": tripwires.UNVERIFIABLE, "evidence": f"{name} unseen", "bug_class": None}
    return {"run_id": run_id, "verdict": verdict, "bug_class": named, "evidence": "x", "checks": checks,
            "advisory": {"no_skill_margin": 0.1}, "replay": {"status": "ok", "seconds": 1.0},
            "version": version, "tier": tier}


def ran(led, hypothesis, run_id, status="ok"):
    led.append(hypothesis, ledger.PROPOSED, {})
    led.append(hypothesis, ledger.PREREGISTERED, {})
    led.append(hypothesis, ledger.RAN, {"run_id": run_id, "run_status": status})


def store(folder, rec):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{rec['run_id']}.json").write_text(json.dumps(rec), encoding="utf-8")


@pytest.fixture
def led(tmp_path):
    return ledger.Ledger(tmp_path / "ledger.db")


def never(_folder):
    raise AssertionError("no record may be made here")


# The entry

def test_the_payload_carries_the_audit_shape_checks_version_and_hash():
    rec = record("r1", "flag", fired=("K2",), named="B03")
    payload = tl.ledger_payload("r1", rec)
    assert payload["role"] == tl.ROLE == "tripwire_v1"
    assert payload["audit"] == {"verdict": "flag", "bug_class": "B03", "evidence": "x"}
    assert payload["checks"]["K2"] == tripwires.FIRED and payload["checks"]["K1"] == tripwires.OK
    assert payload["tripwire_version"] == VERSION
    assert payload["record_sha256"] == tl.record_sha256(rec)
    assert tl.record_sha256(dict(reversed(list(rec.items())))) == payload["record_sha256"]  # key order is irrelevant


def test_a_static_tier_record_or_another_runs_record_is_refused():
    with pytest.raises(tl.TripwireLedgerError, match="replay-tier"):
        tl.ledger_payload("r1", record("r1", tier="static"))
    with pytest.raises(tl.TripwireLedgerError, match="offered for"):
        tl.ledger_payload("r2", record("r1"))


# Writing

def test_a_dry_run_writes_nothing_and_says_what_it_would_write(led, tmp_path):
    ran(led, "h1", "r1")
    store(tmp_path / "found", record("r1", "flag", fired=("K1",), named="B01"))
    before = len(led.entries())
    report = tl.record_runs(["r1"], led, folders=[tmp_path / "found"], records_dir=tmp_path / "made",
                            runs_dir=tmp_path / "runs", inspect=never)
    assert report.would_write == ["r1"] and report.written == [] and report.verdicts == {"flag": 1}
    assert len(led.entries()) == before and not (tmp_path / "made").exists()


def test_write_appends_one_audited_entry_per_run_and_a_repeat_adds_nothing(led, tmp_path):
    ran(led, "h1", "r1")
    ran(led, "h2", "r2", status="timeout")  # a run that timed out still gets its (flagging) record, as in the test
    store(tmp_path / "found", record("r1"))
    store(tmp_path / "found", record("r2", "flag", unverifiable=("K0",)))
    report = tl.record_runs(["r1", "r2"], led, write=True, folders=[tmp_path / "found"],
                            records_dir=tmp_path / "made", runs_dir=tmp_path / "runs", inspect=never)
    assert report.written == ["r1", "r2"] and report.verdicts == {"pass": 1, "flag": 1}
    audits = [e for e in led.entries(ledger.AUDITED) if e.payload["role"] == tl.ROLE]
    assert [(e.hypothesis_id, e.payload["audit"]["verdict"]) for e in audits] == [("h1", "pass"), ("h2", "flag")]
    again = tl.record_runs(["r1", "r2"], led, write=True, folders=[tmp_path / "found"],
                           records_dir=tmp_path / "made", runs_dir=tmp_path / "runs", inspect=never)
    assert again.already_recorded == ["r1", "r2"] and again.written == []
    assert len(led.entries()) == 8 and led.verify() == []


def test_runs_outside_the_ledger_closed_runs_and_runs_without_a_record_are_reported(led, tmp_path):
    ran(led, "h1", "r1")
    led.append("h1", ledger.GRAVEYARD, {})
    ran(led, "h2", "r2")
    report = tl.record_runs(["r1", "r2", "r3"], led, write=False, folders=[tmp_path / "none"],
                            records_dir=tmp_path / "made", runs_dir=tmp_path / "runs", inspect=never)
    assert report.closed == ["r1"] and report.no_record == ["r2"] and report.not_in_ledger == ["r3"]
    assert "1 closed" in report.summary() and "1 not in the ledger" in report.summary()


def test_a_record_of_another_version_is_not_used(led, tmp_path):
    ran(led, "h1", "r1")
    store(tmp_path / "found", record("r1", version="v1:old"))
    report = tl.record_runs(["r1"], led, folders=[tmp_path / "found"], records_dir=tmp_path / "made",
                            runs_dir=tmp_path / "runs", inspect=never)
    assert report.no_record == ["r1"]


def test_a_missing_record_is_made_from_the_folder_only_when_writing(led, tmp_path):
    ran(led, "h1", "r1")
    runs = tmp_path / "runs"
    (runs / "r1").mkdir(parents=True)
    seen = []

    def inspect(folder):
        seen.append(folder)
        rec = record("r1", "flag", fired=("K5",), named="B05")
        del rec["run_id"]  # run_tripwires returns no run_id; record_runs adds it
        return rec

    dry = tl.record_runs(["r1"], led, records_dir=tmp_path / "made", runs_dir=runs, inspect=inspect)
    assert dry.no_record == ["r1"] and seen == []
    report = tl.record_runs(["r1"], led, write=True, records_dir=tmp_path / "made", runs_dir=runs, inspect=inspect)
    assert report.made == ["r1"] and report.written == ["r1"] and seen == [runs / "r1"]
    stored = json.loads((tmp_path / "made" / "r1.json").read_text(encoding="utf-8"))
    assert stored["run_id"] == "r1" and tl.record_sha256(stored) == led.entries(ledger.AUDITED)[0].payload["record_sha256"]
    assert sorted(p.name for p in (runs / "r1").iterdir()) == []  # nothing written in the run folder


def test_records_of_another_version_under_the_role_stop_every_write(led, tmp_path):
    ran(led, "h1", "r1")
    ran(led, "h2", "r2")
    old = tl.ledger_payload("r1", record("r1", version="v1:old"))
    led.append("h1", ledger.AUDITED, old)
    store(tmp_path / "found", record("r2"))
    before = len(led.entries())
    with pytest.raises(tl.TripwireLedgerError, match="new VERSION"):
        tl.record_runs(["r2"], led, write=True, folders=[tmp_path / "found"], records_dir=tmp_path / "made",
                       runs_dir=tmp_path / "runs", inspect=never)
    assert len(led.entries()) == before


def test_verify_records_finds_an_edited_or_lost_record_file(led, tmp_path):
    ran(led, "h1", "r1")
    ran(led, "h2", "r2")
    folder = tmp_path / "found"
    store(folder, record("r1"))
    store(folder, record("r2", "flag", fired=("K3",), named="B04"))
    tl.record_runs(["r1", "r2"], led, write=True, folders=[folder], records_dir=tmp_path / "made",
                   runs_dir=tmp_path / "runs", inspect=never)
    assert tl.verify_records(led, [folder]) == []
    edited = record("r1", "flag", fired=("K1",), named="B01")
    store(folder, edited)
    (folder / "r2.json").unlink()
    problems = tl.verify_records(led, [folder])
    assert len(problems) == 2 and "does not match its hash" in problems[0] and "no record file" in problems[1]


# Living beside the LLM reviewer (the union is measured from both parts' records)

def test_a_tripwire_record_does_not_stop_the_llm_from_reviewing_the_run(led, tmp_path):
    ran(led, "h1", "r1")
    store(tmp_path / "found", record("r1", "flag", fired=("K1",), named="B01"))
    tl.record_runs(["r1"], led, write=True, folders=[tmp_path / "found"], records_dir=tmp_path / "made",
                   runs_dir=tmp_path / "runs", inspect=never)
    assert [entry.payload["run_id"] for entry, _ in skeptic._waiting(led, "skeptic_d")] == ["r1"]
    assert skeptic._waiting(led, tl.ROLE) == []
    led.append("h1", ledger.AUDITED, {"run_id": "r1", "role": "skeptic_d",
                                      "audit": {"verdict": "pass", "bug_class": None}})
    assert skeptic._waiting(led, "skeptic_d") == []


# The join gives the numbers the locked test's scoring gives (plan step 11, "Tests")

def _impact(change=0.0):
    return {"control": change, "treatment": 0.0, "effect": -change, "size": abs(change), "threshold": 0.005,
            "comparable": True}


def test_trust_from_the_ledger_equals_the_test_scoring_on_the_same_records(led, tmp_path):
    table = sealed.SealedTable(tmp_path / "sealed.db")
    batch = {"batch": "b1"}
    rows = [  # (run_id, type, bug, tier, record)
        ("c1", sealed.CANARY_MEASURE, "B01", "obvious", record("c1", "flag", fired=("K1",), named="B01")),
        ("c2", sealed.CANARY_MEASURE, "B01", "subtle", record("c2", "flag", fired=("K2",), named="B02")),
        ("c3", sealed.CANARY_MEASURE, "B05", "subtle", record("c3", "flag", unverifiable=("K0",))),
        ("c4", sealed.CANARY_MEASURE, "B09", "obvious", record("c4")),
        ("c5", sealed.CANARY_MEASURE, "B06", "obvious", record("c5", "flag", fired=("L1",), named="B06")),
        ("k1", sealed.CONTROL, None, None, record("k1")),
        ("k2", sealed.CONTROL, None, None, record("k2", "flag", unverifiable=("K0",))),
        ("s1", sealed.SHAM, None, None, record("s1")),
    ]
    folder = tmp_path / "found"
    for number, (run_id, run_type, bug, tier, rec) in enumerate(rows):
        details = {**batch, "impact": _impact(0.01)} if bug else dict(batch)
        table.seal(run_id, run_type, bug, tier, f"t{number}" if bug else None, f"pool:{number}", details)
        ran(led, f"h{number}", run_id)
        store(folder, rec)
    table.seal("other", sealed.CONTROL, details={"batch": "b2"})
    ran(led, "h-other", "other")
    store(folder, record("other", "flag", unverifiable=("K0",)))
    report = tl.record_runs([r[0] for r in rows] + ["other"], led, write=True, folders=[folder],
                            records_dir=tmp_path / "made", runs_dir=tmp_path / "runs", inspect=never)
    assert len(report.written) == 9

    observations, excluded = trust.collect_observations(table, led, tl.ROLE, "b1")
    summary = trust.summarize(observations, BUGS, 200)
    truths = [t for t in table.all() if t.details.get("batch") == "b1"]
    scored = dev.score({r[0]: r[4] for r in rows}, truths, {}, BUGS, 200)
    for bug in BUGS:
        any_flag = scored["per_class"][bug]["any_flag"]
        assert (summary.per_class[bug].successes, summary.per_class[bug].n) == (any_flag["successes"], any_flag["n"])
    pooled = scored["any_flag"]["recall"]
    assert sum(p.successes for p in summary.per_class.values()) == pooled["successes"] == 4
    assert sum(p.n for p in summary.per_class.values()) == pooled["n"] == 5
    for mine, theirs in ((summary.specificity, "specificity"), (summary.control_specificity, "control_specificity"),
                         (summary.sham_specificity, "sham_specificity")):
        assert (mine.successes, mine.n) == (scored["headline"][theirs]["successes"], scored["headline"][theirs]["n"])
    assert (summary.specificity.successes, summary.specificity.n) == (2, 3)  # hand count: k1 and s1 pass, k2 flags
    assert excluded["other_batch"] == 1


# Guards: this module chooses nothing from the truth and reads no reviewer's opinion

FORBIDDEN = ("canary.sealed", "canary.controls", "canary.mixer", "canary.trust", "canary.padding", "canary.skeptic",
             "canary.blinding", "canary.llm", "canary.review_tasks")


def test_the_ledger_writer_imports_nothing_that_reaches_the_truth_or_a_reviewer():
    assert canary_imports(PACKAGE / "tripwire_ledger.py") == {"canary.ledger", "canary.sandbox", "canary.tripwires",
                                                              "canary.config", "canary.prereg"}
    reached = reachable_modules("canary.tripwire_ledger")
    assert "canary.ledger" in reached and "canary.tripwires" in reached  # proves the walk follows imports
    for module in reached:
        assert module not in FORBIDDEN and not module.startswith("canary.saboteur"), module


def test_the_ledger_writer_never_names_the_sealed_table_plans_or_twins():
    source = (PACKAGE / "tripwire_ledger.py").read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]  # the module docstring may say what it never opens
    for word in ("sealed", "run_type", "sealed_plans", "twins", "TWINS_DIR"):
        assert word not in code, word


def test_the_default_records_folder_is_outside_the_run_folders():
    assert tl.RECORDS_DIR == config.DATA_DIR / "tripwires" / "v1"
    assert not str(tl.RECORDS_DIR).startswith(str(config.DATA_DIR / "runs"))
