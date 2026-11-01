"""Shared helpers for the command coach (status line + hooks).

Reads PROGRESS.md, git and the campaign log to work out where the student is,
and picks the most useful /command to suggest. Must be fast and never crash.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

# Mission-specific tips: the first matching prefix wins.
MISSION_TIPS = [
    ("1.", "/explain <new file> after each mission, so you can explain it in a viva"),
    ("2.1", "/test the saboteur, then /challenge: would a reviewer spot these bugs too easily?"),
    ("2.2", "/constraints checks the sealed run-type table is never visible to the Skeptic"),
    ("2.3", "stats mission: /learn Beta posterior, then /assumptions"),
    ("2.4", "/challenge RQ1: the reviewer flagged every run, so ask what that means for the plan"),
    ("3.", "/learn Brier score, then /explain canary/calibration.py"),
    ("4.1", "stats mission: /learn Rogan-Gladen, and /test against hand-computed values"),
    ("4.2", "/campaign for the hidden-truth runs; /forecast first to see how long it takes"),
    ("4.3", "/learn control charts; /visualize the chart when done"),
    ("4.4", "/campaign --runs 40, then read the trace: did the agent recalibrate?"),
    ("5.", "/compare LLM vs tripwires vs jury once RQ2 runs"),
    ("6.", "/blindspots after each probe campaign"),
    ("7.", "/demo to script the 5-minute demo; try Beat the Skeptic yourself"),
    ("8.", "/write <section>, /visualize, /proofread, /viva, /novelty"),
]

GENERAL_TIPS = [
    "/btw <question> asks a side question without derailing the session",
    "/tldr shows what changed since the last commit, in 5 bullets",
    "/challenge makes Claude attack its own work like a paper reviewer",
    "/explain <file> to understand new code (viva prep)",
    "add /bullet /table /shorten mid-message to shape any answer",
    "/assumptions before trusting a statistical result",
    "/rewind undoes Claude's last changes if something went wrong",
    "end a session with /summary, then /clear",
]


def project_root(start: str | None) -> Path:
    """Walk up from `start` to the folder that holds CLAUDE.md."""
    p = Path(start or ".").resolve()
    for cand in [p, *p.parents]:
        if (cand / "CLAUDE.md").exists():
            return cand
    return p


def next_mission(root: Path) -> tuple[str, str] | None:
    """Return (id, title) of the first unticked mission in PROGRESS.md."""
    try:
        text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"- \[ \] (\d+\.\d+) (.+)", text)
    return (m.group(1), m.group(2).strip()) if m else None


def last_done(root: Path) -> str | None:
    try:
        text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    except OSError:
        return None
    done = re.findall(r"- \[x\] (\d+\.\d+) (.+)", text, flags=re.IGNORECASE)
    return f"{done[-1][0]} {done[-1][1].strip()}" if done else None


def git_dirty_count(root: Path) -> int:
    try:
        out = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True,
                             text=True, timeout=1.5)
        return len([l for l in out.stdout.splitlines() if l.strip()]) if out.returncode == 0 else 0
    except (OSError, subprocess.SubprocessError):
        return 0


def campaign_state(root: Path) -> str | None:
    """'running', 'interrupted' or None, from data/runs/campaign.log."""
    log = root / "data" / "runs" / "campaign.log"
    try:
        age = time.time() - log.stat().st_mtime
        tail = log.read_text(encoding="utf-8", errors="ignore")[-2000:].lower()
    except OSError:
        return None
    if "campaign finished" in tail or "campaign complete" in tail:
        return None
    return "running" if age < 180 else "interrupted"


def mission_tip(mission_id: str) -> str | None:
    for prefix, tip in MISSION_TIPS:
        if mission_id.startswith(prefix):
            return tip
    return None


def pick_tip(root: Path, ctx_pct: float | None) -> str:
    """Most urgent useful command for right now."""
    if ctx_pct is not None and ctx_pct >= 80:
        return "context almost full: /summary, then /clear (then /where to pick up)"
    camp = campaign_state(root)
    if camp == "running":
        return "campaign running: /tasks to watch it, /btw for questions meanwhile"
    if camp == "interrupted":
        return "a campaign was interrupted: /campaign to resume it"
    if ctx_pct is not None and ctx_pct >= 60:
        return "context over 60%: /compact keep the current mission details"
    if git_dirty_count(root) >= 15:
        return "many uncommitted changes: finish the mission, or /summary to save state"
    nm = next_mission(root)
    # Alternate every 40 s between the mission tip and a rotating general tip.
    slot = int(time.time() // 40)
    if nm and slot % 2 == 0:
        tip = mission_tip(nm[0])
        if tip:
            return tip
    return GENERAL_TIPS[slot % len(GENERAL_TIPS)]
