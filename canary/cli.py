"""Command line for Canary. Run with `python -m canary.cli <command>`."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from canary import config, datasets, ledger, llm, sandbox, scientist, skeptic
from canary.saboteur import classes as bug_classes
from canary.saboteur import transforms

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
    code = 0
    for number in range(1, args.hypotheses + 1):
        try:
            locked, model = scientist.propose(client, args.question, led)
        except (llm.LLMError, scientist.ProposalRejected) as exc:
            print(f"Hypothesis {number}: no proposal. {exc}")
            code = 1
            break
        outcome = scientist.run_locked(locked, model, led)
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


def _arm_means(record: dict, runs_dir: Path) -> tuple[float, float]:
    results = json.loads((runs_dir / record["run_id"] / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))
    return statistics.fmean(results["control"]), statistics.fmean(results["treatment"])


def cmd_sabotage_check(args: argparse.Namespace) -> int:
    """Run every bug variant on real data and show how far each one moves the numbers from the clean run.

    Runs go to a temporary folder: these are checks of the Saboteur, not experiments, so they must stay out of the
    crash rate and the ledger. A variant that barely moves the numbers is still a bug in the code, but it is worth knowing.
    """
    experiment = yaml.safe_load(Path(args.path).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as folder:
        runs_dir = Path(folder)
        clean = sandbox.run_config(experiment, runs_dir)
        if clean["status"] != sandbox.STATUS_OK:
            print(f"The clean run failed: {clean['status']} ({clean['reason']})")
            return 1
        clean_control, clean_treatment = _arm_means(clean, runs_dir)
        print(f"{experiment['dataset']}, {experiment['control']['model']}, {experiment['metric']}: "
              f"clean control {clean_control:.4f}, treatment {clean_treatment:.4f}")
        print(f"{'variant':<12} {'status':<14} {'control':>8} {'treatment':>9} {'d_control':>10} {'d_treat':>8}")
        failures = 0
        for bug_id, tier in sorted(transforms.TRANSFORMS):
            label = f"{bug_id} {tier}"
            reason = bug_classes.why_not_applicable(bug_id, tier, experiment)
            if reason:
                print(f"{label:<12} skipped: {reason}")
                continue
            planted = transforms.sabotage(experiment, bug_id, tier)
            record = sandbox.run_config(planted.config, runs_dir, script=planted.script)
            if record["status"] != sandbox.STATUS_OK:
                failures += 1
                last = record["stderr_tail"].strip().splitlines()[-1:] or [record["reason"]]
                print(f"{label:<12} {record['status']:<14} {last[0][:90]}")
                continue
            control, treatment = _arm_means(record, runs_dir)
            print(f"{label:<12} {'ok':<14} {control:>8.4f} {treatment:>9.4f} "
                  f"{control - clean_control:>+10.4f} {treatment - clean_treatment:>+8.4f}")
    print(f"sabotage-check: {'all ran' if not failures else f'{failures} FAILED'}")
    return 1 if failures else 0


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
    sabotage_parser.set_defaults(func=cmd_sabotage_check)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
