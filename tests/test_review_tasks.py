"""Review tasks (the task screen): prompts, schemas, the code's verdict, token-probability scores and their plumbing.

No real model: replies and token probabilities are written by hand, so each expected number can be checked by eye.
"""
import copy
import json
import math

import pytest

from canary import blinding, config, ledger, llm, prompts, review_tasks, sealed, skeptic, trust
from canary.ledger import Ledger
from tests.test_llm import CFG, SCHEMA, FakeProvider, FakeOllamaClient
from tests.test_skeptic import add_ran_run

BUGS = config.load_yaml("bug_classes.yaml")
IDS = sorted(BUGS)
BLINDED = blinding.BlindedRun(
    script="X_train, X_test = split(X)\nscaler.fit(X_all)\nscore = model.score(X_train, y_train)\n",
    results='{"metric": "f1"}', prereg='{"metric": "accuracy", "model": "logistic_regression"}')


# --- prompts and schemas ---------------------------------------------------------------------------------------------

def test_the_baseline_task_is_exactly_the_original_prompt_system_and_schema():
    system, prompt, schema = review_tasks.build(review_tasks.BASELINE, BLINDED, BUGS)
    assert system == prompts.SKEPTIC_SYSTEM and prompt == prompts.skeptic_prompt(BLINDED, BUGS)
    assert schema == skeptic.audit_schema(IDS)
    order = list(reversed(IDS))
    assert review_tasks.build(review_tasks.BASELINE, BLINDED, BUGS, order)[2] == skeptic.audit_schema(order)


def test_new_tasks_use_the_neutral_system_text_and_no_strict_wording():
    for task in (review_tasks.GROUNDED, review_tasks.CHECKLIST):
        system, prompt, _ = review_tasks.build(task, BLINDED, BUGS)
        assert system == prompts.SKEPTIC_SYSTEM_NEUTRAL and "strict" not in (system + prompt).lower()
        assert BLINDED.script in prompt and all(f"- {b}:" in prompt for b in IDS)
        for word in ("canary", "control run", "sham", "planted"):  # the reviewer is not told it is being tested
            assert word not in (system + prompt).lower()


def test_the_grounded_schema_asks_for_the_line_before_the_verdict_in_both_forms():
    schema = review_tasks.build(review_tasks.GROUNDED, BLINDED, BUGS)[2]
    for form in schema["anyOf"]:
        assert list(form["properties"])[:3] == ["offending_line", "verdict", "bug_class"]
    pass_form, flag_form = schema["anyOf"]
    assert pass_form["properties"]["bug_class"] == {"type": "null"} and flag_form["properties"]["bug_class"]["enum"] == IDS


def test_the_checklist_schema_has_every_class_with_the_line_first():
    schema = review_tasks.build(review_tasks.CHECKLIST, BLINDED, BUGS)[2]
    assert schema["required"] == IDS and list(schema["properties"]) == IDS
    assert all(list(entry["properties"]) == ["line", "answer"] for entry in schema["properties"].values())
    reply = {b: {"line": "", "answer": "no"} for b in IDS}
    assert llm.schema_problem(reply, schema) is None
    assert llm.schema_problem({**reply, "B01": {"line": "", "answer": "maybe"}}, schema)


def test_only_the_baseline_takes_a_class_order_and_unknown_tasks_fail():
    with pytest.raises(ValueError, match="order"):
        review_tasks.build(review_tasks.CHECKLIST, BLINDED, BUGS, IDS)
    with pytest.raises(ValueError, match="unknown"):
        review_tasks.build("vibes", BLINDED, BUGS)


# --- the code's verdict ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("quote, found", [
    ("scaler.fit(X_all)", True),
    ("  scaler.fit(X_all)  ", True),
    ("`scaler.fit(X_all)`", True),
    ("X_train, X_test = split(X)\n  scaler.fit(X_all)", True),  # two lines, indentation changed
    ('"metric": "accuracy"', True),  # from the pre-registration
    ("scaler.fit(X_test)", False),  # not in anything shown
    ("fit(", False),  # too short to mean anything
    (")))))))))", False),  # no letter
    ("", False),
])
def test_a_quote_must_appear_in_what_the_reviewer_saw(quote, found):
    assert review_tasks.quote_found(quote, BLINDED) is found


def grounded(verdict, line, bug=None):
    return {"offending_line": line, "verdict": verdict, "bug_class": bug, "evidence": "e", "confidence": 0.9}


def test_a_grounded_flag_counts_only_with_a_verified_line_and_keeps_the_raw_verdict():
    real = review_tasks.decide(review_tasks.GROUNDED, grounded("flag", "scaler.fit(X_all)", "B01"), BLINDED)
    made_up = review_tasks.decide(review_tasks.GROUNDED, grounded("flag", "scaler.fit(X_test)", "B01"), BLINDED)
    passed = review_tasks.decide(review_tasks.GROUNDED, grounded("pass", ""), BLINDED)
    assert real == {"verdict": "flag", "bug_class": "B01", "raw_verdict": "flag", "raw_bug_class": "B01", "line_verified": True}
    assert made_up["verdict"] == "pass" and made_up["bug_class"] is None and made_up["raw_verdict"] == "flag"
    assert passed["verdict"] == "pass" and passed["raw_verdict"] == "pass"


