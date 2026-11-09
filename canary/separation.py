"""How well a number separates buggy runs from clean ones: AUC with run-level and base-level intervals.

Used two ways. eval/compare_tasks.py and eval/confirm.py measure reviewers with it. The length gate measures the
runs themselves: before any reviewer sees a length-matched batch, blinded line count and character count must not
separate canaries from clean runs, or a reviewer could look good by reacting to script size.

Why base-level intervals: runs cloned from the same base share a dataset, a model and most of their script, so they
are not independent. Resampling whole bases gives the honest, wider interval.
"""
from __future__ import annotations

import numpy as np

from canary import trust

BOOTSTRAP_DRAWS = 2000
LENGTH_FEATURES = ("line_count", "char_count")


def auc(scores_bug: list[float], scores_clean: list[float]) -> float | None:
    """P(a buggy run scores above a clean one), ties counting half (the Mann-Whitney form). 0.5 is chance."""
    if len(scores_bug) == 0 or len(scores_clean) == 0:
        return None
    b, c = np.asarray(scores_bug)[:, None], np.asarray(scores_clean)[None, :]
    return float(np.mean((b > c) + 0.5 * (b == c)))


def auc_stat(b, c) -> float | None:
    return auc(list(b), list(c))


def bootstrap(bug: list, clean: list, statistic, seed: int = 0, draws: int | None = None) -> list[float] | None:
    """90% percentile interval, resampling buggy and clean runs separately so each draw keeps the batch's mix."""
    if len(bug) == 0 or len(clean) == 0:
        return None
    rng, draws = np.random.default_rng(seed), draws or BOOTSTRAP_DRAWS  # read at call time, so tests can lower it
    bug_arr, clean_arr = np.asarray(bug), np.asarray(clean)
    values = [statistic(bug_arr[rng.integers(0, len(bug_arr), len(bug_arr))],
                        clean_arr[rng.integers(0, len(clean_arr), len(clean_arr))]) for _ in range(draws)]
    values = [v for v in values if v is not None]
    return [float(v) for v in np.percentile(values, trust.INTERVAL_PERCENTILES)] if values else None


def base_bootstrap(items: list[tuple], statistic, seed: int = 0, draws: int | None = None) -> list[float] | None:
    """90% interval resampling whole bases: `items` holds (base, is_buggy, value, ...) per run.

    `statistic(bug_values, clean_values)` gets the values of one draw. A draw with no buggy or no clean run is skipped.
    With one base the interval is a single value, which is the honest answer: one base says nothing about others.
    Extra fields after the value are passed along as tuples, for paired statistics (see `paired_auc_gap`).
    """
    by_base: dict[str, list[tuple]] = {}
    for base, buggy, *value in items:
        by_base.setdefault(base, []).append((buggy, value[0] if len(value) == 1 else tuple(value)))
    bases = sorted(by_base)
    if not bases:
        return None
    rng, draws = np.random.default_rng(seed), draws or BOOTSTRAP_DRAWS  # read at call time, so tests can lower it
    values = []
    for _ in range(draws):
        picked = [row for i in rng.integers(0, len(bases), len(bases)) for row in by_base[bases[i]]]
        v = statistic([x for b, x in picked if b], [x for b, x in picked if not b])
        if v is not None:
            values.append(v)
    return [float(v) for v in np.percentile(values, trust.INTERVAL_PERCENTILES)] if values else None


def auc_summary(values: dict[str, float | None], buggy: set[str], base_of: dict[str, str]) -> dict:
    """AUC with run-level and base-level 90% intervals for the runs in `values` that have a value.

    Runs are sorted by ID first: the resampling draws depend on order, and callers often build `values` from a set,
    whose order changes between Python processes. Without the sort an interval could move by 0.01 between two runs.
    """
    scored = {r: values[r] for r in sorted(values, key=str) if values[r] is not None}
    bug = [v for r, v in scored.items() if r in buggy]
    clean = [v for r, v in scored.items() if r not in buggy]
    return {"value": auc(bug, clean), "interval_90": bootstrap(bug, clean, auc_stat),
            "interval_90_base": base_bootstrap([(base_of[r], r in buggy, v) for r, v in scored.items()], auc_stat),
            "scored_buggy": len(bug), "scored_clean": len(clean), "bases": len({base_of[r] for r in scored})}


