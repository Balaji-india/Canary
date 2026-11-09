"""The cue-sensitivity probe: its pre-registered rule, its padding, its choice of controls, and that it stores nothing
in the ledger, the sealed table or the LLM cache. No model is called: a fake client stands in."""
import ast
import random
import types

import pytest

from canary import blinding, codegen, ledger, llm, padding, sealed
from canary.ledger import Ledger
from eval import cue_probe
from tests.test_padding import CONFIG
from tests.test_skeptic import add_ran_run


def pairs(differences, per_base=2, large=0.5):
    """Records for one control per difference: small = large + difference. `per_base` controls share a base."""
    records = []
    for i, d in enumerate(differences):
        common = {"run_id": f"r{i:02d}", "base": f"pool:{i // per_base}", "outcome": "scored", "verdict": "pass"}
        records += [{**common, "size": cue_probe.LARGE, "p_flag": large},
                    {**common, "size": cue_probe.SMALL, "p_flag": large + d}]
    return records


def test_a_score_that_follows_the_helper_is_a_live_cue():
    result = cue_probe.analyse(pairs([0.2] * 16))
    assert result["decision"] == cue_probe.CUE_LIVE and not result["batch_may_run"]
    assert result["mean_difference"] == pytest.approx(0.2) and result["interval_90_base"] == pytest.approx([0.2, 0.2])
    assert result["small_higher"] == 16 and result["pairs"] == 16 and result["bases"] == 8
    # Either direction counts: a reviewer that flags longer scripts more is reacting to padding too.
    assert cue_probe.analyse(pairs([-0.2] * 16))["decision"] == cue_probe.CUE_LIVE


def test_a_score_that_ignores_the_helper_lets_the_batch_run():
    result = cue_probe.analyse(pairs([0.1, -0.1] * 8))  # each base holds +0.1 and -0.1: every draw's mean is 0
    assert result["decision"] == cue_probe.NO_SENSITIVITY and result["batch_may_run"]
    assert result["mean_difference"] == pytest.approx(0.0) and result["interval_90_base"] == pytest.approx([0.0, 0.0])


def test_too_few_pairs_or_a_prompt_too_large_is_inconclusive():
    assert cue_probe.analyse(pairs([0.0] * 14))["decision"] == cue_probe.INCONCLUSIVE
    records = pairs([0.0] * 16)
    records[0] = {**records[0], "outcome": llm.KIND_PROMPT_TOO_LARGE, "p_flag": None}
    result = cue_probe.analyse(records)
    assert result["decision"] == cue_probe.INCONCLUSIVE and result["prompts_too_large"] == 1


def test_a_later_record_replaces_an_earlier_one_and_flips_are_counted():
    records = pairs([0.0] * 16) + [{"run_id": "r00", "base": "pool:0", "size": cue_probe.SMALL, "outcome": "scored",
                                    "p_flag": 0.9, "verdict": "flag"}]
    result = cue_probe.analyse(records)
    assert result["versions_recorded"] == 32 and result["verdict_flips"] == 1
    assert result["mean_difference"] == pytest.approx(0.4 / 16)


def test_padding_to_a_size_adds_only_that_many_helper_statements():
    script = codegen.render_script(CONFIG)
    small = cue_probe.pad_to_statements(script, 6, random.Random(1))
    large = cue_probe.pad_to_statements(script, 21, random.Random(1))
    assert (small.statements, large.statements) == (6, 21)
    assert padding.length(large.script)[0] - padding.length(small.script)[0] == 15
    for padded in (small, large):  # the helper and its call are the only change
        assert padding.strip_padding(padded.script) == ast.unparse(ast.parse(script))


