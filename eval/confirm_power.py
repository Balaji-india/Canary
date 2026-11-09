"""Power of the confirmation batch for H1 (J at the cut-off), H2 (AUC) and H3 (AUC minus the strongest trivial
feature), written before the batch runs.

Run with `python -m eval.confirm_power`. Normal approximations, so these are planning numbers, not results:
- AUC: Hanley-McNeil standard error for n_buggy and n_clean runs.
- J at a cut-off: binomial standard errors of recall and false-alarm rate.
- Both are widened by a design effect for clustering by base: (base-level / run-level interval width)^2 of the
  llama-checklist fresh AUC on task-dev-1, never below 1.
Power is P(lower 90% bound above the null) = Phi((effect - null) / (SE * sqrt(deff)) - 1.645). It is given over a
grid of true effects, because no llama AUC has yet been measured on a batch without size cues.

H3: the strongest trivial feature's direction-free AUC comes from eval/results/padding_v2/dry_proof.json (the
100-run decoy plan's script features and effect spread on existing pool-1 runs). The gap's SE treats the two AUCs as
independent, which ignores their pairing. H1 needs the cut-off from the development batch (task-dev-2), so until that
file exists its grid is left out and says so.

History: the first plan's numbers (helper size at 0.85 made H3 power near 0) stay in
eval/results/confirm_llama_1/power.json.
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
PROOF_PATH = compare_tasks.RESULTS_DIR / "padding_v2" / "dry_proof.json"
PROOF_PLAN = "100 runs, seed 1109, decoys"
OUT_PATH = compare_tasks.RESULTS_DIR / "confirm_llama_2" / "power.json"


def auc_se(auc: float, n_bug: int, n_clean: int) -> float:
    """Hanley and McNeil (1982)."""
    q1, q2 = auc / (2 - auc), 2 * auc ** 2 / (1 + auc)
    return math.sqrt((auc * (1 - auc) + (n_bug - 1) * (q1 - auc ** 2) + (n_clean - 1) * (q2 - auc ** 2))
                     / (n_bug * n_clean))


def j_se(recall: float, false_alarm: float, n_bug: int, n_clean: int) -> float:
    return math.sqrt(recall * (1 - recall) / n_bug + false_alarm * (1 - false_alarm) / n_clean)


def power(effect: float, null: float, se: float, deff: float) -> float:
    return float(stats.norm.cdf((effect - null) / (se * math.sqrt(deff)) - Z))


def h3_power(auc: float, feature_auc: float, n_bug: int, n_clean: int, deff: float) -> float:
    """P(lower bound of AUC - feature AUC above 0), both AUCs with Hanley-McNeil SEs, treated as independent."""
    se = math.sqrt(auc_se(auc, n_bug, n_clean) ** 2 + auc_se(feature_auc, n_bug, n_clean) ** 2)
    return power(auc, feature_auc, se, deff)


def strongest_feature(proof: dict) -> tuple[str, float]:
    """The trivial feature with the highest direction-free AUC in the dry proof (script features of the decoy plan
    the size of the batch, plus the gating result features)."""
    aucs = {name: r["auc"] for name, r in proof["script_features"][PROOF_PLAN]["features"].items()}
    aucs.update({name: r["auc"] for name, r in proof["result_features"]["features"].items() if r["gating"]})
    name = max(aucs, key=lambda n: max(aucs[n], 1 - aucs[n]))
    return name, max(aucs[name], 1 - aucs[name])


def design_effect(cell: dict) -> float:
    run, base = cell["auc_fresh"]["interval_90"], cell["auc_fresh"]["interval_90_base"]
    return max(1.0, ((base[1] - base[0]) / (run[1] - run[0])) ** 2)


def build(compare: dict, cutoff: dict | None, runs: int, feature: tuple[str, float]) -> dict:
    split = mixer.split_runs(runs)
    n_bug, n_clean = split[sealed.CANARY_MEASURE], split[sealed.CONTROL] + split[sealed.SHAM]
    deff = design_effect(compare["cells"]["skeptic_c_checklist"])
    h1 = None
    if cutoff is not None:
        fa = cutoff["false_alarm_rate"]
        h1 = {f"{j:.2f}": power(j, 0.0, j_se(min(fa + j, 1.0), fa, n_bug, n_clean), deff) for j in J_GRID}
    return {
        "runs": runs, "buggy": n_bug, "clean": n_clean, "design_effect": deff,
        "source": "design effect: eval/results/task_dev_1/compare_tasks.json (skeptic_c_checklist auc_fresh); "
                  f"strongest feature: {PROOF_PATH.name} ({PROOF_PLAN}, and effect spread on existing pool-1 runs)",
        "H2_power_by_true_auc": {f"{a:.2f}": power(a, 0.5, auc_se(a, n_bug, n_clean), deff) for a in AUC_GRID},
        "H1_power_by_true_j": h1,
        "H1_note": ("false-alarm rate held at the task-dev-2 cut-off's value, recall raised by J" if h1 is not None
                    else "needs the task-dev-2 cut-off: run again after `python -m eval.cutoff --batch task-dev-2`"),
        "H3_strongest_feature": feature[0], "H3_strongest_feature_auc": feature[1],
        "H3_power_by_true_auc": {f"{a:.2f}": h3_power(a, feature[1], n_bug, n_clean, deff) for a in AUC_GRID},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=RUNS)
    args = parser.parse_args(argv)
    compare = json.loads((compare_tasks.RESULTS_DIR / "task_dev_1" / "compare_tasks.json").read_text(encoding="utf-8"))
    feature = strongest_feature(json.loads(PROOF_PATH.read_text(encoding="utf-8")))
    cutoff = json.loads(CUTOFF_PATH.read_text(encoding="utf-8")) if CUTOFF_PATH.exists() else None
    result = build(compare, cutoff, args.runs, feature)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"{result['buggy']} canaries + {result['clean']} clean, design effect {result['design_effect']:.2f}")
    print("H2 power by true AUC: " + ", ".join(f"{k} -> {v:.2f}" for k, v in result["H2_power_by_true_auc"].items()))
    print("H1 power by true J:   " + (", ".join(f"{k} -> {v:.2f}" for k, v in result["H1_power_by_true_j"].items())
                                       if result["H1_power_by_true_j"] else result["H1_note"]))
    print(f"H3 power by true AUC (strongest feature {feature[0]}, AUC {feature[1]:.3f}): "
          + ", ".join(f"{k} -> {v:.2f}" for k, v in result["H3_power_by_true_auc"].items()))
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
