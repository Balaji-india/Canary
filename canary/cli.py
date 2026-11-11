"""Command line for Canary. Run with `python -m canary.cli <command>`."""
from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.metadata
import json
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

from canary import config, controls, datasets, ledger, llm, mixer, sandbox, scientist, sealed, skeptic, trust
from canary.saboteur import classes as bug_classes
from canary.saboteur import impact, transforms

REQUIRED_PACKAGES = ["numpy", "pandas", "scipy", "scikit-learn", "pyyaml", "python-dotenv",
                     "sentence-transformers", "matplotlib", "streamlit", "pytest", "ollama"]
MIN_FREE_DISK_GB = 5


def _line(ok: bool, label: str, detail: str = "") -> bool:
    print(f"[{'OK' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")
    return ok


def check_python() -> bool:
    ok = sys.version_info >= (3, 11)
    in_venv = sys.prefix != sys.base_prefix
    return _line(ok and in_venv, "Python", f"{platform.python_version()}, "
                 f"{'in venv' if in_venv else 'NOT in the venv (run .venv\\Scripts\\activate)'}")


def check_packages() -> bool:
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            missing.append(pkg)
    return _line(not missing, "Packages", f"missing {missing}" if missing else f"{len(REQUIRED_PACKAGES)} installed")


def check_git() -> bool:
    if not shutil.which("git"):
        return _line(False, "Git", "not found")
    out = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=config.ROOT,
                         capture_output=True, text=True, timeout=10)
    return _line(out.returncode == 0, "Git", "repository OK" if out.returncode == 0 else "not a repository")


def check_disk() -> bool:
    free = shutil.disk_usage(config.ROOT).free / 1024**3
    return _line(free >= MIN_FREE_DISK_GB, "Disk", f"{free:.1f} GB free")


def installed_ollama_models() -> set[str]:
    import ollama

    return {m.model for m in ollama.Client(timeout=10).list().models}


def check_cloud_roles(cfg: dict) -> bool:
    """One line per cloud role: provider, model, and whether its key is present. Never prints the key, never calls.

    A missing key is a note, not a failure: Canary runs without any cloud role.
    """
    ok = True
    for role in config.cloud_roles(cfg):
        if "use_role" in cfg["roles"][role]:
            continue
        settings = cfg["roles"][role]
        entry = cfg["providers"][settings["provider"]]
        if settings["model"] not in entry["models"]:
            ok = _line(False, f"Cloud {role}", f"{settings['model']} is not on {settings['provider']}'s allow-list")
            continue
        key = "key present" if llm.read_key(entry["key_env"]) else \
            f"key missing (add {entry['key_env']} to .env; needed only for the ceiling check)"
        _line(True, f"Cloud {role}", f"{settings['provider']} {settings['model']}, {key}, not called")
    return ok


def check_models() -> bool:
    cfg = config.load_yaml("models.yaml")
    if cfg["provider"] != "ollama":
        return _line(False, "Models", f"provider '{cfg['provider']}' is not supported yet")
    cloud_ok = check_cloud_roles(cfg)
    try:
        installed = installed_ollama_models()
    except Exception as exc:  # the client raises several types when the server is down
        return _line(False, "Ollama", f"server not reachable ({exc}). Start the Ollama app.")
    _line(True, "Ollama", f"server running, {len(installed)} models installed")

    ok = cloud_ok
    clashes = config.family_clashes(cfg)
    if clashes:
        ok = _line(False, "Model families", f"same family as the Scientist: {clashes}")
    for choice in config.resolve_roles(cfg, installed):
        if choice.model is None:
            ok = _line(False, f"Model {choice.role}",
                       f"run: ollama pull {choice.preferred}  (or the fallback: ollama pull {choice.fallback})")
        else:
            note = f" (fallback; preferred {choice.preferred} is not installed)" if choice.used_fallback else ""
            _line(True, f"Model {choice.role}", choice.model + note)
    return ok


def check_datasets() -> bool:
    cfg = config.load_yaml("datasets.yaml")
    ok = True
    for entry in cfg["sklearn"] + cfg["openml"]:
        try:
            frame = datasets.load_dataset(entry["name"])
            problem = datasets.check_frame(frame, entry["classes"])
        except FileNotFoundError:
            problem = "not cached (run: python -m canary.cli cache-datasets)"
        if problem:
            ok = _line(False, f"Dataset {entry['name']}", problem)
        else:
            _line(True, f"Dataset {entry['name']}", f"{len(frame)} rows, {entry['classes']} classes")
    return ok


def cmd_doctor(_args: argparse.Namespace) -> int:
    checks = [check_python, check_packages, check_git, check_disk, check_models, check_datasets]
    # Run every check, so one failure does not hide the others.
    results = [check() for check in checks]
    print("\nDoctor: all OK" if all(results) else "\nDoctor: problems found (see FAIL lines)")
    return 0 if all(results) else 1


def cmd_cache_datasets(_args: argparse.Namespace) -> int:
    report = datasets.cache_openml()
    for name, status in report:
        print(f"{name}: {status}")
    return 1 if any(status.startswith("FAILED") for _, status in report) else 0