def test_controls_are_spread_over_bases_and_only_clean_finished_pool_1_controls_count(tmp_path):
    table, led = sealed.SealedTable(tmp_path / "s.db"), Ledger(tmp_path / "l.db")
    rows = [("c1", sealed.CONTROL, "pool:0", "rq1-full", "ok"), ("c2", sealed.CONTROL, "pool:0", "rq1-full", "ok"),
            ("c3", sealed.CONTROL, "pool:1", "task-dev-1", "ok"), ("c4", sealed.CONTROL, "pool:2", "rq1-full", "ok"),
            ("c5", sealed.CONTROL, "pool:3", "rq1-full", "crash"), ("c6", sealed.CONTROL, "pool:4", "pilot", "ok"),
            ("k1", sealed.CANARY_MEASURE, "pool:5", "rq1-full", "ok")]
    for run_id, run_type, base, batch, status in rows:
        bug = ("B01", "obvious") if run_type == sealed.CANARY_MEASURE else (None, None)
        table.seal(run_id, run_type, *bug, source=base, details={"batch": batch})
        for step, payload in ((ledger.PROPOSED, {}), (ledger.PREREGISTERED, {}),
                              (ledger.RAN, {"run_id": run_id, "run_status": status})):
            led.append(f"h-{run_id}", step, payload)
    picked = cue_probe.select_controls(table, led, n=3)
    assert len(picked) == 3 and len({t.source for t in picked}) == 3  # one per base before any base repeats
    assert {t.run_id for t in picked} <= {"c1", "c2", "c3", "c4"}
    assert [t.run_id for t in picked] == [t.run_id for t in cue_probe.select_controls(table, led, n=3)]
    assert {t.run_id for t in cue_probe.select_controls(table, led, n=10)} == {"c1", "c2", "c3", "c4"}


class FakeClient:
    """Duck-typed llm.LLM: a checklist role, scripted outcomes, no cache, no ledger."""

    def __init__(self, outcomes):
        self.cfg = {"roles": {"probe": {"model": "m", "task": "checklist"}}, "llm": {"review_top_logprobs": 0}}
        self.outcomes = list(outcomes)
        self.calls = 0

    def call(self, role, prompt, schema, system=None, top_logprobs=0, cache_write=True):
        assert cache_write is False and top_logprobs > 0
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        reply = {b: {"line": "", "answer": "no"} for b in schema["required"]}
        return types.SimpleNamespace(data=reply, logprobs=None, model="m", seconds=1.0)


def jobs(n=2):
    blinded = blinding.BlindedRun(script="x = 1", results="{}", prereg="{}")
    return [{"run_id": f"r{i}", "base": "pool:0", "size": size, "statements": 6, "line_count": 1, "char_count": 5,
             "blinded": blinded} for i in range(n) for size in (cue_probe.SMALL, cue_probe.LARGE)]


def test_the_run_stores_each_reply_and_resumes_where_it_stopped(tmp_path):
    path = tmp_path / "probe.jsonl"
    server = llm.LLMError("down", llm.KIND_TIMEOUT_OR_SERVER)
    client = FakeClient(["ok", server, server, server])
    assert cue_probe.run(client, "probe", jobs(), path, echo=lambda _: None) == "3 server failures in a row"
    stored = cue_probe.read_records(path)
    assert len(stored) == 1 and stored[0]["outcome"] == "unscored" and stored[0]["verdict"] == "pass"

    client = FakeClient(["ok", llm.LLMError("big", llm.KIND_PROMPT_TOO_LARGE), "ok"])
    assert cue_probe.run(client, "probe", jobs(), path, echo=lambda _: None) is None
    stored = cue_probe.read_records(path)
    assert client.calls == 3 and len(stored) == 4  # the first job was not asked again
    assert [r["outcome"] for r in stored].count(llm.KIND_PROMPT_TOO_LARGE) == 1


def test_the_probe_writes_nothing_to_the_ledger(tmp_path):
    """A real control on disk, padded twice and asked about: the ledger and sealed table are unchanged."""
    led, table = Ledger(tmp_path / "l.db"), sealed.SealedTable(tmp_path / "s.db")
    runs = tmp_path / "runs"
    add_ran_run(led, runs, "h1", "c1", script=codegen.render_script(CONFIG))
    table.seal("c1", sealed.CONTROL, source="pool:0", details={"batch": "rq1-full"})
    before = [e.hash for e in led.entries()]
    target = padding.batch_target([CONFIG])
    sizes = {"target": {"lines": target.lines, "chars": target.chars}, "small_statements": 6}
    built = cue_probe.build_jobs(cue_probe.select_controls(table, led), led, sizes, runs)
    assert sorted(j["size"] for j in built) == [cue_probe.LARGE, cue_probe.SMALL]
    assert {j["size"]: j["line_count"] for j in built}[cue_probe.LARGE] == target.lines
    cue_probe.run(FakeClient(["ok", "ok"]), "probe", built, tmp_path / "p.jsonl", echo=lambda _: None)
    assert [e.hash for e in led.entries()] == before and len(table.all()) == 1
