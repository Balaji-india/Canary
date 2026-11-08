"""Power of the confirmation batch for H1 (J at the cut-off) and H2 (AUC), written before the batch runs.

Run with `python -m eval.confirm_power`. Normal approximations, so these are planning numbers, not results:
- AUC: Hanley-McNeil standard error for n_buggy and n_clean runs.
- J at a cut-off: binomial standard errors of recall and false-alarm rate.
- Both are widened by a design effect for clustering by base: (base-level / run-level interval width)^2 of the
  llama-checklist fresh AUC on task-dev-1, never below 1.
Power is P(lower 90% bound above the null) = Phi((effect - null) / (SE * sqrt(deff)) - 1.645). It is given over a
grid of true effects, because the task-dev-1 values were measured on length-confounded data and may be too high.
"""
from __future__ import annotations

import argparse
import json
import math

from scipy import stats

from canary import mixer, sealed
from eval import compare_tasks
from eval.cutoff import CUTOFF_PATH

RUNS = 100
AUC_GRID = (0.60, 0.65, 0.70, 0.75)
J_GRID = (0.10, 0.20, 0.30, 0.40)
Z = 1.6448536269514722  # one-sided 5%: the lower end of a 90% interval


def auc_se(auc: float, n_bug: int, n_clean: int) -> float:
    """Hanley and McNeil (1982)."""
    q1, q2 = auc / (2 - auc), 2 * auc ** 2 / (1 + auc)
    return math.sqrt((auc * (1 - auc) + (n_bug - 1) * (q1 - auc ** 2) + (n_clean - 1) * (q2 - auc ** 2))
                     / (n_bug * n_clean))


def j_se(recall: float, false_alarm: float, n_bug: int, n_clean: int) -> float:
    return math.sqrt(recall * (1 - recall) / n_bug + false_alarm * (1 - false_alarm) / n_clean)


def power(effect: float, null: float, se: float, deff: float) -> float:
    return float(stats.norm.cdf((effect - null) / (se * math.sqrt(deff)) - Z))


def design_effect(cell: dict) -> float:
    run, base = cell["auc_fresh"]["interval_90"], cell["auc_fresh"]["interval_90_base"]
    return max(1.0, ((base[1] - base[0]) / (run[1] - run[0])) ** 2)


def build(compare: dict, cutoff: dict, runs: int = RUNS) -> dict:
    split = mixer.split_runs(runs)
    n_bug, n_clean = split[sealed.CANARY_MEASURE], split[sealed.CONTROL] + split[sealed.SHAM]
    deff = design_effect(compare["cells"]["skeptic_c_checklist"])
    fa = cutoff["false_alarm_rate"]
    return {
        "runs": runs, "buggy": n_bug, "clean": n_clean, "design_effect": deff,
        "source": "eval/results/task_dev_1/compare_tasks.json (skeptic_c_checklist auc_fresh) and the locked cut-off",
        "task_dev_1": {"auc_fresh": compare["cells"]["skeptic_c_checklist"]["auc_fresh"]["value"],
                       "j_at_cutoff": cutoff["j"], "recall": cutoff["recall"], "false_alarm_rate": fa},
        "H2_power_by_true_auc": {f"{a:.2f}": power(a, 0.5, auc_se(a, n_bug, n_clean), deff) for a in AUC_GRID},
        "H1_power_by_true_j": {f"{j:.2f}": power(j, 0.0, j_se(min(fa + j, 1.0), fa, n_bug, n_clean), deff)
                               for j in J_GRID},
        "note": "H1 grid keeps the false-alarm rate at its task-dev-1 value and raises recall by J.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=RUNS)
    args = parser.parse_args(argv)
    compare = json.loads((compare_tasks.RESULTS_DIR / "task_dev_1" / "compare_tasks.json").read_text(encoding="utf-8"))
    result = build(compare, json.loads(CUTOFF_PATH.read_text(encoding="utf-8")), args.runs)
    out = compare_tasks.RESULTS_DIR / "confirm_llama_1" / "power.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"{result['buggy']} canaries + {result['clean']} clean, design effect {result['design_effect']:.2f}")
    print("H2 power by true AUC: " + ", ".join(f"{k} -> {v:.2f}" for k, v in result["H2_power_by_true_auc"].items()))
    print("H1 power by true J:   " + ", ".join(f"{k} -> {v:.2f}" for k, v in result["H1_power_by_true_j"].items()))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
