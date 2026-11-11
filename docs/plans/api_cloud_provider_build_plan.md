# Build plan for `/api`: a cloud provider in `canary/llm.py` (NOT built)

Written 2026-11-11 by the planning session, for the build session (`/api`). Design and reasons:
`docs/plans/cloud_ceiling_check_outline.md` (sections 2, 8, 9, 10). This file is a plan, not a locked
pre-registration; the build session may adjust details and must note each change in `PROGRESS.md`.

## Scope
**Build:** one OpenAI-style HTTP provider with the standard library, its config, rate-limit handling, a call log,
the small wrapper changes cloud roles need, mocked tests, and a smoke command.
**Do not build here:** `eval/ceiling.py`, the `eval/power_sim.py` extension, the locked plan, the extension batch.
**Do not do at all in this session:** any real cloud call, creating or reading a key, reviewing a run. The session is
finished without network access. The provider decision (Groq + Gemini, pending the student's OK) changes only the
values in `config/models.yaml`, not the code.

## Rules that apply (CLAUDE.md, project memory)
- Only `canary/llm.py`, `config/models.yaml`, `.env.example` and their tests, plus the three small touches named in
  steps 6-8 (`canary/skeptic.py`, `canary/cli.py`). No new dependency: `urllib.request`, `json`, `os`, `time`.
- Tests never touch the network and never need a key. The suite is at its 30 s limit: no real sleeps (inject the
  clock and the sleep function), no new slow tests in the default run.
- The Skeptic stays a different model family from the qwen Scientist (`config.family_clashes`).
- `canary/skeptic.py` may not import anything off its allow-list (`tests/test_skeptic.py`); the touches below add no
  import.
- `config/models.yaml` is listed `-text` in `.gitattributes` (LF bytes) because the llama confirmation plans hashed
  it. Those plans are dead and never ran, so editing the file is allowed; keep LF endings, and if a test pins its
  hash, update the test's expectation and say so in `PROGRESS.md`. Do not edit the other frozen files
  (`canary/review_tasks.py`, `canary/mixer.py`, `canary/separation.py`, `canary/controls.py`): nothing here needs it.
- Existing cache keys must not change (step 5), or every stored reply would be orphaned.

## What exists today (read before starting)
- `canary/llm.py`: `Provider` protocol (`installed_models`, `generate`, `unload`), `OllamaProvider`,
  `PROVIDERS = {"ollama": OllamaProvider}`, `LLM._provider` (builds `PROVIDERS[name](self.settings)`), `LLM.resolve`,
  `LLM.call` (cache, retries, `extra` options "sent only when used"), `ModelQueue`.
- Three traps in the current code that a cloud role would hit:
  1. `LLM.resolve` goes through `config.resolve_roles`, which adds `:latest` to any model name without a colon
     (`config._with_tag`). `gemini-3.8-flash` would be sent as `gemini-3.8-flash:latest`.
  2. `skeptic.audit_pending` asks every role for token probabilities when `llm.review_top_logprobs` is set (it is 20).
     Groq answers 400 to `logprobs`.
  3. `cli.check_models` (doctor) checks every non-alias role against the installed Ollama models, and `cmd_llm_smoke`
     calls every non-alias role. A cloud role would fail doctor and spend quota on every smoke run.
- `tests/test_llm.py`: `FakeProvider`, `make_llm`, and the Ollama tests to copy the style from.

## Target config (`config/models.yaml`)
```yaml
providers:                    # cloud endpoints; Ollama needs no entry
  groq:
    kind: openai_style
    base_url: "https://api.groq.com/openai/v1"
    key_env: GROQ_API_KEY     # the NAME of the key in .env, never the key
    models: ["openai/gpt-oss-120b"]   # allow-list: any other model is refused (the $0 guard)
    schema_mode: json_schema  # json_schema | json_object
    max_tokens_field: max_completion_tokens
    min_interval_s: 35        # pause between calls (8,000 tokens a minute; confirm in the console)
    max_calls_per_day: 45     # our own budget, below the provider's limit (confirm in the console)
    max_wait_s: 90            # a 429 with a longer retry-after stops the pass instead of waiting
  gemini:
    kind: openai_style
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai"
    key_env: GEMINI_API_KEY
    models: ["gemini-3.8-flash"]
    schema_mode: json_schema
    max_tokens_field: max_tokens
    min_interval_s: 15
    max_calls_per_day: 18     # worst case found is 20 a day; read the real limit in AI Studio
    max_wait_s: 90
roles:
  # Ceiling check, arm L and arm R (docs/plans/cloud_ceiling_check_outline.md). No fallback on purpose.
  skeptic_d: {provider: groq, model: "openai/gpt-oss-120b", temperature: 0.0, family: gpt-oss, top_logprobs: 0,
              options: {reasoning_effort: low, max_output_tokens: 4000}}
  skeptic_d_checklist: {use_role: skeptic_d, task: checklist}
  skeptic_e: {provider: gemini, model: "gemini-3.8-flash", temperature: 0.0, family: gemini, top_logprobs: 0,
              options: {reasoning_effort: high, max_output_tokens: 8000}}
  skeptic_e_checklist: {use_role: skeptic_e, task: checklist}
```
The limits are placeholders until the student reads the real ones in the consoles; say so in a comment. Groq counts
tokens per minute, so `max_output_tokens` plus the prompt (about 3k tokens) should stay under that limit.
`.env.example` gains `GROQ_API_KEY=` and `GEMINI_API_KEY=` with empty values and one comment line each.

## Steps (each ends with `pytest -q` green; commit at the end, or after steps 4 and 9)

**Step 1. Config and role resolution.**
- Add the `providers:` block and the four roles above.
- `LLM._provider(name)`: if `name` is in `cfg["providers"]`, build `PROVIDERS[entry["kind"]](self.settings, entry,
  name)`; otherwise as today. Register `"openai_style": OpenAIStyleProvider` in `PROVIDERS`.
- `LLM.resolve`: for a role whose provider is in `cfg["providers"]`, return the configured `model` exactly (no tag,
  no fallback, no network), after checking it is in that provider's `models` allow-list; otherwise raise `LLMError`
  naming the role and the list. Ollama roles resolve as today.
- Tests: the model ID reaches the provider unchanged (`openai/gpt-oss-120b`, `gemini-3.8-flash`); a model off the
  allow-list is refused without a call; an alias (`skeptic_d_checklist`) resolves to its target; a cloud role in
  the qwen family is refused at start-up; the shipped config loads and has no family clash.

**Step 2. The request, as pure functions (no I/O, easy to test and to show in a viva).**
- `wire_schema(schema) -> dict`: what is sent in place of the review schema.
  - A top-level `anyOf` whose options are objects with the same property names in the same order becomes one flat
    object: per property, enums are merged in option order (`pass`, `flag`), and differing forms are put under a
    nested `anyOf` (`bug_class`: null or one of the IDs). `required` and `additionalProperties: false` are kept.
  - Every enum of strings gains `"type": "string"` (strict modes want a type). Anything else is copied unchanged.
  - A schema without a top-level `anyOf` (the checklist, the smoke schema) only gets the enum types.
  - Property: every reply that fits the original schema also fits the wire schema (test this with the three real
    review schemas and hand-written replies, using `schema_problem`). The reverse does not hold (a pass that names a
    bug fits the wire schema), which is why `parse_reply` keeps checking the original.
- `build_request(entry, model, prompt, system, schema, temperature, seed, options) -> dict`: the JSON body.
  `model`; `messages` (system only if given, then user); `temperature`; `seed`; `stream: false`; the output limit
  under `entry["max_tokens_field"]`; `reasoning_effort` if the options have it; `response_format`:
  `{"type": "json_schema", "json_schema": {"name": "reply", "strict": true, "schema": wire_schema(schema)}}` or
  `{"type": "json_object"}` by `schema_mode`. No `logprobs` key, ever, unless `top_logprobs` is above 0.
- `read_reply(body: dict) -> str`: `choices[0].message.content`. Empty content, or a `finish_reason` of `length` or
  `content_filter`, raises `InvalidReply` with that reason (a cut-off or refused reply is the reviewer's failure on
  that run and must leave a trace; the wrapper's retry then says why).
- Tests: the exact body for a baseline and a checklist request compared with a hand-written dict; `json_object`
  mode; no logprobs key; `read_reply` on a good body, an empty one, and a cut-off one.

**Step 3. `OpenAIStyleProvider` and the transport.**
- Constructor `(settings, entry, name, transport=None, clock=time.time, sleep=time.sleep, log_path=None)`.
  `transport(url, headers, body_bytes, timeout_s) -> (status, headers_dict, body_bytes)`; the default uses
  `urllib.request` and turns `HTTPError` into a normal `(status, headers, body)` result, and `URLError` or a timeout
  into `LLMError(kind=KIND_TIMEOUT_OR_SERVER)`.
- The key: read at the first call, not at construction (doctor and tests build providers without a key). Load `.env`
  with `dotenv.load_dotenv(config.ROOT / ".env")`, then `os.environ.get(entry["key_env"])`. Missing key:
  `LLMError("<name>: <KEY_NAME> is not set in .env", KIND_ACCESS)`.
- Headers: `Authorization: Bearer <key>`, `Content-Type: application/json`, and an explicit
  `User-Agent: canary-research/0.1` (urllib's default agent is blocked by some API front ends; no personal details
  in it).
- `installed_models()` returns `set(entry["models"])`: no network. `unload()` does nothing.
- `generate(...)` accepts the protocol's arguments plus `options: dict | None = None`; POSTs to
  `<base_url>/chat/completions`; returns `read_reply(body)` (a string; cloud roles never ask for probabilities, and a
  request with `top_logprobs` above 0 raises a clear `LLMError` rather than sending something the endpoint refuses).
- Status mapping (new kinds beside the three existing ones):
  - 200: parse JSON; a body that is not JSON is `KIND_TIMEOUT_OR_SERVER`.
  - 429: step 4.
  - 401, 403, 404: `KIND_ACCESS = "access"` (bad key, no permission, model gone). Stops the pass, no ledger entry.
  - 400, 422 and other 4xx: `KIND_REQUEST_REFUSED = "request_refused"`. Stored as a failed audit and counted toward
    the three-in-a-row stop: it may be this run's content (a safety refusal) or a systematic schema refusal, and the
    smoke test catches the systematic case before any batch.
  - 5xx, timeouts: `KIND_TIMEOUT_OR_SERVER`, retried by the wrapper as today.
- The error text may quote the response body (cut to a few hundred characters), never a header.
- Tests with a fake transport: URL, method and headers; the key is read from the environment (monkeypatched) and
  appears in no exception text and no log line; each status maps to its kind; the Ollama tests still pass.
- Add an autouse fixture in `tests/conftest.py` that makes `urllib.request.urlopen` raise, so no test can reach the
  network by accident.

**Step 4. Pacing, 429 and the daily budget.**
- Pacing: before each request wait until `min_interval_s` has passed since this provider's last request (use the
  injected `clock` and `sleep`).
- 429: read `retry-after` (seconds). If it is present and at most `max_wait_s`: sleep that long and try once more.
  Otherwise, or if the second try is also 429: `LLMError(kind=KIND_RATE_LIMITED)` with the provider's message and the
  rate-limit headers, so the student sees which limit was hit.
- Daily budget: before any request, count this provider-and-model's logged attempts in the last 24 hours (step 5's
  log). At `max_calls_per_day`: raise `KIND_RATE_LIMITED` without any network call, with the time the oldest counted
  call leaves the window.