def cmd_run_config(args: argparse.Namespace) -> int:
    try:
        experiment = yaml.safe_load(Path(args.path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"Cannot read {args.path}: {exc}")
        return 2
    record = sandbox.run_config(experiment, timeout_s=args.timeout)
    run_dir = sandbox.RUNS_DIR / record["run_id"]
    print(f"Run {record['run_id']}: {record['status']}" + (f" ({record['reason']})" if record["reason"] else ""))
    print(f"Folder: {run_dir}")
    if record["status"] == sandbox.STATUS_OK:
        results = json.loads((run_dir / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))
        for arm in ("control", "treatment"):
            print(f"{arm} {results['metric']}: mean {statistics.fmean(results[arm]):.4f} over "
                  f"{len(results[arm])} seeds")
    elif record["stderr_tail"].strip():
        print("Last error line: " + record["stderr_tail"].strip().splitlines()[-1])
    failed, total = sandbox.crash_rate()
    print(f"Failed runs so far: {failed} of {total} executed")
    return 0 if record["status"] == sandbox.STATUS_OK else 1


SMOKE_PROMPT = 'What is 2 + 3? Reply as JSON with "answer" (the number) and "word" (that number spelled in English).'
SMOKE_SCHEMA = {"type": "object", "required": ["answer", "word"], "additionalProperties": False,
                "properties": {"answer": {"type": "integer"}, "word": {"type": "string"}}}


def cmd_llm_smoke(_args: argparse.Namespace) -> int:
    """Prove each role returns schema-valid JSON from the real model, then that a repeat comes from the cache."""
    client = llm.LLM()
    cloud = set(config.cloud_roles(client.cfg))
    roles = [role for role, cfg in client.cfg["roles"].items() if "use_role" not in cfg and role not in cloud]
    if cloud:  # a routine check must never spend a daily quota
        print(f"Skipping cloud roles (use cloud-smoke --role R): {', '.join(sorted(cloud))}")
    ok = True
    for label, refresh in (("live", True), ("repeat", False)):
        queue = llm.ModelQueue(client)
        for role in roles:
            queue.add(role, SMOKE_PROMPT, SMOKE_SCHEMA, refresh=refresh)
        for result in queue.run():
            if result.error:
                ok = _line(False, f"{label} {result.role}", result.error)
            else:
                source = "cache" if result.cached else f"{result.attempts} attempt(s)"
                _line(True, f"{label} {result.role}", f"{result.model}, {result.seconds:.1f} s, {source}: "
                      f"{json.dumps(result.data)}")
    client.release()
    print("\nllm-smoke: all OK" if ok else "\nllm-smoke: problems found (see FAIL lines)")
    return 0 if ok else 1


SMOKE_RUN = "1875ec26"  # an old real run that is in no batch (outline section 2): never a batch run


def _smoke_requests(client: llm.LLM, role: str, runs_dir: Path = sandbox.RUNS_DIR,
                    led: ledger.Ledger | None = None) -> list[tuple[str, str, str | None, dict]]:
    """(label, prompt, system, schema) for the toy prompt and the role's own review prompt on the smoke run.

    Only the task the role will run is sent (the ceiling check's 2-cell design uses the baseline prompt only).
    """
    from canary import review_tasks

    blinded = skeptic.blinded_run(led or ledger.Ledger(), SMOKE_RUN, runs_dir)
    bugs = config.load_yaml("bug_classes.yaml")
    requests = [("toy", SMOKE_PROMPT, None, SMOKE_SCHEMA)]
    task = skeptic.task_of(client.cfg, role)
    system, prompt, schema = review_tasks.build(task, blinded, bugs)
    requests.append((f"review {task}", prompt, system, schema))
    return requests


def cmd_cloud_smoke(args: argparse.Namespace, runs_dir: Path = sandbox.RUNS_DIR, led: ledger.Ledger | None = None) -> int:
    """The live check of a cloud role before any batch (outline section 2). `--dry` sends nothing and needs no key.

    Live, it sends the toy prompt, the role's review prompt of old run 1875ec26, then that one again with the cache
    bypassed: 3 calls. Sending a blinded run needs the student's OK, so the live form also needs `--send`.
    """
    client = llm.LLM()
    if args.role not in client.cfg["roles"] or client.cloud_entry(args.role) is None:
        print(f"{args.role} is not a cloud role. Cloud roles: {', '.join(config.cloud_roles(client.cfg))}")
        return 2
    entry = client.cloud_entry(args.role)
    provider, model, temperature = client.resolve(args.role)
    options = client.options(args.role)
    requests = _smoke_requests(client, args.role, runs_dir, led)
    if args.dry:
        print(f"Dry run: nothing is sent and no key is read. POST {entry['base_url'].rstrip('/')}/chat/completions "
              f"({provider}, {model}).")
        for label, prompt, system, schema in requests:
            body = llm.build_request(entry, model, prompt, system, schema, temperature, client.settings["seed"], options)
            print(f"\n--- {label}: prompt SHA-256 {hashlib.sha256(prompt.encode('utf-8')).hexdigest()}, wire schema "
                  f"SHA-256 {llm._sha256_json(llm.wire_schema(schema))}")
            print(json.dumps(body, indent=1))
        return 0
    if not args.send:
        print("This sends a blinded run to the cloud and spends daily quota. It needs the student's OK: add --send "
              "(or use --dry to see the requests without sending).")
        return 2
    ok, replies = True, {}
    review = requests[1][0]
    for label, prompt, system, schema in requests + [("repeat", *requests[1][1:])]:
        try:
            result = client.call(args.role, prompt, schema, system=system, refresh=True, cache_write=label == "toy")
            replies[label] = result.data
            log = _last_call_record()
            _line(True, label, f"{result.seconds:.1f} s, {result.attempts} attempt(s), parse_reply OK; server model "
                  f"{log.get('server_model')}, tokens {log.get('prompt_tokens')}+{log.get('completion_tokens')} "
                  f"(reasoning {log.get('reasoning_tokens')}), finish {log.get('finish_reason')}")
        except llm.LLMError as exc:
            ok = _line(False, label, f"{exc.kind}: {exc}")
            if exc.kind in llm.STOP_KINDS:
                break
    if review in replies and "repeat" in replies:
        same = replies[review] == replies["repeat"]
        print(f"Repeat equals first: {same}" + ("" if same else " (write 'temperature 0 not verifiable' in the lock)"))
    print(f"\ncloud-smoke: {'all OK' if ok else 'problems found (see FAIL lines)'}. Every attempt is in "
          f"{llm.CALL_LOG_PATH}.")
    return 0 if ok else 1


def _last_call_record() -> dict:
    path = llm.CALL_LOG_PATH
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return json.loads(lines[-1]) if lines else {}


def cmd_science(args: argparse.Namespace) -> int:
    """Propose, lock, run and judge N hypotheses. Stops at the first model failure; finished entries stay."""
    client = llm.LLM()
    led = ledger.Ledger()
    table = sealed.SealedTable()
    scientist.seal_unsealed_runs_as_real(led, table)
    code = 0
    for number in range(1, args.hypotheses + 1):
        try:
            locked, model = scientist.propose(client, args.question, led, table)
        except (llm.LLMError, scientist.ProposalRejected) as exc:
            print(f"Hypothesis {number}: no proposal. {exc}")
            code = 1
            break
        outcome = scientist.run_locked(locked, model, led, table)
        verdict = outcome.verdict
        print(f"Hypothesis {number}: {outcome.hypothesis}")
        print(f"  Locked {outcome.prereg_sha256[:16]}, run {outcome.run_id}: {outcome.run_status}")
        if verdict["ci_low"] is None:
            print(f"  Verdict: {verdict['outcome']} ({verdict.get('reason', 'too few seeds')})")
        else:
            print(f"  Verdict: {verdict['outcome']} (effect {verdict['mean_effect']:+.4f}, "
                  f"CI [{verdict['ci_low']:+.4f}, {verdict['ci_high']:+.4f}], min {verdict['min_effect']})")
    code = max(code, _run_audits(client, led))
    client.release()
    return code


def _run_audits(client: llm.LLM, led: ledger.Ledger) -> int:
    """Review every run still waiting and print the outcome. Returns 1 if any could not be reviewed."""
    report = skeptic.audit_pending(client, led)
    for item in report.audited:
        audit = item.get("decision") or item["audit"]  # the code's verdict, whatever the review task
        label = audit["verdict"] + (f" {audit['bug_class']}" if audit["bug_class"] else "")
        source = "cache" if item["cached"] else f"{item['attempts']} attempt(s)"
        print(f"Audit {item['hypothesis_id'][:8]} by {item['model']} ({source}): {label}, "
              f"confidence {item['audit'].get('confidence')}")
        print(f"  Evidence: {audit['evidence']}")
    for item in report.no_results:
        print(f"Graveyard {item['hypothesis_id'][:8]}: {item['cause']}")
    for error in report.errors:
        print(f"[FAIL] {error}")
    print(f"Audits: {len(report.audited)} stored, {len(report.no_results)} without results, "
          f"{len(report.errors)} failed")
    return 1 if report.errors else 0


def cmd_audit(_args: argparse.Namespace) -> int:
    client = llm.LLM()
    code = _run_audits(client, ledger.Ledger())
    client.release()
    return code


def cmd_sabotage_check(args: argparse.Namespace) -> int:
    """Run every bug variant on real data and show its impact: how far it moves the numbers from its clean twin.

    Runs go to a temporary folder: these are checks of the Saboteur, not experiments, so they must stay out of the
    crash rate and the ledger.
    """
    experiment = yaml.safe_load(Path(args.path).read_text(encoding="utf-8"))
    print(f"{experiment['dataset']}, {experiment['control']['model']}, {experiment['metric']}")
    print(f"{'variant':<12} {'status':<14} {'d_control':>10} {'d_treat':>8} {'d_effect':>9}  class")
    failures, records = 0, []
    with tempfile.TemporaryDirectory() as folder:
        for bug_id, tier in sorted(transforms.TRANSFORMS):
            label = f"{bug_id} {tier}"
            reason = bug_classes.why_not_applicable(bug_id, tier, experiment)
            if reason:
                print(f"{label:<12} skipped: {reason}")
                continue
            try:
                record = impact.run_canary(experiment, bug_id, tier, Path(folder))
            except bug_classes.NotApplicable as exc:
                print(f"{label:<12} skipped: {exc}")
                continue
            records.append(record.to_dict())
            found = record.impact
            if found is None:
                failures += 1
                print(f"{label:<12} {record.status:<14} {record.reason}")
                continue
            print(f"{label:<12} {'ok':<14} {found['control']:>+10.4f} {found['treatment']:>+8.4f} "
                  f"{found['effect']:>+9.4f}  {impact.impact_class(found)}")
    if args.json:
        Path(args.json).write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(f"sabotage-check: {'all ran' if not failures else f'{failures} FAILED'}")
    return 1 if failures else 0


def cmd_controls_check(args: argparse.Namespace) -> int:
    """Run a control, a sham and a canary through the sealed path on real data, and test what each promises."""
    experiment = yaml.safe_load(Path(args.path).read_text(encoding="utf-8"))
    reason = controls.why_not_clean(experiment)
    if reason:
        print(f"Not usable as a clean base: {reason}")
        return 1
    results = [_line(ok, label, detail) for label, ok, detail in controls.check_config(experiment, random.Random())]
    print(f"\ncontrols-check: {'all OK' if all(results) else 'problems found (see FAIL lines)'}")
    return 0 if all(results) else 1


def _posterior_row(label: str, p: trust.Posterior) -> str:
    low, high = p.interval()
    return f"  {label:<20} {p.successes:>4} of {p.n:<4} Beta({p.alpha}, {p.beta})  mean {p.mean:.3f}  90% [{low:.3f}, {high:.3f}]"


def _print_trust(summary: trust.TrustSummary, excluded: dict[str, int]) -> None:
    low, high = summary.overall_recall_interval
    tested = len(summary.per_class) - len(summary.untested)
    print("Recall per class (a catch is any flag, on canary-measure runs only):")
    for bug_id, posterior in summary.per_class.items():
        print(_posterior_row(bug_id, posterior) + ("  UNTESTED: prior only" if posterior.n == 0 else ""))
    print(f"Overall recall: mean {summary.overall_recall_mean:.3f}, 90% [{low:.3f}, {high:.3f}], "
          f"tested {tested} of {len(summary.per_class)} classes")
    if summary.untested:
        print(f"  Untested classes count at their prior, so this figure is not fully measured: {', '.join(summary.untested)}")
    print(f"Worst tested class: {summary.worst_class or 'none tested yet'}")
    print("Recall by impact:")
    for group, posterior in summary.by_impact.items():
        print(_posterior_row(group, posterior))
    print("Recall by tier:")
    for tier, posterior in summary.by_tier.items():
        print(_posterior_row(tier, posterior))
    print("Flagged and named the right class:")
    print(_posterior_row("named right", summary.named_right))
    print("Specificity (a success is a pass on a clean run):")
    print(_posterior_row("controls", summary.control_specificity))
    print(_posterior_row("shams", summary.sham_specificity))
    print(_posterior_row("combined", summary.specificity))
    print("Audits left out of recall and specificity: " + ", ".join(f"{k} {v}" for k, v in excluded.items()))


# Fixed made-up outcomes for `trust --demo`: (bug, tier, harmful?, caught, missed). B03-B10 stay untested on purpose.
DEMO_CANARIES = [("B01", "obvious", True, 8, 2), ("B02", "subtle", False, 3, 7)]
DEMO_CLEAN = [(sealed.CONTROL, 9, 1), (sealed.SHAM, 7, 3)]  # (type, passed, flagged)


def _fill_demo(table: sealed.SealedTable, led: ledger.Ledger) -> None:
    """Write the synthetic outcomes through the real tables, so the demo exercises the same join as real data."""
    count = 0

    def add(run_type: str, flagged: bool, bug: str | None = None, tier: str | None = None, details: dict | None = None):
        nonlocal count
        count += 1
        hypothesis, run_id = f"demo-h{count}", f"demo-r{count}"
        table.seal(run_id, run_type, bug, tier, details=details)
        for status in (ledger.PROPOSED, ledger.PREREGISTERED, ledger.RAN):
            led.append(hypothesis, status, {})
        audit = {"verdict": "flag" if flagged else "pass", "bug_class": bug or "B01" if flagged else None}
        led.append(hypothesis, ledger.AUDITED, {"run_id": run_id, "role": trust.DEFAULT_ROLE, "audit": audit})

    for bug, tier, harmful, caught, missed in DEMO_CANARIES:
        details = {"impact": {"size": 0.1 if harmful else 0.0, "threshold": 0.005, "comparable": True}}
        for flagged in [True] * caught + [False] * missed:
            add(sealed.CANARY_MEASURE, flagged, bug, tier, details)
    for run_type, passed, flagged_count in DEMO_CLEAN:
        for flagged in [False] * passed + [True] * flagged_count:
            add(run_type, flagged)


def cmd_trust(args: argparse.Namespace) -> int:
    """Print the reviewer's measured trust. Reads the sealed table, so this is never called from the reviewer's path."""
    bug_ids = sorted(config.load_yaml("bug_classes.yaml"))
    draws = config.load_yaml("campaign.yaml")["monte_carlo_draws"]
    if args.demo:
        print("SYNTHETIC DEMO: made-up outcomes, not a measurement of any reviewer.\n")
        with tempfile.TemporaryDirectory() as folder:
            table = sealed.SealedTable(Path(folder) / "sealed.db")
            led = ledger.Ledger(Path(folder) / "ledger.db")
            _fill_demo(table, led)
            observations, excluded = trust.collect_observations(table, led, args.role)
        _print_trust(trust.summarize(observations, bug_ids, draws), excluded)
        return 0
    if not sealed.SEALED_DB_PATH.exists():  # checked first, because opening a SealedTable would create the file
        print("No sealed table yet, so there is nothing to measure. Mission 2.4 (`calibrate`) creates it.")
        return 0
    table, led = sealed.SealedTable(), ledger.Ledger()
    observations, excluded = trust.collect_observations(table, led, args.role, args.batch)
    scope = f"batch {args.batch}" if args.batch else "all batches"
    print(f"Reviewer role {args.role}, {scope}: {len(observations)} audited runs with a sealed type.\n")
    _print_trust(trust.summarize(observations, bug_ids, draws), excluded)
    failures = trust.collect_failures(table, led, args.role, args.batch)
    print("Failed audits and crashed runs, which count in no figure above:")
    for run_type, row in sorted(failures["by_type"].items()):
        print(f"  {run_type:<15} {row['sealed']} sealed, {row['audited']} audited ({row['failed_then_recovered']} after a failure), "
              f"{row['never_reviewed_failed']} failed and unreviewed, {row['not_reached']} not reached, {row['crashed']} crashed, "
              f"kinds {row['failure_kinds'] or 'none'}")
    return 0


def run_without_audit(client: llm.LLM, plan: dict, led: ledger.Ledger, table: sealed.SealedTable,
                      runs_dir: Path = sandbox.RUNS_DIR, twin_dir: Path = controls.TWINS_DIR,
                      plans_dir: Path = sealed.PLANS_DIR, log_path: Path | None = None) -> dict:
    """Run every unfinished slot of a batch and its length gate, and review nothing (`calibrate --no-audit`).

    Why: the ceiling check's extension batch is reviewed later by a cloud role (`reaudit`), in daily sessions, so no
    local model may audit it first. This is `mixer.run_batch` without its last step (mixer.py is frozen, so the steps
    are composed here from its public functions). Safe to call again: finished slots are skipped.
    """
    log_path = log_path or runs_dir / "campaign.log"
    batch = plan["batch"]
    finished = mixer.finished_slots(batch, led, table)
    waiting = [s for s in plan["slots"] if s["slot"] not in finished]
    timings = plans_dir / f"{batch}.timing.jsonl"
    timings.parent.mkdir(parents=True, exist_ok=True)
    mixer._log(log_path, f"batch {batch}: {len(plan['slots'])} slots, {len(waiting)} to run (no audit)")
    skipped = 0
    for number, slot in enumerate(waiting, 1):
        started = time.perf_counter()
        ran = mixer.execute_slot(slot, plan, led, table, runs_dir, twin_dir)
        seconds = time.perf_counter() - started
        skipped += not ran
        with timings.open("a", encoding="utf-8") as handle:  # names the type, so it stays beside the plan, off the log
            handle.write(json.dumps({"stage": "run", "slot": slot["slot"], "run_type": slot["run_type"],
                                     "bug_id": slot["bug_id"], "tier": slot["tier"], "ran": ran,
                                     "seconds": round(seconds, 2)}) + "\n")
        mixer._log(log_path, f"batch {batch}: run {number}/{len(waiting)} {'done' if ran else 'SKIPPED, no base fits'} "
                             f"in {seconds:.1f} s")
    check = None
    if plan.get("length_match"):
        check = mixer.batch_length_check(client, led, table, batch, plan.get("role", skeptic.DEFAULT_ROLE), runs_dir)
        (plans_dir / f"{batch}.length_check.json").write_text(json.dumps(check, indent=1), encoding="utf-8")
        mixer._log(log_path, f"batch {batch}: length gate {'passed' if check['passes'] else 'FAILED'} "
                             f"({mixer.gate_text(check)})")
    mixer._log(log_path, f"batch {batch}: runs finished, nothing audited (--no-audit)")
    return {"ran": len(waiting) - skipped, "skipped": skipped, "length_check": check}


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Run a batch of canaries, controls and shams only, then have the Skeptic review them. Safe to resume."""
    settings = config.load_yaml("campaign.yaml")["calibrate"]
    client, led, table = llm.LLM(), ledger.Ledger(), sealed.SealedTable()
    scientist.seal_unsealed_runs_as_real(led, table)
    path = mixer.plan_path(args.batch)
    if args.resume:
        if not path.exists():
            print(f"Batch {args.batch} has no plan to resume.")
            return 2
        plan = json.loads(path.read_text(encoding="utf-8"))
    else:
        if args.runs is None:
            print("Give --runs N, or --resume to continue a batch.")
            return 2
        if path.exists():
            print(f"Batch {args.batch} already exists. Use --resume, or another batch name.")
            return 2
        pool_path = Path(args.pool) if args.pool else mixer.POOL_PATH
        if args.pool and not pool_path.exists():
            print(f"No pool at {pool_path}. Build it first: python -m canary.cli build-pool --out {args.pool}")
            return 2
        if args.role not in client.cfg["roles"]:
            print(f"Unknown role {args.role}. Roles: {', '.join(client.cfg['roles'])}")
            return 2
        pool = (json.loads(pool_path.read_text(encoding="utf-8")) if pool_path.exists()
                else mixer.build_pool(client, led, table))
        try:
            plan = mixer.plan_batch(args.batch, args.runs, pool, settings["seed"] if args.seed is None else args.seed,
                                    role=args.role)
        except mixer.MixerError as exc:
            print(f"Cannot plan this batch: {exc}")
            return 1
        plan["pool"] = str(pool_path)
        if args.no_audit:
            plan["no_audit"] = True  # kept in the plan, so a --resume never audits this batch by accident
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    if args.no_audit or plan.get("no_audit"):
        if args.no_audit != bool(plan.get("no_audit")):
            print(f"Batch {args.batch} was planned {'without' if plan.get('no_audit') else 'with'} audits; resume it "
                  f"the same way ({'with' if plan.get('no_audit') else 'without'} --no-audit).")
            return 2
        outcome = run_without_audit(client, plan, led, table)
        check = outcome["length_check"]
        print(f"Batch {args.batch}: {outcome['ran']} runs done, {outcome['skipped']} skipped, nothing audited.")
        if check is not None:
            print(f"Length gate {'PASSED' if check['passes'] else 'FAILED'}: {mixer.gate_text(check)}.")
            if not check["passes"]:
                return 1
        print(f"Review it later with: python -m canary.cli reaudit --batch {args.batch} --role <role>")
        return 0
    report = mixer.run_batch(client, plan, led, table)
    if report.stopped:
        print(f"Stopped: {report.stopped} Fix that, then run: python -m canary.cli calibrate --batch {args.batch} --resume")
        return 1
    print(f"Batch {args.batch} finished. Results: python -m eval.rq1 --batch {args.batch}")
    return 0


def cmd_build_pool(args: argparse.Namespace) -> int:
    """Ask the Scientist for a new pool of bases over the fixed grid, avoiding an earlier pool's bases."""
    out = Path(args.out)
    if out.exists():
        print(f"{out} already exists. A pool is written once; choose another file name.")
        return 2
    avoid = json.loads(Path(args.avoid).read_text(encoding="utf-8")) if args.avoid else None
    client, led, table = llm.LLM(), ledger.Ledger(), sealed.SealedTable()
    try:
        pool = mixer.build_pool(client, led, table, out, avoid_pool=avoid)
    except mixer.MixerError as exc:
        print(f"Pool refused: {exc}")
        return 1
    finally:
        client.release()
    shared = len(mixer.pool_keys(pool) & mixer.pool_keys(avoid)) if avoid else 0
    print(f"Pool written to {out}: {len(pool['bases'])} bases kept, {len(pool['dropped'])} dropped, "
          f"{shared} shared with {args.avoid or 'no earlier pool'}.")
    return 0


def cmd_length_check(args: argparse.Namespace) -> int:
    """The length gate. --dry plans a batch from a pool and checks its scripts without running anything."""
    if args.dry:
        if not (args.pool and args.runs and args.seed is not None):
            print("--dry needs --pool, --runs and --seed (the same ones calibrate will use).")
            return 2
        pool = json.loads(Path(args.pool).read_text(encoding="utf-8"))
        check = mixer.dry_length_check(mixer.plan_batch("dry-check", args.runs, pool, args.seed))
        extra = f"largest blinded script {check['largest_script_chars']} characters"
    else:
        if not args.batch:
            print("Give --batch B (runs already made), or --dry with --pool, --runs and --seed.")
            return 2
        client, led, table = llm.LLM(), ledger.Ledger(), sealed.SealedTable()
        plan = json.loads(mixer.plan_path(args.batch).read_text(encoding="utf-8"))
        check = mixer.batch_length_check(client, led, table, args.batch, plan.get("role", skeptic.DEFAULT_ROLE))
        extra = f"largest prompt {check['largest_prompt_chars']} characters, {check['prompts_too_large']} too large"
    print(f"Length gate {'PASSED' if check['passes'] else 'FAILED'}: {mixer.gate_text(check)}; {extra}.")
    print(f"{check['runs']} runs, {check['buggy']} canaries. Rule: {check['rule']}.")
    return 0 if check["passes"] else 1


def cmd_reaudit(args: argparse.Namespace) -> int:
    """Have another reviewer role review a finished batch again. Never runs an experiment. Safe to resume."""
    client, led, table = llm.LLM(), ledger.Ledger(), sealed.SealedTable()
    if args.role not in client.cfg["roles"]:
        print(f"Unknown role {args.role}. Roles: {', '.join(client.cfg['roles'])}")
        return 2
    if not mixer.batch_run_ids(table, args.batch):
        print(f"Batch {args.batch} has no sealed runs.")
        return 2
    run_ids, class_order = None, None
    if args.position_sample:
        sample = mixer.position_sample(table, led, args.batch, args.seed)
        for problem in sample["missing"]:
            print(f"Sample gap: {problem}")
        run_ids = set(sample["run_ids"])
        bug_ids = sorted(config.load_yaml("bug_classes.yaml"))
        class_order = functools.partial(mixer.shuffled_order, bug_ids, args.seed)  # called with a run ID
    report = mixer.reaudit(client, led, table, args.batch, args.role, run_ids, class_order)
    if report.stopped:
        print(f"Stopped: {report.stopped} Fix that, then run the same command again: finished reviews are kept.")
        return 1
    print(f"Re-audit of {args.batch} by {args.role} finished: {len(report.audited)} stored, {len(report.failures)} failed.")
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    """Token-probability scores for a batch's audits that have none. Same prompts; scored only if the reply repeats."""
    client, led, table = llm.LLM(), ledger.Ledger(), sealed.SealedTable()
    if args.reviewer not in client.cfg["roles"] or "use_role" in client.cfg["roles"][args.reviewer]:
        print(f"Give a reviewer with its own model, e.g. skeptic_a, skeptic_b or skeptic_c (not {args.reviewer}).")
        return 2
    if not mixer.batch_run_ids(table, args.batch):
        print(f"Batch {args.batch} has no sealed runs.")
        return 2
    if args.sample is not None:
        if skeptic.top_logprobs_of(client.cfg, args.reviewer) != 0:
            print("--sample is the repeat pass for roles without token probabilities (top_logprobs: 0), e.g. skeptic_d.")
            return 2
        counts = repeat_pass(client, led, table, args.batch, args.reviewer, args.sample, args.seed)
        for role, tally in counts.items():
            print(f"{role}: {tally}")
        if any(t.get("call_failed") for t in counts.values()):
            print("Some calls failed or hit a limit and were not stored. Run the same command again (after the reset).")
            return 1
        print(f"Repeat pass of {args.batch} by {args.reviewer} finished: {mixer.rescore_path(args.batch, kind=REPEAT)}")
        return 0
    counts = mixer.rescore_batch(client, led, table, args.batch, args.reviewer, fresh=args.fresh)
    for role, tally in counts.items():
        print(f"{role}: {tally}")
    if any(t.get("call_failed") for t in counts.values()):
        print("Some calls failed and were not stored. Run the same command again to retry them.")
        return 1
    print(f"Rescore of {args.batch} by {args.reviewer} finished. Results: python -m eval.compare_tasks --batch {args.batch}")
    return 0


REPEAT = "repeat"  # data/rescore/<batch>.repeat.jsonl: the ceiling check's repeat pass


def repeat_sample(table: sealed.SealedTable, led: ledger.Ledger, batch: str, n: int, seed: int) -> set[str]:
    """A seeded draw of `n` run IDs from the batch's finished runs, by ID only: no run type is read."""
    ids = sorted(mixer.batch_run_ids(table, batch) & {e.payload["run_id"] for e in led.entries(ledger.RAN)
                                                       if e.payload.get("results_sha256")})
    return set(random.Random(seed).sample(ids, min(n, len(ids))))


def repeat_pass(client: llm.LLM, led: ledger.Ledger, table: sealed.SealedTable, batch: str, reviewer: str, n: int,
                seed: int, directory: Path = mixer.RESCORE_DIR, runs_dir: Path = sandbox.RUNS_DIR) -> dict[str, dict]:
    """Ask the same `n` sampled runs again for each of the reviewer's roles, cache bypassed; append one record per run.

    Reported only, deciding nothing (outline section 5). Safe to run again: finished records are skipped, and a stop
    at the daily limit records nothing for the run that was not answered.
    """
    sample = repeat_sample(table, led, batch, n, seed)
    path = mixer.rescore_path(batch, directory, REPEAT)
    path.parent.mkdir(parents=True, exist_ok=True)
    finished: dict[str, set[str]] = {}
    for record in mixer.read_rescores(batch, directory, REPEAT):
        finished.setdefault(record["role"], set()).add(record["run_id"])
    counts: dict[str, dict] = {}
    for role in mixer.reviewer_roles(client.cfg, reviewer, led, sample):
        tally = counts.setdefault(role, {})

        def store(record: dict, tally=tally) -> None:
            tally[record["outcome"]] = tally.get(record["outcome"], 0) + 1
            if not record.get("retry"):
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({**record, "sample_seed": seed, "sample_size": n}) + "\n")

        skeptic.rescore(client, led, role, sample, runs_dir, finished.get(role, set()), store)
        if tally.get("call_failed"):
            break  # a limit or outage: the next role would hit it too
    client.release()
    return counts


