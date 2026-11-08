"""The run mixer: plan a blinded batch of canaries, controls and shams, run it, and have the Skeptic review it.

Why clones of Scientist proposals: a canary must look like a real run in every way but the planted difference. Left
free, the Scientist proposes nearly one experiment, so the pool asks it for one proposal per fixed choice of dataset,
metric and model. Otherwise recall would only describe the reviewer on that one experiment.

Why the order is shuffled before anything is reviewed: reviews happen one after another, so if the reviewer or the
machine changed part-way, a fixed order would turn that change into a false difference between run types.

Why a clone is run before it is locked: a bug can change the config (B06, B09), and the pre-registration must describe
the config that really ran. So a clone's lock is bookkeeping. Real runs still lock first (scientist.run_locked).

This module knows run types, so it must never be imported by the reviewer's code (tests/test_skeptic.py checks).
Nothing here is written to the log or the ledger that would reveal a slot's type.
"""
from __future__ import annotations

import json
import random
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from canary import (codegen, controls, ledger, llm, padding, prereg, review_tasks, sandbox, scientist, sealed,
                    separation, skeptic)
from canary.config import DATA_DIR, load_yaml
from canary.saboteur.classes import IMBALANCE_RATIO, NotApplicable, class_counts, why_not_applicable
from canary.saboteur.transforms import TRANSFORMS, TransformError, sabotage

POOL_PATH = DATA_DIR / "calibration" / "pool.json"
CANARY_SHARE = 5 / 9  # 100 of 180: the canaries for 10 per class, plus 40 controls and 40 shams
METRIC_ORDER = ("balanced_accuracy", "f1", "roc_auc", "accuracy")


class MixerError(RuntimeError):
    """The batch cannot be planned or continued as asked."""