- `STOP_KINDS = {KIND_RATE_LIMITED, KIND_ACCESS}`. In `LLM.call`, an error of a stop kind is raised at once: a retry
  cannot succeed and would spend quota. In `ModelQueue.run`, after a stop-kind error the remaining requests of that
  model get the same error without being called.
- Tests (fake clock, no real sleep): two calls are spaced by `min_interval_s`; a short `retry-after` is waited and
  the retry succeeds; a long one raises `rate_limited` after exactly one request; the budget stops call 46 of 45
  with no transport call; `LLM.call` makes one attempt, not three, on `rate_limited`; the queue skips the rest.

**Step 5. The call log, per-role options and the cache key.**
- Log: append one JSON line per HTTP attempt to `data/cloud/calls.jsonl` (`config.DATA_DIR / "cloud"`; `data/` is in
  `.gitignore`): UTC time, provider name, model asked, `temperature`, `seed`, `reasoning_effort`, output limit,
  schema mode, SHA-256 of the wire schema, SHA-256 of the prompt, status, the `retry-after` and `x-ratelimit-*`
  response headers, seconds, and the full response body as text. Never the key or any request header. Written
  before the status is acted on, so failed and rate-limited attempts are in it too. Tests use `tmp_path`.
- Options: in `LLM.call`, if the role (or the role its alias points to) has `options:`, pass them as
  `extra["options"]` ("sent only when used", so `OllamaProvider` and `FakeProvider` are untouched).
