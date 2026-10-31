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
from pathlib import Path

import yaml

from canary import config, datasets, sandbox

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="canary")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check Python, packages, models and datasets").set_defaults(func=cmd_doctor)
    sub.add_parser("cache-datasets", help="download the OpenML datasets once").set_defaults(func=cmd_cache_datasets)
    run_parser = sub.add_parser("run-config", help="generate and run one experiment from a YAML config")
    run_parser.add_argument("path")
    run_parser.add_argument("--timeout", type=float, default=sandbox.DEFAULT_TIMEOUT_S, help="seconds before the kill")
    run_parser.set_defaults(func=cmd_run_config)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
