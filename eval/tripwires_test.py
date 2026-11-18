"""Mission 5.1 locked test: the frozen tripwires, run once on each test batch, judged against bars fixed beforehand.

    python -m eval.tripwires_test --check                     every hash in the lock plan; is the plan locked?
    python -m eval.tripwires_test --lock                      write the plan's .sha256 (after the student's OK only)
    python -m eval.tripwires_test --batch tripwire-test-1     the test, once (then --batch ceiling-ext)
    python -m eval.tripwires_test --git-check                 line endings of the frozen files against git (step 9)
    python -m eval.tripwires_test --sync-lf                   working copies made byte-identical to git (step 9)

Why (docs/plans/mission_5_1_tripwires.md, section 7.2 and step 9): the tripwires were built while looking at the
development batches, so their numbers there say little. The test is the first look at runs the tripwire code has
never met: fresh pool-2 bases. It counts only if the code that makes and scores the records is exactly the code that
was frozen before the batch existed, and only once. So this script:
- refuses any batch but `tripwire-test-1` (primary) and `ceiling-ext` (secondary, only after `eval.ceiling --arm L`);
- refuses unless the lock plan `docs/plans/tripwire_test.md` has its `.sha256` and every file listed in its section 3
  still hashes to the listed value (line endings normalised to LF, so a Windows checkout does not change a hash);
- refuses a batch whose result file already exists: the test runs once. An interrupted run resumes from its stored
  records (same frozen version) until the result is written;
- refuses a batch whose stored batch plan (`data/sealed_plans/<batch>.json`) does not give the slot-list hash locked
  in the plan's section 4, so the built batch is exactly the planned one; refuses a build that has not finished (no
  length-gate file) or whose length gate failed, and a primary batch planned with audits;
- scores one run per planned slot: the slot's sealed run (the latest, if a crash left an earlier one behind), or, for a
  slot that was never built, a stand-in with no record. A missing record counts against both bars: a slot is never
  dropped.

The bars (plan section 12, decision 6, approved 2026-11-13), on the primary batch only:
- specificity on all clean runs (controls and shams; a flag of either kind, fired or unverifiable, is a false alarm),
  Beta 90% lower bound (5th percentile of Beta(1 + passes, 1 + false alarms)) at least 0.95;
- `fired` recall on the chain classes, Beta 90% lower bound at least 0.90. Chain classes: every canary except B09
  (no tripwire, plan section 5) and B06 obvious (the L1 rule, reported apart, plan section 7.3 item 6).
A run without a record counts against both bars (fail closed). Base-level 90% intervals (one cluster per comparison,
the ceiling rule) are printed beside them and decide nothing. Label: "known shapes, fresh bases".

It loads no audit, never opens the ledger and calls no model: the tripwire code gets each run folder's path only, and
the truth is joined afterwards by the development scoring (`eval.tripwires_dev.score`, frozen with this file).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from canary import sandbox, sealed, tripwires
from canary.config import DATA_DIR, ROOT
from canary.saboteur import classes
from eval import ceiling, tripwires_dev as dev

PRIMARY, SECONDARY = "tripwire-test-1", "ceiling-ext"
TEST_BATCHES = (PRIMARY, SECONDARY)
EXPECTED_RUNS = {PRIMARY: 360, SECONDARY: 80}  # plan step 10 (360 = 200 canaries + 80 controls + 80 shams)
PRIMARY_POOL, PRIMARY_SEED = Path("data") / "calibration" / "pool-2.json", 1114  # the dry plan of section 4
PLANS_SUBDIR = Path("data") / "sealed_plans"  # = sealed.PLANS_DIR under ROOT
# What decides which runs a batch holds. Left out: the batch name, the role, the pool's file name, the no-audit flag.
SLOT_KEYS = ("seed", "runs", "split", "length_match", "decoys", "length_target", "bases", "slots")
PLAN = ROOT / "docs" / "plans" / "tripwire_test.md"
RECORDS_DIR = DATA_DIR / "tripwires" / "test"
LOG_PATH = DATA_DIR / "tripwires" / "test.log"
OUT_DIR = dev.OUT_DIR
ARM_L_RESULT = ceiling.OUT_DIR / "arm_L.json"  # ceiling-ext only after `eval.ceiling --arm L` has run
LABEL = "known shapes, fresh bases"
SPECIFICITY_BAR, RECALL_BAR = 0.95, 0.90  # Beta 90% lower bounds (trust.INTERVAL_PERCENTILES, 5th percentile)
NOT_CHAIN = {("B09", classes.OBVIOUS), ("B09", classes.SUBTLE), dev.RULE_VARIANT}
# Files the lock must list: the tripwire code, the scoring, and this script (plan step 9 names the first four).
MUST_FREEZE = ("canary/probe.py", "canary/replay.py", "canary/tripwires.py", "eval/tripwires_test.py",
               "eval/tripwires_dev.py")
SECTION = re.compile(r"^## 3\..*?(?=^## )", re.S | re.M)
ENTRY = re.compile(r"^- `([^`]+)` ([0-9a-f]{64})\b", re.M)
SLOT_LOCK = re.compile(r"^- Slot list `([\w.-]+)` ([0-9a-f]{64})\b", re.M)  # in section 4, outside section 3
NOT_LOCKED = "the plan is NOT LOCKED (no .sha256 file)"


class Refused(RuntimeError):
    """The test may not run (wrong batch, lock broken, already run, batch incomplete)."""


# ---- The lock ------------------------------------------------------------------------------------------------------

def lf_sha256(path: Path) -> str:
    """SHA-256 of the file with CRLF turned into LF: the bytes git stores, whatever the checkout's line endings."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def lock_path(plan: Path) -> Path:
    return plan.with_name(plan.name + ".sha256")


