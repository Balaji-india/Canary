"""Descriptive breakdown of a finished ceiling arm: where the reviewer's hits and misses are. Deciding nothing.

Why a separate file: `eval/ceiling.py` is frozen by the locked plan (`docs/plans/cloud_ceiling_check.md`) and has
already given the arm's one outcome. This script never recomputes that outcome and never writes `arm_<X>.json`. It
reads the same rows through `ceiling.cell_rows` (so the totals must equal the arm file, and it stops if they do not)
and only splits them: recall per bug class and tier, specificity per clean type and per decoy, the repeat pass as
verdict and bug-class agreement, and a side comparison with the local reviewers.

Every table here is exploratory. The groups are small (3 canaries per bug variant), the splits were not
pre-registered, and nothing may be tuned on them without a fresh batch. Only counts and group labels are written:
no run ID, so reading this file tells nobody which run is which.

    python -m eval.ceiling_breakdown --arm L
"""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from scipy import stats

from canary import ledger, mixer, sealed
from eval import ceiling

LEVEL = 0.95  # Jeffreys interval for one proportion; it ignores clustering, so read it as a rough guide only
SCREEN_BATCH = "task-dev-1"  # the only batch gemma and phi reviewed with the baseline prompt
SCREEN_ROLES = ("skeptic_a", "skeptic_b", "skeptic_c")  # gemma3:4b, phi4-mini, llama3.1:8b, baseline prompt


def jeffreys(hits: int, n: int, level: float = LEVEL) -> list[float] | None:
    """Equal-tailed Beta(hits + 0.5, n - hits + 0.5) interval, with the usual ends: 0 at 0 hits, 1 at n hits."""
    if n == 0:
        return None
    low, high = stats.beta.ppf([(1 - level) / 2, (1 + level) / 2], hits + 0.5, n - hits + 0.5)
    return [0.0 if hits == 0 else float(low), 1.0 if hits == n else float(high)]


def rate(hits: int, n: int) -> dict:
    return {"hits": hits, "of": n, "value": hits / n if n else None, "interval_95_jeffreys": jeffreys(hits, n)}


