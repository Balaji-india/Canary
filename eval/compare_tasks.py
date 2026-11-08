"""The review-task screen: does a different way of asking give a reviewer Youden's J clearly above 0?

Run with `python -m eval.compare_tasks --batch task-dev-1` once the batch's reviews are in. Every number comes from the
ledger and the sealed table; nothing here calls a model.

The decision rule was fixed before the batch ran (plan: ~/.claude/plans/review-task-dev-batch.md) and is coded here as
written: a cell passes the screen if the lower end of the 90% interval of its J is above 0. J is RQ1's posterior J,
computed from the code's verdict. Everything else (raw-verdict J, AUC from token probabilities, paired delta J) is
reported beside it but decides nothing. A cell that passes is a candidate only: it must be confirmed on a fresh batch
built from a new pool of bases, because picking the best of six new cells on this batch inflates its J.

Added after the AUC rescore (diagnostics, also deciding nothing):
- Base-level intervals. Runs cloned from the same base share a dataset, model and most of their script, so they are
  not independent. Resampling whole bases gives the honest, wider interval.
- Fresh AUC. Matched-only AUC uses the runs where the model repeated its stored reply. The fresh pass
  (`rescore --fresh`) scores a new reply for the others, so the AUC covers every run.
- Trivial-feature baselines: AUC of signals anyone can read off a run without understanding any bug (blinded script
  length, the spread of the per-seed effect, the effect size, the best arm's score). A reviewer's AUC means little
  unless it beats these. Each is also computed on each cell's matched-only runs, to show whether matching alone
  picked an easier subset.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

from canary import blinding, codegen, config, ledger, mixer, sandbox, sealed, trust
from canary.separation import auc, base_bootstrap, bootstrap  # noqa: F401 (also used by tests via this module)
from canary.separation import auc_stat as _auc_stat
from canary.separation import auc_summary as _auc_of

RESULTS_DIR = Path(__file__).parent / "results"
TASKS = ("baseline", "grounded", "checklist")
REVIEWERS = ("skeptic_a", "skeptic_b", "skeptic_c")


def role_name(reviewer: str, task: str) -> str:
    return reviewer if task == "baseline" else f"{reviewer}_{task}"


def first_audits(led: ledger.Ledger, role: str, run_ids: set[str]) -> dict[str, dict]:
    """The first audit per run for a role, as RQ1 counts it (a later one could be picked for looking better)."""
    audits: dict[str, dict] = {}
    for entry in led.entries(ledger.AUDITED):
        if entry.payload.get("role") == role and entry.payload["run_id"] in run_ids:
            audits.setdefault(entry.payload["run_id"], entry.payload)
    return audits


def _observed_j(flags_bug: np.ndarray, flags_clean: np.ndarray) -> float:
    return float(flags_bug.mean() - flags_clean.mean())


FEATURES = ("line_count", "char_count", "effect_spread", "effect_size", "top_score")


def run_features(run_id: str, runs_dir: Path = sandbox.RUNS_DIR) -> dict[str, float] | None:
    """Signals visible to the reviewer that need no understanding of any bug. None if the run's files are missing.

    line_count, char_count: lines and characters of the blinded script. effect_spread: standard deviation across seeds of treatment - control.
    effect_size: |mean(treatment - control)|. top_score: the better arm's mean score.
    """
    run_dir = runs_dir / run_id
    try:
        script = (run_dir / codegen.SCRIPT_NAME).read_text(encoding="utf-8")
        results = json.loads((run_dir / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))
        effect = np.asarray(results["treatment"], dtype=float) - np.asarray(results["control"], dtype=float)
        blinded = blinding.blind_script(script)
        return {"line_count": float(len(blinded.splitlines())), "char_count": float(len(blinded)),
                "effect_spread": float(effect.std(ddof=1)) if len(effect) > 1 else 0.0,
                "effect_size": float(abs(effect.mean())),
                "top_score": float(max(np.mean(results["control"]), np.mean(results["treatment"])))}
    except (OSError, ValueError, KeyError, SyntaxError):
        return None


def _spearman(pairs: list[tuple[float | None, dict | None]]) -> dict | None:
    """Spearman's rho between a score and the blinded line count, within one group (buggy or clean).

    Within a group the truth is fixed, so a strong rho means the score follows script length rather than the bug.
    """
    xy = [(s, f["line_count"]) for s, f in pairs if s is not None and f]
    if len(xy) < 5 or len({x for x, _ in xy}) < 2 or len({y for _, y in xy}) < 2:
        return None
    rho, p = stats.spearmanr([x for x, _ in xy], [y for _, y in xy])
    return {"rho": float(rho), "p": float(p), "n": len(xy)}


def feature_baselines(run_ids: set[str], buggy: set[str], base_of: dict[str, str],
                      features: dict[str, dict[str, float] | None]) -> dict:
    """AUC of each trivial feature over `run_ids`. AUC below 0.5 means the feature is lower on buggy runs; a feature
    far from 0.5 in either direction is a cue a reviewer could use without finding the bug."""
    have = {r for r in run_ids if features.get(r)}
    return {name: _auc_of({r: features[r][name] for r in have}, buggy, base_of) for name in FEATURES} if have else {}


def cell(table: sealed.SealedTable, led: ledger.Ledger, batch: str, role: str, bug_ids: list[str], draws: int,
         rescores: dict[tuple[str, str], dict] | None = None, fresh: dict[tuple[str, str], dict] | None = None,
         features: dict[str, dict[str, float] | None] | None = None) -> dict | None:
    observations, excluded = trust.collect_observations(table, led, role, batch)
    observations = [o for o in observations if o.run_type in (sealed.CANARY_MEASURE, sealed.CONTROL, sealed.SHAM)]
    if not observations:
        return None
    audits = first_audits(led, role, {o.run_id for o in observations})
    summary = trust.summarize(observations, bug_ids, draws)
    j = trust.discrimination(summary, draws)
    decisions = {o.run_id: audits[o.run_id].get("decision") or audits[o.run_id]["audit"] for o in observations}

    raw_flagged = {o.run_id: decisions[o.run_id].get("raw_verdict", decisions[o.run_id]["verdict"]) == trust.FLAG
                   for o in observations}
    raw_obs = [trust.Observation(o.run_id, o.run_type, o.bug_id, o.tier, o.impact, raw_flagged[o.run_id], o.named_class)
               for o in observations]
    raw_j = trust.discrimination(trust.summarize(raw_obs, bug_ids, draws), draws)

    buggy = [o for o in observations if o.run_type == sealed.CANARY_MEASURE]
    clean = [o for o in observations if o.run_type != sealed.CANARY_MEASURE]
    # The audit's own score; else a rescore, used only if it belongs to this very audit and the reply repeated exactly.
    rescores = rescores or {}
    scores, sources, one_sided = {}, {"audit": 0, "rescore": 0, "none": 0}, 0
    for o in observations:
        score = audits[o.run_id].get("score")
        source = "audit" if score else "none"
        record = rescores.get((role, o.run_id))
        if not score and record and record["outcome"] == "matched" and record["prompt_sha256"] == audits[o.run_id]["prompt_sha256"]:
            score, source = record["score"], "rescore"
        sources[source if score else "none"] += 1
        scores[o.run_id] = score["p_flag"] if score else None
        one_sided += bool(score and score.get("both_seen") is False)
    outcomes: dict[str, int] = {}
    for (r, _), record in rescores.items():
        if r == role:
            outcomes[record["outcome"]] = outcomes.get(record["outcome"], 0) + 1
    scored_bug = [scores[o.run_id] for o in buggy if scores[o.run_id] is not None]
    scored_clean = [scores[o.run_id] for o in clean if scores[o.run_id] is not None]

    # Fresh: the matched score where there is one, else the fresh pass's score of a new reply to the same prompt.
    fresh = fresh or {}
    fresh_scores = dict(scores)
    fresh_outcomes = {"matched_first": 0, "fresh": 0, "missing": 0}
    for o in observations:
        record = fresh.get((role, o.run_id))
        usable = bool(record and record.get("score") and record["prompt_sha256"] == audits[o.run_id]["prompt_sha256"])
        if fresh_scores[o.run_id] is not None:
            fresh_outcomes["matched_first"] += 1
        elif usable:
            fresh_scores[o.run_id] = record["score"]["p_flag"]
            fresh_outcomes["fresh"] += 1
        else:
            fresh_outcomes["missing"] += 1
    base_of = {o.run_id: (table.get(o.run_id).source or o.run_id) for o in observations}
    buggy_ids = {o.run_id for o in buggy}
    auc_fresh = _auc_of(fresh_scores, buggy_ids, base_of)
    auc_fresh.update({"sources": fresh_outcomes, "complete": fresh_outcomes["missing"] == 0,
                      "verdict_changed": sum(bool(fresh.get((role, o.run_id), {}).get("verdict_changed"))
                                             for o in observations),
                      "fresh_records": sum((role, o.run_id) in fresh for o in observations)})
    matched_base = base_bootstrap([(base_of[r], r in buggy_ids, v) for r, v in scores.items() if v is not None],
                                  _auc_stat)
    features_on_matched = feature_baselines({r for r, v in scores.items() if v is not None}, buggy_ids, base_of,
                                            features or {})
    length_link = {group: _spearman([(fresh_scores[r], (features or {}).get(r)) for r in ids])
                   for group, ids in (("buggy", buggy_ids), ("clean", {o.run_id for o in clean}))}

    yes_counts = [len(d["yes_classes"]) for d in decisions.values() if "yes_classes" in d]
    in_yes = [o.bug_id in decisions[o.run_id]["yes_classes"] for o in buggy if "yes_classes" in decisions[o.run_id]]
    verified = [d["line_verified"] for d in decisions.values() if "line_verified" in d]
    failures = trust.collect_failures(table, led, role, batch)
    return {
        "role": role, "models": sorted({a["model"] for a in audits.values()}), "reviewed": len(observations),
        "buggy": len(buggy), "clean": len(clean), "flagged_buggy": sum(o.flagged for o in buggy),
        "flagged_clean": sum(o.flagged for o in clean), "excluded": excluded,
        "youden_j": j, "passes_screen": bool(j and j["interval"][0] > 0),
        "raw_verdict_youden_j": raw_j,
        "named_right": {"successes": summary.named_right.successes, "n": summary.named_right.n},
        "auc": {"value": auc(scored_bug, scored_clean),
                "interval_90": bootstrap(scored_bug, scored_clean, lambda b, c: auc(list(b), list(c))),
                "interval_90_base": matched_base,
                "scored_buggy": len(scored_bug), "scored_clean": len(scored_clean), "sources": sources,
                "rescore_outcomes": outcomes, "one_sided_scores": one_sided},
        "auc_fresh": auc_fresh,
        "features_on_matched_runs": features_on_matched,
        "score_vs_line_count_rho": length_link,
        "line_verified_share": (sum(verified) / len(verified)) if verified else None,
        "checklist": {"mean_yes_per_run": float(np.mean(yes_counts)), "truth_among_yes": sum(in_yes),
                      "canaries": len(in_yes)} if yes_counts else None,
        "failed_audits": {k: sum(row["failure_kinds"].get(k, 0) for row in failures["by_type"].values())
                          for k in {kind for row in failures["by_type"].values() for kind in row["failure_kinds"]}},
        "seconds_median": float(np.median([a["seconds"] for a in audits.values() if not a.get("cached")] or [np.nan])),
        "_flags": {o.run_id: (o.run_type == sealed.CANARY_MEASURE, o.flagged) for o in observations},
    }


def paired_delta(variant: dict, base: dict) -> dict | None:
    """J of the variant minus J of the same model's baseline, on the runs both reviewed (observed counts)."""
    common = sorted(set(variant["_flags"]) & set(base["_flags"]))
    bug = [(variant["_flags"][r][1], base["_flags"][r][1]) for r in common if variant["_flags"][r][0]]
    clean = [(variant["_flags"][r][1], base["_flags"][r][1]) for r in common if not variant["_flags"][r][0]]
    if not bug or not clean:
        return None

    def delta(b: np.ndarray, c: np.ndarray) -> float:
        b, c = np.asarray(b, dtype=float).reshape(-1, 2), np.asarray(c, dtype=float).reshape(-1, 2)
        return _observed_j(b[:, 0], c[:, 0]) - _observed_j(b[:, 1], c[:, 1])

    return {"runs": len(common), "observed": delta(np.asarray(bug), np.asarray(clean)),
            "interval_90": bootstrap(bug, clean, delta)}