def plan_entries(text: str) -> list[tuple[str, str]]:
    """(path, SHA-256) for every frozen file listed in the plan's section 3."""
    section = SECTION.search(text)
    if not section:
        raise ValueError("the plan has no section 3 (frozen inputs)")
    return ENTRY.findall(section.group(0))


def file_problems(plan: Path = PLAN, root: Path = ROOT) -> list[str]:
    """One line per problem with the frozen files (missing, changed, or a required file not listed)."""
    if not plan.exists():
        return [f"{plan.name}: missing"]
    entries = plan_entries(plan.read_text(encoding="utf-8"))
    problems = [f"{name}: not listed in section 3" for name in MUST_FREEZE if name not in dict(entries)]
    for name, digest in entries:
        file = root / name
        if not file.exists():
            problems.append(f"{name}: missing")
        elif lf_sha256(file) != digest:
            problems.append(f"{name}: hash differs from the plan")
    return problems


def slots_sha256(batch_plan: dict) -> str:
    """SHA-256 of what decides a batch's runs (SLOT_KEYS), as canonical JSON: equal plans give equal hashes."""
    core = {key: batch_plan.get(key) for key in SLOT_KEYS}
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def dry_plan_sha256(root: Path = ROOT) -> str:
    """The slot-list hash of the primary batch as `calibrate` will plan it (mixer.plan_batch, pool 2, seed 1114, 360
    runs, default role). Computed here so `--check` catches a change in the planning code before an hour of building."""
    from canary import mixer  # plans only: no model is loaded or called
    pool = json.loads((root / PRIMARY_POOL).read_text(encoding="utf-8"))
    return slots_sha256(mixer.plan_batch(PRIMARY, EXPECTED_RUNS[PRIMARY], pool, PRIMARY_SEED))


def stored_plan(batch: str, root: Path = ROOT) -> dict | None:
    path = root / PLANS_SUBDIR / f"{batch}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def slot_problems(text: str, root: Path = ROOT) -> list[str]:
    """The slot-list locks of section 4: listed for both batches, the primary's dry plan still reproduces its hash,
    and every stored batch plan that exists matches its lock."""
    locked = dict(SLOT_LOCK.findall(text))
    problems = [f"slot list of {b}: not listed in section 4" for b in TEST_BATCHES if b not in locked]
    if PRIMARY in locked and (root / PRIMARY_POOL).exists() and dry_plan_sha256(root) != locked[PRIMARY]:
        problems.append(f"slot list of {PRIMARY}: the dry plan (pool 2, seed {PRIMARY_SEED}, "
                        f"{EXPECTED_RUNS[PRIMARY]} runs) no longer gives the locked hash")
    for batch, digest in locked.items():
        stored = stored_plan(batch, root)
        if stored is not None and slots_sha256(stored) != digest:
            problems.append(f"slot list of {batch}: the stored batch plan differs from the locked one")
    return problems


