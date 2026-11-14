"""The model is faked here: these tests cover what the Skeptic may see and what gets stored."""
import ast
import hashlib
import json
from pathlib import Path

import pytest

from canary import blinding, config, ledger, llm, prereg, prompts, sandbox, skeptic
from canary.ledger import Ledger
from tests.test_llm import CFG, FakeProvider
from tests.test_scientist import lock

PACKAGE = Path(skeptic.__file__).parent
PASS_REPLY = json.dumps({"verdict": "pass", "bug_class": None, "evidence": "Looks fine.", "confidence": 0.8})
FLAG_REPLY = json.dumps({"verdict": "flag", "bug_class": "B03", "evidence": "Scored on X_train.", "confidence": 0.9})
SCRIPT = "# a comment\nx = 1\n"
RESULTS = {"schema_version": 1, "dataset": "breast_cancer", "metric": "f1", "seeds": [0, 1], "control": [0.8, 0.8],
           "treatment": [0.9, 0.9], "class_balance": {"0": 1}, "split_sizes": {"train": [3, 3], "test": [1, 1]},
           "runtime_seconds": 1.5}


def canary_imports(module_file):
    """Every part of the canary package that a source file imports."""
    found = set()
    for node in ast.walk(ast.parse(module_file.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.split(".")[0] == "canary")
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "canary":
            if node.module == "canary":
                found.update(f"canary.{alias.name}" for alias in node.names)
            else:
                found.add(node.module)
    return found


@pytest.mark.parametrize("name, allowed", [
    ("blinding.py", set()),
    ("skeptic.py", {"canary.blinding", "canary.codegen", "canary.config", "canary.ledger", "canary.llm",
                    "canary.prereg", "canary.review_tasks", "canary.sandbox"}),
    ("review_tasks.py", {"canary.prompts"}),
])
def test_reviewer_code_imports_only_what_is_allowed(name, allowed):
    """Ground truth is sacred. A new import here must be justified: adding the sealed table's module fails this test."""
    assert canary_imports(PACKAGE / name) <= allowed


@pytest.mark.parametrize("name", ["blinding.py", "skeptic.py", "ledger.py", "review_tasks.py"])
def test_reviewer_code_never_mentions_run_types(name):
    source = (PACKAGE / name).read_text(encoding="utf-8")
    tree = ast.parse(source)
    text = " ".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and not _is_docstring(tree, n))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for word in ("run_type", "sealed", "ground_truth"):
        assert word not in text and word not in names


def _is_docstring(tree, constant):
    return any(isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef)) and owner.body
               and getattr(owner.body[0], "value", None) is constant for owner in ast.walk(tree))


def reachable_modules(start):
    """Every canary module reached from `start` by following imports, however indirectly."""
    seen, waiting = set(), [start]
    while waiting:
        name = waiting.pop()
        if name in seen:
            continue
        seen.add(name)
        path = PACKAGE.parent / Path(*name.split("."))
        file = path.with_suffix(".py") if path.with_suffix(".py").exists() else path / "__init__.py"
        waiting.extend(canary_imports(file))
    return seen


@pytest.mark.parametrize("start", ["canary.skeptic", "canary.blinding"])
def test_no_import_chain_from_reviewer_code_reaches_ground_truth(start):
    """A direct-import test would miss the table being reached through a helper."""
    reached = reachable_modules(start)
    assert "canary.ledger" in reached or start == "canary.blinding"  # proves the walk follows imports
    for module in reached:
        assert module not in ("canary.sealed", "canary.controls", "canary.trust", "canary.mixer"), module
        assert not module.startswith("canary.saboteur"), module


def test_no_module_on_the_reviewer_path_names_the_sealed_file_or_table():
    for module in reachable_modules("canary.skeptic"):
        source = (PACKAGE.parent / Path(*module.split("."))).with_suffix(".py").read_text(encoding="utf-8")
        for word in ("sealed.db", "run_types", "SEALED_DB_PATH", "sealed_plans", "PLANS_DIR"):
            assert word not in source, f"{module} mentions {word}"


def test_ground_truth_file_is_not_opened_during_an_audit(tmp_path, monkeypatch):
    """The import tests read the code; this one watches a real audit with a filled table sitting beside the ledger."""
    import sqlite3
    from canary import sealed

    led = Ledger(tmp_path / "ledger.db")
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    table = sealed.SealedTable(tmp_path / "sealed.db")
    table.seal("r1", sealed.CANARY_MEASURE, "B03", "obvious")
    client, _ = make_client(tmp_path, [PASS_REPLY])
    opened = []
    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda path, *a, **k: opened.append(Path(path)) or real_connect(path, *a, **k))
    report = skeptic.audit_pending(client, led, runs)
    assert len(report.audited) == 1 and opened
    assert table.path not in opened


