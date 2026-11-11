"""Cloud roles in the audit path and the CLI: no probabilities, the daily stop, the repeat pass, isolation, smoke.

A real OpenAIStyleProvider runs with a fake transport and a fake clock: nothing reaches the network or waits.
"""
import argparse
import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from canary import cli, config, ledger, llm, review_tasks, sealed, skeptic
from canary.ledger import Ledger
from tests.test_cloud import CFG, KEY, FakeClock, FakeTransport, ok_body
from tests.test_llm import FakeProvider
from tests.test_skeptic import FLAG_REPLY, PASS_REPLY, add_ran_run, reachable_modules

CLOUD_CFG = copy.deepcopy(CFG)
CLOUD_CFG["providers"]["cloudy"] = dict(CLOUD_CFG["providers"]["cloudy"], context_tokens=131072)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("TEST_CLOUD_KEY", KEY)


def cloud_client(tmp_path, answers=(), cfg=CLOUD_CFG, clock=None, cache="cache.db", **entry_changes):
    clock = clock or FakeClock()
    transport = FakeTransport(answers)
    entry = dict(cfg["providers"]["cloudy"], **entry_changes)
    provider = llm.OpenAIStyleProvider(cfg["llm"], entry, "cloudy", transport, clock, clock.sleep, tmp_path / "calls.jsonl")
    local = FakeProvider([PASS_REPLY] * 10)
    client = llm.LLM(copy.deepcopy(cfg), {"cloudy": provider, "fake": local}, tmp_path / cache)
    return client, transport, clock, local


def reply(text):
    return 200, {}, ok_body(text)


def runs_in(led, tmp_path, n):
    runs = tmp_path / "runs"
    for i in range(n):
        add_ran_run(led, runs, f"h{i}", f"r{i}", script=f"x = {i}\n")
    return runs


# ---- step 6: no token probabilities for cloud roles -------------------------------------------------------------------

