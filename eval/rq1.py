"""RQ1: how reliable is a small local LLM reviewer at catching realistic ML-experiment bugs?

Run with `python -m eval.rq1 --batch rq1-full`. Every number comes from the ledger and the sealed table, and the JSON
keeps the raw per-run records so that any table here can be regenerated without a model.

Why any-flag recall, right-type recall and a chance baseline sit together: a reviewer that flags everything has any-flag
recall 1, and one that always names B01 is always "right" about B01. Neither figure means anything until it is compared
with what flagging at random would score.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from canary import config, ledger, sealed, trust

RESULTS_DIR = Path(__file__).parent / "results"
FIGURES_DIR = Path(__file__).parent / "figures"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
ANY_COLOR, RIGHT_COLOR = "#2a78d6", "#eb6834"  # the first two slots of the validated dataviz palette


def _posterior(p: trust.Posterior) -> dict:
    return {"successes": p.successes, "n": p.n, "alpha": p.alpha, "beta": p.beta, "mean": p.mean,
            "raw": p.successes / p.n if p.n else None, "interval_90": list(p.interval())}


def model_digests(models: set[str]) -> dict[str, str | None]:
    """Record which weights were reviewed, since a tag can be re-pulled with new ones. Absent if Ollama is off."""
    try:
        import ollama

        listed = {m.model: m.digest for m in ollama.Client(timeout=10).list().models}
    except Exception:  # the client raises several types when the server is down; the result stays valid without this
        listed = {}
    return {model: listed.get(model) for model in sorted(models)}


def build_results(table: sealed.SealedTable, led: ledger.Ledger, batch: str, role: str, bug_ids: list[str], draws: int) -> dict:
    """Every RQ1 number for one batch. Pure apart from reading the two stores."""
    observations, excluded = trust.collect_observations(table, led, role, batch)
    summary = trust.summarize(observations, bug_ids, draws)
    failures = trust.collect_failures(table, led, role, batch)
    chance = trust.chance_baseline(observations, bug_ids, draws)
    unreviewed = sum(failures["unreviewed_canaries"].values())
    bounds = trust.recall_bounds(observations, unreviewed)
    truths = {t.run_id: t for t in table.all() if t.details.get("batch") == batch}
    audits = {}
    for entry in led.entries(ledger.AUDITED):
        if entry.payload.get("role") == role and entry.payload["run_id"] in truths:
            audits.setdefault(entry.payload["run_id"], entry.payload)
    bases: dict[str, set[str]] = {}
    for truth in truths.values():
        if truth.bug_id:
            bases.setdefault(truth.bug_id, set()).add(truth.source)
    models = {a["model"] for a in audits.values()}
    records = [{
        "run_id": o.run_id, "run_type": o.run_type, "bug_id": o.bug_id, "tier": o.tier, "impact": o.impact,
        "flagged": o.flagged, "named_class": o.named_class, "confidence": audits[o.run_id]["audit"]["confidence"],
        "base": truths[o.run_id].source, "attempts": audits[o.run_id].get("attempts"), "cached": audits[o.run_id].get("cached"),
        "seconds": audits[o.run_id].get("seconds"),
    } for o in observations]
    return {
        "batch": batch, "role": role, "models": model_digests(models), "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewed": len(observations), "excluded": excluded,
        "classes_tested": len(bug_ids) - len(summary.untested), "classes_total": len(bug_ids), "untested": summary.untested,
        "per_class": {b: {"any_flag": _posterior(summary.per_class[b]), "right_type": _posterior(summary.per_class_named_right[b]),
                          "chance": chance["per_class"][b], "distinct_bases": len(bases.get(b, set()))} for b in sorted(bug_ids)},
        "overall": {
            "any_flag_mean_over_classes": summary.overall_recall_mean,
            "any_flag_interval_90": list(summary.overall_recall_interval),
            "any_flag_pooled": _posterior(trust._tally([o.flagged for o in observations if o.run_type == sealed.CANARY_MEASURE])),
            "right_type_pooled": _posterior(summary.named_right), "chance": chance["overall"],
            "worst_class": summary.worst_class,
        },
        "flag_rate": chance["flag_rate"], "flagged": chance["flagged"], "named_share": chance["named_share"],
        "by_tier": {k: _posterior(v) for k, v in summary.by_tier.items()},
        "by_impact": {k: _posterior(v) for k, v in summary.by_impact.items()},
        "specificity": {"controls": _posterior(summary.control_specificity), "shams": _posterior(summary.sham_specificity),
                        "combined": _posterior(summary.specificity)},
        "discrimination": trust.discrimination(summary, draws),
        "failures": failures, "any_flag_bounds_if_unreviewed": list(bounds) if bounds else None,
        "records": records,
    }


def _pct(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:5.2f}"


def print_tables(r: dict) -> None:
    print(f"RQ1, batch {r['batch']}, {r['role']} ({', '.join(r['models'])}): {r['reviewed']} reviewed, "
          f"{r['classes_tested']} of {r['classes_total']} classes tested")
    print(f"Overall flag rate f = {r['flagged']}/{r['reviewed']} = {r['flag_rate']:.3f}\n")
    print(f"{'class':<8}{'n':>3} {'any-flag':>9} {'chance':>7}  {'right-type':>10} {'chance f/10':>12} {'chance matched':>15} {'bases':>6}")
    for bug, row in r["per_class"].items():
        print(f"{bug:<8}{row['any_flag']['n']:>3} {_pct(row['any_flag']['raw']):>9} {row['chance']['any_flag']:>7.2f}  "
              f"{_pct(row['right_type']['raw']):>10} {row['chance']['right_type_uniform']:>12.3f} "
              f"{row['chance']['right_type_matched']:>15.3f} {row['distinct_bases']:>6}")
    o, c = r["overall"], r["overall"]["chance"]
    print(f"{'pooled':<8}{o['any_flag_pooled']['n']:>3} {_pct(o['any_flag_pooled']['raw']):>9} {c['any_flag']:>7.2f}  "
          f"{_pct(o['right_type_pooled']['raw']):>10} {c['right_type_uniform']:>12.3f} {c['right_type_matched']:>15.3f}")
    if c["any_flag_interval"]:
        print(f"Chance noise at this sample size, 90%: any-flag [{c['any_flag_interval'][0]:.2f}, {c['any_flag_interval'][1]:.2f}], "
              f"right-type matched [{c['right_type_matched_interval'][0]:.2f}, {c['right_type_matched_interval'][1]:.2f}]")
    tied = len({row["any_flag"]["mean"] for row in r["per_class"].values() if row["any_flag"]["n"]}) == 1
    worst = "none, all classes tie" if tied else o["worst_class"]
    print(f"Mean recall over classes: {o['any_flag_mean_over_classes']:.3f}, 90% "
          f"[{o['any_flag_interval_90'][0]:.3f}, {o['any_flag_interval_90'][1]:.3f}]. Worst tested class: {worst}")
    print("\nSpecificity (a pass on a clean run):")
    for name, p in r["specificity"].items():
        print(f"  {name:<10} {p['successes']:>3} of {p['n']:<3} mean {p['mean']:.3f}  90% [{p['interval_90'][0]:.3f}, {p['interval_90'][1]:.3f}]")
    d = r["discrimination"]
    if d:
        print(f"\nYouden's J (0 = cannot tell buggy from clean, whatever the flag rate): observed {d['observed_j']:+.3f}, "
              f"posterior {d['youden_j']:+.3f}, 90% [{d['interval'][0]:+.3f}, {d['interval'][1]:+.3f}]; "
              f"P(recall > false-alarm rate) = {d['p_recall_above_false_alarm']:.3f}")
    print("\nRecall by tier and impact:")
    for name, p in {**r["by_tier"], **r["by_impact"]}.items():
        print(f"  {name:<11} {p['successes']:>3} of {p['n']:<3} mean {p['mean']:.3f}  90% [{p['interval_90'][0]:.3f}, {p['interval_90'][1]:.3f}]")
    print("\nFAILED AUDITS AND CRASHES (not misses, and not in any figure above):")
    print(f"  {'type':<16}{'sealed':>7}{'audited':>8}{'recovered':>10}{'unreviewed':>11}{'not reached':>12}{'crashed':>8}{'orphan':>7}  kinds")
    for name, row in sorted(r["failures"]["by_type"].items()):
        print(f"  {name:<16}{row['sealed']:>7}{row['audited']:>8}{row['failed_then_recovered']:>10}{row['never_reviewed_failed']:>11}"
              f"{row['not_reached']:>12}{row['crashed']:>8}{row['not_recorded']:>7}  {row['failure_kinds'] or '-'}")
    if r["any_flag_bounds_if_unreviewed"]:
        low, high = r["any_flag_bounds_if_unreviewed"]
        print(f"Pooled any-flag recall if every unreviewed canary were a miss / a catch: {low:.3f} / {high:.3f}")
    print(f"Audits left out: {r['excluded']}")


def _error_bar(p: dict) -> tuple[float, float]:
    return p["mean"] - p["interval_90"][0], p["interval_90"][1] - p["mean"]


def _style(ax) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, length=0)


def make_figures(r: dict, directory: Path = FIGURES_DIR) -> list[Path]:
    """Recall against chance per class, and specificity by clean run type. Means with 90% intervals."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    directory.mkdir(parents=True, exist_ok=True)
    classes = list(r["per_class"])
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=160)
    for offset, key, color, label in ((-0.15, "any_flag", ANY_COLOR, "Any-flag recall"), (0.15, "right_type", RIGHT_COLOR, "Right-type recall")):
        posts = [r["per_class"][b][key] for b in classes]
        low_high = list(zip(*[_error_bar(p) for p in posts]))
        ax.errorbar([i + offset for i in range(len(classes))], [p["mean"] for p in posts], yerr=low_high, fmt="o", ms=7,
                    color=color, elinewidth=2, capsize=0, markeredgecolor="#fcfcfb", markeredgewidth=1.5, label=label)
    ax.axhline(r["flag_rate"], color=MUTED, linestyle=(0, (4, 3)), linewidth=1.5, label=f"Chance any-flag (flag rate {r['flag_rate']:.2f})")
    matched = [r["per_class"][b]["chance"]["right_type_matched"] for b in classes]
    ax.hlines(matched, [i - 0.35 for i in range(len(classes))], [i + 0.35 for i in range(len(classes))], color=INK, linewidth=2,
              label="Chance right-type (reviewer's own class mix)")
    ax.set_xticks(range(len(classes)), classes)
    ax.set_ylim(-0.02, 1.02)
    ax.set_ylabel("Share of canaries (posterior mean, 90% interval)", color=MUTED)
    ax.set_title(f"Recall per bug class, {', '.join(r['models'])}, batch {r['batch']}", color=INK, loc="left")
    _style(ax)
    ax.legend(frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.08), labelcolor=MUTED)
    fig.text(0.01, 0.005, "Posterior means start from a flat prior, so 10 of 10 plots at 0.92 and 0 of 10 at 0.08.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    recall_path = directory / "rq1_recall.png"
    fig.savefig(recall_path, facecolor="#fcfcfb")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 3), dpi=160)
    names = ["controls", "shams", "combined"]
    posts = [r["specificity"][n] for n in names]
    ax.errorbar([p["mean"] for p in posts], range(3), xerr=list(zip(*[_error_bar(p) for p in posts])), fmt="o", ms=7, color=ANY_COLOR, elinewidth=2,
                markeredgecolor="#fcfcfb", markeredgewidth=1.5)
    ax.axvline(1 - r["flag_rate"], color=MUTED, linestyle=(0, (4, 3)), linewidth=1.5)
    ax.annotate("Chance", (1 - r["flag_rate"], 2.45), color=MUTED, ha="center", fontsize=8, annotation_clip=False)
    ax.set_yticks(range(3), [f"{n} (n={p['n']})" for n, p in zip(names, posts)])
    ax.set_xlim(-0.02, 1.02)
    ax.invert_yaxis()
    ax.set_xlabel("Specificity (posterior mean, 90% interval)", color=MUTED)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, length=0)
    fig.tight_layout()
    specificity_path = directory / "rq1_specificity.png"
    fig.savefig(specificity_path, facecolor="#fcfcfb")
    plt.close(fig)
    return [recall_path, specificity_path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", required=True)
    parser.add_argument("--role", default=trust.DEFAULT_ROLE)
    parser.add_argument("--suffix", default="", help="added to the output names, so a pilot does not replace the real results")
    args = parser.parse_args(argv)
    if not sealed.SEALED_DB_PATH.exists():
        print("No sealed table yet. Run `python -m canary.cli calibrate` first.")
        return 1
    bug_ids = sorted(config.load_yaml("bug_classes.yaml"))
    draws = config.load_yaml("campaign.yaml")["monte_carlo_draws"]
    results = build_results(sealed.SealedTable(), ledger.Ledger(), args.batch, args.role, bug_ids, draws)
    if results["reviewed"] == 0:
        print(f"Batch {args.batch} has no reviewed runs yet.")
        return 1
    print_tables(results)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"rq1_{args.role}{args.suffix}.json"
    path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    figures = make_figures(results, FIGURES_DIR / args.suffix.lstrip("_") if args.suffix else FIGURES_DIR)
    print(f"\nWrote {path} and {', '.join(str(f) for f in figures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
