"""Position-bias diagnostic: does Skeptic A name B01 because B01 is listed first?

Run with `python -m eval.position_bias --batch rq1-full`, after
`python -m canary.cli reaudit --batch rq1-full --role skeptic_a_shuffled --position-sample`.

The same model, at temperature 0, re-reviews 40 runs (one canary per class and tier, 10 controls, 10 shams) with the
bug-class list shuffled per run, in the prompt and in the schema alike. Among its flags we count how often it names the
class listed first, and how often it names B01, against the chance share 1/10.

The reading was fixed before the run (plan for the reviewer study, PROGRESS.md) and is applied here by code:
- first-listed share above chance and B01 share near chance: position bias;
- B01 share stays above chance: not position, the model prefers B01 itself;
- neither: the order changes the choice in no consistent way.
"Above chance" means the 90% interval lies wholly above 1/10; "near chance" means it contains 1/10.
This tests only which class gets named. If the flag rate stays near 100%, flagging everything is not caused by order.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from canary import config, ledger, sealed, trust

RESULTS_DIR = Path(__file__).parent / "results"
ROLE = "skeptic_a_shuffled"
FLAG = "flag"


def _post(values: list[bool]) -> dict:
    p = trust._tally(values)
    return {"successes": p.successes, "n": p.n, "mean": p.mean, "raw": p.successes / p.n if p.n else None,
            "interval_90": list(p.interval())}


def first_audits(led: ledger.Ledger, role: str, run_ids: set[str]) -> dict[str, dict]:
    """The first stored opinion per run for one role. As in RQ1, a later opinion never replaces it."""
    found: dict[str, dict] = {}
    for entry in led.entries(ledger.AUDITED):
        if entry.payload.get("role") == role and entry.payload["run_id"] in run_ids:
            found.setdefault(entry.payload["run_id"], entry.payload)
    return found


def reading(first: dict, b01: dict, chance: float) -> str:
    if first["n"] == 0:
        return "no flags: nothing to read"
    first_above = first["interval_90"][0] > chance
    b01_near = b01["interval_90"][0] <= chance <= b01["interval_90"][1]
    if first_above and b01_near:
        return "position bias"
    if b01["interval_90"][0] > chance:
        return "prefers B01 itself, not its position"
    return "no consistent order effect"


def build_results(table: sealed.SealedTable, led: ledger.Ledger, batch: str, bug_ids: list[str], role: str = ROLE) -> dict:
    truths = {t.run_id: t for t in table.all() if t.details.get("batch") == batch}
    shuffled = {r: a for r, a in first_audits(led, role, set(truths)).items() if a.get("class_order")}
    baseline = first_audits(led, trust.DEFAULT_ROLE, set(shuffled))
    listed_first_by_default = sorted(bug_ids)[0]
    chance = 1 / len(bug_ids)
    records = []
    for run_id, audit in shuffled.items():
        truth, order, named = truths[run_id], audit["class_order"], audit["audit"]["bug_class"]
        base = baseline.get(run_id, {}).get("audit")
        records.append({"run_id": run_id, "run_type": truth.run_type, "bug_id": truth.bug_id, "tier": truth.tier,
                        "flagged": audit["audit"]["verdict"] == FLAG, "named_class": named,
                        "named_position": order.index(named) if named in order else None, "class_order": order,
                        "baseline_flagged": None if base is None else base["verdict"] == FLAG,
                        "baseline_named": None if base is None else base["bug_class"], "seconds": audit.get("seconds")})
    flags = [r for r in records if r["flagged"]]
    first = _post([r["named_position"] == 0 for r in flags])
    b01 = _post([r["named_class"] == listed_first_by_default for r in flags])
    with_base = [r for r in records if r["baseline_flagged"] is not None]
    failed = sum(1 for e in led.entries(ledger.AUDIT_FAILED) if e.payload.get("role") == role and e.payload["run_id"] in truths)
    strata: dict[str, int] = {}
    for r in records:
        key = r["run_type"] if r["bug_id"] is None else f"{r['bug_id']} {r['tier']}"
        strata[key] = strata.get(key, 0) + 1
    flag_rate = _post([r["flagged"] for r in records])
    return {
        "batch": batch, "role": role, "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewed": len(records), "failed_audits": failed, "strata": dict(sorted(strata.items())),
        "chance_share": chance, "listed_first_by_default": listed_first_by_default,
        "flag_rate": flag_rate,
        "first_listed_share": first, "b01_share": b01,
        "share_by_position": {str(i): _post([r["named_position"] == i for r in flags]) for i in range(len(bug_ids))},
        "named_mix": {b: sum(r["named_class"] == b for r in flags) for b in sorted(bug_ids)},
        "baseline_same_runs": {
            "n": len(with_base), "flag_rate": _post([r["baseline_flagged"] for r in with_base]),
            "b01_share": _post([r["baseline_named"] == listed_first_by_default for r in with_base if r["baseline_flagged"]]),
            "same_verdict": sum(r["flagged"] == r["baseline_flagged"] for r in with_base),
        },
        "reading": reading(first, b01, chance),
        # True: it still flags nearly everything with the list shuffled, so the order does not explain the flagging.
        "still_flags_nearly_everything": None if not records else flag_rate["interval_90"][0] >= 0.9,
        "records": records,
    }


def _fmt(p: dict) -> str:
    return f"{p['successes']}/{p['n']} = {p['raw']:.2f}, 90% [{p['interval_90'][0]:.2f}, {p['interval_90'][1]:.2f}]" if p["n"] else "n/a"


def print_summary(r: dict) -> None:
    print(f"Position bias, batch {r['batch']}, {r['role']}: {r['reviewed']} reviewed, {r['failed_audits']} failed audits")
    print(f"Strata: {r['strata']}")
    print(f"Flag rate: {_fmt(r['flag_rate'])}")
    print(f"Flags naming the first-listed class: {_fmt(r['first_listed_share'])} (chance {r['chance_share']:.2f})")
    print(f"Flags naming {r['listed_first_by_default']}: {_fmt(r['b01_share'])} (chance {r['chance_share']:.2f})")
    print("Named class mix: " + ", ".join(f"{b} {n}" for b, n in r["named_mix"].items() if n))
    b = r["baseline_same_runs"]
    print(f"Same runs, unshuffled baseline: flag rate {_fmt(b['flag_rate'])}, {r['listed_first_by_default']} share "
          f"{_fmt(b['b01_share'])}, same verdict on {b['same_verdict']}/{b['n']}")
    print(f"Reading (rule fixed before the run): {r['reading']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", required=True)
    args = parser.parse_args(argv)
    bug_ids = sorted(config.load_yaml("bug_classes.yaml"))
    results = build_results(sealed.SealedTable(), ledger.Ledger(), args.batch, bug_ids)
    if results["reviewed"] == 0:
        print(f"No shuffled audits for batch {args.batch} yet.")
        return 1
    print_summary(results)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "position_bias_skeptic_a.json"
    path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
