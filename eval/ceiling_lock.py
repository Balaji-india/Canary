"""Lock tools for the cloud ceiling check: the run manifest, the hash check and the lock itself.

    python -m eval.ceiling_lock --write-manifest   the 120 runs and the exact prompt each will be sent (no run types)
    python -m eval.ceiling_lock --check            every hash in the plan, the manifest, the call log, counts per arm
    python -m eval.ceiling_lock --lock             write the plan's .sha256 (only if --check finds nothing else wrong)
    python -m eval.ceiling_lock --check --working-tree   the check as it was before amendment 1 (working copies)
    python -m eval.ceiling_lock --amend-lock       new .sha256 after a written amendment (prints old and new)

Why a tool: the plan (docs/plans/cloud_ceiling_check.md, section 3) freezes code, config, data and prompts by SHA-256,
and one of its stop rules is "any hash that no longer matches". A rule nobody can check in one command is not a rule.
Run `--check` before every daily session and before `python -m eval.ceiling --arm L`.

Amendment 1 (2026-11-19, plan section 11): the freeze ended when arm L's result was committed, and later missions must
change frozen files (`canary/cli.py`). Since then `--check` verifies each listed file that git tracked at the lock
against `git show ceiling-check-lock:<path>` (`eval.lock_git`), not the working copy; files outside git (pools, sealed
plans, the call log) and the manifest rebuilt from `data/` are checked on disk as before. Working copies that differ
from the locked version are printed for information only. `--working-tree` gives the original check.

It prints counts only (answered, failed, waiting): never a verdict, a flag rate or a run type, so it is safe to run
while an arm is unfinished. It calls no model and no network. It reads the sealed table only to list a batch's run
IDs and (through `ceiling.cell_rows`) to count; it lives in eval/, outside the reviewer's code path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from canary import config, ledger, llm, mixer, review_tasks, sandbox, sealed, skeptic
from canary.config import ROOT
from eval import ceiling, lock_git

PLAN = ROOT / "docs" / "plans" / "cloud_ceiling_check.md"
MANIFEST = ceiling.OUT_DIR / "lock_manifest.json"
MANIFEST_ROLE = "skeptic_d"  # arm R's role uses the same task, so the same prompts and wire schema
NOT_LOCKED = "the plan is NOT LOCKED (no .sha256 file)"
SECTION = re.compile(r"^## 3\..*?(?=^## )", re.S | re.M)
ENTRY = re.compile(r"^- (?:first (\d+) lines of )?`([^`]+)` ([0-9a-f]{64})\b", re.M)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan_entries(text: str) -> list[tuple[str, int | None, str]]:
    """(path, first-n-lines or None, SHA-256) for every frozen file listed in the plan's section 3."""
    section = SECTION.search(text)
    if not section:
        raise ValueError("the plan has no section 3 (frozen inputs)")
    return [(path, int(lines) if lines else None, digest) for lines, path, digest in ENTRY.findall(section.group(0))]


def file_problems(entries: list[tuple[str, int | None, str]], root: Path = ROOT) -> list[str]:
    """One line per listed file that is missing or whose bytes no longer hash to the plan's value.

    `first n lines` entries hash only the start of a file that grows (the call log): later lines may be added, the
    lines that existed at the lock may not change.
    """
    problems = []
    for path, lines, digest in entries:
        file = root / path
        if not file.exists():
            problems.append(f"{path}: missing")
            continue
        data = file.read_bytes()
        if lines is not None:
            data = b"".join(data.splitlines(keepends=True)[:lines])
        if sha256(data) != digest:
            problems.append(f"{path}: hash differs from the plan" + (f" (first {lines} lines)" if lines else ""))
    return problems


