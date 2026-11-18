"""Mission 5.1 locked test: the frozen tripwires, run once on each test batch, judged against bars fixed beforehand.

    python -m eval.tripwires_test --check                     every hash in the lock plan; is the plan locked?
    python -m eval.tripwires_test --lock                      write the plan's .sha256 (after the student's OK only)
    python -m eval.tripwires_test --batch tripwire-test-1     the test, once (then --batch ceiling-ext)

Why (docs/plans/mission_5_1_tripwires.md, section 7.2 and step 9): the tripwires were built while looking at the
development batches, so their numbers there say little. The test is the first look at runs the tripwire code has
never met: fresh pool-2 bases. It counts only if the code that makes and scores the records is exactly the code that
was frozen before the batch existed, and only once. So this script:
- refuses any batch but `tripwire-test-1` (primary) and `ceiling-ext` (secondary, only after `eval.ceiling --arm L`);
- refuses unless the lock plan `docs/plans/tripwire_test.md` has its `.sha256` and every file listed in its section 3
  still hashes to the listed value (line endings normalised to LF, so a Windows checkout does not change a hash);
- refuses a batch whose result file already exists: the test runs once. An interrupted run resumes from its stored
  records (same frozen version) until the result is written;
- refuses a batch whose run count differs from the plan's, so a half-built batch is never scored.

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


def lock_problems(plan: Path = PLAN, root: Path = ROOT) -> list[str]:
    """Everything that stops the test: file problems, no lock, or a plan edited after it was locked."""
    problems = file_problems(plan, root)
    lock = lock_path(plan)
    if not lock.exists():
        return problems + [NOT_LOCKED]
    if plan.exists() and lock.read_text(encoding="utf-8").split()[0] != lf_sha256(plan):
        problems.append(f"{plan.name}: edited after it was locked (hash differs from {lock.name})")
    return problems


def write_lock(plan: Path = PLAN, root: Path = ROOT) -> str:
    """Write the plan's .sha256. Refuses a plan still marked DRAFT or any file problem: lock only what was checked."""
    problems = file_problems(plan, root)
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


def preflight(batch: str, table: sealed.SealedTable, plan: Path = PLAN, root: Path = ROOT,
              out_dir: Path = OUT_DIR, arm_l: Path = ARM_L_RESULT) -> list[sealed.Truth]:
    """Every refusal, before any replay. Returns the batch's scored runs."""
    if batch not in TEST_BATCHES:
        raise Refused(f"{batch!r} is not a test batch; only {', '.join(TEST_BATCHES)}")
    problems = lock_problems(plan, root)
    if problems:
        raise Refused("lock: " + "; ".join(problems))
    if out_path(batch, out_dir).exists():
        raise Refused(f"{out_path(batch, out_dir).name} exists: the test of {batch} has run; it runs once")
    if batch == SECONDARY and not arm_l.exists():
        raise Refused("ceiling-ext only after `eval.ceiling --arm L` has run")
    truths = batch_truths(table, batch)
    if len(truths) != EXPECTED_RUNS[batch]:
        raise Refused(f"{batch} has {len(truths)} scored runs, the plan says {EXPECTED_RUNS[batch]}; finish the batch "
                      f"(calibrate --resume) or amend the plan")
    return truths


def run_test(batch: str, workers: int = 4, table: sealed.SealedTable | None = None, inspect=tripwires.run_tripwires,
             runs_dir: Path | None = None, records_dir: Path = RECORDS_DIR, log_path: Path = LOG_PATH,
             plan: Path = PLAN, root: Path = ROOT, out_dir: Path = OUT_DIR, arm_l: Path = ARM_L_RESULT,
             draws: int = dev.DRAWS) -> dict:
    table = table or sealed.SealedTable()
    truths = preflight(batch, table, plan, root, out_dir, arm_l)
    started = time.perf_counter()
    records = dev.inspect_runs(batch, [t.run_id for t in truths], runs_dir or sandbox.RUNS_DIR, records_dir / batch,
                               log_path, workers, inspect)
    clusters = {t.run_id: ceiling.cluster_labels(batch, t.source, t.run_id)[0] for t in truths}
    result = dev.score(records, truths, clusters, sorted(classes.catalog()), draws)
    result = {"batch": batch, "tripwire_version": tripwires.source_version(), "plan_sha256": lf_sha256(plan),
              "generated_at": datetime.now(timezone.utc).isoformat(), "wall_seconds": time.perf_counter() - started,
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
    try:
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