def build(table: sealed.SealedTable, led: ledger.Ledger, batch: str, bug_ids: list[str], draws: int,
          rescore_dir: Path = mixer.RESCORE_DIR, runs_dir: Path = sandbox.RUNS_DIR) -> dict:
    rescores = {(r["role"], r["run_id"]): r for r in mixer.read_rescores(batch, rescore_dir)}
    fresh = {(r["role"], r["run_id"]): r for r in mixer.read_rescores(batch, rescore_dir, mixer.FRESH)}
    reviewed = {t.run_id: t for t in (table.get(r) for r in mixer.batch_run_ids(table, batch))
                if t and t.run_type in (sealed.CANARY_MEASURE, sealed.CONTROL, sealed.SHAM)}
    features = {r: run_features(r, runs_dir) for r in reviewed}
    cells = {}
    for reviewer in REVIEWERS:
        for task in TASKS:
            result = cell(table, led, batch, role_name(reviewer, task), bug_ids, draws, rescores, fresh, features)
            if result:
                cells[result["role"]] = {"reviewer": reviewer, "task": task, **result}
    for name, c in cells.items():
        base = cells.get(c["reviewer"])
        c["delta_j_vs_baseline"] = paired_delta(c, base) if base and c["task"] != "baseline" else None
    for c in cells.values():
        c.pop("_flags")
    buggy = {r for r, t in reviewed.items() if t.run_type == sealed.CANARY_MEASURE}
    base_of = {r: t.source or r for r, t in reviewed.items()}
    return {"batch": batch, "generated_at": datetime.now(timezone.utc).isoformat(),
            "rule": "a cell passes the screen if the lower end of the 90% interval of its posterior Youden's J is above 0",
            "cells": cells, "passing": [name for name, c in cells.items() if c["passes_screen"]],
            "feature_baselines": feature_baselines(set(reviewed), buggy, base_of, features)}