def split_runs(runs: int, variants: int = len(TRANSFORMS)) -> dict[str, int]:
    """Divide N runs. Canaries are a whole multiple of the variants, so every class and tier appears equally often."""
    canaries = max(variants, round(runs * CANARY_SHARE / variants) * variants)
    rest = runs - canaries
    if rest < 2:
        raise MixerError(f"{runs} runs leave too few for controls and shams after {canaries} canaries")
    return {sealed.CANARY_MEASURE: canaries, sealed.CONTROL: rest // 2, sealed.SHAM: rest - rest // 2}


def focus_grid(datasets: list[dict], models: list[str], rounds: int, balance: dict[str, float] | None = None) -> list[dict]:
    """The fixed choices for the pool, rotating metric and model so that no dataset is tied to one of either.

    Accuracy is skipped on imbalanced data (the clean base would already be bug B06), and roc_auc on multiclass data
    (the template refuses it).
    """
    grid = []
    for index in range(rounds * len(datasets)):
        dataset = datasets[index % len(datasets)]
        ratio = (balance or {}).get(dataset["name"], 1.0)
        metrics = [m for m in METRIC_ORDER
                   if not (m == "roc_auc" and dataset["classes"] != 2) and not (m == "accuracy" and ratio > IMBALANCE_RATIO)]
        grid.append({"dataset": dataset["name"], "metric": metrics[index % len(metrics)], "model": models[index % len(models)]})
    return grid


def _log(log_path: Path, message: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def pool_keys(pool: dict) -> set[str]:
    """What each base runs, ignoring wording and seeds: two pools share a base if they share a key."""
    return {scientist._experiment_key(b["prereg"]) for b in pool["bases"]}


def build_pool(client: llm.LLM, led: ledger.Ledger, table: sealed.SealedTable, path: Path = POOL_PATH,
               log_path: Path = sandbox.RUNS_DIR / "campaign.log", avoid_pool: dict | None = None) -> dict:
    """Ask the Scientist for each focus and keep the proposals that are clean and really run.

    Trial runs use a temporary folder and nothing goes in the ledger: a pool entry is raw material, not an experiment.
    `avoid_pool` is an earlier pool: the same fixed grid is asked again, and no base of it may come back (checked by
    code, and raised as MixerError if one slips through).
    """
    avoid = [b["prereg"] for b in avoid_pool["bases"]] if avoid_pool else None
    settings = load_yaml("campaign.yaml")["calibrate"]
    catalog = load_yaml("datasets.yaml")
    datasets = catalog["sklearn"] + catalog["openml"]
    balance = {}
    for dataset in datasets:
        counts = class_counts(dataset["name"])
        balance[dataset["name"]] = max(counts) / min(counts)
    grid = focus_grid(datasets, sorted(codegen.MODELS), settings["grid_rounds"], balance)
    bases, dropped = [], []
    with tempfile.TemporaryDirectory() as folder:
        for number, focus in enumerate(grid, 1):
            label = f"{focus['dataset']} / {focus['metric']} / {focus['model']}"
            try:
                locked, model = scientist.propose(client, settings["question"], led, table, focus, avoid)
            except (scientist.ProposalRejected, llm.LLMError) as exc:
                dropped.append({"focus": focus, "reason": str(exc)})
                _log(log_path, f"pool {number}/{len(grid)} dropped {label}: {exc}")
                continue
            config = prereg.to_run_config(locked)
            reason = controls.why_not_clean(config)
            record = None if reason else sandbox.run_config(config, Path(folder))
            if reason or record["status"] != sandbox.STATUS_OK:
                reason = reason or f"trial run {record['status']}: {record['reason']}"
                dropped.append({"focus": focus, "reason": reason})
                _log(log_path, f"pool {number}/{len(grid)} dropped {label}: {reason}")
                continue
            bases.append({"focus": focus, "prereg": locked, "model": model, "trial_seconds": record["seconds"]})
            _log(log_path, f"pool {number}/{len(grid)} kept {label} ({record['seconds']:.0f} s trial)")
    pool = {"bases": bases, "dropped": dropped}
    if avoid_pool and pool_keys(pool) & pool_keys(avoid_pool):
        raise MixerError("the new pool repeats a base of the pool it had to avoid")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pool, indent=1), encoding="utf-8")
    return pool


def _usable(run_type: str, bug: str | None, tier: str | None, base: dict) -> bool:
    config = prereg.to_run_config(base["prereg"])
    if controls.why_not_clean(config):
        return False
    return run_type != sealed.CANARY_MEASURE or why_not_applicable(bug, tier, config) is None


def plan_batch(batch: str, runs: int, pool: dict, seed: int, length_match: bool = True,
               role: str = skeptic.DEFAULT_ROLE) -> dict:
    """Assign every slot a type and an ordered list of bases to try, then shuffle the slots.

    Each kind of slot walks through its usable bases in turn, so clones spread over experiments. The later bases on
    a slot's list are fallbacks for a bug that turns out not to fit, which only trying it can show (B09 subtle).
    Raises MixerError if some variant has no usable base: dropping it silently would leave a class untested.
    `length_match` pads every run to a length drawn independently of its type (canary/padding.py); plans written
    before it existed have no such key and run unpadded on resume. `role` is the reviewer that audits the batch.
    """
    rng = random.Random(seed)
    split = split_runs(runs)
    bases = pool["bases"]
    wanted: list[tuple[str, str | None, str | None]] = []
    variants = sorted(TRANSFORMS)
    per_variant = split[sealed.CANARY_MEASURE] // len(variants)
    wanted += [(sealed.CANARY_MEASURE, bug, tier) for bug, tier in variants for _ in range(per_variant)]
    wanted += [(sealed.CONTROL, None, None)] * split[sealed.CONTROL]
    wanted += [(sealed.SHAM, None, None)] * split[sealed.SHAM]

    usable_cache: dict[tuple, list[int]] = {}
    turn: dict[tuple, int] = {}
    slots = []
    for run_type, bug, tier in wanted:
        key = (run_type, bug, tier)
        if key not in usable_cache:
            usable_cache[key] = [i for i, base in enumerate(bases) if _usable(run_type, bug, tier, base)]
            if not usable_cache[key]:
                raise MixerError(f"no base in the pool fits {run_type} {bug or ''} {tier or ''}")
            rng.shuffle(usable_cache[key])
        usable = usable_cache[key]
        start = turn.get(key, 0)
        turn[key] = start + 1
        order = [usable[(start + offset) % len(usable)] for offset in range(len(usable))]
        slots.append({"run_type": run_type, "bug_id": bug, "tier": tier, "candidates": order})
    rng.shuffle(slots)
    for number, slot in enumerate(slots):
        slot["slot"] = number
    plan = {"batch": batch, "seed": seed, "runs": runs, "split": split, "bases": bases, "slots": slots,
            "length_match": length_match, "role": role}
    if length_match:
        target = padding.batch_target([prereg.to_run_config(b["prereg"]) for b in bases])
        plan["length_target"] = {"lines": target.lines, "chars": target.chars}
    return plan


