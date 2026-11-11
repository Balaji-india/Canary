"""The single doorway to every language model: roles, JSON output, retries, cache and the model queue.

Why one wrapper: callers ask for a *role* ("skeptic_a") and get checked JSON back. They never see a model name or
a provider, so moving a role to a cloud API means adding one Provider class and changing `config/models.yaml`.

Why the model switching lives here: 6 GB of VRAM fits one model. Every path to a model goes through
`LLM._prepare_model`, so no caller can end up with two models loaded by accident.

Cloud roles (the ceiling check, docs/plans/cloud_ceiling_check_outline.md) go through `OpenAIStyleProvider`: one
POST request per attempt with the standard library, paced, rationed per day, and logged line by line. The key is read
by its variable name from `.env` at the first call and is never printed, logged or stored.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from canary import config

_SCHEMA_KEYWORDS = {"type", "enum", "required", "properties", "additionalProperties", "items", "minimum", "maximum",
                    "anyOf"}
_JSON_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    # bool is a subclass of int in Python, but true is not a number in JSON.
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


# Why a call failed. They mean different things for trust: an invalid reply is the reviewer's own failure, while a
# timeout or an unreachable server may be the machine's. Reports must keep them apart.
KIND_INVALID_REPLY = "invalid_reply"
KIND_TIMEOUT_OR_SERVER = "timeout_or_server"
KIND_PROMPT_TOO_LARGE = "prompt_too_large"
# Cloud kinds. A rate limit (the server's 429, or our own daily budget) and an access problem (bad key, no permission,
# model gone) say nothing about the reviewer: they depend on how many calls were made, or on the account. A config
# problem (a model off the allow-list) is the same: nothing about the run. These three stop the pass and leave no trace
# in the ledger (`STOP_KINDS`). A refused request (other 4xx) may be this run's content, so it is stored as a failed
# audit, like a server failure.
KIND_RATE_LIMITED = "rate_limited"
KIND_ACCESS = "access"
KIND_CONFIG = "config"
KIND_REQUEST_REFUSED = "request_refused"
STOP_KINDS = frozenset({KIND_RATE_LIMITED, KIND_ACCESS, KIND_CONFIG})
# Not retried inside one call: the same request would fail the same way and spend daily quota. Running the command
# again is the retry (the ceiling check's "retried once" rule).
NO_RETRY_KINDS = STOP_KINDS | {KIND_REQUEST_REFUSED}

ENV_PATH = config.ROOT / ".env"  # read at call time, so tests can point it elsewhere
CALL_LOG_PATH = config.DATA_DIR / "cloud" / "calls.jsonl"  # data/ is in .gitignore
USER_AGENT = "canary-research/0.1"  # urllib's default agent is blocked by some API front ends; nothing personal here
DAY_S = 24 * 3600
OPTION_KEYS = {"reasoning_effort", "max_output_tokens"}  # per-role cloud options; any other key is a typo, refused
SCHEMA_MODES = ("json_schema", "json_object")


class LLMError(RuntimeError):
    """A model could not give a valid answer, or could not be reached."""

    def __init__(self, message: str, kind: str = KIND_TIMEOUT_OR_SERVER):
        super().__init__(message)
        self.kind = kind


class InvalidReply(ValueError):
    """The model answered, but not with JSON that fits the schema. The message is shown to it on the retry."""


def schema_problem(value: object, schema: dict, path: str = "$") -> str | None:
    """Return the first way `value` breaks `schema`, or None if it fits.

    Covers the small JSON Schema subset that Canary uses. An unsupported keyword raises instead of being ignored,
    because a rule that is silently not enforced would let a malformed reviewer verdict through.
    """
    unknown = set(schema) - _SCHEMA_KEYWORDS
    if unknown:
        raise ValueError(f"unsupported schema keywords: {sorted(unknown)}")
    if "anyOf" in schema:
        problems = [schema_problem(value, option, path) for option in schema["anyOf"]]
        if all(problems):
            return f"{path} fits none of the allowed forms; closest: {min(problems, key=len)}"
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_JSON_TYPES[name](value) for name in allowed):
            return f"{path} must be {' or '.join(allowed)}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} must be one of {schema['enum']}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path} must be at least {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path} must be at most {schema['maximum']}"
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                return f"{path} is missing {key!r}"
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                return f"{path} has unexpected keys {extra}"
        for key, subschema in properties.items():
            if key in value:
                problem = schema_problem(value[key], subschema, f"{path}.{key}")
                if problem:
                    return problem
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            problem = schema_problem(item, schema["items"], f"{path}[{i}]")
            if problem:
                return problem
    return None


def parse_reply(text: str, schema: dict) -> object:
    """Turn a model's reply into checked data, or raise InvalidReply.

    Reasoning blocks and code fences are removed, and what remains must be exactly one JSON value. It does not
    hunt for JSON inside prose: a reply holding two candidate verdicts would make the choice of verdict a guess.
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    try:
        value = json.loads(cleaned)
    except ValueError as exc:
        raise InvalidReply(f"not valid JSON ({exc})") from exc
    problem = schema_problem(value, schema)
    if problem:
        raise InvalidReply(problem)
    return value


