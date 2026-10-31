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
                    "canary.prereg", "canary.prompts", "canary.sandbox"}),
])
def test_reviewer_code_imports_only_what_is_allowed(name, allowed):
    """Ground truth is sacred. A new import here must be justified: adding the sealed table's module fails this test."""
    assert canary_imports(PACKAGE / name) <= allowed


@pytest.mark.parametrize("name", ["blinding.py", "skeptic.py", "ledger.py"])
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
