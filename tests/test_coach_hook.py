"""The Stop hook's "something failed?" reminder must fire on real failure output, not on the word "failed" in prose."""
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "coach_hook.py"
FAILURE_TIP = "something failed?"


def stop_message(text, monkeypatch, capsys):
    """Run the hook's stop event on this message and return what it printed."""
    spec = importlib.util.spec_from_file_location("coach_hook", HOOK_PATH)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    monkeypatch.setattr(sys, "argv", ["coach_hook.py", "stop"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"last_assistant_message": text})))
    capsys.readouterr()
    hook.main()
    return capsys.readouterr().out


@pytest.mark.parametrize("text", [
    "Traceback (most recent call last):\n  File \"x.py\", line 1, in <module>",
    "Here is the output:\n    Traceback (most recent call last):",
    "2 failed, 340 passed in 28.1s",
    "=== 10 failed in 3.2s ===",
    "1 failed",
    "Error: dataset not cached",
    "The command printed:\n  Error: dataset not cached",
])
def test_real_failures_trigger_the_tip(text, monkeypatch, capsys):
    assert FAILURE_TIP in stop_message(text, monkeypatch, capsys)


@pytest.mark.parametrize("text", [
    "None of the 114 canaries failed.",
    "0 failed, 344 passed",
    "The clean run failed earlier, and I fixed it.",
    "A failed run goes to the graveyard.",
    "the tests failed yesterday",
    "A traceback would show here if something broke.",
    "The word error: appears mid-sentence, and so does Error: here.",
    "All 344 tests passed.",
])
def test_ordinary_prose_does_not_trigger_the_tip(text, monkeypatch, capsys):
    assert FAILURE_TIP not in stop_message(text, monkeypatch, capsys)


def test_mission_done_tip_still_works_when_prose_says_failed(monkeypatch, capsys):
    out = stop_message("Mission 2.1 is committed. None of the canaries failed.", monkeypatch, capsys)
    assert "mission done" in out
