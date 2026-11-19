"""Amendment 1 of both locked plans: the lock checks verify frozen files at the lock tag (`eval/lock_git.py`).

Fast tests use a fake git (a dict of commits); the tests marked slow use a real temporary git repository and the real
repo (they skip if the tags are absent, e.g. in a clone without tags). No network, no model.
"""
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from canary.config import ROOT
from eval import ceiling_lock, lock_git
from eval import tripwires_test as tt
from tests.test_tripwires_locked import world_plan

TAG = "plan-lock"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def amendment(plan_bytes: bytes, tag: str = TAG, plan_digest: str | None = None) -> bytes:
    digest = plan_digest or sha(plan_bytes)
    return (f"\n## 9. Amendment 1 (test): checked at the lock commit\n"
            f"- Lock commit: tag `{tag}`, plan SHA-256 at the tag {digest}\n").encode()


@pytest.fixture
def fake_git(monkeypatch):
    """commits: {commit: {path: bytes}}; tags: {tag: commit}. Replaces the two git readers."""
    state = {"commits": {}, "tags": {}}
    monkeypatch.setattr(lock_git, "tag_commit", lambda tag, root: state["tags"].get(tag))
    monkeypatch.setattr(lock_git, "blob_at", lambda commit, path, root: state["commits"].get(commit, {}).get(path))
    return state


def world(root: Path, fake_git: dict) -> tuple[Path, list[tuple[str, str]], dict]:
    """A tracked code file and an untracked data file, a plan listing both, committed and tagged, then amended."""
    (root / "code.py").write_bytes(b"x = 1\n")
    (root / "data").mkdir()
    (root / "data" / "pool.json").write_bytes(b"[1, 2]\n")
    entries = [("code.py", sha(b"x = 1\n")), ("data/pool.json", sha(b"[1, 2]\n"))]
    locked = ("# Plan\n\n## 3. Frozen inputs\n" + "".join(f"- `{p}` {d}\n" for p, d in entries) + "\n## 4. Data\n").encode()
    plan = root / "plan.md"
    plan.write_bytes(locked + amendment(locked))
    fake_git["commits"]["c1"] = {"code.py": b"x = 1\n", "plan.md": locked}
    fake_git["tags"][TAG] = "c1"
    return plan, entries, fake_git


def on_disk(root: Path):
    def check(path: str, digest: str) -> str | None:
        file = root / path
        if not file.exists():
            return f"{path}: missing"
        return None if sha(file.read_bytes()) == digest else f"{path}: hash differs from the plan"
    return check


def test_the_check_passes_when_the_tag_and_the_disk_files_match(tmp_path, fake_git):
    plan, entries, _ = world(tmp_path, fake_git)
    assert lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path)) == ([], [])


def test_a_changed_working_copy_of_a_tagged_file_is_information_not_a_problem(tmp_path, fake_git):
    plan, entries, _ = world(tmp_path, fake_git)
    (tmp_path / "code.py").write_bytes(b"x = 2\n")
    assert lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path)) == (
        [], ["code.py: working copy differs from the locked version (content)"])
    (tmp_path / "code.py").write_bytes(b"x = 1\r\n")
    assert lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path))[1] == [
        "code.py: working copy differs from the locked version (line endings only)"]
    (tmp_path / "code.py").unlink()
    assert lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path))[1] == [
        "code.py: working copy differs from the locked version (missing from the working tree)"]


def test_a_wrong_listed_hash_of_a_tagged_file_fails(tmp_path, fake_git):
    plan, entries, git = world(tmp_path, fake_git)
    git["commits"]["c1"]["code.py"] = b"x = 3\n"  # the bytes at the tag do not hash to the listed value
    assert lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path))[0] == [
        f"code.py: the version at {TAG} does not hash to the plan's value"]


def test_a_missing_tag_fails(tmp_path, fake_git):
    plan, entries, git = world(tmp_path, fake_git)
    del git["tags"][TAG]
    problems, info = lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path))
    assert problems == [f"tag {TAG}: missing (the lock commit cannot be found; fetch or recreate the tag)"] and info == []


