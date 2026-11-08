"""Rescoring: token probabilities for stored audits, without touching their verdicts, the ledger or the cache."""
import copy
import json
import math
import sqlite3
from contextlib import closing

import pytest

from canary import ledger, llm, mixer, sealed, skeptic
from canary.ledger import Ledger
from eval import compare_tasks
from tests.test_llm import CFG, FakeProvider
from tests.test_skeptic import FLAG_REPLY, PASS_REPLY, add_ran_run


class ScoredReplies(FakeProvider):
    """Replays replies; with probabilities, splits each reply at its verdict and gives "flag" probability `p`."""

    def __init__(self, replies=(), p=0.7):
        super().__init__(replies)
        self.p = p

    def generate(self, model, prompt, system, schema, temperature, timeout_s, seed_offset=0, **options):
        text = super().generate(model, prompt, system, schema, temperature, timeout_s, seed_offset)
        if not options.get("top_logprobs"):
            return text
        cut = text.index('"verdict": "') + len('"verdict": "')
        word = text[cut:cut + 4]
        alternatives = [{"token": "flag", "logprob": math.log(self.p)}, {"token": "pass", "logprob": math.log(1 - self.p)}]
        tokens = [{"token": text[:cut], "logprob": 0.0, "top_logprobs": []},
                  {"token": word, "logprob": 0.0, "top_logprobs": alternatives},
                  {"token": text[cut + 4:], "logprob": 0.0, "top_logprobs": []}]
        return text, tokens


def audited_run(tmp_path, reply=PASS_REPLY, run_id="r1", hypothesis_id="h1", led=None, script="x = 1\n"):
    led = led or Ledger(tmp_path / "ledger.db")
    runs = tmp_path / "runs"
    add_ran_run(led, runs, hypothesis_id, run_id, script=script)
    client = llm.LLM(CFG, {"fake": FakeProvider([reply])}, tmp_path / f"audit-{run_id}.db")
    skeptic.audit_pending(client, led, runs)
    return led, runs


def scoring_client(tmp_path, replies, p=0.7, name="rescore.db"):
    cfg = copy.deepcopy(CFG)
    cfg["llm"]["review_top_logprobs"] = 20
    provider = ScoredReplies(replies, p)
    return llm.LLM(cfg, {"fake": provider}, tmp_path / name), provider


def test_a_repeated_reply_gets_a_score_and_nothing_else_is_written(tmp_path):
    led, runs = audited_run(tmp_path)
    before = [e.hash for e in led.entries()]
    client, provider = scoring_client(tmp_path, [PASS_REPLY])
    records = skeptic.rescore(client, led, "skeptic_a", {"r1"}, runs)
    assert [r["outcome"] for r in records] == ["matched"]
    assert records[0]["score"] == {"p_flag": pytest.approx(0.7), "both_seen": True}
    assert records[0]["prompt_sha256"] == led.entries(ledger.AUDITED)[0].payload["prompt_sha256"]
    assert [e.hash for e in led.entries()] == before  # no ledger entry, so no verdict can change
    with closing(sqlite3.connect(tmp_path / "rescore.db")) as db:
        assert db.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0  # the cache is not written either


def test_a_different_reply_gets_no_score(tmp_path):
    led, runs = audited_run(tmp_path, reply=PASS_REPLY)
    client, _ = scoring_client(tmp_path, [FLAG_REPLY])
    record = skeptic.rescore(client, led, "skeptic_a", {"r1"}, runs)[0]
    assert record["outcome"] == "reply_differs" and record["score"] is None
    assert record["verdict_changed"] is True and record["new_decision"]["verdict"] == "flag"
    assert record["fields_changed"] == ["bug_class", "confidence", "evidence", "verdict"]


def test_an_edited_file_is_refused_without_asking_the_model(tmp_path):
    led, runs = audited_run(tmp_path)
    (runs / "r1" / "experiment.py").write_text("x = 2\n", encoding="utf-8")
    client, provider = scoring_client(tmp_path, [PASS_REPLY])
    assert skeptic.rescore(client, led, "skeptic_a", {"r1"}, runs)[0]["outcome"] == "files_changed"
    assert provider.calls == []


def test_finished_runs_are_skipped_and_failed_calls_are_retried(tmp_path):
    led, runs = audited_run(tmp_path)
    led, runs = audited_run(tmp_path, run_id="r2", hypothesis_id="h2", led=led, script="y = 2\n")
    client, provider = scoring_client(tmp_path, [llm.LLMError("down")] * 3 + [PASS_REPLY])
    seen = []
    first = skeptic.rescore(client, led, "skeptic_a", {"r1", "r2"}, runs, done={"r2"}, on_record=seen.append)
    assert first == [] and [r["outcome"] for r in seen] == ["call_failed"]  # 3 attempts, then not stored
    again = skeptic.rescore(client, led, "skeptic_a", {"r1", "r2"}, runs, done={"r2"})
    assert [(r["run_id"], r["outcome"]) for r in again] == [("r1", "matched")]