class Provider(Protocol):
    """What a model backend must offer. Add a cloud API by implementing this and registering it in PROVIDERS."""

    def installed_models(self) -> set[str]: ...

    def generate(self, model: str, prompt: str, system: str | None, schema: dict, temperature: float,
                 timeout_s: float, seed_offset: int = 0, num_ctx: int | None = None,
                 top_logprobs: int = 0) -> str | tuple[str, list[dict]]: ...

    def unload(self, model: str) -> None: ...


class OllamaProvider:
    """Local models through the Ollama server. Any client failure is raised as LLMError."""

    def __init__(self, settings: dict):
        self.settings = settings

    def _client(self, timeout_s: float):
        import ollama  # imported here so that code which never calls a model does not pay for the import

        return ollama.Client(timeout=timeout_s)

    def installed_models(self) -> set[str]:
        try:
            return {m.model for m in self._client(10).list().models}
        except Exception as exc:  # the client raises several types when the server is down
            raise LLMError(f"Ollama server not reachable: {exc}") from exc

    def generate(self, model: str, prompt: str, system: str | None, schema: dict, temperature: float,
                 timeout_s: float, seed_offset: int = 0, num_ctx: int | None = None,
                 top_logprobs: int = 0) -> str | tuple[str, list[dict]]:
        """Return the reply text, or (text, token probabilities) when `top_logprobs` is above 0.

        Ollama reports each token's probability under the model before the schema constrains it, with the
        `top_logprobs` most likely alternatives. Only `token`, `logprob` and `bytes` are kept.
        """
        # `format` makes Ollama constrain the output to the schema. num_ctx is set because Ollama silently cuts off
        # prompts longer than the context, and a reviewer must never judge a script it only partly saw.
        options = {"temperature": temperature, "seed": self.settings["seed"] + seed_offset,
                   "num_ctx": num_ctx or self.settings["num_ctx"],
                   "num_predict": self.settings["num_predict"]}
        extra = {"logprobs": True, "top_logprobs": top_logprobs} if top_logprobs else {}
        try:
            reply = self._client(timeout_s).generate(model=model, prompt=prompt, system=system, format=schema,
                                                     think=False, stream=False, options=options, **extra)
        except Exception as exc:
            raise LLMError(f"{model}: {type(exc).__name__}: {exc}") from exc
        if not top_logprobs:
            return reply.response
        return reply.response, [_compact(t) for t in (getattr(reply, "logprobs", None) or [])]

    def unload(self, model: str) -> None:
        try:
            self._client(30).generate(model=model, keep_alive=0)
        except Exception as exc:
            raise LLMError(f"{model}: could not unload: {exc}") from exc


def _field(item, key: str):
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


def _compact(token) -> dict:
    """One token's probabilities as plain data, from the client's object or a dict.

    `bytes` is kept only when reported: the ollama client (0.6.3) drops it, and an empty list would read as zero bytes.
    """
    def item(t) -> dict:
        out = {"token": _field(t, "token"), "logprob": _field(t, "logprob")}
        if _field(t, "bytes"):
            out["bytes"] = list(_field(t, "bytes"))
        return out

    return {**item(token), "top_logprobs": [item(a) for a in (_field(token, "top_logprobs") or [])]}


# ---- cloud: OpenAI-style chat endpoints (Groq, Gemini's OpenAI endpoint, Azure, OpenRouter) ------------------------

def read_key(name: str) -> str | None:
    """The key stored under the variable `name`, from the environment or `.env`. Callers must never print it.

    `dotenv_values` reads the file without copying it into the environment, so no child process inherits the key.
    """
    value = os.environ.get(name)
    if value:
        return value
    if ENV_PATH.exists():
        from dotenv import dotenv_values  # imported here: only cloud roles need it

        return dotenv_values(ENV_PATH).get(name) or None
    return None