def test_a_changed_file_outside_git_fails(tmp_path, fake_git):
    plan, entries, _ = world(tmp_path, fake_git)
    (tmp_path / "data" / "pool.json").write_bytes(b"[1, 3]\n")
    assert lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path))[0] == [
        "data/pool.json: hash differs from the plan"]


def test_the_plan_must_name_its_tag_be_the_locked_plan_and_keep_the_locked_text(tmp_path, fake_git):
    plan, entries, git = world(tmp_path, fake_git)
    text = plan.read_bytes()
    plan.write_bytes(text.split(b"\n## 9.")[0] + b"\n")
    assert "no amendment line naming the lock tag" in lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path))[0][0]
    plan.write_bytes(text.replace(b"## 4. Data", b"## 4. Data (edited)"))
    assert lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path))[0] == [
        "plan.md: the locked text was changed (an amendment may only add text after it)"]
    plan.write_bytes(text)
    git["commits"]["c0"] = {"code.py": b"x = 1\n", "plan.md": b"# an earlier draft\n"}
    git["tags"][TAG] = "c0"  # the tag on the wrong commit
    problems = lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path))[0]
    assert f"plan.md at {TAG} does not hash to the declared lock hash: the tag is not the lock commit" in problems


def test_ceiling_entries_outside_git_keep_their_first_lines_rule(tmp_path, fake_git):
    plan, _, git = world(tmp_path, fake_git)
    log = tmp_path / "data" / "calls.jsonl"
    log.write_bytes(b"a\nb\n")
    entries = [("code.py", None, sha(b"x = 1\n")), ("data/calls.jsonl", 1, sha(b"a\n"))]
    assert ceiling_lock.tagged_problems(plan, entries, tmp_path) == ([], [])
    log.write_bytes(b"a\nb\nc\n")  # appended lines are allowed
    assert ceiling_lock.tagged_problems(plan, entries, tmp_path) == ([], [])
    log.write_bytes(b"z\nb\n")
    assert ceiling_lock.tagged_problems(plan, entries, tmp_path)[0] == [
        "data/calls.jsonl: hash differs from the plan (first 1 lines)"]


def test_tripwire_tagged_check_reads_tagged_files_and_keeps_its_other_rules(tmp_path, fake_git):
    plan = world_plan(tmp_path)  # every required file (CRLF on disk) and both slot locks
    locked = plan.read_bytes()
    fake_git["commits"]["c1"] = {name: (tmp_path / name).read_bytes().replace(b"\r\n", b"\n") for name in tt.MUST_FREEZE}
    fake_git["commits"]["c1"]["docs/plans/tripwire_test.md"] = locked
    fake_git["tags"][TAG] = "c1"
    plan.write_bytes(locked + amendment(locked))
    tt.lock_path(plan).write_bytes(f"{tt.lf_sha256(plan)}  {plan.name}\n".encode())
    problems, info = tt.tagged_lock_problems(plan, tmp_path)
    assert problems == [] and len(info) == len(tt.MUST_FREEZE) and all("line endings only" in i for i in info)
    for name in tt.MUST_FREEZE:
        (tmp_path / name).write_bytes(fake_git["commits"]["c1"][name])  # as `--sync-lf` makes them
    assert tt.tagged_lock_problems(plan, tmp_path) == ([], [])
    (tmp_path / "canary" / "trust.py").write_bytes(b"# Mission 4.1 changed this\n")  # listed by the real plan only
    (tmp_path / "canary" / "tripwires.py").write_bytes(b"# changed after the lock\n")
    problems, info = tt.tagged_lock_problems(plan, tmp_path)
    assert problems == [] and info == ["canary/tripwires.py: working copy differs from the locked version (content)"]
    assert tt.lock_problems(plan, tmp_path) == ["canary/tripwires.py: hash differs from the plan"]  # original check
    plan.write_bytes(plan.read_bytes() + b"more\n")
    assert any("edited after it was locked" in p for p in tt.tagged_lock_problems(plan, tmp_path)[0])