- Cache key: two roles on one model at different reasoning effort must not share replies. `Cache.key` gains an
  optional `options` argument that is added to the hashed list **only when given**. Test: the key of a call without
  options is byte-identical to today's (compare with a hash computed from the current formula), and differs once
  options are set or changed.
- Test: the key string and the word "Bearer" appear nowhere in the log file after a call.

**Step 6. No token probabilities for cloud roles (`canary/skeptic.py`, small).**
- New helper beside `task_of`: the role's (or its alias target's) `top_logprobs` if the key is present, else
  `llm.review_top_logprobs`. `audit_pending` uses it in place of the global value; with 0 it stores no `score`, as
  it already does when probabilities are off.
- `rescore` uses the same helper: with 0 it calls `client.call(..., refresh=True, cache_write=False)` (no
  probabilities, cache bypassed, stored reply untouched) and records matched / reply_differs / verdict_changed with
  `score: None`. This is the ceiling check's repeat pass. Add `--sample N --seed S` to `canary.cli rescore`: a seeded
  draw of N run IDs from the batch, by ID only (no ground truth).
- Tests: a role with `top_logprobs: 0` is audited without the provider being asked for probabilities and without a
  `score`; llama's roles still ask for 20; the repeat call bypasses the cache and leaves it unchanged.

