"""Shared test settings."""
import socket
import urllib.request

import pytest

from canary import llm, separation


@pytest.fixture(autouse=True)
def fewer_bootstrap_draws(monkeypatch):
    """200 draws instead of 2000 keeps the suite under 30 s (400 until decoys and the dev report added tests, 2026-11-09). Seeds are fixed, so results stay deterministic; tests
    check interval logic, not the third decimal of a real result."""
    monkeypatch.setattr(separation, "BOOTSTRAP_DRAWS", 200)


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network_no_keys(monkeypatch, tmp_path):
    """No test may reach the network, read the real .env or write the real call log (CLAUDE.md section 6).

    urllib's two entry points are blocked, and so is any socket connection that is not to this machine (the sandbox
    and asyncio may use local sockets). The key file and the call log point into the test's own folder.
    """
    def refuse(*args, **kwargs):
        raise NetworkBlocked("a test tried to open a network connection")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)
    real_connect = socket.socket.connect

    def local_only(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise NetworkBlocked(f"a test tried to connect to {host}")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    monkeypatch.setattr(llm, "ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr(llm, "CALL_LOG_PATH", tmp_path / "cloud" / "calls.jsonl")
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