def test_a_cloud_role_is_audited_without_probabilities_or_a_score(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    runs = runs_in(led, tmp_path, 1)
    client, transport, _, _ = cloud_client(tmp_path, [reply(FLAG_REPLY)])
    report = skeptic.audit_pending(client, led, runs, role="skeptic_d")
    stored = led.entries(ledger.AUDITED)[0].payload
    assert len(report.audited) == 1 and "score" not in stored
    assert stored["decision"]["verdict"] == "flag" and stored["model"] == "vendor/model-x"
    assert not any("logprob" in k for k in transport.requests[0]["body"])


def test_local_roles_still_ask_for_twenty_probabilities():
    assert skeptic.top_logprobs_of(CLOUD_CFG, "skeptic_a") == 20
    assert skeptic.top_logprobs_of(CLOUD_CFG, "skeptic_d") == 0
    assert skeptic.top_logprobs_of(CLOUD_CFG, "skeptic_d_checklist") == 0  # through the alias
    shipped = config.load_yaml("models.yaml")
    assert skeptic.top_logprobs_of(shipped, "skeptic_c_checklist") == 20
    assert {skeptic.top_logprobs_of(shipped, r) for r in config.cloud_roles(shipped)} == {0}


# ---- step 7: a daily stop is not a failed audit ------------------------------------------------------------------------

def test_a_daily_stop_stores_nothing_and_the_next_day_continues(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    runs = runs_in(led, tmp_path, 4)
    client, transport, clock, _ = cloud_client(tmp_path, [reply(PASS_REPLY)] * 4, max_calls_per_day=2)
    report = skeptic.audit_pending(client, led, runs, role="skeptic_d")
    assert "daily limit reached" in report.stopped and len(report.audited) == 2
    assert led.entries(ledger.AUDIT_FAILED) == [] and report.failures == [] and report.errors == []
    assert len(transport.requests) == 2  # the 3rd and 4th were never sent
    clock.now += llm.DAY_S
    second = skeptic.audit_pending(client, led, runs, role="skeptic_d")
    assert second.stopped is None and sorted(a["run_id"] for a in second.audited) == ["r2", "r3"]
    assert len(led.entries(ledger.AUDITED)) == 4 and led.verify(runs) == []


def test_an_access_problem_stops_without_a_trace(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    runs = runs_in(led, tmp_path, 2)
    client, transport, _, _ = cloud_client(tmp_path, [(401, {}, b'{"error": "invalid key"}')])
    report = skeptic.audit_pending(client, led, runs, role="skeptic_d")
    assert "HTTP 401" in report.stopped and led.entries(ledger.AUDIT_FAILED) == [] and len(transport.requests) == 1


def test_refused_requests_are_failed_audits_and_three_in_a_row_stop_the_pass(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    runs = runs_in(led, tmp_path, 4)
    client, transport, _, _ = cloud_client(tmp_path, [(400, {}, b'{"error": "bad request"}')] * 4)
    report = skeptic.audit_pending(client, led, runs, role="skeptic_d", chunk_size=1, stop_after=3)
    failed = led.entries(ledger.AUDIT_FAILED)
    assert [f.payload["kind"] for f in failed] == [llm.KIND_REQUEST_REFUSED] * 3
    assert "is the API reachable" in report.stopped and len(transport.requests) == 3  # one attempt each


def test_reaudit_tells_the_student_to_run_the_same_command_again(monkeypatch, capsys):
    stopped = skeptic.AuditReport(stopped="stopped without storing anything ...: daily limit reached")
    monkeypatch.setattr(llm, "LLM", lambda: type("C", (), {"cfg": {"roles": {"skeptic_d": {}}}})())
    monkeypatch.setattr(ledger, "Ledger", lambda: None)
    monkeypatch.setattr(sealed, "SealedTable", lambda: None)
    monkeypatch.setattr(cli.mixer, "batch_run_ids", lambda table, batch: {"r1"})
    monkeypatch.setattr(cli.mixer, "reaudit", lambda *a, **k: stopped)
    code = cli.main(["reaudit", "--batch", "task-dev-2", "--role", "skeptic_d"])
    out = capsys.readouterr().out
    assert code == 1 and "daily limit reached" in out and "run the same command again" in out


# ---- the repeat pass ----------------------------------------------------------------------------------------------

def sealed_batch(tmp_path, n, batch="b"):
    table = sealed.SealedTable(tmp_path / "sealed.db")
    for i in range(n):
        table.seal(f"r{i}", sealed.CONTROL, details={"batch": batch})
    return table


def cache_rows(path: Path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT key, reply FROM llm_cache ORDER BY key").fetchall()


def test_the_repeat_pass_bypasses_the_cache_and_leaves_it_unchanged(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    runs = runs_in(led, tmp_path, 3)
    table = sealed_batch(tmp_path, 3)
    client, transport, _, _ = cloud_client(tmp_path, [reply(PASS_REPLY)] * 3 + [reply(PASS_REPLY), reply(FLAG_REPLY)],
                                           max_calls_per_day=10)
    skeptic.audit_pending(client, led, runs, role="skeptic_d")
    before = cache_rows(tmp_path / "cache.db")
    counts = cli.repeat_pass(client, led, table, "b", "skeptic_d", 2, seed=5, directory=tmp_path / "rescore",
                             runs_dir=runs)
    assert len(transport.requests) == 5  # 3 audits + 2 repeats: the cached reply was not used
    assert cache_rows(tmp_path / "cache.db") == before
    records = [json.loads(line) for line in (tmp_path / "rescore" / "b.repeat.jsonl").read_text().splitlines()]
    assert sorted(r["outcome"] for r in records) == ["matched", "reply_differs"] and counts["skeptic_d"]
    assert all(r["score"] is None and r["sample_seed"] == 5 for r in records)
    assert [r["verdict_changed"] for r in records if r["outcome"] == "reply_differs"] == [True]
    # Same seed, same sample; finished runs are not asked again.
    assert cli.repeat_sample(table, led, "b", 2, 5) == {r["run_id"] for r in records}
    cli.repeat_pass(client, led, table, "b", "skeptic_d", 2, seed=5, directory=tmp_path / "rescore", runs_dir=runs)
    assert len(transport.requests) == 5


# ---- isolation: the provider never reaches ground truth, the reviewer sees only the blinded prompt ------------------

def test_the_provider_module_cannot_reach_ground_truth_or_the_bug_catalog():
    reached = reachable_modules("canary.llm")
    assert reached == {"canary.llm", "canary.config"}  # nothing else, however indirectly
    source = Path(llm.__file__).read_text(encoding="utf-8")
    for word in ("sealed", "saboteur", "bug_classes", "transforms", "decoys", "run_type", "DESIGN"):
        assert word not in source, word


def test_the_cloud_request_holds_the_blinded_prompt_and_nothing_else(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    runs = tmp_path / "runs"
    add_ran_run(led, runs, hypothesis_id="HYP-ID-MARKER", run_id="RUN-ID-MARKER",
                script="# COMMENT-MARKER\nx = 1\n")
    client, transport, _, _ = cloud_client(tmp_path, [reply(PASS_REPLY)])
    skeptic.audit_pending(client, led, runs, role="skeptic_d")
    body = transport.requests[0]["body"]
    bugs = config.load_yaml("bug_classes.yaml")
    system, prompt, _ = review_tasks.build("baseline", skeptic.blinded_run(led, "RUN-ID-MARKER", runs), bugs)
    assert body["messages"] == [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    assert set(body) == {"model", "messages", "temperature", "seed", "stream", "max_completion_tokens",
                         "reasoning_effort", "response_format"}
    sent = json.dumps(body)
    # ("control" is allowed: it is the name of the experiment's baseline arm in the results.)
    for hidden in ("COMMENT-MARKER", "RUN-ID-MARKER", "HYP-ID-MARKER", "VERDICT_MARKER", "runtime_seconds",
                   "canary", "sham", "planted"):
        assert hidden not in sent, hidden
    for bug in bugs.values():  # the catalog's hints never leave
        assert bug["subtle"] not in sent and bug["obvious"] not in sent


# ---- step 8: doctor and smoke commands ----------------------------------------------------------------------------

def test_doctor_notes_a_missing_key_without_failing_or_calling(monkeypatch, capsys):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert cli.check_cloud_roles(config.load_yaml("models.yaml")) is True
    out = capsys.readouterr().out
    assert "key missing (add GROQ_API_KEY to .env" in out and "key missing (add GEMINI_API_KEY to .env" in out
    assert "[FAIL]" not in out


def test_doctor_says_key_present_and_never_prints_it(monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    cli.check_cloud_roles(config.load_yaml("models.yaml"))
    out = capsys.readouterr().out
    assert "skeptic_d: groq openai/gpt-oss-120b, key present" in out and KEY not in out


def test_llm_smoke_skips_cloud_roles(tmp_path, monkeypatch, capsys):
    client, transport, _, local = cloud_client(tmp_path)
    monkeypatch.setattr(llm, "LLM", lambda: client)
    cli.cmd_llm_smoke(argparse.Namespace())
    assert transport.requests == [] and local.calls  # local roles were asked, the cloud one was not
    assert "Skipping cloud roles" in capsys.readouterr().out


def smoke_setup(tmp_path, monkeypatch):
    led = Ledger(tmp_path / "ledger.db")
    runs = tmp_path / "runs"
    add_ran_run(led, runs, run_id=f"{cli.SMOKE_RUN}-0000-test")
    real = llm.LLM
    monkeypatch.setattr(llm, "LLM", lambda: real(cache_path=tmp_path / "c.db"))  # the shipped config, a test cache
    return led, runs


@pytest.mark.parametrize("role", ["skeptic_d", "skeptic_e"])
def test_cloud_smoke_dry_prints_valid_bodies_and_sends_nothing(tmp_path, monkeypatch, capsys, role):
    led, runs = smoke_setup(tmp_path, monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    assert cli.cmd_cloud_smoke(argparse.Namespace(role=role, dry=True, send=False), runs, led) == 0
    out = capsys.readouterr().out
    blocks = out.split("\n--- ")[1:]
    bodies = [json.loads(block.split("\n", 1)[1]) for block in blocks]
    assert [b["messages"][-1]["content"][:20] for b in bodies][0].startswith("What is 2 + 3?")
    assert len(bodies) == 3 and all(b["response_format"]["type"] == "json_schema" for b in bodies)
    assert {b["model"] for b in bodies} == {config.load_yaml("models.yaml")["roles"][role]["model"]}
    assert KEY not in out and not llm.CALL_LOG_PATH.exists()


def test_cloud_smoke_live_needs_an_explicit_send(tmp_path, monkeypatch, capsys):
    led, runs = smoke_setup(tmp_path, monkeypatch)
    assert cli.cmd_cloud_smoke(argparse.Namespace(role="skeptic_d", dry=False, send=False), runs, led) == 2
    assert "needs the student's OK" in capsys.readouterr().out and not llm.CALL_LOG_PATH.exists()


def test_cloud_smoke_refuses_a_local_role(tmp_path, monkeypatch, capsys):
    led, runs = smoke_setup(tmp_path, monkeypatch)
    assert cli.cmd_cloud_smoke(argparse.Namespace(role="skeptic_c", dry=True, send=False), runs, led) == 2
