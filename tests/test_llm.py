"""All tests use a fake provider or a mocked Ollama client: nothing here reaches a real model."""
import json
import types

import pytest

from canary import config, llm

SCHEMA = {"type": "object", "required": ["n"], "additionalProperties": False, "properties": {"n": {"type": "integer"}}}
GOOD = '{"n": 1}'
CFG = {
    "provider": "fake",
    "roles": {
        "scientist": {"model": "sci:1", "fallback": "sci:0", "temperature": 0.2, "family": "qwen"},
        "skeptic_a": {"model": "ska:1", "temperature": 0.0, "family": "gemma"},
        "skeptic_b": {"model": "skb:1", "temperature": 0.0, "family": "phi"},
        "mutant_writer": {"use_role": "scientist"},
    },
    "llm": {"retries": 2, "timeout_cold_s": 300, "timeout_warm_s": 120, "num_ctx": 8192, "num_predict": 1024, "seed": 0},
}


class FakeProvider:
    """Records every call and replays scripted replies. An Exception in the script is raised instead of returned."""

    def __init__(self, replies=(), installed=("sci:1", "ska:1", "skb:1")):
        self.replies = list(replies)
        self.installed = set(installed)
        self.events = []  # ("generate", model) and ("unload", model), in order
        self.calls = []
        self.seed_offsets = []

    def installed_models(self):
        return self.installed

    def generate(self, model, prompt, system, schema, temperature, timeout_s, seed_offset=0):
        self.events.append(("generate", model))
        self.calls.append({"model": model, "prompt": prompt, "system": system, "temperature": temperature,
                           "timeout_s": timeout_s})
        self.seed_offsets.append(seed_offset)
        reply = self.replies.pop(0) if self.replies else GOOD
        if isinstance(reply, Exception):
            raise reply
        return reply

    def unload(self, model):
        self.events.append(("unload", model))


@pytest.fixture
def fake():
    return FakeProvider()


def make_llm(provider, tmp_path, cfg=CFG):
    return llm.LLM(cfg, {"fake": provider}, tmp_path / "test.db")


@pytest.mark.parametrize("text", [
    GOOD,
    f"  {GOOD}\n",
    f"<think>let me see {{\"n\": 9}}</think>{GOOD}",
    f"<think>\nline one\nline two\n</think>\n\n{GOOD}",
    f"```json\n{GOOD}\n```",
    f"```\n{GOOD}\n```",
])
def test_parse_reply_accepts_clean_forms(text):
    assert llm.parse_reply(text, SCHEMA) == {"n": 1}


@pytest.mark.parametrize("text", [
    "",
    "no json here",
    f"Sure! Here it is: {GOOD}",
    f'{GOOD} {{"n": 2}}',  # two candidate answers: never guess
    '{"n": 1',
    '{"n": "one"}',
    '{"n": 1, "m": 2}',
    "<think>never closed",
])
def test_parse_reply_rejects_everything_else(text):
    with pytest.raises(llm.InvalidReply):
        llm.parse_reply(text, SCHEMA)


