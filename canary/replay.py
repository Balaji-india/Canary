"""Replay a stored run under the probe, in a temporary copy, and return what it did (Mission 5.1).

Why a temporary copy: the SHA-256 of every run's results.json is in the ledger and, for the ceiling runs, in the lock
manifest of the open ceiling arm (docs/plans/mission_5_1_tripwires.md, section 2.5). A replay inside the run folder
would overwrite it. So `replay` only *reads* the run folder: it copies the script and the dataset to a new temporary
folder, runs the probe there through `sandbox.run_script` (same timeout and environment as any experiment), reads the
replayed results.json and the trace, and removes the folder. A test proves the run folder is byte-identical after.

Cost and a limit: the probe adds a few tenths of a second (fingerprinting the rows at each recorded call; 3.1 s against
2.9 s on the baseline config), under the same timeout as the original run. A run that finished just under the
timeout can therefore time out on replay; that is a recorded `timeout` status (unverifiable later), never a pass.

Usage: `python -m canary.replay <run_dir>` prints the status, "numbers identical: yes/no" (every results.json key
except runtime_seconds, compared exactly) and how many calls of each kind the trace holds.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from canary import codegen, probe, sandbox

PROBE_NAME = "probe.py"
COPIED_FILES = (codegen.SCRIPT_NAME, codegen.DATASET_NAME)
STATUS_NO_TRACE = "no_trace"
IGNORED_KEYS = ("runtime_seconds",)  # the only key a correct replay may change
_CLEANUP_TRIES = 5


@dataclass(frozen=True)
class ReplayResult:
    """What one replay gave. `results` and `trace` are None when they could not be read; `workdir` is the temporary
    folder that was used and has already been removed."""

    status: str
    reason: str | None
    results: dict | None
    trace: dict | None
    seconds: float
    stderr_tail: str
    workdir: str


def _read_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"cannot read {path.name}: {exc}"


def _remove(folder: Path) -> None:
    """Delete the temporary folder. On Windows a just-killed process can hold a file for a moment, so retry."""
    for attempt in range(_CLEANUP_TRIES):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == _CLEANUP_TRIES - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def replay(run_dir: Path, timeout_s: float = sandbox.DEFAULT_TIMEOUT_S) -> ReplayResult:
    """Run the run's script once more under the probe, in a temporary copy. Failures are returned, never raised.

    The run folder is only read (the two copied files); nothing is written into it.
    """
    run_dir = Path(run_dir)
    workdir = Path(tempfile.mkdtemp(prefix="canary-replay-"))
    try:
        for name in COPIED_FILES:
            shutil.copyfile(run_dir / name, workdir / name)
        shutil.copyfile(Path(probe.__file__), workdir / PROBE_NAME)
        outcome = sandbox.run_script(workdir / PROBE_NAME, workdir, timeout_s)
        trace, trace_problem = _read_json(workdir / probe.DEFAULT_TRACE)
        results, results_problem = _read_json(workdir / sandbox.RESULTS_NAME)
        if outcome.timed_out:
            status, reason = sandbox.STATUS_TIMEOUT, f"killed after {outcome.seconds:.0f} s"
        elif outcome.returncode != 0:
            status, reason = sandbox.STATUS_CRASH, f"exit code {outcome.returncode}"
        elif trace is None:
            status, reason = STATUS_NO_TRACE, trace_problem
        elif results is None:
            status, reason = sandbox.STATUS_INVALID_RESULTS, results_problem
        else:
            status, reason = sandbox.STATUS_OK, None
        return ReplayResult(status, reason, results, trace, round(outcome.seconds, 3), outcome.stderr_tail,
                            str(workdir))
    finally:
        _remove(workdir)


def numbers_identical(stored: dict | None, replayed: dict | None) -> bool:
    """True when both results exist and agree exactly on every key except runtime_seconds."""
    if not isinstance(stored, dict) or not isinstance(replayed, dict):
        return False
    strip = lambda results: {k: v for k, v in results.items() if k not in IGNORED_KEYS}  # noqa: E731
    return strip(stored) == strip(replayed)


def event_counts(trace: dict | None) -> Counter:
    """How many recorded calls of each kind a trace holds: `split`, `metric`, or the estimator method's name."""
    counts: Counter = Counter()
    for event in (trace or {}).get("events", []):
        counts[event["method"] if event["kind"] == "estimator" else event["kind"]] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m canary.replay", description=__doc__.split("\n\n")[0])
    parser.add_argument("run_dir", type=Path, help="a run folder holding experiment.py and dataset.csv.gz")
    parser.add_argument("--timeout", type=float, default=sandbox.DEFAULT_TIMEOUT_S, help="seconds before the kill")
    args = parser.parse_args(argv)
    stored, problem = _read_json(args.run_dir / sandbox.RESULTS_NAME)
    result = replay(args.run_dir, args.timeout)
    print(f"replay: {result.status} in {result.seconds:.1f} s" + (f" ({result.reason})" if result.reason else ""))
    same = numbers_identical(stored, result.results)
    print(f"numbers identical: {'yes' if same else 'no'}" + (f" ({problem})" if stored is None else ""))
    counts = event_counts(result.trace)
    print("events: " + (", ".join(f"{name} {n}" for name, n in sorted(counts.items())) or "none"))
    if result.status != sandbox.STATUS_OK and result.stderr_tail:
        print(result.stderr_tail.rstrip()[-600:])
    return 0 if result.status == sandbox.STATUS_OK and same else 1


if __name__ == "__main__":
    sys.exit(main())