def _padder(plan: dict, slot: dict, attempt: int) -> padding.Padder | None:
    """The slot's padder: the batch's one target, and an RNG stream seeded without the run type."""
    if not plan.get("length_match"):
        return None
    target = padding.Target(plan["length_target"]["lines"], plan["length_target"]["chars"])
    return padding.Padder(target, random.Random(f"{plan['seed']}:{slot['slot']}:{attempt}:pad"))


def plan_path(batch: str, plans_dir: Path = sealed.PLANS_DIR) -> Path:
    return plans_dir / f"{batch}.json"


def _run_slot(slot: dict, plan: dict, table: sealed.SealedTable, runs_dir: Path, twin_dir: Path) -> tuple[dict, dict, dict] | None:
    """Run one slot on the first base that fits. Returns (locked record, run record, base), or None if none fits."""
    extra = {"batch": plan["batch"], "slot": slot["slot"]}
    run_type = slot["run_type"]
    for attempt, index in enumerate(slot["candidates"]):
        base = plan["bases"][index]
        rng = random.Random(f"{plan['seed']}:{slot['slot']}:{attempt}")
        padder = _padder(plan, slot, attempt)
        clone = controls.clone_config(prereg.to_run_config(base["prereg"]), rng)
        source = f"pool:{index}"
        try:
            # Checked before running, so a refusal leaves no sealed run behind.
            if run_type == sealed.CANARY_MEASURE:
                controls.clone_prereg(base["prereg"], sabotage(clone, slot["bug_id"], slot["tier"]).config)
            else:
                controls.clone_prereg(base["prereg"], clone)
            if run_type == sealed.CANARY_MEASURE:
                canary = controls.run_canary(clone, slot["bug_id"], slot["tier"], table, runs_dir, twin_dir, source,
                                             extra=extra, padder=padder)
                # The run's own record: `canary.status` also reports a failed twin, but this run may still be reviewable.
                record = json.loads((runs_dir / canary.run_id / sandbox.RECORD_NAME).read_text(encoding="utf-8"))
                return controls.clone_prereg(base["prereg"], canary.config), record, base
            if run_type == sealed.CONTROL:
                return (controls.clone_prereg(base["prereg"], clone),
                        controls.run_control(clone, table, runs_dir, source, extra, padder), base)
            return (controls.clone_prereg(base["prereg"], clone),
                    controls.run_sham(clone, table, rng, runs_dir, source, extra, padder), base)
        except (NotApplicable, TransformError):
            continue
    return None


