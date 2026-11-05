"""Compare two reviewers' RQ1 results on the same batch, side by side and run by run.

Run with `python -m eval.compare_reviewers` after both `eval/results/rq1_<role>.json` files exist. Every number is read
from those files; nothing here calls a model. The paired part uses the runs both reviewers gave an opinion on, because
the two reviewed the very same scripts and an unpaired comparison would throw that away.
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def _interval(p: dict) -> dict:
    return {"raw": p["raw"], "mean": p["mean"], "interval_90": p["interval_90"], "successes": p["successes"], "n": p["n"]}


def summary(r: dict) -> dict:
    """The comparison row for one reviewer, copied or derived from its RQ1 file."""
    o, chance = r["overall"], r["overall"]["chance"]
    live = [rec["seconds"] for rec in r["records"] if rec.get("seconds") is not None and not rec.get("cached")]
    failed = sum(sum(row["failure_kinds"].values()) for row in r["failures"]["by_type"].values())
    return {
        "role": r["role"], "models": r["models"], "reviewed": r["reviewed"],
        "any_flag_recall": _interval(o["any_flag_pooled"]), "right_type_recall": _interval(o["right_type_pooled"]),
        "chance": {"any_flag": chance["any_flag"], "any_flag_interval": chance["any_flag_interval"],
                   "right_type_uniform": chance["right_type_uniform"], "right_type_matched": chance["right_type_matched"],
                   "right_type_matched_interval": chance["right_type_matched_interval"]},
        "specificity": {k: _interval(v) for k, v in r["specificity"].items()},
        "youden_j": r["discrimination"],
        "flag_rate": r["flag_rate"], "named_share": r["named_share"], "failed_audits": failed,
        "seconds_per_audit": {"mean": statistics.mean(live) if live else None,
                              "median": statistics.median(live) if live else None, "n": len(live)},
    }


def paired(a: dict, b: dict) -> dict:
    """Agreement on the runs both reviewed, with Cohen's kappa for the flag/pass verdict."""
    ra, rb = {x["run_id"]: x for x in a["records"]}, {x["run_id"]: x for x in b["records"]}
    common = sorted(set(ra) & set(rb))
    n = len(common)
    both_flag = sum(ra[i]["flagged"] and rb[i]["flagged"] for i in common)
    both_pass = sum(not ra[i]["flagged"] and not rb[i]["flagged"] for i in common)
    agree = both_flag + both_pass
    kappa = None
    if n:
        pa, pb = sum(ra[i]["flagged"] for i in common) / n, sum(rb[i]["flagged"] for i in common) / n
        expected = pa * pb + (1 - pa) * (1 - pb)
        kappa = None if expected == 1 else (agree / n - expected) / (1 - expected)  # undefined if both never vary
    same_class = sum(ra[i]["named_class"] == rb[i]["named_class"] for i in common if ra[i]["flagged"] and rb[i]["flagged"])
    by_type = {}
    for i in common:
        row = by_type.setdefault(ra[i]["run_type"], {"n": 0, "a_flags": 0, "b_flags": 0, "agree": 0})
        row["n"] += 1
        row["a_flags"] += ra[i]["flagged"]
        row["b_flags"] += rb[i]["flagged"]
        row["agree"] += ra[i]["flagged"] == rb[i]["flagged"]
    return {"n": n, "both_flag": both_flag, "both_pass": both_pass, "only_a_flags": sum(ra[i]["flagged"] and not rb[i]["flagged"] for i in common),
            "only_b_flags": sum(rb[i]["flagged"] and not ra[i]["flagged"] for i in common), "verdict_agreement": agree / n if n else None,
            "cohen_kappa": kappa, "same_named_class_when_both_flag": same_class, "by_type": by_type}


def build(a: dict, b: dict) -> dict:
    if a["batch"] != b["batch"]:
        raise ValueError(f"different batches: {a['batch']} and {b['batch']}")
    return {"batch": a["batch"], "generated_at": datetime.now(timezone.utc).isoformat(),
            "reviewers": {a["role"]: summary(a), b["role"]: summary(b)}, "paired": paired(a, b),
            "sources": {a["role"]: a["generated_at"], b["role"]: b["generated_at"]}}


def _p(p: dict) -> str:
    return f"{p['raw']:.3f} [{p['interval_90'][0]:.3f}, {p['interval_90'][1]:.3f}]" if p["n"] else "n/a"


def print_table(c: dict) -> None:
    rows = c["reviewers"]
    roles = list(rows)
    print(f"{'':<34}" + "".join(f"{r:>34}" for r in roles))
    lines = [
        ("model", lambda s: ", ".join(s["models"])),
        ("reviewed", lambda s: str(s["reviewed"])),
        ("flag rate", lambda s: f"{s['flag_rate']:.3f}"),
        ("any-flag recall (90%)", lambda s: _p(s["any_flag_recall"])),
        ("  chance any-flag", lambda s: f"{s['chance']['any_flag']:.3f}"),
        ("right-type recall (90%)", lambda s: _p(s["right_type_recall"])),
        ("  chance right-type (own mix)", lambda s: f"{s['chance']['right_type_matched']:.3f}"),
        ("specificity controls", lambda s: _p(s["specificity"]["controls"])),
        ("specificity shams", lambda s: _p(s["specificity"]["shams"])),
        ("Youden's J (90%)", lambda s: f"{s['youden_j']['youden_j']:+.3f} [{s['youden_j']['interval'][0]:+.3f}, {s['youden_j']['interval'][1]:+.3f}]"),
        ("failed audits", lambda s: str(s["failed_audits"])),
        ("seconds per audit (median)", lambda s: f"{s['seconds_per_audit']['median']:.1f}" if s["seconds_per_audit"]["median"] else "n/a"),
    ]
    for label, get in lines:
        print(f"{label:<34}" + "".join(f"{get(rows[r]):>34}" for r in roles))
    p = c["paired"]
    print(f"\nPaired on {p['n']} runs: both flag {p['both_flag']}, both pass {p['both_pass']}, only {roles[0]} flags "
          f"{p['only_a_flags']}, only {roles[1]} flags {p['only_b_flags']}; kappa {p['cohen_kappa']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--a", default="skeptic_a")
    parser.add_argument("--b", default="skeptic_b")
    args = parser.parse_args(argv)
    paths = [RESULTS_DIR / f"rq1_{role}.json" for role in (args.a, args.b)]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print(f"Missing: {', '.join(missing)}. Run `python -m eval.rq1 --batch <batch> --role <role>` first.")
        return 1
    a, b = (json.loads(p.read_text(encoding="utf-8")) for p in paths)
    comparison = build(a, b)
    print_table(comparison)
    out = RESULTS_DIR / "rq1_comparison.json"
    out.write_text(json.dumps(comparison, indent=1), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
