"""Lock checks against the locked commit, not the working tree (amendment 1 of both locked plans, 2026-11-19).

Why: a locked plan freezes files by SHA-256 so a result can be reproduced. While a check ran, the working copy had to
stay equal to those bytes. Once the results are committed the freeze is over (both plans say so), but later missions
must change some of the frozen files (Mission 4.1 changes `canary/cli.py` and `canary/trust.py`). Comparing the
working tree would then fail forever, and a check that always fails is no check. What matters for reproducing a
result is that the frozen bytes still exist and can be checked out: so each frozen file that git tracked at the lock
is checked as `git show <tag>:<path>` at the plan's lock commit. Files git never tracked (pool files, sealed plans, the
call log) can only be checked on disk, as before.

Each amended plan names its tag and the SHA-256 the plan had at the lock in one line (`LOCKED_AT`). The check reads
that line, so the plan itself says which commit is the reference, and verifies:
- the tag exists and the plan at the tag hashes to the declared lock hash (so the tag is the lock commit);
- the working plan starts with the locked plan's bytes (an amendment only adds text after the locked text);
- each listed file that git tracked at the tag hashes, at the tag, to the listed value;
- each listed file git did not track at the tag passes the caller's on-disk check.
Working copies that now differ from the locked version are returned as information: they decide nothing.

Used by `eval.ceiling_lock` and `eval.tripwires_test`. Reads git only (no network, no model, no sealed data).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Callable

LOCKED_AT = re.compile(r"^- Lock commit: tag `([\w.-]+)`, plan SHA-256 at the tag ([0-9a-f]{64})\b", re.M)
AMENDMENT_HEADING = re.compile(r"^## .*Amendment", re.M)


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=60)


def tag_commit(tag: str, root: Path) -> str | None:
    """The commit a tag points to (tags only, never a branch of the same name), or None."""
    result = _git(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}"], root)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def blob_at(commit: str, path: str, root: Path) -> bytes | None:
    """The file's bytes as committed at `commit`, or None when git did not track it there."""
    result = _git(["cat-file", "blob", f"{commit}:{path}"], root)
    return result.stdout if result.returncode == 0 else None


def lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def difference(working: Path, locked: bytes) -> str | None:
    """How a working copy differs from the locked bytes, in words; None when identical."""
    if not working.exists():
        return "missing from the working tree"
    data = working.read_bytes()
    if data == locked:
        return None
    return "line endings only" if lf(data) == lf(locked) else "content"


def declared_lock(text: str) -> tuple[str, str] | None:
    """(tag, plan SHA-256 at the tag) from the plan's amendment line, or None."""
    found = LOCKED_AT.search(text)
    return (found.group(1), found.group(2)) if found else None


def check_at_tag(plan: Path, entries: list[tuple[str, str]], root: Path,
                 disk_problem: Callable[[str, str], str | None],
                 normalize: Callable[[bytes], bytes] = lambda b: b) -> tuple[list[str], list[str]]:
    """(problems, information) for a plan whose frozen files are checked at its lock tag.

    `entries` are (path, listed SHA-256). `normalize` is applied to bytes before hashing or comparing (the tripwire
    plan hashes LF bytes; the ceiling plan hashes the bytes as stored). `disk_problem(path, digest)` checks a file git
    did not track at the tag and returns one problem line or None.
    """
    declared = declared_lock(plan.read_bytes().decode("utf-8"))
    if declared is None:
        return [f"{plan.name}: no amendment line naming the lock tag ('- Lock commit: tag `...`, plan SHA-256 at "
                f"the tag ...')"], []
    tag, plan_digest = declared
    commit = tag_commit(tag, root)
    if commit is None:
        return [f"tag {tag}: missing (the lock commit cannot be found; fetch or recreate the tag)"], []
    problems, info = [], []
    locked_plan = blob_at(commit, plan.relative_to(root).as_posix(), root)
    if locked_plan is None:
        problems.append(f"{plan.name}: not in git at {tag}")
    else:
        if hashlib.sha256(normalize(locked_plan)).hexdigest() != plan_digest:
            problems.append(f"{plan.name} at {tag} does not hash to the declared lock hash: the tag is not the lock "
                            f"commit")
        if not normalize(plan.read_bytes()).startswith(normalize(locked_plan)):
            problems.append(f"{plan.name}: the locked text was changed (an amendment may only add text after it)")
    for path, digest in entries:
        locked = blob_at(commit, path, root)
        if locked is None:
            problem = disk_problem(path, digest)
            if problem:
                problems.append(problem)
            continue
        if hashlib.sha256(normalize(locked)).hexdigest() != digest:
            problems.append(f"{path}: the version at {tag} does not hash to the plan's value")
        how = difference(root / path, locked)
        if how:
            info.append(f"{path}: working copy differs from the locked version ({how})")
    return problems, info


def amend_lock(plan: Path, root: Path, normalize: Callable[[bytes], bytes] = lambda b: b) -> tuple[str, str]:
    """Replace the plan's .sha256 after a written amendment. Returns (old hash, new hash).

    Refuses unless the plan as committed at HEAD is the one the current .sha256 locks (so nothing unrecorded slipped
    in), the working plan starts with those bytes, and the added text contains an amendment heading. Writes LF bytes in
    the sha256sum format, like the original lock.
    """
    lock = plan.with_name(plan.name + ".sha256")
    if not lock.exists():
        raise ValueError(f"{lock.name} does not exist: an unlocked plan is locked, not amended")
    old = lock.read_text(encoding="utf-8").split()[0]
    committed = blob_at("HEAD", plan.relative_to(root).as_posix(), root)
    if committed is None or hashlib.sha256(normalize(committed)).hexdigest() != old:
        raise ValueError(f"{plan.name} at HEAD is not the plan {lock.name} locks; commit nothing to it but amendments")
    current = normalize(plan.read_bytes())
    if not current.startswith(normalize(committed)) or current == normalize(committed):
        raise ValueError(f"{plan.name}: an amendment adds text after the locked text and changes nothing above it")
    if not AMENDMENT_HEADING.search(current[len(normalize(committed)):].decode("utf-8")):
        raise ValueError(f"{plan.name}: the added text has no '## ... Amendment' heading")
    new = hashlib.sha256(current).hexdigest()
    lock.write_bytes(f"{new}  {plan.name}\n".encode("utf-8"))
    return old, new