def split(rows: list[dict], key, hit) -> dict:
    """rate of `hit(row)` in each group `key(row)`, groups in sorted order."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(str(key(row)), []).append(row)
    return {name: rate(sum(hit(r) for r in group), len(group)) for name, group in sorted(groups.items())}


def _count(labels) -> dict:
    return dict(sorted(Counter(labels).items()))


def recall_tables(rows: list[dict]) -> dict:
    """Caught canaries of all canaries, split one way at a time. A canary is caught when the verdict is `flag`."""
    canaries = [r for r in rows if r["buggy"]]
    caught = lambda r: r["flagged"]  # noqa: E731
    return {"overall": rate(sum(map(caught, canaries)), len(canaries)),
            "by_class": split(canaries, lambda r: r["bug_id"], caught),
            "by_tier": split(canaries, lambda r: r["tier"], caught),
            "by_class_and_tier": split(canaries, lambda r: f"{r['bug_id']} {r['tier']}", caught),
            "by_batch": split(canaries, lambda r: r["batch"], caught),
            "by_dataset": split(canaries, lambda r: r["focus"].split("|")[0], caught),
            "by_metric": split(canaries, lambda r: r["focus"].split("|")[1], caught),
            "by_model": split(canaries, lambda r: r["focus"].split("|")[2], caught),
            "missed_by_class_and_dataset": _count(f"{r['bug_id']} {r['tier']} on {r['focus'].split('|')[0]}, "
                                                  f"{r['focus'].split('|')[1]}" for r in canaries if not caught(r))}


def naming_tables(rows: list[dict]) -> dict:
    """Of the caught canaries, how many were flagged with the planted class named (right for the right reason)."""
    caught = [r for r in rows if r["buggy"] and r["flagged"]]
    right = lambda r: r["named"] == r["bug_id"]  # noqa: E731
    wrong = Counter(f"{r['bug_id']} named {r['named']}" for r in caught if not right(r))
    return {"overall": rate(sum(map(right, caught)), len(caught)),
            "by_class": split(caught, lambda r: r["bug_id"], right),
            "wrong_names": dict(sorted(wrong.items()))}


def specificity_tables(rows: list[dict]) -> dict:
    """Passed clean runs of all clean runs, by clean type and by the decoy the clean run carries."""
    clean = [r for r in rows if not r["buggy"]]
    passed = lambda r: not r["flagged"]  # noqa: E731
    with_decoy = [r for r in clean if r["decoy"]]
    return {"overall": rate(sum(map(passed, clean)), len(clean)),
            "by_type": split(clean, lambda r: r["run_type"], passed),
            "with_decoy": rate(sum(map(passed, with_decoy)), len(with_decoy)),
            "without_decoy": rate(sum(passed(r) for r in clean if not r["decoy"]), len(clean) - len(with_decoy)),
            "by_decoy_class": split(with_decoy, lambda r: r["decoy"]["bug_id"], passed),
            "by_decoy_tier": split(with_decoy, lambda r: r["decoy"]["tier"], passed),
            "by_type_and_decoy_tier": split(with_decoy, lambda r: f"{r['run_type']} {r['decoy']['tier']}", passed)}


def repeat_tables(records: list[dict], first: dict[str, dict], truth: dict[str, dict]) -> dict:
    """The repeat pass as agreement of decisions, not of wording.

    `records` are the repeat records that got a reply, `first` maps a run to its first decision
    ({"verdict", "bug_class"}), `truth` to its row. Bug-class agreement is counted over all asked runs (a pass names
    no class, so two passes agree) and again over the runs flagged both times, where a class is really named.
    """
    # a `matched` record is a reply identical to the first one: it stores no new decision, the first one stands
    asked = [{**r, "new_decision": r.get("new_decision") or first[r["run_id"]]} for r in records if r["run_id"] in first]
    same_verdict = [r for r in asked if r["new_decision"]["verdict"] == first[r["run_id"]]["verdict"]]
    same_class = [r for r in asked if r["new_decision"].get("bug_class") == first[r["run_id"]].get("bug_class")]
    both_flag = [r for r in same_verdict if r["new_decision"]["verdict"] == "flag"]
    changed = [r for r in asked if r["new_decision"]["verdict"] != first[r["run_id"]]["verdict"]]
    return {"asked": len(asked),
            "buggy_asked": sum(truth[r["run_id"]]["buggy"] for r in asked),
            "clean_asked": sum(not truth[r["run_id"]]["buggy"] for r in asked),
            "verdict_same": rate(len(same_verdict), len(asked)),
            "bug_class_same": rate(len(same_class), len(asked)),
            "bug_class_same_when_flagged_twice": rate(sum(r in same_class for r in both_flag), len(both_flag)),
            "wording_differs": sum(r["outcome"] == "reply_differs" for r in asked),
            "fields_changed": dict(sorted(Counter(f for r in asked for f in r.get("fields_changed") or []).items())),
            "verdict_changes": dict(sorted(Counter(
                f"{'buggy' if truth[r['run_id']]['buggy'] else 'clean'} run: {first[r['run_id']]['verdict']} then "
                f"{r['new_decision']['verdict']}" for r in changed).items()))}


def verdict_summary(rows: list[dict]) -> dict:
    """Flagged buggy, flagged clean and Youden's J (recall minus false-alarm rate) of one reviewer on its rows."""
    buggy, clean = [r for r in rows if r["buggy"]], [r for r in rows if not r["buggy"]]
    hit, alarm = sum(r["flagged"] for r in buggy), sum(r["flagged"] for r in clean)
    j = hit / len(buggy) - alarm / len(clean) if buggy and clean else None
    return {"runs": len(rows), "flagged_buggy": rate(hit, len(buggy)), "flagged_clean": rate(alarm, len(clean)),
            "youden_j": j, "auc_verdict": None if j is None else (1 + j) / 2}


# ---------- loading (the only part that touches the ledger and the sealed table) ----------

def first_decisions(led: ledger.Ledger, role: str) -> dict[str, dict]:
    """Run ID -> the code's decision from the role's first stored reply (the reply the locked analysis counts)."""
    first: dict[str, dict] = {}
    for e in led.entries():
        if e.status == ledger.AUDITED and e.payload.get("role") == role:
            first.setdefault(e.payload["run_id"], e.payload.get("decision") or e.payload["audit"])
    return first


def detailed_rows(table: sealed.SealedTable, led: ledger.Ledger, batches: tuple[str, ...], role: str) -> list[dict]:
    """`ceiling.cell_rows` (the frozen analysis' own rows) plus class, batch, decoy and the class the reviewer named."""
    truths = {t.run_id: t for t in table.all()}
    decisions = first_decisions(led, role)
    rows = []
    for row in ceiling.cell_rows(table, led, batches, role)["rows"]:
        truth = truths[row["run_id"]]
        rows.append({**row, "bug_id": truth.bug_id, "batch": truth.details["batch"],
                     "decoy": truth.details.get("decoy"),
                     "named": (decisions.get(row["run_id"]) or {}).get("bug_class")})
    return rows