VERDICT = {
    "type": "object", "required": ["verdict", "bug_class", "confidence"],
    "properties": {
        "verdict": {"enum": ["pass", "flag"]},
        "bug_class": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}


def test_schema_accepts_a_good_verdict():
    good = {"verdict": "flag", "bug_class": None, "confidence": 1, "tags": ["a"]}
    assert llm.schema_problem(good, VERDICT) is None


@pytest.mark.parametrize("value, expected", [
    ([], "$ must be object"),
    ({"verdict": "pass", "bug_class": None}, "missing 'confidence'"),
    ({"verdict": "maybe", "bug_class": None, "confidence": 0.5}, "$.verdict must be one of"),
    ({"verdict": "pass", "bug_class": 3, "confidence": 0.5}, "$.bug_class must be string or null"),
    ({"verdict": "pass", "bug_class": None, "confidence": 1.5}, "at most 1"),
    ({"verdict": "pass", "bug_class": None, "confidence": -0.1}, "at least 0"),
    ({"verdict": "pass", "bug_class": None, "confidence": True}, "$.confidence must be number"),
    ({"verdict": "pass", "bug_class": None, "confidence": 0.5, "tags": [1]}, "$.tags[0] must be string"),
])
def test_schema_reports_the_problem(value, expected):
    assert expected in llm.schema_problem(value, VERDICT)


def test_any_of_passes_when_one_form_fits():
    schema = {"anyOf": [{"type": "string"}, {"type": "integer", "minimum": 5}]}
    assert llm.schema_problem("x", schema) is None
    assert llm.schema_problem(7, schema) is None
    assert "fits none" in llm.schema_problem(3, schema)


def test_true_is_not_an_integer():
    assert llm.schema_problem(True, {"type": "integer"}) is not None


def test_unsupported_schema_keyword_raises_rather_than_being_ignored():
    with pytest.raises(ValueError, match="pattern"):
        llm.schema_problem("x", {"type": "string", "pattern": "a+"})


def test_call_returns_checked_data_with_role_settings(fake, tmp_path):
    result = make_llm(fake, tmp_path).call("skeptic_a", "p", SCHEMA, system="s")
    assert (result.data, result.model, result.cached, result.attempts) == ({"n": 1}, "ska:1", False, 1)
    assert fake.calls[0] == {"model": "ska:1", "prompt": "p", "system": "s", "temperature": 0.0, "timeout_s": 300}


def test_alias_role_uses_the_target_model_and_temperature(fake, tmp_path):
    make_llm(fake, tmp_path).call("mutant_writer", "p", SCHEMA)
    assert (fake.calls[0]["model"], fake.calls[0]["temperature"]) == ("sci:1", 0.2)


def test_fallback_model_is_used_when_preferred_is_missing(tmp_path):
    provider = FakeProvider(installed=("sci:0", "ska:1", "skb:1"))
    assert make_llm(provider, tmp_path).call("scientist", "p", SCHEMA).model == "sci:0"


def test_unknown_role_and_missing_model_raise(tmp_path):
    client = make_llm(FakeProvider(installed=()), tmp_path)
    with pytest.raises(llm.LLMError, match="unknown role"):
        client.call("nobody", "p", SCHEMA)
    with pytest.raises(llm.LLMError, match="installed"):
        client.call("skeptic_a", "p", SCHEMA)


def test_family_clash_refuses_to_start(fake, tmp_path):
    cfg = json.loads(json.dumps(CFG))
    cfg["roles"]["skeptic_a"]["family"] = "qwen"
    with pytest.raises(llm.LLMError, match="family"):
        make_llm(fake, tmp_path, cfg)


def test_unknown_provider_is_a_clear_error(tmp_path):
    cfg = dict(CFG, provider="nope")
    with pytest.raises(llm.LLMError, match="not supported"):
        llm.LLM(cfg, cache_path=tmp_path / "test.db").call("skeptic_a", "p", SCHEMA)


def test_role_can_override_the_provider(fake, tmp_path):
    """A cloud Scientist beside local Skeptics must be a config change only."""
    cfg = json.loads(json.dumps(CFG))
    cloud = FakeProvider()
    cfg["roles"]["scientist"]["provider"] = "cloud"
    client = llm.LLM(cfg, {"fake": fake, "cloud": cloud}, tmp_path / "test.db")
    client.call("scientist", "p", SCHEMA)
    client.call("skeptic_a", "p", SCHEMA)
    assert (len(cloud.calls), len(fake.calls)) == (1, 1)


def test_invalid_reply_retries_with_the_problem_in_the_prompt(tmp_path):
    provider = FakeProvider(["junk", GOOD])
    result = make_llm(provider, tmp_path).call("skeptic_a", "p", SCHEMA)
    assert result.attempts == 2
    assert provider.calls[0]["prompt"] == "p"
    assert provider.calls[1]["prompt"].startswith("p\n") and "rejected" in provider.calls[1]["prompt"]


def test_provider_failure_is_retried_as_a_cold_call(tmp_path):
    provider = FakeProvider([llm.LLMError("timed out"), GOOD])
    assert make_llm(provider, tmp_path).call("skeptic_a", "p", SCHEMA).attempts == 2
    assert [c["timeout_s"] for c in provider.calls] == [300, 300]


def test_prompt_that_may_not_fit_is_refused_without_calling_the_model(fake, tmp_path):
    """(8192 - 1024) * 3 = 21504 characters, counting the system prompt."""
    client = make_llm(fake, tmp_path)
    assert client.call("skeptic_a", "x" * 21503, SCHEMA, system="s").attempts == 1
    with pytest.raises(llm.LLMError, match="may not fit"):
        client.call("skeptic_a", "x" * 21504, SCHEMA, system="s")
    assert len(fake.calls) == 1


def test_each_retry_uses_a_new_seed(tmp_path):
    """Found in a real run: at one seed, Ollama's token-repeat abort simply happened again on every retry."""
    provider = FakeProvider([llm.LLMError("token repeat limit"), "junk", GOOD])
    make_llm(provider, tmp_path).call("scientist", "p", SCHEMA)
    assert provider.seed_offsets == [0, 1, 2]


@pytest.mark.slow
def test_ollama_receives_the_offset_seed(monkeypatch):
    monkeypatch.setattr("ollama.Client", FakeOllamaClient)
    llm.OllamaProvider(CFG["llm"]).generate("sci:1", "p", None, SCHEMA, 0.2, 5, seed_offset=2)
    assert FakeOllamaClient.last["options"]["seed"] == 2


def test_gives_up_after_one_try_plus_two_retries(tmp_path):
    provider = FakeProvider(["junk"] * 5)
    with pytest.raises(llm.LLMError, match="3 attempts"):
        make_llm(provider, tmp_path).call("skeptic_a", "p", SCHEMA)
    assert len(provider.calls) == 3


def test_second_call_is_served_from_cache_without_touching_the_model(fake, tmp_path):
    client = make_llm(fake, tmp_path)
    client.call("skeptic_a", "p", SCHEMA)
    second = client.call("skeptic_a", "p", SCHEMA)
    assert second.cached and second.data == {"n": 1}
    assert len(fake.calls) == 1


def test_cache_survives_a_new_client(fake, tmp_path):
    make_llm(fake, tmp_path).call("skeptic_a", "p", SCHEMA)
    assert make_llm(fake, tmp_path).call("skeptic_a", "p", SCHEMA).cached


def test_refresh_skips_the_cache_read_and_updates_it(tmp_path):
    client = make_llm(FakeProvider([GOOD, '{"n": 2}']), tmp_path)
    client.call("skeptic_a", "p", SCHEMA)
    assert client.call("skeptic_a", "p", SCHEMA, refresh=True).data == {"n": 2}
    assert client.call("skeptic_a", "p", SCHEMA).data == {"n": 2}


@pytest.mark.parametrize("other", [
    {"role": "skeptic_b", "prompt": "p", "schema": SCHEMA},
    {"role": "skeptic_a", "prompt": "q", "schema": SCHEMA},
    {"role": "skeptic_a", "prompt": "p", "schema": SCHEMA, "system": "s"},
    {"role": "skeptic_a", "prompt": "p", "schema": dict(SCHEMA, required=[])},
])
def test_anything_that_shapes_the_reply_gets_its_own_cache_entry(fake, tmp_path, other):
    client = make_llm(fake, tmp_path)
    client.call("skeptic_a", "p", SCHEMA)
    assert not client.call(**other).cached


def test_failed_replies_are_not_cached(tmp_path):
    client = make_llm(FakeProvider(["junk"] * 3 + [GOOD]), tmp_path)
    with pytest.raises(llm.LLMError):
        client.call("skeptic_a", "p", SCHEMA)
    assert client.call("skeptic_a", "p", SCHEMA).data == {"n": 1}


def test_switching_model_unloads_the_previous_one_first(fake, tmp_path):
    client = make_llm(fake, tmp_path)
    client.call("skeptic_a", "1", SCHEMA)
    client.call("skeptic_a", "2", SCHEMA)
    client.call("skeptic_b", "3", SCHEMA)
    assert fake.events == [("generate", "ska:1"), ("generate", "ska:1"), ("unload", "ska:1"), ("generate", "skb:1")]
    assert [c["timeout_s"] for c in fake.calls] == [300, 120, 300]


def test_cache_hit_does_not_switch_models(fake, tmp_path):
    client = make_llm(fake, tmp_path)
    client.call("skeptic_b", "p", SCHEMA)
    client.call("skeptic_a", "q", SCHEMA)
    fake.events.clear()
    client.call("skeptic_b", "p", SCHEMA)
    assert fake.events == []


def test_release_unloads_once(fake, tmp_path):
    client = make_llm(fake, tmp_path)
    client.call("skeptic_a", "p", SCHEMA)
    client.release()
    client.release()
    assert fake.events.count(("unload", "ska:1")) == 1


def test_queue_groups_by_model_and_keeps_submission_order(fake, tmp_path):
    client = make_llm(fake, tmp_path)
    queue = llm.ModelQueue(client)
    roles = ["skeptic_a", "skeptic_b", "skeptic_a", "skeptic_b", "scientist", "skeptic_a"]
    for i, role in enumerate(roles):
        assert queue.add(role, f"p{i}", SCHEMA) == i
    results = queue.run()
    assert [r.role for r in results] == roles
    assert [c["model"] for c in fake.calls] == ["ska:1"] * 3 + ["skb:1"] * 2 + ["sci:1"]
    assert [c["prompt"] for c in fake.calls] == ["p0", "p2", "p5", "p1", "p3", "p4"]
    assert fake.events.count(("unload", "ska:1")) == 1


def test_queue_treats_aliases_as_the_same_model(fake, tmp_path):
    queue = llm.ModelQueue(make_llm(fake, tmp_path))
    queue.add("scientist", "1", SCHEMA)
    queue.add("skeptic_a", "2", SCHEMA)
    queue.add("mutant_writer", "3", SCHEMA)
    queue.run()
    assert [c["model"] for c in fake.calls] == ["sci:1", "sci:1", "ska:1"]


def test_one_failure_does_not_stop_the_queue(tmp_path):
    provider = FakeProvider(["junk"] * 3 + [GOOD])
    queue = llm.ModelQueue(make_llm(provider, tmp_path))
    queue.add("skeptic_a", "bad", SCHEMA)
    queue.add("nobody", "x", SCHEMA)
    queue.add("skeptic_a", "good", SCHEMA)
    failed, unknown, good = queue.run()
    assert "3 attempts" in failed.error and failed.data is None
    assert "unknown role" in unknown.error
    assert good.error is None and good.data == {"n": 1}


def test_run_empties_the_queue(fake, tmp_path):
    queue = llm.ModelQueue(make_llm(fake, tmp_path))
    queue.add("skeptic_a", "p", SCHEMA)
    queue.run()
    assert queue.run() == []


class FakeOllamaClient:
    last = None

    def __init__(self, timeout):
        self.timeout = timeout

    def generate(self, **kwargs):
        FakeOllamaClient.last = {"timeout": self.timeout, **kwargs}
        return types.SimpleNamespace(response=GOOD)

    def list(self):
        return types.SimpleNamespace(models=[types.SimpleNamespace(model="sci:1")])


class BrokenOllamaClient(FakeOllamaClient):
    def generate(self, **kwargs):
        raise ConnectionError("server down")

    def list(self):
        raise ConnectionError("server down")


def test_ollama_provider_sends_schema_settings_and_timeout(monkeypatch):
    monkeypatch.setattr("ollama.Client", FakeOllamaClient)
    provider = llm.OllamaProvider(CFG["llm"])
    assert provider.generate("sci:1", "p", "s", SCHEMA, 0.2, 77) == GOOD
    sent = FakeOllamaClient.last
    assert sent["timeout"] == 77 and sent["format"] == SCHEMA and sent["think"] is False
    assert sent["options"] == {"temperature": 0.2, "seed": 0, "num_ctx": 8192, "num_predict": 1024}
    assert provider.installed_models() == {"sci:1"}


def test_ollama_unload_asks_for_zero_keep_alive(monkeypatch):
    monkeypatch.setattr("ollama.Client", FakeOllamaClient)
    llm.OllamaProvider(CFG["llm"]).unload("sci:1")
    assert FakeOllamaClient.last["keep_alive"] == 0


def test_ollama_failures_become_llm_errors(monkeypatch):
    monkeypatch.setattr("ollama.Client", BrokenOllamaClient)
    provider = llm.OllamaProvider(CFG["llm"])
    with pytest.raises(llm.LLMError):
        provider.generate("sci:1", "p", None, SCHEMA, 0.2, 5)
    with pytest.raises(llm.LLMError):
        provider.installed_models()
    with pytest.raises(llm.LLMError):
        provider.unload("sci:1")


def test_shipped_config_has_the_settings_the_wrapper_needs():
    cfg = config.load_yaml("models.yaml")
    assert set(CFG["llm"]) == set(cfg["llm"])
    assert cfg["roles"]["scientist"]["temperature"] == 0.2
    assert cfg["roles"]["skeptic_a"]["temperature"] == 0.0
