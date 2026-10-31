"""Run a generated experiment in a subprocess and record exactly what happened.

Why a subprocess: a crash, a hang or a memory blow-up in an experiment must not take the campaign down with it.
Every attempt leaves a run_record.json, including failures, because the crash rate is itself a reported result.

This is isolation against accidents, not a security boundary: the script runs as the same user and could still
reach the network or other files. Scripts only come from our own template, so that is acceptable for now.
"""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from canary import codegen
from canary.config import DATA_DIR, load_yaml

RUNS_DIR = DATA_DIR / "runs"
DEFAULT_TIMEOUT_S = load_yaml("campaign.yaml")["sandbox_timeout_s"]
STDERR_TAIL_CHARS = 2000
RESULTS_NAME = "results.json"
RECORD_NAME = "run_record.json"

# Status values of a run record. Only STATUS_OK has a usable results.json.
STATUS_OK = "ok"
STATUS_CRASH = "crash"
STATUS_TIMEOUT = "timeout"
STATUS_INVALID_RESULTS = "invalid_results"
STATUS_INVALID_CONFIG = "invalid_config"

# The only environment passed on, so API keys in the parent's environment never reach an experiment.
_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LANG")


@dataclass(frozen=True)
class ScriptOutcome:
    """How a script's process ended. returncode is None when it was killed on timeout."""

    timed_out: bool
    returncode: int | None
    stderr_tail: str
    seconds: float


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the script and anything it started: killing only the parent would leave worker processes running."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30)
    else:
        os.killpg(proc.pid, signal.SIGKILL)
    proc.kill()  # harmless if already dead; makes sure the parent is gone even if taskkill failed


def run_script(script: Path, cwd: Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> ScriptOutcome:
    """Run a script with the current Python in its own working directory.

    Output goes to files, not pipes: a leftover child process holding a pipe open can make the wait hang forever,
    which would defeat the timeout. `-I` keeps the working directory off sys.path and ignores PYTHON* variables.
    """
    env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
    started = time.perf_counter()
    with (cwd / "stdout.log").open("wb") as out, (cwd / "stderr.log").open("wb") as err:
        proc = subprocess.Popen([sys.executable, "-I", script.name], cwd=cwd, env=env, stdout=out, stderr=err,
                                start_new_session=os.name != "nt")
        try:
            returncode = proc.wait(timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.wait(timeout=30)
            returncode, timed_out = None, True
    stderr = (cwd / "stderr.log").read_text(encoding="utf-8", errors="replace")
    return ScriptOutcome(timed_out, returncode, stderr[-STDERR_TAIL_CHARS:], time.perf_counter() - started)


def _is_metric_list(values: object, length: int) -> bool:
    return (isinstance(values, list) and len(values) == length
            and all(type(v) is float and math.isfinite(v) and 0 <= v <= 1 for v in values))


def validate_results(results: object, config: dict) -> str | None:
    """Return a problem description, or None when results.json has the fixed schema and matches the config.

    This checks shape only. Whether the numbers are honest is the job of the Skeptic and the tripwires.
    """
    expected = {"schema_version", "dataset", "metric", "seeds", "control", "treatment", "class_balance",
                "split_sizes", "runtime_seconds"}
    if not isinstance(results, dict) or set(results) != expected:
        return f"keys must be exactly {sorted(expected)}"
    if results["schema_version"] != 1:
        return f"unknown schema_version {results['schema_version']!r}"
    for key in ("dataset", "metric", "seeds"):
        if results[key] != config[key]:
            return f"{key} is {results[key]!r} but the config says {config[key]!r}"
    n_seeds = len(config["seeds"])
    for arm in ("control", "treatment"):
        if not _is_metric_list(results[arm], n_seeds):
            return f"{arm} must hold {n_seeds} finite metric values between 0 and 1"
    balance = results["class_balance"]
    if not isinstance(balance, dict) or not balance or not all(type(c) is int and c > 0 for c in balance.values()):
        return "class_balance must map each class to a positive count"
    sizes = results["split_sizes"]
    if not isinstance(sizes, dict) or set(sizes) != {"train", "test"}:
        return "split_sizes must have the keys train and test"
    for part, values in sizes.items():
        if not isinstance(values, list) or len(values) != n_seeds or not all(type(v) is int and v > 0 for v in values):
            return f"split_sizes.{part} must hold {n_seeds} positive counts"
    runtime = results["runtime_seconds"]
    if type(runtime) is not float or not math.isfinite(runtime) or runtime < 0:
        return "runtime_seconds must be a non-negative number"
    return None


def _status_of(outcome: ScriptOutcome, run_dir: Path, config: dict) -> tuple[str, str | None]:
    """Decide a run's status and, for a failure, the reason."""
    if outcome.timed_out:
        return STATUS_TIMEOUT, f"killed after {outcome.seconds:.0f} s"
    if outcome.returncode != 0:
        return STATUS_CRASH, f"exit code {outcome.returncode}"
    try:
        results = json.loads((run_dir / RESULTS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return STATUS_INVALID_RESULTS, f"cannot read {RESULTS_NAME}: {exc}"
    problem = validate_results(results, config)
    return (STATUS_INVALID_RESULTS, problem) if problem else (STATUS_OK, None)


def run_config(config: dict, runs_dir: Path = RUNS_DIR, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """Generate and run one experiment, and return its record. Failures are recorded, never raised.

    The run ID is a random UUID so that an ID reveals nothing about a run's type or order.
    """
    run_id = str(uuid.uuid4())
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    record = {"run_id": run_id, "status": STATUS_OK, "reason": None, "returncode": None, "seconds": None,
              "stderr_tail": ""}
    try:
        script = codegen.prepare_run(config, run_dir)
    except (codegen.ConfigError, FileNotFoundError) as exc:  # FileNotFoundError: dataset was never cached
        record.update(status=STATUS_INVALID_CONFIG, reason=str(exc))
    else:
        outcome = run_script(script, run_dir, timeout_s)
        status, reason = _status_of(outcome, run_dir, config)
        record.update(status=status, reason=reason, returncode=outcome.returncode,
                      seconds=round(outcome.seconds, 3), stderr_tail=outcome.stderr_tail)
    (run_dir / RECORD_NAME).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def crash_rate(runs_dir: Path = RUNS_DIR) -> tuple[int, int]:
    """Return (failed, total) over all recorded runs that got as far as executing.

    Invalid configs are left out: no code ran, so they say nothing about the template. Timeouts and bad results
    count as failures. This is the number to compare with the 42% reported for Sakana's AI Scientist.
    """
    statuses = [json.loads(p.read_text(encoding="utf-8"))["status"] for p in runs_dir.glob(f"*/{RECORD_NAME}")]
    executed = [s for s in statuses if s != STATUS_INVALID_CONFIG]
    return sum(s != STATUS_OK for s in executed), len(executed)