def tagged_problems(plan: Path, entries: list[tuple[str, int | None, str]],
                    root: Path = ROOT) -> tuple[list[str], list[str]]:
    """(problems, information): the listed files checked at the plan's lock tag (amendment 1, `eval.lock_git`).

    A file git tracked at the tag must hash there to the listed value (whole file; only the call log, outside git, has a
    `first n lines` entry). A file git did not track is checked on disk exactly as `file_problems` does."""
    lines_of = {path: lines for path, lines, _ in entries}

    def on_disk(path: str, digest: str) -> str | None:
        found = file_problems([(path, lines_of[path], digest)], root)
        return found[0] if found else None

    return lock_git.check_at_tag(plan, [(path, digest) for path, _, digest in entries], root, on_disk)


def build_manifest(led: ledger.Ledger, table: sealed.SealedTable, models_cfg: dict, bugs: dict,
                   batches: tuple[str, ...] = ceiling.BATCHES, role: str = MANIFEST_ROLE,
                   runs_dir: Path = sandbox.RUNS_DIR) -> dict:
    """The batches' runs by batch then run ID, each with the hash of the exact prompt the role will be sent.

    `skeptic._prepare` re-checks every run's files against the ledger first, so a manifest that still matches also
    says: same runs, same files, same blinding, same prompt template, same schema.
    """
    task = skeptic.task_of(models_cfg, role)
    locks = {e.hypothesis_id: e.payload for e in led.entries(ledger.PREREGISTERED)}
    ran = {e.payload["run_id"]: e for e in led.entries(ledger.RAN) if "run_id" in e.payload}
    runs, schemas = [], set()
    for batch in batches:
        for run_id in sorted(mixer.batch_run_ids(table, batch)):
            entry = ran[run_id]
            job = skeptic._prepare(entry, locks[entry.hypothesis_id], runs_dir)
            system, prompt, schema = review_tasks.build(task, job.blinded, bugs, None)
            schemas.add(llm._sha256_json(llm.wire_schema(schema)))
            runs.append({"batch": batch, "run_id": run_id, "results_sha256": entry.payload["results_sha256"],
                         "prompt_sha256": sha256(((system or "") + "\n\n" + prompt).encode("utf-8"))})
    return {"note": "the 120 ceiling runs, sorted by batch then run ID: no run types. prompt_sha256 = SHA-256 of system + "
                    "two newlines + user prompt, exactly as review_tasks.build makes them for skeptic_d",
            "task": task, "wire_schema_sha256": sorted(schemas), "runs": runs}


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, indent=1) + "\n").encode("utf-8")


def lock_problem(plan: Path) -> str | None:
    """None if the plan's bytes hash to its .sha256 file."""
    lock = plan.with_name(plan.name + ".sha256")
    if not lock.exists():
        return NOT_LOCKED
    if lock.read_text(encoding="utf-8").split()[0] != sha256(plan.read_bytes()):
        return f"{plan.name} does not match its .sha256: the locked plan was changed"
    return None


def write_lock(plan: Path) -> Path:
    """Write `<plan>.sha256` (LF bytes, the sha256sum format). Refuses to replace an existing lock."""
    lock = plan.with_name(plan.name + ".sha256")
    if lock.exists():
        raise FileExistsError(f"{lock.name} exists: a locked plan changes only by a written amendment")
    lock.write_bytes(f"{sha256(plan.read_bytes())}  {plan.name}\n".encode("utf-8"))
    return lock