def test_a_checklist_flags_when_any_yes_has_a_verified_line():
    reply = {b: {"line": "", "answer": "no"} for b in IDS}
    assert review_tasks.decide(review_tasks.CHECKLIST, reply, BLINDED)["verdict"] == "pass"
    reply["B03"] = {"line": "score = model.score(X_train, y_train)", "answer": "yes"}
    reply["B05"] = {"line": "best = max(seed_scores)", "answer": "yes"}  # not in the script
    decision = review_tasks.decide(review_tasks.CHECKLIST, reply, BLINDED)
    assert decision == {"verdict": "flag", "bug_class": "B03", "raw_verdict": "flag",
                        "yes_classes": ["B03", "B05"], "verified_classes": ["B03"]}
    reply["B03"]["line"] = "made up"
    assert review_tasks.decide(review_tasks.CHECKLIST, reply, BLINDED)["verdict"] == "pass"


def test_the_baseline_decision_is_the_replys_own_verdict():
    reply = {"verdict": "flag", "bug_class": "B01", "evidence": "", "confidence": 0.9}
    assert review_tasks.decide(review_tasks.BASELINE, reply, BLINDED) == {"verdict": "flag", "bug_class": "B01", "raw_verdict": "flag"}


# --- token-probability scores ----------------------------------------------------------------------------------------

def tok(text, logprob=0.0, alternatives=()):
    """One token as Ollama reports it; alternatives are (text, probability)."""
    return {"token": text, "logprob": logprob, "bytes": list(text.encode()),
            "top_logprobs": [{"token": t, "logprob": math.log(p), "bytes": list(t.encode())} for t, p in alternatives]}


def test_the_verdict_score_renormalises_over_the_two_allowed_words():
    # Before the schema, the model also wanted "B0" (0.3): that token is not allowed there, so it is left out.
    reply = [tok('{"verdict": "'), tok("fl", alternatives=[("fl", 0.6), ("pass", 0.1), ("B0", 0.3)]), tok('ag", "x": 1}')]
    assert review_tasks.score(review_tasks.BASELINE, reply, IDS) == {"p_flag": pytest.approx(0.6 / 0.7), "both_seen": True}


def test_a_choice_token_that_starts_before_the_value_is_matched_after_its_prefix():
    # The token ' "pass' holds the opening quote and the word; an alternative must share the ' "' to count.
    reply = [tok('{"verdict":'), tok(' "pass', alternatives=[(' "pass', 0.5), (' "flag', 0.25), ('"flag', 0.2)]), tok('"}')]
    assert review_tasks.score(review_tasks.BASELINE, reply, IDS)["p_flag"] == pytest.approx(0.25 / 0.75)


def test_a_word_finished_inside_the_token_must_end_there():
    reply = [tok('{"verdict": "'), tok('flag"', alternatives=[('flag"', 0.5), ('flagged"', 0.3), ('pass",', 0.2)]), tok("}")]
    assert review_tasks.score(review_tasks.BASELINE, reply, IDS)["p_flag"] == pytest.approx(0.5 / 0.7)


def test_no_score_without_probabilities_or_without_either_word():
    assert review_tasks.score(review_tasks.BASELINE, None, IDS) is None
    reply = [tok('{"verdict": "'), tok("fl", alternatives=[("B0", 0.9)]), tok('ag"}')]
    assert review_tasks.score(review_tasks.BASELINE, reply, IDS) is None


def test_the_grounded_score_is_read_at_the_verdict_after_the_line():
    reply = [tok('{"offending_line": "x", "verdict": "'), tok("pass", alternatives=[("pass", 0.9), ("flag", 0.1)]), tok('"}')]
    assert review_tasks.score(review_tasks.GROUNDED, reply, IDS)["p_flag"] == pytest.approx(0.1)


def test_the_checklist_score_is_the_largest_yes_probability():
    ids = ["B01", "B02"]
    reply = [tok('{"B01": {"line": "", "answer": "'), tok("no", alternatives=[("no", 0.8), ("yes", 0.2)]),
             tok('"}, "B02": {"line": "x", "answer": "'), tok("yes", alternatives=[("yes", 0.7), ("no", 0.3)]), tok('"}}')]
    result = review_tasks.score(review_tasks.CHECKLIST, reply, ids)
    assert result["per_class"] == {"B01": pytest.approx(0.2), "B02": pytest.approx(0.7)}
    assert result["p_flag"] == pytest.approx(0.7)


# --- the wrapper: per-role context and probabilities -----------------------------------------------------------------

class ScoringProvider(FakeProvider):
    """Returns (text, probabilities) when asked for them, like the Ollama provider."""

    def __init__(self, replies=(), installed=("sci:1", "ska:1", "skb:1", "big:1")):
        super().__init__(replies, installed)
        self.options = []

    def generate(self, model, prompt, system, schema, temperature, timeout_s, seed_offset=0, **options):
        self.options.append(options)
        text = super().generate(model, prompt, system, schema, temperature, timeout_s, seed_offset)
        return (text, [tok(text)]) if options.get("top_logprobs") else text