**Step 7. A daily stop is not a failed audit (`canary/skeptic.py`, small).**
- In `audit_pending`: a result whose `error_kind` is in `llm.STOP_KINDS` writes **nothing** to the ledger, sets
  `report.stopped` ("daily limit reached ..." or "access problem ..."; the existing "is Ollama running?" text stays
  for server failures), and ends the pass after the current chunk. Results of the same chunk that did succeed are
  stored as usual. Reason, for the docstring: a quota stop depends on how many calls were made, not on the run, so
  it says nothing about the reviewer; a trace in the ledger would later be counted as a retry against it.
- `request_refused` is stored as `audit_failed` and counts toward the three-in-a-row stop like a server failure.
- Tests with a fake provider: the pass stops, the ledger has no `audit_failed` for the unasked runs, a second pass
  reviews exactly the remaining runs, and `canary.cli reaudit` prints the "run the same command again" line.

**Step 8. Doctor and smoke commands (`canary/cli.py`).**
- `check_models`: Ollama roles as today. For each cloud role print one line: provider, model, and "key present" or
  "key missing (add <KEY_NAME> to .env)". A missing key is a note, not a failure: Canary runs without any cloud
  role, and Mission 1.1's "doctor reports OK" must hold on a machine with no keys. No network call.
- `cmd_llm_smoke`: skip roles whose provider is a cloud one and say so in one line.
- New `cloud-smoke --role R [--dry]`. `--dry` prints the exact JSON body for the smoke prompt and for a review
  prompt built from old real run `1875ec26` (both tasks), plus each wire schema's SHA-256, with no key and no
  network. Without `--dry` it sends: the toy prompt (`SMOKE_PROMPT`), then the two review prompts, then the baseline
  one once more with the cache bypassed; prints for each the model named by the server, token usage, seconds and
  whether the reply passed `parse_reply`; and says whether the repeat equalled the first. About 4 calls.
  **The live form is not run in the build session**: it sends a blinded run, which needs the student's OK, and a key.
- Tests: doctor is OK with no key set and never opens a connection; `llm-smoke` skips cloud roles; `cloud-smoke
  --dry` prints valid JSON bodies and makes no call.

**Step 9. Close.**
- `pytest -q` (under 30 s; time it twice) and `pytest -m slow`.
- Done when: `python -m canary.cli doctor` says all OK with no `.env`; `python -m canary.cli cloud-smoke --role
  skeptic_d --dry` and `--role skeptic_e --dry` print their request bodies; `python -m canary.cli ledger verify` is
  OK and unchanged in length; no file under `data/cloud/` exists (no call was made).
- `PROGRESS.md`: what was built, the check results, any deviation from this plan, and "no cloud call made".
- Commit `"/api: OpenAI-style cloud provider (stdlib HTTP), pacing and daily budget, call log, cloud-smoke; no call made"`.

## What the next sessions need (not part of `/api`)
1. `eval/ceiling.py` (frozen analysis, verdict-based) and the `eval/power_sim.py` extension that sizes the batch
   (outline sections 5-7); the extension batch if the size is above 40.
2. The student's steps: confirm the provider, create the two keys without a payment method, read the limits in both
   consoles, put them in `config/models.yaml` (outline section 9).
3. Live `cloud-smoke` (with the OK to send), then the lock, then arm L one session a day.

## Things to check against the live API later (cannot be settled offline)
- Whether each endpoint accepts `response_format` of type `json_schema` with the wire schemas (else `json_object`).
- The name of the output-limit field each endpoint accepts, and whether reasoning tokens count against it.
- Whether Gemini's OpenAI-style endpoint accepts `seed` and `temperature: 0` (remove a field the endpoint refuses,
  record it in the lock).
- Where each response reports reasoning tokens in `usage`.
- The real free limits (the numbers in the config above are placeholders).