def execute_slot(slot: dict, plan: dict, led: ledger.Ledger, table: sealed.SealedTable, runs_dir: Path, twin_dir: Path) -> bool:
    """Run a slot and enter it in the ledger exactly like a real run. Returns False if no base could take it."""
    outcome = _run_slot(slot, plan, table, runs_dir, twin_dir)
    if outcome is None:
        return False
    locked, record, base = outcome
    hypothesis_id = str(uuid.uuid4())
    digest = prereg.prereg_hash(locked)
    led.append(hypothesis_id, ledger.PROPOSED, {"hypothesis": locked["hypothesis"], "model": base["model"]})
    led.append(hypothesis_id, ledger.PREREGISTERED, {"prereg": locked, "prereg_sha256": digest})
    scientist.record_ran(led, hypothesis_id, locked, digest, record, runs_dir)
    return True


def finished_slots(batch: str, led: ledger.Ledger, table: sealed.SealedTable) -> set[int]:
    """Slots whose run reached the ledger. A run sealed just before a crash has no ledger entry, so its slot runs again."""
    in_ledger = {e.payload["run_id"] for e in led.entries(ledger.RAN)}
    return {t.details["slot"] for t in table.all() if t.details.get("batch") == batch and t.run_id in in_ledger}


def run_batch(client: llm.LLM, plan: dict, led: ledger.Ledger, table: sealed.SealedTable,
              runs_dir: Path = sandbox.RUNS_DIR, twin_dir: Path = controls.TWINS_DIR, plans_dir: Path = sealed.PLANS_DIR,
              log_path: Path | None = None) -> skeptic.AuditReport:
    """Run every unfinished slot, then review everything waiting. Safe to call again after any interruption."""
    log_path = log_path or runs_dir / "campaign.log"
    batch = plan["batch"]
    finished = finished_slots(batch, led, table)
    timings = plans_dir / f"{batch}.timing.jsonl"
    timings.parent.mkdir(parents=True, exist_ok=True)
    waiting = [s for s in plan["slots"] if s["slot"] not in finished]
    _log(log_path, f"batch {batch}: {len(plan['slots'])} slots, {len(waiting)} to run")
    for number, slot in enumerate(waiting, 1):
        started = time.perf_counter()
        ran = execute_slot(slot, plan, led, table, runs_dir, twin_dir)
        seconds = time.perf_counter() - started
        with timings.open("a", encoding="utf-8") as handle:  # names the type, so it stays beside the plan and off the log
            handle.write(json.dumps({"stage": "run", "slot": slot["slot"], "run_type": slot["run_type"],
                                     "bug_id": slot["bug_id"], "tier": slot["tier"], "ran": ran,
                                     "seconds": round(seconds, 2)}) + "\n")
        _log(log_path, f"batch {batch}: run {number}/{len(waiting)} {'done' if ran else 'SKIPPED, no base fits'} in {seconds:.1f} s")

    role = plan.get("role", skeptic.DEFAULT_ROLE)
    if plan.get("length_match"):
        check = batch_length_check(client, led, table, batch, role, runs_dir)
        (plans_dir / f"{batch}.length_check.json").write_text(json.dumps(check, indent=1), encoding="utf-8")
        _log(log_path, f"batch {batch}: length gate {'passed' if check['passes'] else 'FAILED'} ({gate_text(check)})")
        if not check["passes"]:
            return skeptic.AuditReport(stopped=f"length gate failed ({gate_text(check)}); nothing was audited")
    return _audit_and_log(client, led, batch, runs_dir, log_path, role, batch_run_ids(table, batch))


# ---- The length gate: blinded size must not give a run's type away (see canary/padding.py) ----

def gate_text(check: dict) -> str:
    parts = [f"{name} AUC {f['value']:.3f}, base 90% [{f['interval_90_base'][0]:.2f}, {f['interval_90_base'][1]:.2f}]"
             for name, f in check["features"].items() if f["value"] is not None and f["interval_90_base"]]
    if check.get("prompts_too_large"):
        parts.append(f"{check['prompts_too_large']} prompts too large")
    return "; ".join(parts) or "nothing to measure"


