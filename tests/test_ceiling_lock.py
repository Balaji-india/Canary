"""The lock tools of the ceiling check: plan parsing, hash checks, the manifest and the lock file. No network."""
import hashlib
import json

import pytest

from canary import config, sealed
from canary.ledger import Ledger
from eval import ceiling_lock
from tests.test_skeptic import add_ran_run


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan_text(entries: str) -> str:
    return ("# Plan\n\n## 2. Settings\n- `not/frozen.py` " + "a" * 64 + "\n\n## 3. Frozen inputs\nText.\n" + entries +
            "\n## 4. Data\n- `also/not.py` " + "b" * 64 + "\n")


def test_only_section_3_entries_are_read_whole_files_and_first_lines():
    text = plan_text(f"- `eval/x.py` {'c' * 64}\n- first 3 lines of `data/log.jsonl` {'d' * 64}: the smoke test\n"
                     f"- Wire schema: {'e' * 64} (not a file)\n")
    assert ceiling_lock.plan_entries(text) == [("eval/x.py", None, "c" * 64), ("data/log.jsonl", 3, "d" * 64)]
    with pytest.raises(ValueError, match="no section 3"):
        ceiling_lock.plan_entries("# Plan\n\n## 1. Question\n")


def test_a_changed_or_missing_file_is_named_and_a_grown_log_still_passes(tmp_path):
    (tmp_path / "code.py").write_bytes(b"x = 1\n")
    (tmp_path / "log.jsonl").write_bytes(b"one\ntwo\n")
    entries = [("code.py", None, digest(b"x = 1\n")), ("log.jsonl", 2, digest(b"one\ntwo\n")),
               ("gone.py", None, "0" * 64)]
    assert ceiling_lock.file_problems(entries, tmp_path) == ["gone.py: missing"]
    with (tmp_path / "log.jsonl").open("ab") as f:
        f.write(b"three\n")  # new calls append lines: allowed
    (tmp_path / "code.py").write_bytes(b"x = 2\n")
    assert ceiling_lock.file_problems(entries[:2], tmp_path) == ["code.py: hash differs from the plan"]
    (tmp_path / "log.jsonl").write_bytes(b"ONE\ntwo\nthree\n")  # an old line edited: not allowed
    assert ceiling_lock.file_problems(entries[1:2], tmp_path) == ["log.jsonl: hash differs from the plan (first 2 lines)"]


def test_the_lock_is_written_once_and_an_edited_plan_fails_it(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_bytes(b"# Plan\n")
    assert ceiling_lock.lock_problem(plan) == ceiling_lock.NOT_LOCKED
    lock = ceiling_lock.write_lock(plan)
    assert lock.read_bytes() == f"{digest(b'# Plan' + bytes([10]))}  plan.md\n".encode() and ceiling_lock.lock_problem(plan) is None
    with pytest.raises(FileExistsError, match="amendment"):
        ceiling_lock.write_lock(plan)
    plan.write_bytes(b"# Plan, edited\n")
    assert "does not match" in ceiling_lock.lock_problem(plan)


def test_the_manifest_names_no_run_type_and_changes_when_a_prompt_would(tmp_path):
    led, table, runs = Ledger(tmp_path / "ledger.db"), sealed.SealedTable(tmp_path / "sealed.db"), tmp_path / "runs"
    for i, run_type in enumerate((sealed.CANARY_MEASURE, sealed.CONTROL)):
        add_ran_run(led, runs, f"h{i}", f"r{i}", script=f"x = {i}\n")
        table.seal(f"r{i}", run_type, *(("B01", "obvious") if i == 0 else (None, None)), source="pool:0",
                   details={"batch": "b"})
    cfg, bugs = config.load_yaml("models.yaml"), config.load_yaml("bug_classes.yaml")
    manifest = ceiling_lock.build_manifest(led, table, cfg, bugs, ("b",), runs_dir=runs)
    assert [r["run_id"] for r in manifest["runs"]] == ["r0", "r1"] and len(manifest["wire_schema_sha256"]) == 1
    assert manifest["runs"][0]["prompt_sha256"] != manifest["runs"][1]["prompt_sha256"]
    text = json.dumps(manifest["runs"])
    assert not any(word in text for word in (sealed.CANARY_MEASURE, sealed.CONTROL, "B01", "obvious"))
    assert ceiling_lock.build_manifest(led, table, cfg, bugs, ("b",), runs_dir=runs) == manifest  # deterministic
    (runs / "r1" / "experiment.py").write_text("x = 99\n", encoding="utf-8")  # a run file edited after the lock
    with pytest.raises(ValueError, match="does not match its stored hash"):
        ceiling_lock.build_manifest(led, table, cfg, bugs, ("b",), runs_dir=runs)