def check(plan: Path = PLAN, root: Path = ROOT, manifest_path: Path = MANIFEST, working_tree: bool = False) -> list[str]:
    """Every problem found: the lock, the listed files, and the manifest rebuilt from the runs on disk.

    By default (amendment 1) the listed files git tracked are checked at the lock tag and differing working copies are
    printed for information; `working_tree=True` is the original check of every working copy."""
    text = plan.read_bytes().decode("utf-8")
    entries = plan_entries(text)
    problems = [p for p in (lock_problem(plan),) if p]
    if working_tree:
        problems += file_problems(entries, root)
        print(f"{len(entries)} frozen files listed in {plan.name}, section 3 (working copies, the original check)")
    else:
        found, info = tagged_problems(plan, entries, root)
        problems += found
        tag = (lock_git.declared_lock(text) or ("(no tag declared)",))[0]
        print(f"{len(entries)} frozen files listed in {plan.name}, section 3 (files in git checked at tag {tag}, "
              f"the others on disk)")
        for line in info:
            print(f"  information only: {line}")
        if not info:
            print("  information only: every working copy equals its locked version")
    led, table = ledger.Ledger(), sealed.SealedTable()
    try:
        rebuilt = build_manifest(led, table, config.load_yaml("models.yaml"), config.load_yaml("bug_classes.yaml"))
        if manifest_bytes(rebuilt) != manifest_path.read_bytes():
            problems.append(f"{manifest_path.name}: the runs, their files or their prompts no longer match the manifest")
        print(f"manifest: {len(rebuilt['runs'])} runs rebuilt from disk, wire schema {rebuilt['wire_schema_sha256']}")
    except (OSError, ValueError, KeyError, SyntaxError) as exc:
        problems.append(f"manifest could not be rebuilt: {exc}")
    return problems


def print_counts(led: ledger.Ledger, table: sealed.SealedTable) -> None:
    """Where each arm stands, in counts only. No verdict is read out of an audit."""
    for arm, roles in ceiling.ARMS.items():
        for role in roles:
            c = ceiling.cell_rows(table, led, ceiling.BATCHES, role)
            twice = sum(r["failed"] for r in c["rows"])
            print(f"arm {arm} {role}: {len(c['rows']) - twice} answered, {twice} failed twice (count against), "
                  f"{c['failed_once']} failed once (ask again), {c['waiting']} not asked yet, {c['crashed']} crashed")
    log = llm.CALL_LOG_PATH
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()] if log.exists() else []
    models = sorted({str(r.get("server_model")) for r in records if r.get("server_model")})
    print(f"call log: {len(records)} attempts, server models seen: {', '.join(models) or 'none'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write-manifest", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--lock", action="store_true")
    group.add_argument("--amend-lock", action="store_true", help="new .sha256 after a written amendment")
    parser.add_argument("--working-tree", action="store_true",
                        help="with --check: the original check of the working copies (before amendment 1)")
    args = parser.parse_args(argv)
    if args.amend_lock:
        try:
            old, new = lock_git.amend_lock(PLAN, ROOT)
        except ValueError as exc:
            print(f"Not amended: {exc}")
            return 1
        print(f"AMENDED: {PLAN.name}.sha256 old {old}")
        print(f"AMENDED: {PLAN.name}.sha256 new {new}")
        return 0
    led, table = ledger.Ledger(), sealed.SealedTable()
    if args.write_manifest:
        if lock_problem(PLAN) != NOT_LOCKED:
            print("The plan is locked: the manifest is frozen with it.")
            return 1
        manifest = build_manifest(led, table, config.load_yaml("models.yaml"), config.load_yaml("bug_classes.yaml"))
        MANIFEST.write_bytes(manifest_bytes(manifest))
        print(f"Wrote {MANIFEST}: {len(manifest['runs'])} runs, SHA-256 {sha256(MANIFEST.read_bytes())}")
        return 0
    problems = check(working_tree=args.working_tree or args.lock)
    if args.lock:
        if NOT_LOCKED not in problems:
            print("Already locked: a locked plan changes only by a written amendment.")
            return 1
        others = [p for p in problems if p != NOT_LOCKED]
        if others:
            print("Not locked, fix these first:" + "".join(f"\n  PROBLEM {p}" for p in others))
            return 1
        lock = write_lock(PLAN)
        print(f"LOCKED: {lock.name} = {lock.read_text(encoding='utf-8').split()[0]}")
        return 0
    print_counts(led, table)
    for problem in problems:
        print(f"PROBLEM {problem}")
    print("Lock check: " + ("FAILED: stop, send nothing" if problems else "OK, every hash matches"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