def batch_length_check(client: llm.LLM, led: ledger.Ledger, table: sealed.SealedTable, batch: str, role: str,
                       runs_dir: Path = sandbox.RUNS_DIR) -> dict:
    """The gate on the runs as they will be reviewed: blinded scripts from the run folders, and the real prompts.

    A prompt the role cannot take would fail its audit, so it fails the gate too. Reads the sealed table, so it lives
    here and never in the reviewer's code path.
    """
    locks = {e.hypothesis_id: e.payload for e in led.entries(ledger.PREREGISTERED)}
    ids = batch_run_ids(table, batch)
    task, bugs = skeptic.task_of(client.cfg, role), load_yaml("bug_classes.yaml")
    rows, too_large, largest = [], 0, 0
    for entry in led.entries(ledger.RAN):
        run_id = entry.payload.get("run_id")
        truth = table.get(run_id) if run_id in ids else None
        reviewable = truth is not None and entry.payload.get("run_status") == sandbox.STATUS_OK
        if not reviewable or truth.run_type not in (sealed.CANARY_MEASURE, sealed.CONTROL, sealed.SHAM):
            continue
        job = skeptic._prepare(entry, locks[entry.hypothesis_id], runs_dir)
        rows.append({"base": truth.source or run_id, "buggy": truth.known_buggy,
                     "line_count": len(job.blinded.script.splitlines()), "char_count": len(job.blinded.script),
                     "helper_statements": truth.details.get("padding", {}).get("statements")})
        system, prompt, _ = review_tasks.build(task, job.blinded, bugs, None)
        largest = max(largest, len(prompt) + len(system or ""))
        try:
            client._check_prompt_size(prompt, system, client.num_ctx(role))
        except llm.LLMError:
            too_large += 1
    check = separation.length_check(rows)
    check.update({"role": role, "largest_prompt_chars": largest, "prompts_too_large": too_large,
                  "passes": check["passes"] and too_large == 0})
    return check


def dry_length_check(plan: dict) -> dict:
    """The gate before anything runs: every slot's script as it would be written, from its first base that fits.

    No experiment runs and nothing is stored. B09 subtle uses its ladder's first rung instead of measuring, which
    matters for its numbers but barely for its length (that bug only changes values in CONFIG).
    """
    rows = []
    for slot in plan["slots"]:
        for attempt, index in enumerate(slot["candidates"]):
            base = plan["bases"][index]
            rng = random.Random(f"{plan['seed']}:{slot['slot']}:{attempt}")
            padder = _padder(plan, slot, attempt)
            clone = controls.clone_config(prereg.to_run_config(base["prereg"]), rng)
            try:
                if slot["run_type"] == sealed.CANARY_MEASURE:
                    script = sabotage(clone, slot["bug_id"], slot["tier"], measure=False).script
                elif slot["run_type"] == sealed.CONTROL:
                    script = codegen.render_script(clone)
                else:
                    script = controls.make_sham(clone, rng).script
            except (NotApplicable, TransformError):
                continue
            helper = None
            if padder:
                padded = padder.pad(script)
                script, helper = padded.script, padded.statements
            lines, chars = padding.length(script)
            rows.append({"base": f"pool:{index}", "buggy": slot["run_type"] == sealed.CANARY_MEASURE,
                         "line_count": lines, "char_count": chars, "helper_statements": helper})
            break
    check = separation.length_check(rows)
    check["slots_without_base"] = len(plan["slots"]) - len(rows)
    check["largest_script_chars"] = max((r["char_count"] for r in rows), default=0)
    return check


