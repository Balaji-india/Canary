"""The llama-checklist confirmation, exactly as pre-registered in docs/plans/llama_checklist_confirmation.md.

Run with `python -m eval.confirm --batch confirm-llama-1` after the batch is audited. It refuses to run unless the plan
matches its recorded SHA-256 and the cut-off file matches the SHA-256 written in the plan, so neither can be changed
after the data exist without it showing.

Hypotheses (90% intervals resample whole bases, 2000 draws, seed 0):
- H1: J at the locked cut-off (flag when P(flag) >= cut-off): lower bound above 0.
- H2: AUC of P(flag): lower bound above 0.5.
- H3: AUC of P(flag) minus AUC of blinded line count, paired on the same runs: lower bound above 0.
Confirmed = (H1 or H2) and H3. Everything else in the output is a diagnostic and decides nothing.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from canary import blinding, codegen, config, ledger, mixer, sandbox, sealed, separation, trust
from eval import compare_tasks
from eval.cutoff import CUTOFF_PATH, sha256_file

ROLE = "skeptic_c_checklist"
DEFAULT_BATCH = "confirm-llama-1"
PLAN_PATH = Path(__file__).parent.parent / "docs" / "plans" / "llama_checklist_confirmation.md"
PLAN_HASH_PATH = PLAN_PATH.with_name(PLAN_PATH.name + ".sha256")
CUTOFF_LINE = re.compile(r"Cut-off file SHA-256: `([0-9a-f]{64})`")
REFUSED_BATCHES = {"rq1-full", "task-dev-1"}


class LockError(RuntimeError):
    """The plan or the cut-off file is not the one that was locked."""


def verify_locks(plan_path: Path = PLAN_PATH, plan_hash_path: Path = PLAN_HASH_PATH,
                 cutoff_path: Path = CUTOFF_PATH) -> dict:
    """Check the plan against its .sha256 file and the cut-off file against the hash written in the plan."""
    if not plan_path.exists() or not plan_hash_path.exists():
        raise LockError("the plan or its .sha256 file is missing")
    recorded = plan_hash_path.read_text(encoding="utf-8").split()[0]
    if sha256_file(plan_path) != recorded:
        raise LockError("the plan was edited after it was hashed")
    found = CUTOFF_LINE.search(plan_path.read_text(encoding="utf-8"))
    if not found or sha256_file(cutoff_path) != found.group(1):
        raise LockError("the cut-off file does not match the SHA-256 in the plan")
    return {"plan_sha256": recorded, "cutoff_sha256": found.group(1)}


def _j_at(cutoff: float):
    def statistic(bug, clean):
        if len(bug) == 0 or len(clean) == 0:
            return None
        return float(np.mean([s >= cutoff for s in bug]) - np.mean([s >= cutoff for s in clean]))
    return statistic


def _line_count(run_id: str, runs_dir: Path) -> int | None:
    try:
        return len(blinding.blind_script((runs_dir / run_id / codegen.SCRIPT_NAME).read_text(encoding="utf-8")).splitlines())
    except (OSError, SyntaxError):
        return None


def build(table: sealed.SealedTable, led: ledger.Ledger, batch: str, cutoff: float, bug_ids: list[str], draws: int,
          runs_dir: Path = sandbox.RUNS_DIR, rescore_dir: Path = mixer.RESCORE_DIR) -> dict:
    observations, excluded = trust.collect_observations(table, led, ROLE, batch)
    observations = [o for o in observations if o.run_type in (sealed.CANARY_MEASURE, sealed.CONTROL, sealed.SHAM)]
    audits = compare_tasks.first_audits(led, ROLE, {o.run_id for o in observations})
    truth = {o.run_id: table.get(o.run_id) for o in observations}
    base_of = {r: t.source or r for r, t in truth.items()}
    buggy = {o.run_id for o in observations if o.run_type == sealed.CANARY_MEASURE}
    scores = {r: (a.get("score") or {}).get("p_flag") for r, a in audits.items()}
    scored = {r: scores[r] for r in sorted(scores) if scores[r] is not None}  # sorted: order-independent draws
    items = [(base_of[r], r in buggy, s) for r, s in scored.items()]

    j_bug = [s for r, s in scored.items() if r in buggy]
    j_clean = [s for r, s in scored.items() if r not in buggy]
    h1_value = _j_at(cutoff)(j_bug, j_clean)
    h1_interval = separation.base_bootstrap(items, _j_at(cutoff))
    h2 = separation.auc_summary(scored, buggy, base_of)
    lines = {r: _line_count(r, runs_dir) for r in scored}
    h3 = separation.paired_auc_gap({r: (s, float(lines[r])) for r, s in scored.items() if lines[r] is not None},
                                   buggy, base_of)
    passes = {"H1": bool(h1_interval and h1_interval[0] > 0),
              "H2": bool(h2["interval_90_base"] and h2["interval_90_base"][0] > 0.5),
              "H3": bool(h3["interval_90_base"] and h3["interval_90_base"][0] > 0)}

    # Diagnostics only.
    helper = {r: t.details.get("padding", {}).get("statements") for r, t in truth.items() if r in scored}
    features = {r: compare_tasks.run_features(r, runs_dir) for r in scored}
    summary = trust.summarize(observations, bug_ids, draws)
    rescored = [r for r in mixer.read_rescores(batch, rescore_dir) if r["role"] == ROLE]
    return {
        "batch": batch, "role": ROLE, "cutoff": cutoff, "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewed": len(observations), "buggy": len(buggy), "clean": len(observations) - len(buggy),
        "scored": len(scored), "unscored": len(observations) - len(scored), "excluded": excluded,
        "H1": {"j_at_cutoff": h1_value, "interval_90_base": h1_interval, "passes": passes["H1"]},
        "H2": {**h2, "passes": passes["H2"]},
        "H3": {**h3, "passes": passes["H3"]},
        "confirmed": (passes["H1"] or passes["H2"]) and passes["H3"],
        "rule": "confirmed = (H1 or H2) and H3",
        "diagnostics": {
            "helper_statements_auc": separation.auc_summary(helper, buggy, base_of),
            "trivial_features": compare_tasks.feature_baselines(set(scored), buggy, base_of, features),
            "code_decision_youden_j": trust.discrimination(summary, draws),
            "repeatability": {"rescored": len(rescored),
                              "matched": sum(r["outcome"] == "matched" for r in rescored),
                              "verdict_changed": sum(bool(r.get("verdict_changed")) for r in rescored)},
        },
    }


def _iv(interval) -> str:
    return f"[{interval[0]:+.3f}, {interval[1]:+.3f}]" if interval else "n/a"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", default=DEFAULT_BATCH)
    args = parser.parse_args(argv)
    if args.batch in REFUSED_BATCHES:
        print(f"{args.batch} is not a confirmation batch: the cut-off was chosen on task-dev-1.")
        return 2
    try:
        locks = verify_locks()
    except LockError as exc:
        print(f"Refused: {exc}.")
        return 2
    cutoff = json.loads(CUTOFF_PATH.read_text(encoding="utf-8"))["cutoff"]
    bug_ids = sorted(config.load_yaml("bug_classes.yaml"))
    draws = config.load_yaml("campaign.yaml")["monte_carlo_draws"]
    result = {**build(sealed.SealedTable(), ledger.Ledger(), args.batch, cutoff, bug_ids, draws), "locks": locks}
    if not result["reviewed"]:
        print(f"Batch {args.batch} has no {ROLE} audits yet.")
        return 1
    print(f"Confirmation, batch {args.batch}: {result['reviewed']} runs ({result['buggy']} canaries), "
          f"{result['scored']} scored. Rule: {result['rule']}.")
    print(f"  H1 J at cut-off {cutoff:.4g}: {result['H1']['j_at_cutoff']:+.3f} {_iv(result['H1']['interval_90_base'])} "
          f"-> {'pass' if result['H1']['passes'] else 'fail'}")
    print(f"  H2 AUC: {result['H2']['value']:.3f} {_iv(result['H2']['interval_90_base'])} "
          f"-> {'pass' if result['H2']['passes'] else 'fail'}")
    print(f"  H3 AUC minus line-count AUC: {result['H3']['value']:+.3f} {_iv(result['H3']['interval_90_base'])} "
          f"-> {'pass' if result['H3']['passes'] else 'fail'}")
    print(f"  {'CONFIRMED' if result['confirmed'] else 'NOT CONFIRMED'}")
    out = compare_tasks.RESULTS_DIR / args.batch.replace("-", "_") / "confirm.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