def model_of(led: ledger.Ledger, role: str) -> list[str]:
    return sorted({str(e.payload.get("model")) for e in led.entries()
                   if e.status == ledger.AUDITED and e.payload.get("role") == role})


def build(arm: str, table: sealed.SealedTable, led: ledger.Ledger, out_dir: Path = ceiling.OUT_DIR) -> dict:
    """The whole breakdown of one finished arm. Stops if the arm file is missing or the totals do not match it."""
    arm_file = out_dir / f"arm_{arm}.json"
    if not arm_file.exists():
        raise SystemExit(f"{arm_file} is missing: run the locked analysis first (it runs once)")
    locked = json.loads(arm_file.read_text(encoding="utf-8"))
    (role,) = ceiling.ARMS[arm]
    rows = detailed_rows(table, led, ceiling.BATCHES, role)
    cell, totals = locked["cells"][role], verdict_summary(rows)
    if (totals["runs"], totals["flagged_buggy"]["hits"], totals["flagged_clean"]["hits"]) != (
            cell["runs"], cell["flagged_buggy"], cell["flagged_clean"]):
        raise SystemExit("the rows do not add up to the locked arm file: nothing written")

    truth = {r["run_id"]: r for r in rows}
    repeats = [r for b in ceiling.BATCHES for r in mixer.read_rescores(b, mixer.RESCORE_DIR, ceiling.REPEAT_KIND)
               if r["role"] == role and r["outcome"] in ("matched", "reply_differs")]

    same_runs = {}
    dev2_ids = {r["run_id"] for r in rows if r["batch"] == ceiling.LLAMA_BATCH}
    for other in (role, ceiling.LLAMA_ROLE):
        other_rows = [r for r in ceiling.cell_rows(table, led, (ceiling.LLAMA_BATCH,), other)["rows"]
                      if r["run_id"] in dev2_ids]
        same_runs[other] = {"models": model_of(led, other), **verdict_summary(other_rows)}
    screen = {r: {"models": model_of(led, r), **verdict_summary(ceiling.cell_rows(table, led, (SCREEN_BATCH,), r)["rows"])}
              for r in SCREEN_ROLES}

    return {"arm": arm, "role": role, "models": cell["models"], "generated_at": datetime.now(timezone.utc).isoformat(),
            "arm_file_outcome": locked["outcome"]["outcome"], "totals_match_arm_file": True,
            "status": "exploratory: not pre-registered, small groups, decides nothing",
            "interval": "95% Jeffreys per proportion, clustering ignored",
            "recall": recall_tables(rows), "class_named": naming_tables(rows),
            "specificity": specificity_tables(rows),
            "repeat_pass": repeat_tables(repeats, first_decisions(led, role), truth),
            "side_comparison": {
                "paired_auc_difference_from_arm_file": cell.get("paired_vs_llama"),
                "same_runs": {"batch": ceiling.LLAMA_BATCH, "note": "the same 40 padded runs with decoys; the prompts "
                              "differ (cloud: baseline, llama: checklist with a line check)", "reviewers": same_runs},
                "other_runs": {"batch": SCREEN_BATCH, "note": "40 different runs, no padding and no decoys, baseline "
                               "prompt; the cloud model never saw them, so this is context only", "reviewers": screen}}}


# ---------- printing ----------

def _cell(r: dict) -> str:
    low, high = r["interval_95_jeffreys"] or (None, None)
    return f"{r['hits']}/{r['of']}" if low is None else f"{r['hits']}/{r['of']} ({r['value']:.0%}) [{low:.2f}, {high:.2f}]"