def lock_problems(plan: Path = PLAN, root: Path = ROOT) -> list[str]:
    """Everything that stops the test: file problems, slot-list problems, no lock, or a plan edited after the lock."""
    problems = file_problems(plan, root)
    if plan.exists():
        problems += slot_problems(plan.read_text(encoding="utf-8"), root)
    lock = lock_path(plan)
    if not lock.exists():
        return problems + [NOT_LOCKED]
    if plan.exists() and lock.read_text(encoding="utf-8").split()[0] != lf_sha256(plan):
        problems.append(f"{plan.name}: edited after it was locked (hash differs from {lock.name})")
    return problems


def write_lock(plan: Path = PLAN, root: Path = ROOT) -> str:
    """Write the plan's .sha256. Refuses a plan still marked DRAFT or any file problem: lock only what was checked."""
    problems = file_problems(plan, root)
    if not problems:
        problems = slot_problems(plan.read_text(encoding="utf-8"), root)
    if problems:
        raise Refused("; ".join(problems))
    if "DRAFT" in plan.read_text(encoding="utf-8").splitlines()[0]:
        raise Refused(f"{plan.name} is still a DRAFT (its title line says so); the student's OK comes first")
    lock = lock_path(plan)
    if lock.exists():
        raise Refused(f"{lock.name} exists already: a locked plan is changed only by an amendment")
    digest = lf_sha256(plan)
    lock.write_bytes(f"{digest}  {plan.name}\n".encode("utf-8"))
    return digest


# ---- Line endings against git (plan step 9) ------------------------------------------------------------------------

def _git(args: list[str], root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=60)


def git_blob(name: str, root: Path = ROOT) -> bytes | None:
    """The file's bytes as committed at HEAD, or None when git does not track it."""
    result = _git(["cat-file", "blob", f"HEAD:{name}"], root)
    return result.stdout if result.returncode == 0 else None


def git_text_attr(name: str, root: Path = ROOT) -> str:
    """The `text` attribute git gives the path: 'unset' when .gitattributes says -text."""
    out = _git(["check-attr", "text", "--", name], root).stdout.decode("utf-8", "replace").strip()
    return out.rsplit(": ", 1)[-1] if out else "unknown"


def line_ending_rows(plan: Path = PLAN, root: Path = ROOT, blob=git_blob, attr=git_text_attr) -> list[dict]:
    """Per frozen file: in git?, -text?, working copy byte-identical to the HEAD blob?, listed hash = SHA-256 of it?"""
    rows = []
    for name, digest in plan_entries(plan.read_text(encoding="utf-8")):
        committed = blob(name, root)
        row = {"file": name, "in_git": committed is not None}
        if committed is not None:
            file = root / name
            row.update(minus_text=attr(name, root) == "unset",
                       working_is_blob=file.exists() and file.read_bytes() == committed,
                       hash_is_blob=hashlib.sha256(committed).hexdigest() == digest)
        rows.append(row)
    return rows


def line_endings_ok(rows: list[dict]) -> bool:
    return all(r["minus_text"] and r["working_is_blob"] and r["hash_is_blob"] for r in rows if r["in_git"])