def _audit_and_log(client: llm.LLM, led: ledger.Ledger, batch: str, runs_dir: Path, log_path: Path,
                   role: str = skeptic.DEFAULT_ROLE, run_ids: set[str] | None = None,
                   class_order=None) -> skeptic.AuditReport:
    """Review what is waiting and log progress without run types. Ends with the line the status-line tip looks for."""
    started = time.perf_counter()

    def progress(done: int, total: int, item: dict) -> None:
        # The code's verdict: a checklist reply has no verdict of its own, and a grounded one may be overruled.
        state = (item.get("decision") or item["audit"])["verdict"] if "audit" in item else f"FAILED ({item['kind']})"
        _log(log_path, f"batch {batch}: audit {done}/{total} {state} [{time.perf_counter() - started:.0f} s so far]")

    report = skeptic.audit_pending(client, led, runs_dir, role=role, on_progress=progress, run_ids=run_ids,
                                   class_order=class_order)
    client.release()
    for error in report.errors:
        if "not reviewed" in error:  # a file problem, not a reviewer failure: these runs stay waiting
            _log(log_path, f"batch {batch}: PROBLEM {error}")
    _log(log_path, f"batch {batch}: {len(report.audited)} audits stored, {len(report.failures)} failed, "
                   f"{len(report.no_results)} runs with no results" + (f". STOPPED: {report.stopped}" if report.stopped else ""))
    return report


# The position-bias diagnostic: one canary per class and tier, plus some clean runs, reviewed again with the class list
# shuffled per run. 40 runs is enough to tell "names whatever is listed first" from "names B01 wherever it is listed".
POSITION_CLEAN = {sealed.CONTROL: 10, sealed.SHAM: 10}


def batch_run_ids(table: sealed.SealedTable, batch: str) -> set[str]:
    return {t.run_id for t in table.all() if t.details.get("batch") == batch}


def _reviewable(led: ledger.Ledger) -> set[str]:
    """Runs that finished with results. A crashed run has nothing to review, so sampling it would waste a slot."""
    return {e.payload["run_id"] for e in led.entries(ledger.RAN) if e.payload.get("results_sha256")}


def position_sample(table: sealed.SealedTable, led: ledger.Ledger, batch: str, seed: int) -> dict:
    """Pick the diagnostic's runs. A class x tier cell, or a clean type, that cannot be filled is reported, not skipped.

    Returns {"run_ids": [...], "missing": [descriptions]}. The same seed and data give the same sample, so a resumed
    re-audit reviews the same runs.
    """
    rng = random.Random(seed)
    ok = _reviewable(led)
    truths = sorted((t for t in table.all() if t.details.get("batch") == batch and t.run_id in ok), key=lambda t: t.run_id)
    picked, missing = [], []
    for bug, tier in sorted(TRANSFORMS):
        cell = [t.run_id for t in truths if t.run_type == sealed.CANARY_MEASURE and t.bug_id == bug and t.tier == tier]
        if cell:
            picked.append(rng.choice(cell))
        else:
            missing.append(f"canary {bug} {tier}: no reviewable run")
    for run_type, wanted in POSITION_CLEAN.items():
        pool = [t.run_id for t in truths if t.run_type == run_type]
        if len(pool) < wanted:
            missing.append(f"{run_type}: {len(pool)} of {wanted}")
        picked += rng.sample(pool, min(wanted, len(pool)))
    return {"run_ids": picked, "missing": missing}


def shuffled_order(bug_ids: list[str], seed: int, run_id: str) -> list[str]:
    """A fixed shuffle per run, so a resumed re-audit asks with exactly the same prompt as before."""
    order = sorted(bug_ids)
    random.Random(f"{seed}:{run_id}").shuffle(order)
    return order


def reaudit(client: llm.LLM, led: ledger.Ledger, table: sealed.SealedTable, batch: str, role: str,
            run_ids: set[str] | None = None, class_order=None, runs_dir: Path = sandbox.RUNS_DIR,
            log_path: Path | None = None) -> skeptic.AuditReport:
    """Have another reviewer role review runs that already exist. No experiment is run. Safe to call again.

    `run_ids` defaults to the whole batch. Runs this role already reviewed are skipped, so a resume does only the rest.
    """
    log_path = log_path or runs_dir / "campaign.log"
    ids = batch_run_ids(table, batch) if run_ids is None else set(run_ids)
    _log(log_path, f"batch {batch}: re-audit by {role}, {len(ids)} runs in scope")
    return _audit_and_log(client, led, batch, runs_dir, log_path, role, ids, class_order)


