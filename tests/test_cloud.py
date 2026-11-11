"""The cloud provider (canary/llm.py OpenAIStyleProvider) with a fake transport, a fake clock and a fake key.

Nothing here reaches the network (tests/conftest.py blocks it) or waits: the clock and the sleep are injected.
"""
import copy
import hashlib
import json

import pytest

from canary import config, llm, review_tasks

KEY = "gsk_TEST_KEY_123456789"
GOOD_REPLY = '{"n": 1}'
SCHEMA = {"type": "object", "required": ["n"], "additionalProperties": False, "properties": {"n": {"type": "integer"}}}
ENTRY = {"kind": "openai_style", "base_url": "https://api.example.test/openai/v1/", "key_env": "TEST_CLOUD_KEY",
         "models": ["vendor/model-x"], "schema_mode": "json_schema", "max_tokens_field": "max_completion_tokens",
         "context_tokens": 8000, "min_interval_s": 30, "max_calls_per_day": 3, "max_wait_s": 60}
CFG = {
    "provider": "fake",
    "roles": {
        "scientist": {"model": "sci:1", "temperature": 0.2, "family": "qwen"},
        "skeptic_a": {"model": "ska:1", "temperature": 0.0, "family": "gemma"},
        "skeptic_d": {"provider": "cloudy", "model": "vendor/model-x", "temperature": 0.0, "family": "gpt-oss",
                      "top_logprobs": 0, "options": {"reasoning_effort": "low", "max_output_tokens": 500}},
        "skeptic_d_checklist": {"use_role": "skeptic_d", "task": "checklist"},
    },
    "providers": {"cloudy": ENTRY},
    "llm": {"retries": 2, "timeout_cold_s": 300, "timeout_warm_s": 120, "num_ctx": 8192, "num_predict": 1024, "seed": 0,
            "review_top_logprobs": 20},
}