def sync_lf(plan: Path = PLAN, root: Path = ROOT, blob=git_blob) -> list[str]:
    """Rewrite each frozen file in git whose working copy differs from its HEAD blob ONLY in line endings, with the
    blob's bytes. Refuses before writing anything if any file differs in content. Returns the files rewritten."""
    todo, problems = [], []
    for name, _ in plan_entries(plan.read_text(encoding="utf-8")):
        committed = blob(name, root)
        if committed is None:
            continue
        current = (root / name).read_bytes()
        if current == committed:
            continue
        if current.replace(b"\r\n", b"\n") != committed:
            problems.append(f"{name}: differs from HEAD in content, not only line endings (commit or revert it first)")
        todo.append((name, committed))
    if problems:
        raise Refused("; ".join(problems))
    for name, committed in todo:
        (root / name).write_bytes(committed)
    return [name for name, _ in todo]


# ---- The bars ------------------------------------------------------------------------------------------------------

def in_chain(bug_id: str | None, tier: str | None) -> bool:
    """A canary whose bug a chain check is meant to fire on (not B09, not the L1 rule)."""
    return bug_id is not None and (bug_id, tier) not in NOT_CHAIN


def bars(records: dict, truths: list[sealed.Truth], clusters: dict[str, str], decides: bool,
         draws: int = dev.DRAWS) -> dict:
    """Both bars from the records and the truth. A run without a record counts against (fail closed)."""
    chain = [t for t in truths if t.run_type == sealed.CANARY_MEASURE and in_chain(t.bug_id, t.tier)]
    clean = [t for t in truths if t.run_type in dev.CLEAN_TYPES]
    fired = {t.run_id: records.get(t.run_id) is not None and dev._fired(records[t.run_id]) for t in chain}
    passed = {t.run_id: records.get(t.run_id) is not None and records[t.run_id]["verdict"] == "pass" for t in clean}
    recall = dev._posterior(sum(fired.values()), len(chain))
    specificity = dev._posterior(sum(passed.values()), len(clean))
    rows = ([{"cluster": clusters.get(r, r), "buggy": True, "flagged": f} for r, f in fired.items()]
            + [{"cluster": clusters.get(r, r), "buggy": False, "flagged": not p} for r, p in passed.items()])
    recall_ok = bool(chain) and recall["beta_90"][0] >= RECALL_BAR
    specificity_ok = bool(clean) and specificity["beta_90"][0] >= SPECIFICITY_BAR
    return {
        "decides": decides,
        "chain_classes": "every canary except B09 (both tiers) and B06 obvious",
        "chain_canaries": len(chain),
        "chain_by_variant": {f"{b} {t}": sum(1 for x in chain if (x.bug_id, x.tier) == (b, t))
                             for b, t in sorted({(x.bug_id, x.tier) for x in chain})},
        "recall_fired_chain": {**recall, "bar": RECALL_BAR, "meets_bar": recall_ok,
                               "missed_runs": sorted(r for r, f in fired.items() if not f)},
        "specificity": {**specificity, "bar": SPECIFICITY_BAR, "meets_bar": specificity_ok,
                        "false_alarm_runs": sorted(r for r, p in passed.items() if not p)},
        "base_level_beside": dev.base_bootstrap(rows, draws) if chain and clean else None,
        "outcome": ("PASSED" if recall_ok and specificity_ok else "FAILED") if decides else "reported only",
    }


def format_bars(b: dict) -> str:
    r, s = b["recall_fired_chain"], b["specificity"]
    bl = b["base_level_beside"] or {}
    lines = [f"chain-class fired recall: {r['successes']}/{r['n']}, Beta 90% lower bound {r['beta_90'][0]:.4f} "
             f"(bar {r['bar']:.2f}: {'met' if r['meets_bar'] else 'NOT met'})",
             f"specificity: {s['successes']}/{s['n']}, Beta 90% lower bound {s['beta_90'][0]:.4f} "
             f"(bar {s['bar']:.2f}: {'met' if s['meets_bar'] else 'NOT met'})"]
    if bl.get("recall_90"):
        lines.append(f"beside (decides nothing): base-level 90% recall {bl['recall_90'][0]:.2f}-{bl['recall_90'][1]:.2f}, "
                     f"specificity {bl['specificity_90'][0]:.2f}-{bl['specificity_90'][1]:.2f} ({bl['clusters']} clusters)")
    lines.append(f"TEST {b['outcome']}" if b["decides"] else "secondary batch: reported only, decides nothing")
    return "\n".join(lines)