def _j(d: dict | None) -> str:
    return "n/a" if not d else f"{d['youden_j']:+.3f} [{d['interval'][0]:+.3f}, {d['interval'][1]:+.3f}]"


def _range(value: float | None, interval: list[float] | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.3f}" + (f" [{interval[0]:+.3f}, {interval[1]:+.3f}]" if interval else "")


def _auc(a: dict) -> str:
    if a["value"] is None:
        return "n/a"
    low_high = f" [{a['interval_90'][0]:.2f}, {a['interval_90'][1]:.2f}]" if a["interval_90"] else ""
    return f"{a['value']:.3f}{low_high}"


def print_table(r: dict) -> None:
    print(f"Review-task screen, batch {r['batch']}. Rule: {r['rule']}.\n")
    header = f"{'role':<22}{'model':<18}{'n':>4}{'flag bug':>9}{'flag clean':>11}  {'J (90%)':<26}{'pass':<6}{'raw J':<26}{'AUC (90%)':<24}{'dJ vs base (90%)':<26}"
    print(header)
    for name, c in r["cells"].items():
        d = c["delta_j_vs_baseline"]
        print(f"{name:<22}{', '.join(c['models']):<18}{c['reviewed']:>4}{c['flagged_buggy']:>4}/{c['buggy']:<4}"
              f"{c['flagged_clean']:>6}/{c['clean']:<4}  {_j(c['youden_j']):<26}{'YES' if c['passes_screen'] else 'no':<6}"
              f"{_j(c['raw_verdict_youden_j']):<26}"
              f"{_auc(c['auc']):<24}"
              f"{_range(d['observed'], d['interval_90']) if d else '-':<26}")
    print("\nAUC is from token probabilities and decides nothing; raw J ignores the code's line check.")
    for name, c in r["cells"].items():
        extra = []
        if c["line_verified_share"] is not None:
            extra.append(f"line verified {c['line_verified_share']:.2f}")
        if c["checklist"]:
            extra.append(f"mean yes per run {c['checklist']['mean_yes_per_run']:.2f}, truth among yes "
                         f"{c['checklist']['truth_among_yes']}/{c['checklist']['canaries']}")
        if c["failed_audits"]:
            extra.append(f"failed audits {c['failed_audits']}")
        extra.append(f"named right {c['named_right']['successes']}/{c['named_right']['n']}")
        a = c["auc"]
        extra.append(f"scored {a['scored_buggy']}+{a['scored_clean']} (from audit {a['sources']['audit']}, rescore "
                     f"{a['sources']['rescore']}; rescore outcomes {a['rescore_outcomes'] or '-'}; one-sided {a['one_sided_scores']})")
        extra.append(f"median {c['seconds_median']:.1f} s per audit")
        print(f"  {name}: " + "; ".join(extra))
    print(f"\nPassing the screen: {', '.join(r['passing']) or 'none'}. A pass is a candidate for the confirmation batch, not a result.")
    print_auc_table(r)