def cmd_ledger(args: argparse.Namespace) -> int:
    led = ledger.Ledger(Path(args.db))
    if args.action == "show":
        for entry in led.entries():
            print(f"{entry.seq:>4} {entry.hash[:12]} {entry.status:<14} {entry.hypothesis_id}")
        return 0
    problems = led.verify(sandbox.RUNS_DIR)
    for problem in problems:
        print(f"[FAIL] {problem}")
    print(f"Ledger verify: {'FAILED' if problems else 'OK'} ({len(led.entries())} entries, {args.db})")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="canary")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check Python, packages, models and datasets").set_defaults(func=cmd_doctor)
    sub.add_parser("cache-datasets", help="download the OpenML datasets once").set_defaults(func=cmd_cache_datasets)
    sub.add_parser("llm-smoke", help="get valid JSON from every configured model").set_defaults(func=cmd_llm_smoke)
    science_parser = sub.add_parser("science", help="propose, lock, run and judge hypotheses")
    science_parser.add_argument("--hypotheses", type=int, default=1)
    science_parser.add_argument("--question", default="q1", help="a question id from config/campaign.yaml")
    science_parser.set_defaults(func=cmd_science)
    sub.add_parser("audit", help="have the Skeptic review every run still waiting").set_defaults(func=cmd_audit)
    ledger_parser = sub.add_parser("ledger", help="check or list the findings ledger")
    ledger_parser.add_argument("action", choices=["verify", "show"])
    ledger_parser.add_argument("--db", default=str(config.DB_PATH), help="ledger database file")
    ledger_parser.set_defaults(func=cmd_ledger)
    run_parser = sub.add_parser("run-config", help="generate and run one experiment from a YAML config")
    run_parser.add_argument("path")
    run_parser.add_argument("--timeout", type=float, default=sandbox.DEFAULT_TIMEOUT_S, help="seconds before the kill")
    run_parser.set_defaults(func=cmd_run_config)
    sabotage_parser = sub.add_parser("sabotage-check", help="run every bug variant on one config and show its effect")
    sabotage_parser.add_argument("path")
    sabotage_parser.add_argument("--json", help="also save the canary records to this file")
    sabotage_parser.set_defaults(func=cmd_sabotage_check)
    controls_parser = sub.add_parser("controls-check", help="prove a control, sham and canary behave on one config")
    controls_parser.add_argument("path")
    controls_parser.set_defaults(func=cmd_controls_check)
    trust_parser = sub.add_parser("trust", help="show the reviewer's measured recall and specificity")
    trust_parser.add_argument("--role", default=trust.DEFAULT_ROLE)
    trust_parser.add_argument("--demo", action="store_true", help="use made-up outcomes in a temporary folder")
    trust_parser.add_argument("--batch", help="only this calibration batch")
    trust_parser.set_defaults(func=cmd_trust)
    calibrate_parser = sub.add_parser("calibrate", help="run canaries, controls and shams, and review them blinded")
    calibrate_parser.add_argument("--runs", type=int, help="how many runs in a new batch")
    calibrate_parser.add_argument("--batch", required=True, help="the batch's name; RQ1 reports one batch at a time")
    calibrate_parser.add_argument("--seed", type=int, help="seed for the plan (default in config/campaign.yaml)")
    calibrate_parser.add_argument("--resume", action="store_true", help="continue a batch after an interruption")
    calibrate_parser.add_argument("--pool", help="pool file of bases (default data/calibration/pool.json)")
    calibrate_parser.add_argument("--role", default=skeptic.DEFAULT_ROLE, help="the reviewer role that audits the batch")
    calibrate_parser.add_argument("--no-audit", action="store_true",
                                  help="run the slots and the length gate only; review later with reaudit (ceiling-ext)")
    calibrate_parser.set_defaults(func=cmd_calibrate)
    pool_parser = sub.add_parser("build-pool", help="ask the Scientist for a new pool of bases over the fixed grid")
    pool_parser.add_argument("--out", required=True, help="new pool file, e.g. data/calibration/pool-2.json")
    pool_parser.add_argument("--avoid", help="an earlier pool whose bases must not come back")
    pool_parser.set_defaults(func=cmd_build_pool)
    length_parser = sub.add_parser("length-check", help="the length gate: blinded size must not reveal run types")
    length_parser.add_argument("--batch", help="check a batch's runs (after they ran, before any audit)")
    length_parser.add_argument("--dry", action="store_true", help="plan from a pool and check without running anything")
    length_parser.add_argument("--pool")
    length_parser.add_argument("--runs", type=int)
    length_parser.add_argument("--seed", type=int)
    length_parser.set_defaults(func=cmd_length_check)
    reaudit_parser = sub.add_parser("reaudit", help="have another reviewer role review a finished batch (no new runs)")
    reaudit_parser.add_argument("--batch", required=True)
    reaudit_parser.add_argument("--role", required=True, help="a role from config/models.yaml, e.g. skeptic_b")
    reaudit_parser.add_argument("--position-sample", action="store_true",
                                help="only 20 canaries (one per class and tier), 10 controls and 10 shams, with the class "
                                     "list shuffled per run: the position-bias diagnostic")
    reaudit_parser.add_argument("--seed", type=int, default=0, help="seed for the sample and the shuffles")
    reaudit_parser.set_defaults(func=cmd_reaudit)
    rescore_parser = sub.add_parser("rescore", help="token-probability scores for a batch's unscored audits (no verdict changes)")
    rescore_parser.add_argument("--batch", required=True)
    rescore_parser.add_argument("--reviewer", required=True, help="skeptic_a, skeptic_b or skeptic_c: all its task roles, one model")
    rescore_parser.add_argument("--fresh", action="store_true",
                                help="ask again for runs whose reply differed, and keep the new reply's score")
    rescore_parser.add_argument("--sample", type=int, help="repeat pass: this many seeded run IDs, cache bypassed "
                                                           "(roles without token probabilities, e.g. skeptic_d)")
    rescore_parser.add_argument("--seed", type=int, default=0, help="seed for --sample")
    rescore_parser.set_defaults(func=cmd_rescore)
    smoke_parser = sub.add_parser("cloud-smoke", help="check one cloud role before any batch (--dry sends nothing)")
    smoke_parser.add_argument("--role", required=True, help="a cloud role, e.g. skeptic_d")
    smoke_parser.add_argument("--dry", action="store_true", help="print the exact request bodies; no key, no network")
    smoke_parser.add_argument("--send", action="store_true", help="really send (needs the student's OK; 3 calls)")
    smoke_parser.set_defaults(func=cmd_cloud_smoke)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
