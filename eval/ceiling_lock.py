"""Lock tools for the cloud ceiling check: the run manifest, the hash check and the lock itself.

    python -m eval.ceiling_lock --write-manifest   the 120 runs and the exact prompt each will be sent (no run types)
    python -m eval.ceiling_lock --check            every hash in the plan, the manifest, the call log, counts per arm
    python -m eval.ceiling_lock --lock             write the plan's .sha256 (only if --check finds nothing else wrong)

Why a tool: the plan (docs/plans/cloud_ceiling_check.md, section 3) freezes code, config, data and prompts by SHA-256,
and one of its stop rules is "any hash that no longer matches". A rule nobody can check in one command is not a rule.
Run `--check` before every daily session and before `python -m eval.ceiling --arm L`.

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
from eval import ceiling

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


def check(plan: Path = PLAN, root: Path = ROOT, manifest_path: Path = MANIFEST) -> list[str]:
    """Every problem found: the lock, the listed files, and the manifest rebuilt from the runs on disk."""
    text = plan.read_bytes().decode("utf-8")
    entries = plan_entries(text)
    problems = [p for p in (lock_problem(plan),) if p] + file_problems(entries, root)
    print(f"{len(entries)} frozen files listed in {plan.name}, section 3")
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
    args = parser.parse_args(argv)
    led, table = ledger.Ledger(), sealed.SealedTable()
    if args.write_manifest:
        if lock_problem(PLAN) != NOT_LOCKED:
            print("The plan is locked: the manifest is frozen with it.")
            return 1
        manifest = build_manifest(led, table, config.load_yaml("models.yaml"), config.load_yaml("bug_classes.yaml"))
        MANIFEST.write_bytes(manifest_bytes(manifest))
        print(f"Wrote {MANIFEST}: {len(manifest['runs'])} runs, SHA-256 {sha256(MANIFEST.read_bytes())}")
        return 0
    problems = check()
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