def _iv(interval: list[float] | None) -> str:
    return f"[{interval[0]:.2f}, {interval[1]:.2f}]" if interval else "n/a"


def _v(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def print_auc_table(r: dict) -> None:
    """Matched-only and fresh AUC side by side, each with run-level and base-level 90% intervals; then the features."""
    print("\nAUC (decides nothing). run = resample runs; base = resample whole bases.")
    print(f"{'role':<22}{'matched':>8}  {'AUC':>6} {'run 90%':<14}{'base 90%':<14}{'fresh':>7}  {'AUC':>6} "
          f"{'run 90%':<14}{'base 90%':<14}{'verdict chg':>11}")
    for name, c in r["cells"].items():
        m, f = c["auc"], c["auc_fresh"]
        fn = f"{f['scored_buggy'] + f['scored_clean']}/{c['reviewed']}" + ("" if f["complete"] else "*")
        print(f"{name:<22}{m['scored_buggy'] + m['scored_clean']:>5}/{c['reviewed']:<2}  {_v(m['value']):>6} "
              f"{_iv(m['interval_90']):<14}{_iv(m['interval_90_base']):<14}{fn:>7}  {_v(f['value']):>6} "
              f"{_iv(f['interval_90']):<14}{_iv(f['interval_90_base']):<14}{f['verdict_changed']:>6}/{f['fresh_records']}")
    print("* fresh pass incomplete for this cell. verdict chg: fresh replies whose verdict differs from the stored one.")
    fb = r.get("feature_baselines") or {}
    if fb:
        print("\nTrivial-feature baselines on all reviewed runs (AUC < 0.5: lower on buggy runs):")
        for name, a in fb.items():
            print(f"  {name:<14} AUC {_v(a['value'])}  run {_iv(a['interval_90'])}  base {_iv(a['interval_90_base'])}"
                  f"  ({a['scored_buggy']}+{a['scored_clean']} runs, {a['bases']} bases)")
        print("Same features on each cell's matched-only runs (does matching pick an easier subset?):")
        for name, c in r["cells"].items():
            fm = c["features_on_matched_runs"]
            if fm:
                print(f"  {name:<22}" + "  ".join(f"{k} {_v(v['value'])}" for k, v in fm.items()))
    print("Score vs blinded line count, Spearman rho within each group (fresh scores; the truth is fixed in a group):")
    for name, c in r["cells"].items():
        link = c["score_vs_line_count_rho"]
        print(f"  {name:<22}" + "  ".join(
            f"{g} " + (f"{v['rho']:+.2f} (p {v['p']:.2f}, n {v['n']})" if v else "n/a") for g, v in link.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", required=True)
    args = parser.parse_args(argv)
    if args.batch == "rq1-full":
        print("The screen never uses rq1-full: that batch is the untouched baseline.")
        return 2
    bug_ids = sorted(config.load_yaml("bug_classes.yaml"))
    draws = config.load_yaml("campaign.yaml")["monte_carlo_draws"]
    result = build(sealed.SealedTable(), ledger.Ledger(), args.batch, bug_ids, draws)
    if not result["cells"]:
        print(f"Batch {args.batch} has no reviews yet.")
        return 1
    print_table(result)
    out = RESULTS_DIR / args.batch.replace("-", "_") / "compare_tasks.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