# ---- The run -------------------------------------------------------------------------------------------------------

def out_path(batch: str, out_dir: Path = OUT_DIR) -> Path:
    return out_dir / f"test_{batch}.json"


def batch_truths(table: sealed.SealedTable, batch: str) -> list[sealed.Truth]:
    return sorted((t for t in table.all() if t.details.get("batch") == batch and t.run_type in dev.SCORED_TYPES),
                  key=lambda t: t.run_id)


def slot_truths(batch: str, table: sealed.SealedTable, batch_plan: dict) -> tuple[list[sealed.Truth], list[str], list[str]]:
    """One truth per planned slot, in slot order, plus (stand-ins for slots never built, superseded runs).

    A slot's sealed run is the latest one: a run sealed just before a crash never reached the ledger, so `calibrate
    --resume` ran its slot again and the later run is the one the batch holds. A slot with no sealed run (no base
    fitted, or the build failed) gets a stand-in with no run folder, so it has no record and counts against both bars.
    """
    latest: dict[int, sealed.Truth] = {}
    superseded = []
    for truth in sorted(batch_truths(table, batch), key=lambda t: t.created_at):
        slot = truth.details.get("slot")
        if slot in latest:
            superseded.append(latest[slot].run_id)
        latest[slot] = truth
    planned = {s["slot"]: s for s in batch_plan["slots"]}
    stray = sorted(t.run_id for slot, t in latest.items() if slot not in planned)
    if stray:
        raise Refused(f"{batch}: sealed runs with no planned slot: {', '.join(stray)}")
    truths, not_built = [], []
    for number in sorted(planned):
        slot = planned[number]
        truth = latest.get(number)
        if truth is None:
            stand_in = f"not-built-slot-{number:03d}"
            truths.append(sealed.Truth(stand_in, slot["run_type"], slot["bug_id"], slot["tier"], None,
                                       f"pool:{slot['candidates'][0]}",
                                       {"batch": batch, "slot": number, "not_built": True}, ""))
            not_built.append(stand_in)
            continue
        if (truth.run_type, truth.bug_id, truth.tier) != (slot["run_type"], slot["bug_id"], slot["tier"]):
            raise Refused(f"{batch}: run {truth.run_id} of slot {number} is not the slot's planned type")
        truths.append(truth)
    return truths, not_built, sorted(superseded)


def preflight(batch: str, table: sealed.SealedTable, plan: Path = PLAN, root: Path = ROOT,
              out_dir: Path = OUT_DIR, arm_l: Path = ARM_L_RESULT) -> tuple[list[sealed.Truth], list[str], list[str]]:
    """Every refusal, before any replay. Returns `slot_truths` of the batch."""
    if batch not in TEST_BATCHES:
        raise Refused(f"{batch!r} is not a test batch; only {', '.join(TEST_BATCHES)}")
    problems = lock_problems(plan, root)
    if problems:
        raise Refused("lock: " + "; ".join(problems))
    if out_path(batch, out_dir).exists():
        raise Refused(f"{out_path(batch, out_dir).name} exists: the test of {batch} has run; it runs once")
    if batch == SECONDARY and not arm_l.exists():
        raise Refused("ceiling-ext only after `eval.ceiling --arm L` has run")
    batch_plan = stored_plan(batch, root)
    if batch_plan is None:
        raise Refused(f"{batch} has no stored batch plan; build it first (plan step 10)")
    if len(batch_plan["slots"]) != EXPECTED_RUNS[batch] or batch_plan.get("runs") != EXPECTED_RUNS[batch]:
        raise Refused(f"{batch} plans {len(batch_plan['slots'])} slots, the lock plan says {EXPECTED_RUNS[batch]}")
    if batch == PRIMARY and not batch_plan.get("no_audit"):
        raise Refused(f"{batch} was planned with audits; it must be built with --no-audit (no LLM ever reviews it)")
    gate = root / PLANS_SUBDIR / f"{batch}.length_check.json"
    if not gate.exists():
        raise Refused(f"{batch}: the build has not finished (no length-gate file); resume it: python -m canary.cli "
                      f"calibrate --batch {batch} --resume --no-audit")
    if not json.loads(gate.read_text(encoding="utf-8")).get("passes"):
        raise Refused(f"{batch}: its length gate failed; stop rule (plan section 7): report, amend before any replay")
    return slot_truths(batch, table, batch_plan)