def cfg_with_big_role():
    cfg = copy.deepcopy(CFG)
    cfg["roles"]["skeptic_c"] = {"model": "big:1", "temperature": 0.0, "family": "llama", "num_ctx": 4096}
    cfg["roles"]["skeptic_c_grounded"] = {"use_role": "skeptic_c", "task": "grounded"}
    return cfg


def test_a_role_can_have_its_own_context_size_and_the_size_guard_uses_it(tmp_path):
    provider = ScoringProvider()
    client = llm.LLM(cfg_with_big_role(), {"fake": provider}, tmp_path / "c.db")
    assert client.num_ctx("skeptic_c_grounded") == 4096 and client.num_ctx("skeptic_a") == 8192
    client.call("skeptic_c", "p", SCHEMA)
    client.call("skeptic_a", "p", SCHEMA)
    assert provider.options == [{"num_ctx": 4096}, {}]  # the global size is not sent as an override
    fits_8192_only = "x" * ((4096 - 1024) * 3 + 1)
    client.call("skeptic_a", fits_8192_only, SCHEMA)
    with pytest.raises(llm.LLMError) as caught:
        client.call("skeptic_c", fits_8192_only, SCHEMA)
    assert caught.value.kind == llm.KIND_PROMPT_TOO_LARGE


def test_asking_for_probabilities_returns_them_and_skips_reading_the_cache(tmp_path):
    provider = ScoringProvider()
    client = llm.LLM(CFG, {"fake": provider}, tmp_path / "c.db")
    plain = client.call("skeptic_a", "p", SCHEMA)
    scored = client.call("skeptic_a", "p", SCHEMA, top_logprobs=20)
    assert plain.logprobs is None and scored.logprobs == [tok('{"n": 1}')] and not scored.cached
    assert provider.options[-1] == {"top_logprobs": 20}
    assert client.call("skeptic_a", "p", SCHEMA).cached  # the reply text is still cached for plain calls
    queue = llm.ModelQueue(client)
    queue.add("skeptic_a", "q", SCHEMA, top_logprobs=5)
    assert queue.run()[0].logprobs is not None and provider.options[-1] == {"top_logprobs": 5}


def test_ollama_provider_asks_for_probabilities_and_returns_plain_data(monkeypatch):
    class ScoredClient(FakeOllamaClient):
        def generate(self, **kwargs):
            FakeOllamaClient.last = kwargs
            alt = {"token": "{", "logprob": -0.1, "bytes": [123]}
            return type("R", (), {"response": '{"n": 1}', "logprobs": [{**alt, "top_logprobs": [alt]}]})()

    monkeypatch.setattr("ollama.Client", ScoredClient)
    text, probabilities = llm.OllamaProvider(CFG["llm"]).generate("m", "p", None, SCHEMA, 0.0, 9, 0, num_ctx=4096,
                                                                   top_logprobs=20)
    sent = FakeOllamaClient.last
    assert sent["logprobs"] is True and sent["top_logprobs"] == 20 and sent["options"]["num_ctx"] == 4096
    assert text == '{"n": 1}' and probabilities[0]["top_logprobs"][0] == {"token": "{", "logprob": -0.1, "bytes": [123]}


# --- the Skeptic stores the task, the code's decision and the score --------------------------------------------------

def test_an_audit_stores_its_task_decision_and_score_and_trust_reads_the_decision(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    runs = tmp_path / "runs"
    add_ran_run(led, runs)  # the script is "# a comment\nx = 1\n"; blinding drops the comment
    cfg = cfg_with_big_role()
    cfg["llm"]["review_top_logprobs"] = 20
    reply = json.dumps(grounded("flag", "y = model.leak()", "B01"))  # a line that is not in the script
    client = llm.LLM(cfg, {"fake": ScoringProvider([reply])}, tmp_path / "c.db")
    report = skeptic.audit_pending(client, led, runs, role="skeptic_c_grounded")
    stored = led.entries(ledger.AUDITED)[0].payload
    assert report.audited and stored["task"] == "grounded" and stored["audit"]["verdict"] == "flag"
    assert stored["decision"]["verdict"] == "pass" and stored["decision"]["line_verified"] is False
    assert "score" in stored  # None here: the fake's single token has no verdict choice in it

    table = sealed.SealedTable(tmp_path / "sealed.db")
    table.seal("r1", sealed.CONTROL)
    observations, _ = trust.collect_observations(table, led, "skeptic_c_grounded")
    assert [o.flagged for o in observations] == [False]  # the code's verdict, not the reply's


def test_a_role_with_an_unknown_task_is_refused():
    cfg = copy.deepcopy(CFG)
    cfg["roles"]["skeptic_x"] = {"use_role": "skeptic_a", "task": "vibes"}
    with pytest.raises(ValueError, match="unknown review task"):
        skeptic.task_of(cfg, "skeptic_x")
    assert skeptic.task_of(CFG, "skeptic_a") == "baseline"