def ok_body(content=GOOD_REPLY, finish="stop", **extra) -> bytes:
    return json.dumps({"id": "resp-1", "model": "vendor/model-x-2026", "choices": [
        {"message": {"role": "assistant", "content": content, **extra}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
                  "completion_tokens_details": {"reasoning_tokens": 7}}}).encode()


class FakeTransport:
    """Records each request and replays scripted (status, headers, body) answers; an exception is raised instead."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, url, headers, body, timeout_s):
        self.requests.append({"url": url, "headers": headers, "body": json.loads(body), "timeout_s": timeout_s})
        answer = self.answers.pop(0) if self.answers else (200, {}, ok_body())
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeClock:
    def __init__(self, start=1_800_000_000.0):
        self.now = start
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("TEST_CLOUD_KEY", KEY)


def make_provider(tmp_path, answers=(), entry=ENTRY, clock=None):
    clock = clock or FakeClock()
    transport = FakeTransport(answers)
    provider = llm.OpenAIStyleProvider(CFG["llm"], dict(entry), "cloudy", transport, clock, clock.sleep,
                                       tmp_path / "calls.jsonl")
    return provider, transport, clock


def make_client(tmp_path, provider, cfg=CFG):
    return llm.LLM(copy.deepcopy(cfg), {"cloudy": provider}, tmp_path / "cache.db")


def generate(provider, prompt="p", system="s", schema=SCHEMA, **kw):
    return provider.generate("vendor/model-x", prompt, system, schema, 0.0, 30, **kw)


# ---- step 1: config and role resolution -----------------------------------------------------------------------------

def test_the_model_id_reaches_the_provider_unchanged(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path)
    result = make_client(tmp_path, provider).call("skeptic_d", "p", SCHEMA)
    assert result.model == "vendor/model-x" and result.data == {"n": 1}
    assert transport.requests[0]["body"]["model"] == "vendor/model-x"  # no ":latest", no fallback


def test_a_model_off_the_allow_list_is_refused_without_a_call(tmp_path, key):
    cfg = copy.deepcopy(CFG)
    cfg["roles"]["skeptic_d"]["model"] = "vendor/paid-model"
    provider, transport, _ = make_provider(tmp_path)
    with pytest.raises(llm.LLMError, match="allow-list") as caught:
        make_client(tmp_path, provider, cfg).call("skeptic_d", "p", SCHEMA)
    assert caught.value.kind == llm.KIND_CONFIG and transport.requests == []


def test_the_provider_refuses_an_unlisted_model_even_if_asked_directly(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path)
    with pytest.raises(llm.LLMError, match="allow-list"):
        provider.generate("vendor/other", "p", None, SCHEMA, 0.0, 30)
    assert transport.requests == []


def test_an_alias_resolves_to_its_cloud_target(tmp_path):
    provider, _, _ = make_provider(tmp_path)
    assert make_client(tmp_path, provider).resolve("skeptic_d_checklist") == ("cloudy", "vendor/model-x", 0.0)


def test_cloud_families_pass_and_a_qwen_model_under_another_label_is_refused():
    shipped = config.load_yaml("models.yaml")
    assert config.family_clashes(shipped) == []
    assert {shipped["roles"][r]["family"] for r in ("skeptic_d", "skeptic_e")} == {"gpt-oss", "gemini"}
    cfg = copy.deepcopy(CFG)
    cfg["roles"]["skeptic_d"].update(model="qwen/qwen3.8-27b", family="other")
    assert config.family_clashes(cfg) == ["skeptic_d"]


def test_the_shipped_config_loads_and_lists_its_cloud_roles(tmp_path):
    client = llm.LLM(cache_path=tmp_path / "c.db")
    assert set(config.cloud_roles(client.cfg)) == {"skeptic_d", "skeptic_d_checklist", "skeptic_e", "skeptic_e_checklist"}
    for role in config.cloud_roles(client.cfg):
        provider, model, temperature = client.resolve(role)  # no network: the allow-list only
        assert model in client.cfg["providers"][provider]["models"] and temperature == 0.0
        assert ":" not in model
    assert all(c.role not in config.cloud_roles(client.cfg)
               for c in config.resolve_roles(client.cfg, {"gemma3:4b"}))  # doctor never looks for them in Ollama


# ---- step 2: the request as pure functions ---------------------------------------------------------------------------

BUGS = ["B01", "B03"]


def test_the_baseline_wire_schema_is_one_flat_object():
    wire = llm.wire_schema(review_tasks.baseline_schema(BUGS))
    assert wire == {
        "type": "object", "required": ["verdict", "bug_class", "evidence", "confidence"], "additionalProperties": False,
        "properties": {
            "verdict": {"enum": ["pass", "flag"], "type": "string"},
            "bug_class": {"anyOf": [{"type": "null"}, {"enum": BUGS, "type": "string"}]},
            "evidence": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }}


@pytest.mark.parametrize("task", review_tasks.TASKS)
def test_every_reply_that_fits_the_original_schema_fits_the_wire_schema(task):
    from canary import blinding

    bugs = config.load_yaml("bug_classes.yaml")
    _, _, schema = review_tasks.build(task, blinding.BlindedRun("x = 1", "{}", "{}"), bugs)
    ids = sorted(bugs)
    if task == review_tasks.CHECKLIST:
        replies = [{b: {"line": "x = 1", "answer": a} for b in ids} for a in ("yes", "no")]
    else:
        head = {"offending_line": "x = 1"} if task == review_tasks.GROUNDED else {}
        replies = [{**head, "verdict": "pass", "bug_class": None, "evidence": "e", "confidence": 0.5}] + \
                  [{**head, "verdict": "flag", "bug_class": b, "evidence": "e", "confidence": 1} for b in ids]
    wire = llm.wire_schema(schema)
    for reply in replies:
        assert llm.schema_problem(reply, schema) is None
        assert llm.schema_problem(reply, wire) is None
    # The reverse does not hold, which is why parse_reply keeps checking the original schema.
    if task != review_tasks.CHECKLIST:
        bad = {**replies[0], "bug_class": ids[0]}
        assert llm.schema_problem(bad, wire) is None and llm.schema_problem(bad, schema) is not None
    else:
        assert wire == llm._typed_enums(schema)  # no top-level anyOf: only the enum types are added


def test_build_request_gives_exactly_this_body():
    body = llm.build_request(ENTRY, "vendor/model-x", "the prompt", "the system", SCHEMA, 0.0, 7,
                             {"reasoning_effort": "low", "max_output_tokens": 500})
    assert body == {
        "model": "vendor/model-x",
        "messages": [{"role": "system", "content": "the system"}, {"role": "user", "content": "the prompt"}],
        "temperature": 0.0, "seed": 7, "stream": False, "max_completion_tokens": 500, "reasoning_effort": "low",
        "response_format": {"type": "json_schema", "json_schema": {"name": "reply", "strict": True, "schema": SCHEMA}}}
    assert not any("logprob" in k for k in body)


def test_json_object_mode_and_no_system_message():
    body = llm.build_request(dict(ENTRY, schema_mode="json_object"), "m", "p", None, SCHEMA, 0.0, 0)
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == [{"role": "user", "content": "p"}]
    assert "max_completion_tokens" not in body and "reasoning_effort" not in body


def test_an_unknown_option_is_refused_rather_than_ignored():
    with pytest.raises(llm.LLMError, match="unknown cloud options"):
        llm.build_request(ENTRY, "m", "p", None, SCHEMA, 0.0, 0, {"reasoning": "low"})


def test_read_reply_takes_the_content_and_drops_reasoning():
    body = json.loads(ok_body(content='<think>maybe {"n": 2}</think>{"n": 1}', reasoning="long thoughts"))
    assert llm.read_reply(body) == '{"n": 1}'


@pytest.mark.parametrize("content, finish, problem", [
    ("", "stop", "empty"), (None, "stop", "empty"), ('{"n": 1', "length", "cut off"), ("x", "content_filter", "filtered")])
def test_read_reply_refuses_empty_cut_off_and_filtered_replies(content, finish, problem):
    with pytest.raises(llm.InvalidReply, match=problem):
        llm.read_reply(json.loads(ok_body(content=content, finish=finish)))


# ---- step 3: the provider and the transport ---------------------------------------------------------------------------

def test_one_post_with_the_key_in_the_header_and_nothing_else(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path)
    assert generate(provider) == GOOD_REPLY
    sent = transport.requests[0]
    assert sent["url"] == "https://api.example.test/openai/v1/chat/completions"
    assert sent["headers"] == {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
                               "User-Agent": "canary-research/0.1"}


def test_azure_style_key_header(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path, entry=dict(ENTRY, auth_header="api-key"))
    generate(provider)
    assert transport.requests[0]["headers"]["api-key"] == KEY and "Authorization" not in transport.requests[0]["headers"]


def test_the_key_is_read_from_the_env_file_at_the_first_call(tmp_path, monkeypatch):
    env = tmp_path / "test.env"
    env.write_text(f"TEST_CLOUD_KEY={KEY}\n", encoding="utf-8")
    provider, transport, _ = make_provider(tmp_path)  # building it needs no key
    monkeypatch.setattr(llm, "ENV_PATH", env)
    generate(provider)
    assert transport.requests[0]["headers"]["Authorization"] == f"Bearer {KEY}"


def test_a_missing_key_stops_without_any_request(tmp_path):
    provider, transport, _ = make_provider(tmp_path)
    with pytest.raises(llm.LLMError, match="TEST_CLOUD_KEY is not set") as caught:
        generate(provider)
    assert caught.value.kind == llm.KIND_ACCESS and transport.requests == []


@pytest.mark.parametrize("status, kind", [
    (401, llm.KIND_ACCESS), (403, llm.KIND_ACCESS), (404, llm.KIND_ACCESS), (307, llm.KIND_ACCESS),
    (400, llm.KIND_REQUEST_REFUSED), (413, llm.KIND_REQUEST_REFUSED), (422, llm.KIND_REQUEST_REFUSED),
    (500, llm.KIND_TIMEOUT_OR_SERVER), (503, llm.KIND_TIMEOUT_OR_SERVER)])
def test_each_status_maps_to_its_kind(tmp_path, key, status, kind):
    provider, _, _ = make_provider(tmp_path, [(status, {}, f'{{"error": "nope, key {KEY}"}}'.encode())])
    with pytest.raises(llm.LLMError) as caught:
        generate(provider)
    assert caught.value.kind == kind
    assert KEY not in str(caught.value)  # scrubbed even when the provider echoes it


def test_a_200_whose_body_is_not_json_is_a_server_failure(tmp_path, key):
    provider, _, _ = make_provider(tmp_path, [(200, {}, b"<html>gateway</html>")])
    with pytest.raises(llm.LLMError) as caught:
        generate(provider)
    assert caught.value.kind == llm.KIND_TIMEOUT_OR_SERVER


def test_a_timeout_is_a_server_failure_and_is_logged(tmp_path, key):
    provider, _, _ = make_provider(tmp_path, [llm.LLMError("not reachable: timed out")])
    with pytest.raises(llm.LLMError) as caught:
        generate(provider)
    assert caught.value.kind == llm.KIND_TIMEOUT_OR_SERVER
    assert json.loads((tmp_path / "calls.jsonl").read_text(encoding="utf-8"))["status"] is None


def test_the_real_transport_never_follows_a_redirect():
    handler = llm._NoRedirect()
    assert handler.redirect_request(None, None, 307, "moved", {}, "https://elsewhere.test/") is None


def test_the_test_suite_cannot_reach_the_network():
    with pytest.raises(RuntimeError, match="network"):
        llm.urllib_transport("https://api.example.test/x", {}, b"{}", 1)


def test_token_probabilities_are_never_requested_from_a_cloud_provider(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path)
    with pytest.raises(llm.LLMError, match="never ask for token probabilities"):
        generate(provider, top_logprobs=20)
    assert transport.requests == []


# ---- step 4: pacing, 429 and the daily budget -------------------------------------------------------------------------

def test_two_calls_are_spaced_by_the_minimum_interval(tmp_path, key):
    provider, _, clock = make_provider(tmp_path)
    generate(provider, prompt="a")
    clock.now += 5
    generate(provider, prompt="b")
    assert clock.slept == [25]


def test_the_pause_survives_a_restart_through_the_log(tmp_path, key):
    clock = FakeClock()
    first, _, _ = make_provider(tmp_path, clock=clock)
    generate(first)
    second, _, _ = make_provider(tmp_path, clock=clock)  # a new process: knows only the log
    generate(second)
    assert clock.slept == [30]


def test_a_short_retry_after_is_waited_and_the_retry_succeeds(tmp_path, key):
    provider, transport, clock = make_provider(tmp_path, [(429, {"retry-after": "12"}, b'{"error": "slow down"}')])
    assert generate(provider) == GOOD_REPLY
    assert 12 in clock.slept and len(transport.requests) == 2


@pytest.mark.parametrize("headers", [{"retry-after": "3600"}, {}])
def test_a_long_or_missing_retry_after_stops_after_exactly_one_request(tmp_path, key, headers):
    provider, transport, _ = make_provider(tmp_path, [(429, {**headers, "x-ratelimit-remaining-requests": "0"},
                                                       b'{"error": "daily limit"}')])
    with pytest.raises(llm.LLMError, match="x-ratelimit-remaining-requests") as caught:
        generate(provider)
    assert caught.value.kind == llm.KIND_RATE_LIMITED and len(transport.requests) == 1


def test_a_second_429_after_waiting_stops(tmp_path, key):
    answer = (429, {"retry-after": "5"}, b"{}")
    provider, transport, _ = make_provider(tmp_path, [answer, answer])
    with pytest.raises(llm.LLMError) as caught:
        generate(provider)
    assert caught.value.kind == llm.KIND_RATE_LIMITED and len(transport.requests) == 2


def test_the_daily_call_budget_stops_the_call_after_it_without_a_request(tmp_path, key):
    provider, transport, clock = make_provider(tmp_path)
    for i in range(3):
        generate(provider, prompt=str(i))
        clock.now += 60
    with pytest.raises(llm.LLMError, match="daily limit reached") as caught:
        generate(provider, prompt="fourth")
    assert caught.value.kind == llm.KIND_RATE_LIMITED and len(transport.requests) == 3
    clock.now += llm.DAY_S  # the window has moved on: tomorrow it resumes
    assert generate(provider, prompt="next day") == GOOD_REPLY


def test_the_daily_token_budget_counts_reported_usage(tmp_path, key):
    entry = dict(ENTRY, max_calls_per_day=None, max_tokens_per_day=300)
    provider, transport, clock = make_provider(tmp_path, entry=entry)
    generate(provider, prompt="x" * 30)  # 120 tokens used
    clock.now += 60
    with pytest.raises(llm.LLMError, match="tokens"):  # 120 + 10 + 500 output limit > 300
        generate(provider, prompt="x" * 30, options={"max_output_tokens": 500})
    assert len(transport.requests) == 1


def test_a_stop_kind_is_not_retried_by_the_wrapper(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path, [(429, {}, b"{}")] * 3)
    with pytest.raises(llm.LLMError) as caught:
        make_client(tmp_path, provider).call("skeptic_d", "p", SCHEMA)
    assert caught.value.kind == llm.KIND_RATE_LIMITED and len(transport.requests) == 1


def test_a_refused_request_is_not_retried_inside_one_call(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path, [(400, {}, b'{"error": "bad"}')] * 3)
    with pytest.raises(llm.LLMError) as caught:
        make_client(tmp_path, provider).call("skeptic_d", "p", SCHEMA)
    assert caught.value.kind == llm.KIND_REQUEST_REFUSED and len(transport.requests) == 1


def test_an_invalid_reply_is_still_retried_with_the_problem_named(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path, [(200, {}, ok_body("junk")), (200, {}, ok_body())])
    assert make_client(tmp_path, provider).call("skeptic_d", "p", SCHEMA).attempts == 2
    assert "rejected" in transport.requests[1]["body"]["messages"][-1]["content"]


def test_the_queue_asks_nothing_more_of_a_model_after_a_daily_stop(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path, [(429, {}, b"{}")])
    queue = llm.ModelQueue(make_client(tmp_path, provider))
    for prompt in "abc":
        queue.add("skeptic_d", prompt, SCHEMA)
    results = queue.run()
    assert [r.error_kind for r in results] == [llm.KIND_RATE_LIMITED] * 3 and len(transport.requests) == 1


# ---- step 5: call log, options, cache key -----------------------------------------------------------------------------

def test_every_attempt_is_logged_without_the_key_or_any_header(tmp_path, key):
    provider, _, _ = make_provider(tmp_path, [(429, {"retry-after": "1", "x-ratelimit-limit-tokens": "8000",
                                                     "set-cookie": "secret"}, b"{}")])
    make_client(tmp_path, provider).call("skeptic_d", "the prompt", SCHEMA, system="sys")
    text = (tmp_path / "calls.jsonl").read_text(encoding="utf-8")
    assert KEY not in text and "Bearer" not in text and "set-cookie" not in text
    first, second = [json.loads(line) for line in text.splitlines()]
    assert first["status"] == 429 and first["rate_limit_headers"] == {"retry-after": "1", "x-ratelimit-limit-tokens": "8000"}
    assert second["status"] == 200 and second["role"] == "skeptic_d" and second["model"] == "vendor/model-x"
    assert (second["server_model"], second["total_tokens"], second["reasoning_tokens"]) == ("vendor/model-x-2026", 120, 7)
    assert second["prompt_sha256"] == hashlib.sha256(b"the prompt").hexdigest()
    assert (second["reasoning_effort"], second["max_output_tokens"], second["schema_mode"]) == ("low", 500, "json_schema")
    assert second["wire_schema_sha256"] == llm._sha256_json(llm.wire_schema(SCHEMA))
    assert "response_body" in second and isinstance(second["seconds"], float)


def test_role_options_reach_the_request(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path)
    make_client(tmp_path, provider).call("skeptic_d_checklist", "p", SCHEMA)  # an alias gets its target's options
    body = transport.requests[0]["body"]
    assert (body["reasoning_effort"], body["max_completion_tokens"]) == ("low", 500)


def test_cache_keys_without_an_endpoint_are_exactly_as_before():
    old = hashlib.sha256(json.dumps(["m", "p", "s", SCHEMA, 0.0], sort_keys=True).encode("utf-8")).hexdigest()
    assert llm.Cache.key("m", "p", "s", SCHEMA, 0.0) == old
    low = llm.Cache.key("m", "p", "s", SCHEMA, 0.0, {"provider": "a", "base_url": "u", "options": {"reasoning_effort": "low"}})
    high = llm.Cache.key("m", "p", "s", SCHEMA, 0.0, {"provider": "a", "base_url": "u", "options": {"reasoning_effort": "high"}})
    other = llm.Cache.key("m", "p", "s", SCHEMA, 0.0, {"provider": "b", "base_url": "u", "options": {"reasoning_effort": "low"}})
    assert len({old, low, high, other}) == 4


def test_changing_the_schema_mode_does_not_reuse_a_stored_reply(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path)
    make_client(tmp_path, provider).call("skeptic_d", "p", SCHEMA)
    cfg = copy.deepcopy(CFG)
    cfg["providers"]["cloudy"]["schema_mode"] = "json_object"
    other, transport2, _ = make_provider(tmp_path, entry=cfg["providers"]["cloudy"])
    assert not make_client(tmp_path, other, cfg).call("skeptic_d", "p", SCHEMA).cached and len(transport2.requests) == 1


def test_a_provider_timeout_replaces_the_ollama_timeouts(tmp_path, key):
    cfg = copy.deepcopy(CFG)
    cfg["providers"]["cloudy"]["timeout_s"] = 77
    provider, transport, _ = make_provider(tmp_path, entry=cfg["providers"]["cloudy"])
    make_client(tmp_path, provider, cfg).call("skeptic_d", "p", SCHEMA)
    assert transport.requests[0]["timeout_s"] == 77


def test_a_cloud_reply_is_cached_under_the_endpoint_key(tmp_path, key):
    provider, transport, _ = make_provider(tmp_path)
    client = make_client(tmp_path, provider)
    client.call("skeptic_d", "p", SCHEMA)
    assert client.call("skeptic_d", "p", SCHEMA).cached and len(transport.requests) == 1


def test_the_context_guard_uses_the_providers_size(tmp_path, key):
    """(8000 context - 500 output) * 3 = 22500 characters, counting the system prompt."""
    provider, transport, _ = make_provider(tmp_path)
    client = make_client(tmp_path, provider)
    client.call("skeptic_d", "x" * 22499, SCHEMA, system="s")
    with pytest.raises(llm.LLMError, match="may not fit") as caught:
        client.call("skeptic_d", "y" * 22500, SCHEMA, system="s")
    assert caught.value.kind == llm.KIND_PROMPT_TOO_LARGE and len(transport.requests) == 1