def _table(title: str, header: list[str], lines: list[list[str]]) -> str:
    out = [f"**{title}**", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(out + ["| " + " | ".join(line) + " |" for line in lines]) + "\n"


def render(b: dict) -> str:
    rec, spec, rep, side = b["recall"], b["specificity"], b["repeat_pass"], b["side_comparison"]
    parts = [f"Arm {b['arm']} breakdown, `{b['role']}` ({', '.join(b['models'])}). Locked outcome: "
             f"{b['arm_file_outcome']}. Exploratory, decides nothing. Intervals: {b['interval']}.\n"]
    tiers = sorted(rec["by_tier"])
    classes = sorted(rec["by_class"])
    parts.append(_table("1. Recall per bug class and tier (caught / planted)", ["Class", *tiers, "Both tiers",
                                                                               "Planted class named, of caught"],
                        [[c, *(f"{rec['by_class_and_tier'][f'{c} {t}']['hits']}/{rec['by_class_and_tier'][f'{c} {t}']['of']}"
                               for t in tiers), _cell(rec["by_class"][c]),
                          _cell(b["class_named"]["by_class"][c]) if c in b["class_named"]["by_class"] else "none caught"]
                         for c in classes]
                        + [["All", *(_cell(rec["by_tier"][t]) for t in tiers), _cell(rec["overall"]),
                            _cell(b["class_named"]["overall"])]]))
    for name, key in (("batch", "by_batch"), ("dataset", "by_dataset"), ("metric", "by_metric"), ("model", "by_model")):
        parts.append(_table(f"1b. Recall by {name}", [name.capitalize(), "Caught"],
                            [[k, _cell(v)] for k, v in rec[key].items()]))
    parts.append(_table("1b. The missed canaries: class, tier, dataset, metric", ["Missed", "Runs"],
                        [[k, str(v)] for k, v in rec["missed_by_class_and_dataset"].items()]))
    if b["class_named"]["wrong_names"]:
        parts.append(_table("1c. Caught, but another class named", ["Planted, named", "Runs"],
                            [[k, str(v)] for k, v in b["class_named"]["wrong_names"].items()]))
    parts.append(_table("2. Specificity (passed / clean runs)", ["Group", "Passed"],
                        [["all clean runs", _cell(spec["overall"])],
                         *[[f"type: {k}", _cell(v)] for k, v in spec["by_type"].items()],
                         ["clean runs carrying a decoy", _cell(spec["with_decoy"])],
                         ["clean runs without a decoy", _cell(spec["without_decoy"])],
                         *[[f"decoy tier: {k}", _cell(v)] for k, v in spec["by_decoy_tier"].items()],
                         *[[f"{k} decoy", _cell(v)] for k, v in spec["by_type_and_decoy_tier"].items()],
                         *[[f"decoy of class {k}", _cell(v)] for k, v in spec["by_decoy_class"].items()]]))
    parts.append(_table("3. Repeat pass (same prompt asked again, days later)", ["Measure", "Value"],
                        [["runs asked again", f"{rep['asked']} ({rep['buggy_asked']} buggy, {rep['clean_asked']} clean)"],
                         ["same verdict", _cell(rep["verdict_same"])],
                         ["same bug class (a pass names none)", _cell(rep["bug_class_same"])],
                         ["same bug class, runs flagged both times", _cell(rep["bug_class_same_when_flagged_twice"])],
                         ["wording differs (not a disagreement)", f"{rep['wording_differs']}/{rep['asked']}"],
                         ["fields that changed", ", ".join(f"{k} {v}" for k, v in rep["fields_changed"].items()) or "none"],
                         ["verdict changes", ", ".join(f"{k} ({v})" for k, v in rep["verdict_changes"].items()) or "none"]]))
    for label, block in (("4a. SIDE COMPARISON, same runs", side["same_runs"]),
                         ("4b. SIDE COMPARISON, other runs (context only)", side["other_runs"])):
        parts.append(_table(f"{label}: {block['batch']}. {block['note']}",
                            ["Reviewer", "Model", "Flagged buggy", "Flagged clean", "J", "Verdict AUC"],
                            [[r, ", ".join(v["models"]), _cell(v["flagged_buggy"]), _cell(v["flagged_clean"]),
                              f"{v['youden_j']:+.3f}", f"{v['auc_verdict']:.3f}"] for r, v in block["reviewers"].items()]))
    paired = side["paired_auc_difference_from_arm_file"]
    if paired:
        low, high = paired["interval_975_base"]
        parts.append(f"From the locked arm file (secondary): cloud verdict AUC minus {paired['llama_role']}'s P(flag) AUC "
                     f"on the same {paired['runs']} runs = {paired['value']:+.3f} [{low:+.3f}, {high:+.3f}] (97.5%, "
                     f"base-level bootstrap)." + chr(10))
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arm", choices=sorted(ceiling.ARMS), required=True)
    args = parser.parse_args(argv)
    breakdown = build(args.arm, sealed.SealedTable(), ledger.Ledger())
    out = ceiling.OUT_DIR / f"arm_{args.arm}_breakdown.json"
    out.write_text(json.dumps(breakdown, indent=1), encoding="utf-8")
    (ceiling.OUT_DIR / f"arm_{args.arm}_breakdown.md").write_text(render(breakdown), encoding="utf-8")
    print(render(breakdown))
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