def paired_auc_gap(pairs: dict[str, tuple[float, float]], buggy: set[str], base_of: dict[str, str]) -> dict:
    """AUC of the first value minus AUC of the second, on the same runs, with a base-level 90% interval."""
    def gap(bug, clean):
        a = auc([x for x, _ in bug], [x for x, _ in clean])
        b = auc([y for _, y in bug], [y for _, y in clean])
        return None if a is None or b is None else a - b
    pairs = {r: pairs[r] for r in sorted(pairs, key=str)}  # order-independent draws, as in auc_summary
    bug = [p for r, p in pairs.items() if r in buggy]
    clean = [p for r, p in pairs.items() if r not in buggy]
    return {"value": gap(bug, clean), "interval_90_base": base_bootstrap(
        [(base_of[r], r in buggy, x, y) for r, (x, y) in pairs.items()], gap), "runs": len(pairs)}


def direction_free(value: float | None) -> float | None:
    """max(AUC, 1 - AUC): a feature that is lower on buggy runs separates them just as well as one that is higher."""
    return None if value is None else max(value, 1 - value)


def strongest_feature_gap(rows: dict[str, tuple[float, dict[str, float]]], features: tuple[str, ...],
                          buggy: set[str], base_of: dict[str, str]) -> dict:
    """AUC of a score minus the direction-free AUC of the strongest trivial feature, on the same runs.

    `rows` maps run ID to (score, {feature: value}). A run missing any feature is left out, so every AUC uses the same
    runs. The score keeps its direction (higher must mean buggy); each feature counts as max(AUC, 1 - AUC). The
    strongest feature is picked again inside every bootstrap draw, so the interval carries the luck of picking a
    maximum instead of treating the observed winner as fixed. Base-level 90% interval, as everywhere else.
    """
    complete = {r: (s, tuple(f[name] for name in features)) for r, (s, f) in sorted(rows.items(), key=lambda kv: str(kv[0]))
                if s is not None and all(f.get(name) is not None for name in features)}

    def per_feature(bug, clean) -> list[float | None]:
        return [auc([x[1][i] for x in bug], [x[1][i] for x in clean]) for i in range(len(features))]

    def gap(bug, clean):
        score_auc = auc([x[0] for x in bug], [x[0] for x in clean])
        if score_auc is None:
            return None
        return score_auc - max(direction_free(v) for v in per_feature(bug, clean))

    bug = [v for r, v in complete.items() if r in buggy]
    clean = [v for r, v in complete.items() if r not in buggy]
    aucs = dict(zip(features, per_feature(bug, clean))) if bug and clean else {}
    strongest = max(aucs, key=lambda n: direction_free(aucs[n])) if aucs else None
    # base_bootstrap passes extra fields as a tuple, so each run's value arrives as (score, feature values).
    items = [(base_of[r], r in buggy, s, fv) for r, (s, fv) in complete.items()]
    return {"value": gap(bug, clean), "interval_90_base": base_bootstrap(items, gap),
            "score_auc": auc([x[0] for x in bug], [x[0] for x in clean]),
            "feature_auc": aucs, "feature_auc_direction_free": {n: direction_free(v) for n, v in aucs.items()},
            "strongest_feature": strongest, "runs": len(complete), "left_out": len(rows) - len(complete)}


def length_check(rows: list[dict]) -> dict:
    """The length gate. `rows` holds one dict per run: base, buggy, line_count, char_count.

    Passes when, for both features, the base-level 90% interval of the AUC contains 0.5: length then gives no
    detectable clue to the run type. Fails closed when there is nothing to measure.
    """
    buggy = {i for i, r in enumerate(rows) if r["buggy"]}
    base_of = {i: r["base"] for i, r in enumerate(rows)}
    features = {}
    for name in LENGTH_FEATURES:
        summary = auc_summary({i: float(r[name]) for i, r in enumerate(rows)}, buggy, base_of)
        interval = summary["interval_90_base"]
        summary["contains_half"] = bool(interval and interval[0] <= 0.5 <= interval[1])
        features[name] = summary
    # Reported, never gating: the helper's own size differs by type by design (see canary/padding.py).
    helper = {i: r.get("helper_statements") for i, r in enumerate(rows)}
    diagnostic = auc_summary(helper, buggy, base_of) if any(v is not None for v in helper.values()) else None
    return {"rule": "for line_count and char_count, the base-level 90% AUC interval contains 0.5",
            "runs": len(rows), "buggy": len(buggy), "features": features,
            "helper_statements_auc": diagnostic,
            "passes": bool(rows) and all(f["contains_half"] for f in features.values())}