def test_the_batch_file_resumes_and_compare_tasks_uses_only_matching_scores(tmp_path):
    led, runs = audited_run(tmp_path, reply=PASS_REPLY)
    led, runs = audited_run(tmp_path, reply=FLAG_REPLY, run_id="r2", hypothesis_id="h2", led=led, script="y = 2\n")
    table = sealed.SealedTable(tmp_path / "sealed.db")
    table.seal("r1", sealed.CONTROL, details={"batch": "b"})
    table.seal("r2", sealed.CANARY_MEASURE, "B03", "obvious", details={"batch": "b"})
    client, provider = scoring_client(tmp_path, [PASS_REPLY, PASS_REPLY])  # r2's new reply differs from its FLAG audit
    log = tmp_path / "campaign.log"
    counts = mixer.rescore_batch(client, led, table, "b", "skeptic_a", runs, log, tmp_path / "rescore")
    assert counts == {"skeptic_a": {"matched": 1, "reply_differs": 1}}
    assert mixer.rescore_batch(client, led, table, "b", "skeptic_a", runs, log, tmp_path / "rescore") == {"skeptic_a": {}}
    assert len(provider.calls) == 2  # the second pass asked nothing

    result = compare_tasks.build(table, led, "b", ["B03"], 1000, tmp_path / "rescore")
    auc = result["cells"]["skeptic_a"]["auc"]
    assert auc["sources"] == {"audit": 0, "rescore": 1, "none": 1}
    assert auc["rescore_outcomes"] == {"matched": 1, "reply_differs": 1}
    assert auc["value"] is None  # only the clean run has a score, so there is no buggy/clean pair yet
    assert result["cells"]["skeptic_a"]["youden_j"]["observed_j"] == 1.0  # verdicts come from the audits, unchanged


def test_reviewer_roles_are_the_ones_on_that_model_that_audited_the_batch(tmp_path):
    led, _ = audited_run(tmp_path)
    cfg = copy.deepcopy(CFG)
    cfg["roles"]["skeptic_a_grounded"] = {"use_role": "skeptic_a", "task": "grounded"}
    assert mixer.reviewer_roles(cfg, "skeptic_a", led, {"r1"}) == ["skeptic_a"]  # the grounded role has no audit here
    assert mixer.reviewer_roles(cfg, "skeptic_b", led, {"r1"}) == []


def test_the_fresh_pass_scores_only_differing_runs_and_keeps_the_first_file(tmp_path):
    led, runs = audited_run(tmp_path, reply=PASS_REPLY)
    led, runs = audited_run(tmp_path, reply=FLAG_REPLY, run_id="r2", hypothesis_id="h2", led=led, script="y = 2\n")
    table = sealed.SealedTable(tmp_path / "sealed.db")
    table.seal("r1", sealed.CONTROL, source="base-1", details={"batch": "b"})
    table.seal("r2", sealed.CANARY_MEASURE, "B03", "obvious", source="base-2", details={"batch": "b"})
    log, out = tmp_path / "campaign.log", tmp_path / "rescore"
    client, _ = scoring_client(tmp_path, [PASS_REPLY, PASS_REPLY])
    mixer.rescore_batch(client, led, table, "b", "skeptic_a", runs, log, out)  # r1 matched, r2 differs
    first_file = mixer.rescore_path("b", out).read_text(encoding="utf-8")

    fresh_client, provider = scoring_client(tmp_path, [PASS_REPLY], p=0.4, name="fresh.db")
    counts = mixer.rescore_batch(fresh_client, led, table, "b", "skeptic_a", runs, log, out, fresh=True)
    assert counts == {"skeptic_a": {"reply_differs": 1}} and len(provider.calls) == 1  # only r2 was asked again
    record = mixer.read_rescores("b", out, mixer.FRESH)[0]
    assert record["run_id"] == "r2" and record["score"]["p_flag"] == pytest.approx(0.4)
    assert record["verdict_changed"] is True  # the stored audit flagged; the fresh reply passed
    assert mixer.rescore_path("b", out).read_text(encoding="utf-8") == first_file
    assert mixer.rescore_batch(fresh_client, led, table, "b", "skeptic_a", runs, log, out, fresh=True) == {"skeptic_a": {}}

    c = compare_tasks.build(table, led, "b", ["B03"], 1000, out, runs)["cells"]["skeptic_a"]
    assert c["auc"]["value"] is None  # matched-only still has the clean run alone
    fresh = c["auc_fresh"]
    assert fresh["complete"] and fresh["sources"] == {"matched_first": 1, "fresh": 1, "missing": 0}
    assert fresh["value"] == 0.0  # buggy 0.4 below clean 0.7
    assert fresh["verdict_changed"] == 1 and c["youden_j"]["observed_j"] == 1.0  # verdicts still from the audits
