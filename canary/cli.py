"""Command line for Canary. Run with `python -m canary.cli <command>`."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
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


def check_models() -> bool:
    cfg = config.load_yaml("models.yaml")
    if cfg["provider"] != "ollama":
        return _line(False, "Models", f"provider '{cfg['provider']}' is not supported yet")
    try:
        installed = installed_ollama_models()
    except Exception as exc:  # the client raises several types when the server is down
        return _line(False, "Ollama", f"server not reachable ({exc}). Start the Ollama app.")
    _line(True, "Ollama", f"server running, {len(installed)} models installed")

    ok = True
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
    roles = [role for role, cfg in client.cfg["roles"].items() if "use_role" not in cfg]
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
        audit = item["audit"]
        label = audit["verdict"] + (f" {audit['bug_class']}" if audit["bug_class"] else "")
        source = "cache" if item["cached"] else f"{item['attempts']} attempt(s)"
        print(f"Audit {item['hypothesis_id'][:8]} by {item['model']} ({source}): {label}, "
              f"confidence {audit['confidence']}")
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
        pool = (json.loads(mixer.POOL_PATH.read_text(encoding="utf-8")) if mixer.POOL_PATH.exists()
                else mixer.build_pool(client, led, table))
        try:
            plan = mixer.plan_batch(args.batch, args.runs, pool, settings["seed"] if args.seed is None else args.seed)
        except mixer.MixerError as exc:
            print(f"Cannot plan this batch: {exc}")
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    report = mixer.run_batch(client, plan, led, table)
    if report.stopped:
        print(f"Stopped: {report.stopped} Fix that, then run: python -m canary.cli calibrate --batch {args.batch} --resume")
        return 1
    print(f"Batch {args.batch} finished. Results: python -m eval.rq1 --batch {args.batch}")
    return 0


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
    calibrate_parser.set_defaults(func=cmd_calibrate)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
