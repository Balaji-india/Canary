"""The status-line tip must tell a finished batch from one that really stopped part-way."""
import importlib.util
import os
import time
from pathlib import Path

import pytest

STATE_PATH = Path(__file__).resolve().parent.parent / ".claude" / "coach_state.py"
STAMP = "2026-11-01T10:21:27+00:00"
PROGRESS = f"{STAMP} batch rq1-full: audit 179/180 flag [560 s so far]\n"
FINISHED = f"{STAMP} batch rq1-full: 180 audits stored, 0 failed, 0 runs with no results\n"
STOPPED = f"{STAMP} batch rq1-full: 12 audits stored, 0 failed, 0 runs with no results. STOPPED: model not available\n"
RESTARTED = f"{STAMP} batch next: 40 slots, 40 to run\n"


def load_state():
    spec = importlib.util.spec_from_file_location("coach_state", STATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state_of(tmp_path, text, age_seconds):
    """campaign_state for a log holding this text, last written this many seconds ago."""
    log = tmp_path / "data" / "runs" / "campaign.log"
    log.parent.mkdir(parents=True)
    log.write_text(text, encoding="utf-8")
    written = time.time() - age_seconds
    os.utime(log, (written, written))
    return load_state().campaign_state(tmp_path)


@pytest.mark.parametrize("text, age, expected", [
    (PROGRESS + FINISHED, 9999, None),                  # the reported bug: old and finished is not interrupted
    (PROGRESS + FINISHED, 5, None),                     # just finished is not running either
    (f"{STAMP} campaign finished\n", 9999, None),       # the wording the campaign loop was already expected to use
    (PROGRESS, 9999, "interrupted"),                    # died mid-batch
    (PROGRESS, 5, "running"),
    (PROGRESS + STOPPED, 9999, "interrupted"),          # gave up early, so it still needs resuming
    (FINISHED + RESTARTED, 9999, "interrupted"),        # an older finish still in the tail must not hide a new batch
    (FINISHED + RESTARTED, 5, "running"),
])
def test_campaign_state_reads_the_last_line(tmp_path, text, age, expected):
    assert state_of(tmp_path, text, age) == expected


def test_no_log_means_no_campaign(tmp_path):
    assert load_state().campaign_state(tmp_path) is None