# Rescoring: token probabilities for audits stored without them (task-dev-1's scores were lost to a parsing bug).
RESCORE_DIR = DATA_DIR / "rescore"


FRESH = "fresh"  # the pass that scores every new reply, kept in its own file so the first records stay as written


def rescore_path(batch: str, directory: Path = RESCORE_DIR, kind: str = "") -> Path:
    return directory / (f"{batch}.{kind}.jsonl" if kind else f"{batch}.jsonl")


def read_rescores(batch: str, directory: Path = RESCORE_DIR, kind: str = "") -> list[dict]:
    path = rescore_path(batch, directory, kind)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def reviewer_roles(models_cfg: dict, reviewer: str, led: ledger.Ledger, run_ids: set[str]) -> list[str]:
    """The roles running on `reviewer`'s model that audited this batch, in config order. One model, so one load."""
    audited = {e.payload["role"] for e in led.entries(ledger.AUDITED) if e.payload["run_id"] in run_ids}
    return [r for r, cfg in models_cfg["roles"].items()
            if (r == reviewer or cfg.get("use_role") == reviewer) and r in audited]


def rescore_batch(client: llm.LLM, led: ledger.Ledger, table: sealed.SealedTable, batch: str, reviewer: str,
                  runs_dir: Path = sandbox.RUNS_DIR, log_path: Path = sandbox.RUNS_DIR / "campaign.log",
                  directory: Path = RESCORE_DIR, fresh: bool = False) -> dict[str, dict[str, int]]:
    """Rescore every audit of the batch by one reviewer's roles. Safe to run again: finished records are skipped.

    Records are appended one at a time, so a crash or a stop loses at most the call in progress. Failed calls are not
    stored and are tried again on the next run. Returns the outcome counts per role.

    `fresh` asks again only for runs whose first rescore reply differed from the stored audit, and keeps the new
    reply's score whatever it says, in `<batch>.fresh.jsonl`. The first rescore file is only read.
    """
    ids = batch_run_ids(table, batch)
    kind = FRESH if fresh else ""
    path = rescore_path(batch, directory, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    finished: dict[str, set[str]] = {}
    for record in read_rescores(batch, directory, kind):
        finished.setdefault(record["role"], set()).add(record["run_id"])
    differing: dict[str, set[str]] = {}
    for record in read_rescores(batch, directory) if fresh else []:
        if record["outcome"] == "reply_differs":
            differing.setdefault(record["role"], set()).add(record["run_id"])
    counts: dict[str, dict[str, int]] = {}
    for role in reviewer_roles(client.cfg, reviewer, led, ids):
        scope = differing.get(role, set()) if fresh else ids
        todo = len(scope - finished.get(role, set()))
        _log(log_path, f"batch {batch}: {'fresh ' if fresh else ''}rescore by {role}, {todo} to do")
        started, done = time.perf_counter(), 0
        tally = counts.setdefault(role, {})

        def store(record: dict) -> None:
            nonlocal done
            tally[record["outcome"]] = tally.get(record["outcome"], 0) + 1
            if record.get("retry"):
                _log(log_path, f"batch {batch}: rescore {role} FAILED ({record['kind']}), will retry")
                return
            done += 1
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            _log(log_path, f"batch {batch}: rescore {role} {done}/{todo} {record['outcome']} "
                           f"[{time.perf_counter() - started:.0f} s so far]")

        if todo:
            skeptic.rescore(client, led, role, scope, runs_dir, finished.get(role, set()), store, always_score=fresh)
        _log(log_path, f"batch {batch}: rescore by {role} finished: {tally}")
    client.release()
    return counts
