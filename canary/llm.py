"""The single doorway to every language model: roles, JSON output, retries, cache and the model queue.

Why one wrapper: callers ask for a *role* ("skeptic_a") and get checked JSON back. They never see a model name or
a provider, so moving a role to a cloud API means adding one Provider class and changing `config/models.yaml`.

Why the model switching lives here: 6 GB of VRAM fits one model. Every path to a model goes through
`LLM._prepare_model`, so no caller can end up with two models loaded by accident.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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
                 timeout_s: float, seed_offset: int = 0) -> str: ...

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
                 timeout_s: float, seed_offset: int = 0) -> str:
        # `format` makes Ollama constrain the output to the schema. num_ctx is set because Ollama silently cuts off
        # prompts longer than the context, and a reviewer must never judge a script it only partly saw.
        options = {"temperature": temperature, "seed": self.settings["seed"] + seed_offset,
                   "num_ctx": self.settings["num_ctx"],
                   "num_predict": self.settings["num_predict"]}
        try:
            reply = self._client(timeout_s).generate(model=model, prompt=prompt, system=system, format=schema,
                                                     think=False, stream=False, options=options)
        except Exception as exc:
            raise LLMError(f"{model}: {type(exc).__name__}: {exc}") from exc
        return reply.response

    def unload(self, model: str) -> None:
        try:
            self._client(30).generate(model=model, keep_alive=0)
        except Exception as exc:
            raise LLMError(f"{model}: could not unload: {exc}") from exc


PROVIDERS = {"ollama": OllamaProvider}


class Cache:
    """Replies stored in SQLite. Only valid replies are stored, so a failure is always tried again later."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, model TEXT, reply TEXT, "
                       "created REAL)")

    @staticmethod
    def key(model: str, prompt: str, system: str | None, schema: dict, temperature: float) -> str:
        """Hash everything that shapes the reply: the same prompt under another schema is a different question."""
        text = json.dumps([model, prompt, system, schema, temperature], sort_keys=True)
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
            if name not in PROVIDERS:
                raise LLMError(f"provider {name!r} is not supported (known: {sorted(PROVIDERS)})")
            self.providers[name] = PROVIDERS[name](self.settings)
        return self.providers[name]

    def resolve(self, role: str) -> tuple[str, str, float]:
        """Return (provider name, model, temperature) for a role, following aliases such as mutant_writer."""
        if role in self._resolved:
            return self._resolved[role]
        roles = self.cfg["roles"]
        if role not in roles:
            raise LLMError(f"unknown role {role!r}")
        target = roles[role].get("use_role", role)
        cfg = roles[target]
        provider = cfg.get("provider", self.cfg["provider"])
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

    def _check_prompt_size(self, prompt: str, system: str | None) -> None:
        """Refuse a prompt that might not fit, because Ollama would silently cut it instead of failing.

        A reviewer judging half a script is worse than no review. Three characters per token is a cautious estimate:
        real review prompts measured about 3.4.
        """
        limit = (self.settings["num_ctx"] - self.settings["num_predict"]) * 3
        size = len(prompt) + len(system or "")
        if size > limit:
            raise LLMError(f"prompt of {size} characters may not fit (limit {limit}); raise num_ctx in models.yaml",
                           KIND_PROMPT_TOO_LARGE)

    def call(self, role: str, prompt: str, schema: dict, system: str | None = None,
             refresh: bool = False) -> LLMResult:
        """Return checked JSON for a role, from the cache if possible. Raises LLMError when all attempts fail.

        `refresh=True` skips reading the cache but still stores the new reply.
        """
        provider_name, model, temperature = self.resolve(role)
        key = Cache.key(model, prompt, system, schema, temperature)
        started = time.perf_counter()
        if not refresh:
            stored = self.cache.get(key)
            if stored is not None:
                # A cache hit needs no model, so it must not trigger a model switch.
                return LLMResult(role, model, parse_reply(stored, schema), True, 0, time.perf_counter() - started)
        self._check_prompt_size(prompt, system)
        provider = self._provider(provider_name)
        attempts = self.settings["retries"] + 1
        text = prompt
        last_problem = ""
        last_kind = KIND_TIMEOUT_OR_SERVER
        for attempt in range(1, attempts + 1):
            timeout_s = self._prepare_model(provider_name, model)
            try:
                # A new seed per attempt: with the same seed a sampling failure (such as Ollama's "token repeat
                # limit") simply happens again. The attempt order stays fixed, so runs remain reproducible.
                reply = provider.generate(model, text, system, schema, temperature, timeout_s, attempt - 1)
                data = parse_reply(reply, schema)
            except InvalidReply as exc:
                # At temperature 0 the same prompt gives the same bad reply, so the retry must change the prompt.
                last_problem, last_kind = str(exc), KIND_INVALID_REPLY
                text = f"{prompt}\n\nYour previous reply was rejected: {exc}. Reply with only JSON that fits the schema."
            except LLMError as exc:
                last_problem, last_kind = str(exc), exc.kind
                self._loaded = None  # the model may not have loaded, so the next attempt counts as cold
            else:
                self.cache.put(key, model, reply)
                return LLMResult(role, model, data, False, attempt, time.perf_counter() - started)
        raise LLMError(f"role {role}, model {model}: gave up after {attempts} attempts: {last_problem}", last_kind)


class ModelQueue:
    """Collects requests, then runs them grouped by model, so models are never alternated request by request.

    Switching a model costs up to minutes on this laptop, so this ordering decides how long a campaign takes.
    """

    def __init__(self, llm: LLM):
        self.llm = llm
        self._requests: list[dict] = []

    def add(self, role: str, prompt: str, schema: dict, system: str | None = None, refresh: bool = False) -> int:
        """Queue a request and return its position in the list that run() returns."""
        self._requests.append({"role": role, "prompt": prompt, "schema": schema, "system": system, "refresh": refresh})
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
            for index in indexes:
                try:
                    results[index] = self.llm.call(**self._requests[index])
                except LLMError as exc:
                    results[index] = LLMResult(self._requests[index]["role"], model, error=str(exc), error_kind=exc.kind)
        self._requests = []
        return results