def run_test(batch: str, workers: int = 4, table: sealed.SealedTable | None = None, inspect=tripwires.run_tripwires,
             runs_dir: Path | None = None, records_dir: Path = RECORDS_DIR, log_path: Path = LOG_PATH,
             plan: Path = PLAN, root: Path = ROOT, out_dir: Path = OUT_DIR, arm_l: Path = ARM_L_RESULT,
             draws: int = dev.DRAWS) -> dict:
    table = table or sealed.SealedTable()
    truths, not_built, superseded = preflight(batch, table, plan, root, out_dir, arm_l)
    started = time.perf_counter()
    records = dev.inspect_runs(batch, [t.run_id for t in truths if t.run_id not in not_built],
                               runs_dir or sandbox.RUNS_DIR, records_dir / batch, log_path, workers, inspect)
    records.update({stand_in: None for stand_in in not_built})  # no record: counts against both bars
    clusters = {t.run_id: ceiling.cluster_labels(batch, t.source, t.run_id)[0] for t in truths}
    result = dev.score(records, truths, clusters, sorted(classes.catalog()), draws)
    result = {"batch": batch, "tripwire_version": tripwires.source_version(), "plan_sha256": lf_sha256(plan),
              "generated_at": datetime.now(timezone.utc).isoformat(), "wall_seconds": time.perf_counter() - started,
              "slot_list_sha256": slots_sha256(stored_plan(batch, root)), "not_built_slots": not_built,
              "superseded_runs": superseded,
              **result, "label": LABEL, "bars": bars(records, truths, clusters, batch == PRIMARY, draws)}
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path(batch, out_dir).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.tripwires_test", description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="check every hash of the lock plan")
    mode.add_argument("--lock", action="store_true", help="write the plan's .sha256 (after the student's OK)")
    mode.add_argument("--batch", help=f"one of {', '.join(TEST_BATCHES)}; runs once")
    mode.add_argument("--git-check", action="store_true", help="line endings of the frozen files against git HEAD")
    mode.add_argument("--sync-lf", action="store_true",
                      help="make frozen working copies byte-identical to git HEAD (line endings only)")
    parser.add_argument("--workers", type=int, default=4, help="replays at the same time (each is its own process)")
    args = parser.parse_args(argv)
    if args.check:
        problems = lock_problems()
        for line in problems:
            print(f"  {line}")
        if problems == [NOT_LOCKED]:
            print("Tripwire lock check: hashes OK, plan NOT LOCKED (draft)")
            return 1
        print("Tripwire lock check: OK" if not problems else "Tripwire lock check: FAILED")
        return 0 if not problems else 1
    if args.git_check:
        rows = line_ending_rows()
        for r in rows:
            print(f"  {r['file']}: " + ("outside git (hashed as on disk)" if not r["in_git"] else
                  f"-text {'yes' if r['minus_text'] else 'NO'}, working copy = HEAD blob "
                  f"{'yes' if r['working_is_blob'] else 'NO'}, listed hash = SHA-256 of HEAD blob "
                  f"{'yes' if r['hash_is_blob'] else 'NO'}"))
        print("Line endings: OK" if line_endings_ok(rows) else "Line endings: NOT OK")
        return 0 if line_endings_ok(rows) else 1
    try:
        if args.sync_lf:
            changed = sync_lf()
            print(f"rewritten with the HEAD bytes: {', '.join(changed) or 'none (all identical)'}")
            return 0
        if args.lock:
            print(f"locked: {PLAN.name} {write_lock()}")
            return 0
        result = run_test(args.batch, args.workers)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(dev.format_table(result))
    print(format_bars(result["bars"]))
    print(f"written: {out_path(args.batch).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