def _sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _typed_enums(schema: object) -> object:
    """Every enum of strings gains `"type": "string"`: strict JSON-schema modes want a type on every value."""
    if isinstance(schema, list):
        return [_typed_enums(v) for v in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: (v if k == "enum" else _typed_enums(v)) for k, v in schema.items()}
    if "enum" in out and "type" not in out and all(isinstance(v, str) for v in out["enum"]):
        out["type"] = "string"
    return out


def wire_schema(schema: dict) -> dict:
    """What is sent to a cloud endpoint in place of a review schema.

    Strict JSON-schema modes refuse an `anyOf` at the top level, and the baseline schema is one (a pass form and a flag
    form). Its options have the same property names in the same order, so they become one flat object: per property,
    enums are merged in option order and differing forms go under a nested `anyOf`. Every reply that fits the original
    also fits this one; the reverse does not hold (a pass that names a bug fits here), which is why the wrapper still
    checks every reply against the original schema with `parse_reply`.
    """
    if set(schema) != {"anyOf"}:
        return _typed_enums(schema)
    options = schema["anyOf"]
    names = [list(o.get("properties", {})) for o in options]
    if (any(o.get("type") != "object" or o.get("additionalProperties") is not False for o in options)
            or any(n != names[0] for n in names) or any(o.get("required") != options[0].get("required") for o in options)):
        raise ValueError("wire_schema: top-level anyOf options must be closed objects with the same properties")
    properties = {}
    for name in names[0]:
        forms = [o["properties"][name] for o in options]
        if all(set(f) == {"enum"} for f in forms):
            merged: list = []
            for f in forms:
                merged += [v for v in f["enum"] if v not in merged]
            properties[name] = {"enum": merged}
        else:
            distinct: list = []
            for f in forms:
                if f not in distinct:
                    distinct.append(f)
            properties[name] = distinct[0] if len(distinct) == 1 else {"anyOf": distinct}
    return _typed_enums({"type": "object", "required": options[0]["required"], "additionalProperties": False,
                         "properties": properties})


def build_request(entry: dict, model: str, prompt: str, system: str | None, schema: dict, temperature: float,
                  seed: int, options: dict | None = None) -> dict:
    """The JSON body of one chat request. Pure: no I/O, so the exact request can be shown and tested.

    Token probabilities are never asked for: Groq answers 400 to `logprobs`, and Gemini's are not usable.
    """
    options = options or {}
    unknown = set(options) - OPTION_KEYS
    if unknown:
        raise LLMError(f"unknown cloud options {sorted(unknown)} (known: {sorted(OPTION_KEYS)})", KIND_CONFIG)
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body: dict = {"model": model, "messages": messages, "temperature": temperature, "seed": seed, "stream": False}
    if "max_output_tokens" in options:
        body[entry.get("max_tokens_field", "max_tokens")] = options["max_output_tokens"]
    if "reasoning_effort" in options:
        body["reasoning_effort"] = options["reasoning_effort"]
    mode = entry.get("schema_mode", "json_schema")
    if mode == "json_schema":
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "reply", "strict": True, "schema": wire_schema(schema)}}
    elif mode == "json_object":
        # Fallback for an endpoint without schema mode: JSON only. The prompts already say "Reply as JSON" and list the
        # fields, and parse_reply checks the reply against the full schema exactly as in schema mode.
        body["response_format"] = {"type": "json_object"}
    else:
        raise LLMError(f"unknown schema_mode {mode!r} (known: {', '.join(SCHEMA_MODES)})", KIND_CONFIG)
    return body


_REASONING_TEXT = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL)