def test_ledger_database_has_no_table_of_run_types(tmp_path):
    import sqlite3
    from contextlib import closing
    from canary import sealed

    led = Ledger(tmp_path / "ledger.db")
    sealed.SealedTable(tmp_path / "sealed.db").seal("r1", sealed.CONTROL)
    with closing(sqlite3.connect(led.path)) as db:
        assert [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")] == ["ledger"]


def test_prompt_never_mentions_the_test_situation():
    blinded = blinding.BlindedRun("x = 1", "{}", "{}")
    text = (prompts.skeptic_prompt(blinded, config.load_yaml("bug_classes.yaml")) + prompts.SKEPTIC_SYSTEM).lower()
    for word in ("canary", "control run", "sham", "planted", "test of you"):
        assert word not in text


def test_prompt_lists_classes_but_not_the_catalog_hints():
    bugs = config.load_yaml("bug_classes.yaml")
    text = prompts.skeptic_prompt(blinding.BlindedRun("x = 1", "{}", "{}"), bugs)
    assert "B10: easy test subset" in text
    assert bugs["B01"]["subtle"] not in text and bugs["B01"]["obvious"] not in text


SCHEMA = skeptic.audit_schema(["B01", "B03"])


@pytest.mark.parametrize("reply", [
    {"verdict": "pass", "bug_class": None, "evidence": "e", "confidence": 0.5},
    {"verdict": "flag", "bug_class": "B03", "evidence": "e", "confidence": 0.5},
])
def test_consistent_audits_fit_the_schema(reply):
    assert llm.schema_problem(reply, SCHEMA) is None


@pytest.mark.parametrize("reply", [
    {"verdict": "pass", "bug_class": "B03", "evidence": "e", "confidence": 0.5},
    {"verdict": "flag", "bug_class": None, "evidence": "e", "confidence": 0.5},
    {"verdict": "flag", "bug_class": "B99", "evidence": "e", "confidence": 0.5},
    {"verdict": "maybe", "bug_class": None, "evidence": "e", "confidence": 0.5},
    {"verdict": "pass", "bug_class": None, "evidence": "e", "confidence": 1.5},
    {"verdict": "pass", "bug_class": None, "confidence": 0.5},
])
def test_inconsistent_audits_are_rejected(reply):
    assert llm.schema_problem(reply, SCHEMA) is not None


@pytest.fixture
def led(tmp_path):
    return Ledger(tmp_path / "ledger.db")


def add_ran_run(led, runs_dir, hypothesis_id="h1", run_id="r1", script=SCRIPT):
    """Put one finished run into the ledger and on disk."""
    locked = lock()
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "experiment.py").write_text(script, encoding="utf-8")
    (run_dir / sandbox.RESULTS_NAME).write_text(json.dumps(RESULTS), encoding="utf-8")
    led.append(hypothesis_id, ledger.PROPOSED, {})
    led.append(hypothesis_id, ledger.PREREGISTERED, {"prereg": locked, "prereg_sha256": prereg.prereg_hash(locked)})
    led.append(hypothesis_id, ledger.RAN, {
        "run_id": run_id, "run_status": "ok", "reason": None,
        "results_sha256": hashlib.sha256((run_dir / sandbox.RESULTS_NAME).read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256((run_dir / "experiment.py").read_bytes()).hexdigest(),
        "verdict": {"outcome": "VERDICT_MARKER"},
    })
    return run_dir


def add_crashed_run(led, hypothesis_id="h2"):
    locked = lock()
    led.append(hypothesis_id, ledger.PROPOSED, {})
    led.append(hypothesis_id, ledger.PREREGISTERED, {"prereg": locked, "prereg_sha256": prereg.prereg_hash(locked)})
    led.append(hypothesis_id, ledger.RAN, {"run_id": "crashed", "run_status": "crash", "reason": "exit code 1",
                                           "results_sha256": None, "script_sha256": None, "verdict": {}})


def make_client(tmp_path, replies=()):
    provider = FakeProvider(list(replies))
    return llm.LLM(CFG, {"fake": provider}, tmp_path / "cache.db"), provider


def test_audit_is_stored_in_the_ledger(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    client, _ = make_client(tmp_path, [FLAG_REPLY])
    report = skeptic.audit_pending(client, led, runs)
    assert len(report.audited) == 1 and not report.errors
    stored = led.entries(ledger.AUDITED)[0].payload
    assert stored["audit"]["bug_class"] == "B03" and stored["model"] == "ska:1"
    assert led.verify(runs) == []


def test_skeptic_sees_blinded_text_only(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs, hypothesis_id="HYP-ID-MARKER", run_id="RUN-ID-MARKER", script="# COMMENT-MARKER\nx = 1\n")
    client, provider = make_client(tmp_path, [PASS_REPLY])
    skeptic.audit_pending(client, led, runs)
    sent = provider.calls[0]["prompt"] + provider.calls[0]["system"]
    assert "x = 1" in sent
    for hidden in ("COMMENT-MARKER", "RUN-ID-MARKER", "HYP-ID-MARKER", "VERDICT_MARKER", "runtime_seconds"):
        assert hidden not in sent


def test_skeptic_uses_a_different_model_at_temperature_zero(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    client, provider = make_client(tmp_path, [PASS_REPLY])
    skeptic.audit_pending(client, led, runs)
    assert (provider.calls[0]["model"], provider.calls[0]["temperature"]) == ("ska:1", 0.0)


def test_audit_runs_once_per_run(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    client, provider = make_client(tmp_path, [PASS_REPLY])
    skeptic.audit_pending(client, led, runs)
    assert skeptic.audit_pending(client, led, runs).audited == []
    assert len(provider.calls) == 1


def test_crashed_run_goes_to_the_graveyard_without_a_model_call(tmp_path, led):
    add_crashed_run(led)
    client, provider = make_client(tmp_path)
    report = skeptic.audit_pending(client, led, tmp_path / "runs")
    assert "crash" in report.no_results[0]["cause"]
    assert "crash" in led.entries(ledger.GRAVEYARD)[0].payload["cause"]
    assert provider.calls == []


def test_edited_results_are_not_reviewed(tmp_path, led):
    runs = tmp_path / "runs"
    run_dir = add_ran_run(led, runs)
    (run_dir / sandbox.RESULTS_NAME).write_text("{}", encoding="utf-8")
    client, provider = make_client(tmp_path)
    report = skeptic.audit_pending(client, led, runs)
    assert "results.json does not match" in report.errors[0]
    assert provider.calls == [] and led.entries(ledger.AUDITED) == []


def test_edited_script_is_not_reviewed(tmp_path, led):
    runs = tmp_path / "runs"
    run_dir = add_ran_run(led, runs)
    (run_dir / "experiment.py").write_text("x = 2", encoding="utf-8")
    client, provider = make_client(tmp_path)
    assert "experiment.py does not match" in skeptic.audit_pending(client, led, runs).errors[0]
    assert provider.calls == []


def test_missing_files_are_an_error_not_a_crash(tmp_path, led):
    runs = tmp_path / "runs"
    run_dir = add_ran_run(led, runs)
    (run_dir / sandbox.RESULTS_NAME).unlink()
    client, _ = make_client(tmp_path)
    assert skeptic.audit_pending(client, led, runs).errors


def test_model_failure_leaves_the_run_waiting_for_a_later_audit(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    client, _ = make_client(tmp_path, ["junk"] * 3 + [PASS_REPLY])
    assert skeptic.audit_pending(client, led, runs).errors
    assert led.entries(ledger.AUDITED) == []
    assert len(skeptic.audit_pending(client, led, runs).audited) == 1


def test_one_failure_does_not_block_other_audits(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs, "h1", "r1")
    add_ran_run(led, runs, "h2", "r2", script="y = 2\n")
    client, _ = make_client(tmp_path, ["junk"] * 3 + [PASS_REPLY])
    report = skeptic.audit_pending(client, led, runs)
    assert (len(report.errors), len(report.audited)) == (1, 1)
    assert report.audited[0]["hypothesis_id"] == "h2"


def test_failed_audit_is_recorded_with_its_run_and_kind_and_stays_waiting(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    client, _ = make_client(tmp_path, ["junk"] * 3 + [PASS_REPLY])
    report = skeptic.audit_pending(client, led, runs)
    stored = led.entries(ledger.AUDIT_FAILED)[0].payload
    assert (stored["run_id"], stored["kind"]) == ("r1", llm.KIND_INVALID_REPLY)
    assert report.failures[0]["run_id"] == "r1" and led.verify(runs) == []
    assert len(skeptic.audit_pending(client, led, runs).audited) == 1


@pytest.mark.slow
def test_oversized_prompt_is_recorded_as_its_own_kind(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs, script="x = 1\n" * 20000)
    client, provider = make_client(tmp_path)
    report = skeptic.audit_pending(client, led, runs)
    assert report.failures[0]["kind"] == llm.KIND_PROMPT_TOO_LARGE and provider.calls == []


class DownProvider(FakeProvider):
    def generate(self, *args, **kwargs):
        raise llm.LLMError("connection refused")


def test_an_outage_stops_the_pass_and_leaves_the_rest_waiting(tmp_path, led):
    runs = tmp_path / "runs"
    for number in range(4):
        add_ran_run(led, runs, f"h{number}", f"r{number}", script=f"x = {number}\n")
    client = llm.LLM(CFG, {"fake": DownProvider([])}, tmp_path / "cache.db")
    report = skeptic.audit_pending(client, led, runs, chunk_size=1, stop_after=3)
    assert "server failures" in report.stopped
    assert len(report.failures) == 3
    assert all(f["kind"] == llm.KIND_TIMEOUT_OR_SERVER for f in report.failures)


def test_reviews_are_stored_after_each_chunk_not_at_the_end(tmp_path, led):
    runs = tmp_path / "runs"
    for number in range(2):
        add_ran_run(led, runs, f"h{number}", f"r{number}", script=f"x = {number}\n")
    client, _ = make_client(tmp_path, [PASS_REPLY, PASS_REPLY])
    stored_at_progress = []
    skeptic.audit_pending(client, led, runs, chunk_size=1,
                          on_progress=lambda d, t, item: stored_at_progress.append(len(led.entries(ledger.AUDITED))))
    assert stored_at_progress == [1, 2]