def test_amend_lock_rewrites_the_hash_only_for_an_appended_amendment(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    locked = b"# Plan\n\n## 3. Frozen inputs\n"
    plan.write_bytes(locked)
    lock = tmp_path / "plan.md.sha256"
    lock.write_bytes(f"{sha(locked)}  plan.md\n".encode())
    head = {"plan.md": locked}
    monkeypatch.setattr(lock_git, "blob_at", lambda commit, path, root: head.get(path) if commit == "HEAD" else None)
    with pytest.raises(ValueError, match="adds text after the locked text"):
        lock_git.amend_lock(plan, tmp_path)  # nothing added
    plan.write_bytes(locked + b"\nmore words\n")
    with pytest.raises(ValueError, match="no '## ... Amendment' heading"):
        lock_git.amend_lock(plan, tmp_path)
    plan.write_bytes(b"# Plan, edited\n" + amendment(locked))
    with pytest.raises(ValueError, match="adds text after the locked text"):
        lock_git.amend_lock(plan, tmp_path)
    plan.write_bytes(locked + amendment(locked))
    head["plan.md"] = b"# something committed but never locked\n"
    with pytest.raises(ValueError, match="at HEAD is not the plan"):
        lock_git.amend_lock(plan, tmp_path)
    head["plan.md"] = locked
    assert lock_git.amend_lock(plan, tmp_path) == (sha(locked), sha(plan.read_bytes()))
    assert lock.read_bytes() == f"{sha(plan.read_bytes())}  plan.md\n".encode()
    lock.unlink()
    with pytest.raises(ValueError, match="does not exist"):
        lock_git.amend_lock(plan, tmp_path)


# ---- Real git (slow) -----------------------------------------------------------------------------------------------

def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false",
                          *args], cwd=root, capture_output=True, timeout=60, check=True)
    return out.stdout.decode().strip()


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_real_git_repository_tag_branch_and_untracked_files(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "code.py").write_bytes(b"x = 1\n")
    (tmp_path / "pool.json").write_bytes(b"[1]\n")  # never added: outside git
    entries = [("code.py", sha(b"x = 1\n")), ("pool.json", sha(b"[1]\n"))]
    locked = ("# Plan\n\n## 3. Frozen inputs\n" + "".join(f"- `{p}` {d}\n" for p, d in entries)).encode()
    plan = tmp_path / "plan.md"
    plan.write_bytes(locked)
    git(tmp_path, "add", "code.py", "plan.md")
    git(tmp_path, "commit", "-q", "-m", "lock")
    plan.write_bytes(locked + amendment(locked))
    assert lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path))[0] == [
        f"tag {TAG}: missing (the lock commit cannot be found; fetch or recreate the tag)"]
    git(tmp_path, "branch", TAG)  # a branch of that name is not the tag
    assert lock_git.tag_commit(TAG, tmp_path) is None
    git(tmp_path, "tag", TAG)
    (tmp_path / "code.py").write_bytes(b"x = 2\n")
    git(tmp_path, "commit", "-q", "-am", "later change")
    assert lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path)) == (
        [], ["code.py: working copy differs from the locked version (content)"])
    (tmp_path / "pool.json").write_bytes(b"[2]\n")
    assert lock_git.check_at_tag(plan, entries, tmp_path, on_disk(tmp_path))[0] == ["pool.json: hash differs from the plan"]


def real_tag(tag: str) -> bool:
    return shutil.which("git") is not None and lock_git.tag_commit(tag, ROOT) is not None


@pytest.mark.slow
@pytest.mark.skipif(not real_tag("ceiling-check-lock") or not (ROOT / "data" / "cloud" / "calls.jsonl").exists(),
                    reason="needs the tag ceiling-check-lock and data/")
def test_the_real_ceiling_plan_passes_at_its_tag():
    entries = ceiling_lock.plan_entries(ceiling_lock.PLAN.read_text(encoding="utf-8"))
    assert ceiling_lock.tagged_problems(ceiling_lock.PLAN, entries, ROOT)[0] == []
    assert ceiling_lock.lock_problem(ceiling_lock.PLAN) is None


@pytest.mark.slow
@pytest.mark.skipif(not real_tag("tripwire-test-1-lock") or not (ROOT / tt.PRIMARY_POOL).exists(),
                    reason="needs the tag tripwire-test-1-lock and data/")
def test_the_real_tripwire_plan_passes_at_its_tag():
    assert tt.tagged_lock_problems()[0] == []