def read_reply(body: dict) -> str:
    """The reply text of a chat response: `choices[0].message.content`, with any reasoning removed.

    Reasoning models put their reasoning in a separate field (`reasoning`, `reasoning_content`), which is ignored here
    (it stays in the call log), or inline in tags, which are cut out. What remains goes to the strict `parse_reply`.
    An empty, cut-off or filtered reply is the reviewer's failure on that run and raises InvalidReply with the reason.
    """
    try:
        choice = body["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"response without choices[0].message ({type(exc).__name__})") from exc
    reason = choice.get("finish_reason")
    if reason in ("length", "content_filter"):
        raise InvalidReply(f"reply cut off or filtered (finish_reason {reason})")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise InvalidReply("empty reply")
    return _REASONING_TEXT.sub("", content).strip()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would resend the Authorization header to wherever it points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def urllib_transport(url: str, headers: dict, body: bytes, timeout_s: float) -> tuple[int, dict, bytes]:
    """POST `body` and return (status, lower-cased headers, body). An HTTP error status is a normal result here."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(request, timeout=timeout_s) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:  # before URLError, which it subclasses
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read()
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise LLMError(f"not reachable: {type(exc).__name__}: {exc}", KIND_TIMEOUT_OR_SERVER) from exc


def _usage(text: str) -> dict:
    """Token counts, the model the server named, the response ID and the finish reason, when the body has them."""
    try:
        body = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(body, dict):
        return {}
    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    choices = body.get("choices") or [{}]
    return {"server_model": body.get("model"), "response_id": body.get("id"),
            "finish_reason": choices[0].get("finish_reason") if isinstance(choices[0], dict) else None,
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"), "reasoning_tokens": details.get("reasoning_tokens")}


REQUIRED_PROVIDER_KEYS = ("kind", "base_url", "key_env", "models")


class OpenAIStyleProvider:
    """One cloud endpoint that speaks the OpenAI chat format, configured by an entry of `providers:` in models.yaml.

    Before each request: the daily budget is checked against the call log (calls and tokens in the last 24 hours, kept
    below the provider's own limits), then the pause since the last request is kept. A 429 with a short `retry-after`
    is waited out once; otherwise the pass stops with `rate_limited`, which is never stored against the reviewer.
    Every HTTP attempt is appended to the call log before its status is acted on, so failures are in it too.
    `transport`, `clock` and `sleep` are injected so tests never touch the network or wait.
    """

    def __init__(self, settings: dict, entry: dict, name: str, transport: Callable | None = None,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
                 log_path: Path | None = None):
        missing = [k for k in REQUIRED_PROVIDER_KEYS if k not in entry]
        if missing:
            raise LLMError(f"provider {name}: models.yaml entry lacks {missing}", KIND_CONFIG)
        if entry.get("schema_mode", "json_schema") not in SCHEMA_MODES:
            raise LLMError(f"provider {name}: unknown schema_mode {entry['schema_mode']!r}", KIND_CONFIG)
        self.settings, self.entry, self.name = settings, entry, name
        self.base_url = entry["base_url"].rstrip("/")
        self.transport = transport or urllib_transport
        self.clock, self.sleep = clock, sleep
        self.log_path = log_path
        self._history: list[dict] | None = None  # logged attempts of this provider: time, model, tokens

    def installed_models(self) -> set[str]:
        """The allow-list: no network call, and any other model is refused (the $0 guard against a typo)."""
        return set(self.entry["models"])

    def unload(self, model: str) -> None:
        """Nothing to unload: the model lives on the provider's servers."""

    def _log_file(self) -> Path:
        return self.log_path or CALL_LOG_PATH

    def _attempts(self) -> list[dict]:
        """This provider's logged attempts, read from the log once (so a restarted command still knows today's calls)."""
        if self._history is None:
            self._history = []
            path = self._log_file()
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if record.get("provider") == self.name:
                        self._history.append({"t": record["t_epoch"], "model": record["model"],
                                              "tokens": record.get("total_tokens") or 0})
        return self._history

    def _check_budget(self, model: str, prompt_chars: int, options: dict) -> None:
        """Stop before a request that would go over our daily budget. No network call is made when it stops.

        The window is the last 24 hours, which is never looser than a reset at midnight. The token check counts the
        next request at its worst case (the prompt at three characters per token plus the full output limit).
        """
        now = self.clock()
        recent = [a for a in self._attempts() if a["model"] == model and now - a["t"] < DAY_S]
        calls_cap = self.entry.get("max_calls_per_day")
        tokens_cap = self.entry.get("max_tokens_per_day")
        used = sum(a["tokens"] for a in recent)
        next_tokens = prompt_chars // 3 + int(options.get("max_output_tokens", 0))
        reason = None
        if calls_cap is not None and len(recent) >= calls_cap:
            reason = f"{len(recent)} calls in the last 24 h, our budget is {calls_cap}"
        elif tokens_cap is not None and used + next_tokens > tokens_cap:
            reason = f"{used} tokens in the last 24 h plus up to {next_tokens} for the next call, our budget is {tokens_cap}"
        if reason:
            resume = datetime.fromtimestamp(min(a["t"] for a in recent) + DAY_S, timezone.utc) if recent else None
            when = f" Budget frees up from {resume:%Y-%m-%d %H:%M} UTC." if resume else ""
            raise LLMError(f"{self.name} {model}: daily limit reached ({reason}).{when} Run the same command again "
                           f"after that; nothing was stored against the reviewer.", KIND_RATE_LIMITED)

    def _pace(self) -> None:
        """Keep `min_interval_s` between this provider's requests (minute limits on requests and tokens)."""
        interval = self.entry.get("min_interval_s") or 0
        attempts = self._attempts()
        if interval and attempts:
            wait = max(a["t"] for a in attempts) + interval - self.clock()
            if wait > 0:
                self.sleep(wait)

    def _headers(self, key: str) -> dict:
        auth = ({"api-key": key} if self.entry.get("auth_header") == "api-key"  # Azure's key header
                else {"Authorization": f"Bearer {key}"})
        return {**auth, "Content-Type": "application/json", "User-Agent": USER_AGENT}

    def _record(self, record: dict) -> None:
        """Append one attempt to the call log. Never a key or a request header: only what is passed in `record`."""
        path = self._log_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        self._attempts().append({"t": record["t_epoch"], "model": record["model"],
                                 "tokens": record.get("total_tokens") or 0})

    def generate(self, model: str, prompt: str, system: str | None, schema: dict, temperature: float,
                 timeout_s: float, seed_offset: int = 0, num_ctx: int | None = None, top_logprobs: int = 0,
                 role: str | None = None, options: dict | None = None) -> str:
        """Send one chat request (two if a short 429 is waited out) and return the reply text."""
        if top_logprobs:
            raise LLMError(f"{self.name}: cloud roles never ask for token probabilities (set top_logprobs: 0)",
                           KIND_CONFIG)
        if model not in self.entry["models"]:
            raise LLMError(f"{self.name}: model {model!r} is not on the allow-list {self.entry['models']}", KIND_CONFIG)
        options = options or {}
        body = build_request(self.entry, model, prompt, system, schema, temperature,
                             self.settings["seed"] + seed_offset, options)
        key = read_key(self.entry["key_env"])
        if not key:
            raise LLMError(f"{self.name}: {self.entry['key_env']} is not set in .env", KIND_ACCESS)

        def scrub(text: str) -> str:  # a provider could echo the key in an error body
            return text.replace(key, "[key]")

        payload = json.dumps(body).encode("utf-8")
        url = f"{self.base_url}/chat/completions"
        mode = self.entry.get("schema_mode", "json_schema")
        base = {"provider": self.name, "role": role, "model": model, "temperature": temperature, "seed": body["seed"],
                "reasoning_effort": body.get("reasoning_effort"), "max_output_tokens": options.get("max_output_tokens"),
                "schema_mode": mode,
                "wire_schema_sha256": _sha256_json(wire_schema(schema)) if mode == "json_schema" else None,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "system_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest() if system else None}
        for attempt in (1, 2):
            self._check_budget(model, len(prompt) + len(system or ""), options)
            self._pace()
            started = self.clock()
            record = {"time": datetime.fromtimestamp(started, timezone.utc).isoformat(), "t_epoch": started, **base}
            try:
                status, headers, raw = self.transport(url, self._headers(key), payload, timeout_s)
            except LLMError as exc:
                self._record({**record, "status": None, "seconds": round(self.clock() - started, 3),
                              "error": scrub(str(exc))})
                raise LLMError(f"{self.name}: {scrub(str(exc))}", exc.kind) from None
            text = scrub(raw.decode("utf-8", errors="replace"))
            limits = {k: v for k, v in headers.items() if k == "retry-after" or k.startswith("x-ratelimit")}
            self._record({**record, "status": status, "seconds": round(self.clock() - started, 3),
                          "rate_limit_headers": limits, **_usage(text), "response_body": text})
            if status == 429:
                wait = _retry_after(headers)
                if attempt == 1 and wait is not None and wait <= self.entry.get("max_wait_s", 0):
                    self.sleep(wait)
                    continue
                raise LLMError(f"{self.name} {model}: rate limit (HTTP 429, retry-after {wait}, limits {limits}): "
                               f"{_cut(text)}. Run the same command again after the reset; nothing was stored "
                               f"against the reviewer.", KIND_RATE_LIMITED)
            return self._reply(status, text)
        raise AssertionError("unreachable")  # pragma: no cover

    def _reply(self, status: int, text: str) -> str:
        """Map a status to the reply text or to an error of the right kind (see the KIND_ constants)."""
        if status == 200:
            try:
                body = json.loads(text)
            except ValueError:
                raise LLMError(f"{self.name}: HTTP 200 but the body is not JSON: {_cut(text)}") from None
            return read_reply(body)
        if status in (401, 403, 404) or 300 <= status < 400:
            raise LLMError(f"{self.name}: HTTP {status} (bad key, no permission, moved or model gone): {_cut(text)}",
                           KIND_ACCESS)
        if 400 <= status < 500:
            raise LLMError(f"{self.name}: request refused, HTTP {status}: {_cut(text)} (if this names response_format "
                           f"or json_schema, set schema_mode: json_object for {self.name} in models.yaml)",
                           KIND_REQUEST_REFUSED)
        raise LLMError(f"{self.name}: server error HTTP {status}: {_cut(text)}")


def _retry_after(headers: dict) -> float | None:
    try:
        return float(headers["retry-after"])
    except (KeyError, TypeError, ValueError):
        return None


def _cut(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + " ..."


PROVIDERS = {"ollama": OllamaProvider, "openai_style": OpenAIStyleProvider}


class Cache:
    """Replies stored in SQLite. Only valid replies are stored, so a failure is always tried again later."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, model TEXT, reply TEXT, "
                       "created REAL)")

    @staticmethod
    def key(model: str, prompt: str, system: str | None, schema: dict, temperature: float,
            endpoint: dict | None = None) -> str:
        """Hash everything that shapes the reply: the same prompt under another schema is a different question.

        `endpoint` (cloud roles: provider, base URL, options such as reasoning effort) is hashed only when given, so
        every key stored before cloud roles existed stays exactly as it was. Two roles on one cloud model at different
        reasoning effort, or the same model name on two providers, therefore never share a reply.
        """
        parts = [model, prompt, system, schema, temperature] + ([endpoint] if endpoint else [])
        text = json.dumps(parts, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, key: str) -> str | None:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT reply FROM llm_cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, model: str, reply: str) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?, ?)", (key, model, reply, time.time()))


@dataclass(frozen=True)
class LLMResult:
    """One answer. `error` is only ever set on results from ModelQueue, where one failure must not stop the batch."""

    role: str
    model: str | None
    data: object = None
    cached: bool = False
    attempts: int = 0
    seconds: float = 0.0
    error: str | None = None
    error_kind: str | None = None
    logprobs: list[dict] | None = None  # only when asked for; never stored in the cache


class LLM:
    def __init__(self, models_cfg: dict | None = None, providers: dict[str, Provider] | None = None,
                 cache_path: Path = config.DB_PATH):
        self.cfg = models_cfg or config.load_yaml("models.yaml")
        clashes = config.family_clashes(self.cfg)
        if clashes:
            raise LLMError(f"same model family as the Scientist: {clashes}")
        self.settings = self.cfg["llm"]
        self.providers = providers if providers is not None else {}
        self.cache = Cache(cache_path)
        self._loaded: tuple[str, str] | None = None  # (provider name, model) believed to be in memory
        self._resolved: dict[str, tuple[str, str, float]] = {}

    def _provider(self, name: str) -> Provider:
        if name not in self.providers:
            cloud = self.cfg.get("providers") or {}
            if name in cloud:
                kind = cloud[name].get("kind")
                if kind not in PROVIDERS:
                    raise LLMError(f"provider {name}: kind {kind!r} is not supported (known: {sorted(PROVIDERS)})",
                                   KIND_CONFIG)
                self.providers[name] = PROVIDERS[kind](self.settings, cloud[name], name)
            elif name not in PROVIDERS:
                raise LLMError(f"provider {name!r} is not supported (known: {sorted(PROVIDERS)})")
            else:
                self.providers[name] = PROVIDERS[name](self.settings)
        return self.providers[name]

    def target_cfg(self, role: str) -> dict:
        """The settings of the role an alias points to (the role's own settings if it is not an alias)."""
        roles = self.cfg["roles"]
        return roles[roles[role].get("use_role", role)]

    def cloud_entry(self, role: str) -> dict | None:
        """The `providers:` entry a role runs on, or None for a local (Ollama) role."""
        provider = self.target_cfg(role).get("provider", self.cfg["provider"])
        return (self.cfg.get("providers") or {}).get(provider)

    def options(self, role: str) -> dict:
        """Per-role cloud options (`options:` on the role or the role its alias points to), e.g. reasoning effort."""
        roles = self.cfg["roles"]
        return dict(roles[role].get("options") or self.target_cfg(role).get("options") or {})

    def resolve(self, role: str) -> tuple[str, str, float]:
        """Return (provider name, model, temperature) for a role, following aliases such as mutant_writer.

        A cloud role gets its configured model exactly (no `:latest` tag, no fallback, no network call), and only if
        it is on that provider's allow-list.
        """
        if role in self._resolved:
            return self._resolved[role]
        roles = self.cfg["roles"]
        if role not in roles:
            raise LLMError(f"unknown role {role!r}", KIND_CONFIG)
        target = roles[role].get("use_role", role)
        cfg = roles[target]
        provider = cfg.get("provider", self.cfg["provider"])
        entry = self.cloud_entry(role)
        if entry is not None:
            if cfg["model"] not in entry["models"]:
                raise LLMError(f"role {role}: model {cfg['model']!r} is not on {provider}'s allow-list "
                               f"{entry['models']}", KIND_CONFIG)
            self._resolved[role] = (provider, cfg["model"], cfg["temperature"])
            return self._resolved[role]
        installed = self._provider(provider).installed_models()
        choice = config.resolve_roles({"roles": {target: cfg}}, installed)[0]
        if choice.model is None:
            raise LLMError(f"role {role}: neither {choice.preferred} nor {choice.fallback} is installed")
        self._resolved[role] = (provider, choice.model, cfg["temperature"])
        return self._resolved[role]

    def _prepare_model(self, provider: str, model: str) -> float:
        """Unload the previous model if it differs, and return the timeout to use for this call.

        A model not yet in memory gets the longer timeout: a first prompt took over 110 s on this laptop.
        """
        if self._loaded == (provider, model):
            return self.settings["timeout_warm_s"]
        self.release()
        self._loaded = (provider, model)
        return self.settings["timeout_cold_s"]

    def release(self) -> None:
        """Free the loaded model. Best effort: if this fails, Ollama still evicts it when memory runs short."""
        if self._loaded is not None:
            provider, model = self._loaded
            self._loaded = None
            try:
                self._provider(provider).unload(model)
            except LLMError:
                pass

    def num_ctx(self, role: str) -> int:
        """The context size for a role: its own `num_ctx` (set on the role an alias points to), else the global one.

        A per-role size lets a larger model fit the 6 GB card with a smaller KV cache.
        """
        roles = self.cfg["roles"]
        target = roles[role].get("use_role", role)
        return roles[target].get("num_ctx", self.settings["num_ctx"])

    def _check_prompt_size(self, prompt: str, system: str | None, num_ctx: int | None = None,
                           role: str | None = None) -> None:
        """Refuse a prompt that might not fit, because Ollama would silently cut it instead of failing.

        A reviewer judging half a script is worse than no review. Three characters per token is a cautious estimate:
        real review prompts measured about 3.4. A cloud role uses its provider's `context_tokens` minus the role's
        output limit (reasoning tokens count against that limit), so an endpoint that cuts or refuses long prompts is
        never sent one.
        """
        entry = self.cloud_entry(role) if role else None
        if entry is not None:
            if "context_tokens" not in entry:
                raise LLMError(f"role {role}: its provider has no context_tokens in models.yaml", KIND_CONFIG)
            limit = (entry["context_tokens"] - int(self.options(role).get("max_output_tokens", 0))) * 3
        else:
            limit = ((num_ctx or self.settings["num_ctx"]) - self.settings["num_predict"]) * 3
        size = len(prompt) + len(system or "")
        if size > limit:
            raise LLMError(f"prompt of {size} characters may not fit (limit {limit}); raise num_ctx in models.yaml",
                           KIND_PROMPT_TOO_LARGE)

    def call(self, role: str, prompt: str, schema: dict, system: str | None = None,
             refresh: bool = False, top_logprobs: int = 0, cache_write: bool = True) -> LLMResult:
        """Return checked JSON for a role, from the cache if possible. Raises LLMError when all attempts fail.

        `refresh=True` skips reading the cache but still stores the new reply. `top_logprobs` above 0 also returns
        token probabilities. The cache holds reply text only, so such a call always asks the model; the reply is
        the same at temperature 0, and the cache key does not change. `cache_write=False` leaves the cache untouched,
        for re-asking a question whose stored answer must not be replaced (rescoring).
        """
        provider_name, model, temperature = self.resolve(role)
        entry = self.cloud_entry(role)
        endpoint = None
        if entry is not None:  # everything that shapes a cloud request beyond the prompt, schema and temperature
            endpoint = {"provider": provider_name, "base_url": entry["base_url"], "options": self.options(role),
                        "schema_mode": entry.get("schema_mode", "json_schema")}
        key = Cache.key(model, prompt, system, schema, temperature, endpoint)
        started = time.perf_counter()
        if not refresh and not top_logprobs:
            stored = self.cache.get(key)
            if stored is not None:
                # A cache hit needs no model, so it must not trigger a model switch.
                return LLMResult(role, model, parse_reply(stored, schema), True, 0, time.perf_counter() - started)
        num_ctx = self.num_ctx(role)
        self._check_prompt_size(prompt, system, num_ctx, role)
        provider = self._provider(provider_name)
        extra = {}  # sent only when used, so providers without these options keep working
        if num_ctx != self.settings["num_ctx"]:
            extra["num_ctx"] = num_ctx
        if top_logprobs:
            extra["top_logprobs"] = top_logprobs
        if entry is not None:
            extra.update(role=role, options=self.options(role))  # the call log names the role; options shape the request
        attempts = self.settings["retries"] + 1
        text = prompt
        last_problem = ""
        last_kind = KIND_TIMEOUT_OR_SERVER
        for attempt in range(1, attempts + 1):
            timeout_s = self._prepare_model(provider_name, model)
            if entry is not None and entry.get("timeout_s"):
                timeout_s = entry["timeout_s"]  # cloud: no model load, but a long reasoning reply; a timeout costs quota
            try:
                # A new seed per attempt: with the same seed a sampling failure (such as Ollama's "token repeat
                # limit") simply happens again. The attempt order stays fixed, so runs remain reproducible.
                reply = provider.generate(model, text, system, schema, temperature, timeout_s, attempt - 1, **extra)
                logprobs = None
                if top_logprobs:
                    reply, logprobs = reply
                data = parse_reply(reply, schema)
            except InvalidReply as exc:
                # At temperature 0 the same prompt gives the same bad reply, so the retry must change the prompt.
                last_problem, last_kind = str(exc), KIND_INVALID_REPLY
                text = f"{prompt}\n\nYour previous reply was rejected: {exc}. Reply with only JSON that fits the schema."
            except LLMError as exc:
                if exc.kind in NO_RETRY_KINDS:  # the same request would fail the same way and spend daily quota
                    raise LLMError(f"role {role}, model {model}: {exc}", exc.kind) from None
                last_problem, last_kind = str(exc), exc.kind
                self._loaded = None  # the model may not have loaded, so the next attempt counts as cold
            else:
                if cache_write:
                    self.cache.put(key, model, reply)
                return LLMResult(role, model, data, False, attempt, time.perf_counter() - started, logprobs=logprobs)
        raise LLMError(f"role {role}, model {model}: gave up after {attempts} attempts: {last_problem}", last_kind)


class ModelQueue:
    """Collects requests, then runs them grouped by model, so models are never alternated request by request.

    Switching a model costs up to minutes on this laptop, so this ordering decides how long a campaign takes.
    """

    def __init__(self, llm: LLM):
        self.llm = llm
        self._requests: list[dict] = []

    def add(self, role: str, prompt: str, schema: dict, system: str | None = None, refresh: bool = False,
            top_logprobs: int = 0) -> int:
        """Queue a request and return its position in the list that run() returns."""
        request = {"role": role, "prompt": prompt, "schema": schema, "system": system, "refresh": refresh}
        if top_logprobs:
            request["top_logprobs"] = top_logprobs
        self._requests.append(request)
        return len(self._requests) - 1

    def run(self) -> list[LLMResult]:
        """Run everything and return results in the order they were added. A failure is stored in that result."""
        results: list[LLMResult | None] = [None] * len(self._requests)
        groups: dict[str, list[int]] = {}  # dicts keep insertion order, so models run in first-requested order
        for index, request in enumerate(self._requests):
            try:
                groups.setdefault(self.llm.resolve(request["role"])[1], []).append(index)
            except LLMError as exc:
                results[index] = LLMResult(request["role"], None, error=str(exc), error_kind=exc.kind)
        for model, indexes in groups.items():
            stop: LLMError | None = None  # after a stop kind (daily limit, access), the rest of this model is not asked
            for index in indexes:
                try:
                    if stop is not None:
                        raise stop
                    results[index] = self.llm.call(**self._requests[index])
                except LLMError as exc:
                    if exc.kind in STOP_KINDS:
                        stop = exc
                    results[index] = LLMResult(self._requests[index]["role"], model, error=str(exc), error_kind=exc.kind)
        self._requests = []
        return results
