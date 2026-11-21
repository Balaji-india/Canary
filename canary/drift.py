"""Mission 4.3: control chart and drift alarms (docs/plans/mission_4_3_drift.md).

Why this module exists: Mission 4.1 turns calibration counts into a gate, but those counts describe the reviewer on
the day it was measured. A cloud model can change without notice. This module holds the arithmetic that notices a
change: exact small-sample control limits and the three chart rules of plan section 4.

Limits are exact, not normal approximations. For a slice or window of m runs the limit at tail probability t is the
smallest count c with P(X >= c) <= t, where X ~ BetaBinomial(m, 1 + f0, 1 + n0 - f0) and f0 of n0 is the baseline
count (the sentinel's opening pass, or the epoch's calibration set for the fresh charts). The Beta-binomial is the
predictive distribution of a new count when the baseline rate is only known from f0 of n0 (flat prior), so a small
baseline gives wider limits instead of false alarms. When no count is that rare the limit is m + 1, so the rule
cannot fire. Westgard's sigma levels are kept as tail probabilities: "3 sigma" = 0.00135, "2 sigma" = 0.0228.

  R1 (Westgard 1_3s): one slice or window at or beyond the 3-sigma limit.
  R2 (Westgard 2_2s): two in a row, each at or beyond the 2-sigma limit (fires on the second of the two).
  R3 (stands in for 4_1s and 10_x): the count summed over the last W slices or windows at or beyond the 3-sigma
     limit for W * m runs; it needs W complete slices, so it never fires on the first W - 1.

All limits are one-sided (upper): a chart counts bad events (flips, false alarms, misses), and only "more than
expected" is a drift; "fewer" is good news and raises nothing.

Sitting 1 (plan steps 1-3) is arithmetic on records it is given: this module opens no database, no run folder and
no sealed table, and calls no model. No LLM decides anything here; the rules are code.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy.stats import betabinom

TAILS: dict[str, tuple[float, float]] = {"standard": (0.00135, 0.0228), "strict": (0.0005, 0.01)}
RULES = ("R1", "R2", "R3")


def _tails(tails: str | tuple[float, float]) -> tuple[float, float]:
    if isinstance(tails, str):
        if tails not in TAILS:
            raise ValueError(f"unknown tails {tails!r}; use one of {sorted(TAILS)}")
        return TAILS[tails]
    t3, t2 = tails
    return float(t3), float(t2)


@lru_cache(maxsize=None)
def limit(n0: int, f0: int, m: int, tail: float) -> int:
    """The smallest count c in 0..m with P(X >= c) <= tail, X ~ BetaBinomial(m, 1 + f0, 1 + n0 - f0); m + 1 if none.

    Example (plan step 1): baseline 0 flips in 10, m = 2: P(X = 2) = (1/12)(2/13) = 0.0128 and P(X >= 1) = 2/13 =
    0.154, so the 2-sigma limit (0.0228) is 2 and no 3-sigma limit (0.00135) exists: the function returns 3.
    """
    n0, f0, m = int(n0), int(f0), int(m)
    if n0 < 0 or not 0 <= f0 <= n0:
        raise ValueError(f"baseline must be 0 <= f0 <= n0, got f0={f0}, n0={n0}")
    if m < 1:
        raise ValueError(f"a slice or window needs at least one run, got m={m}")
    if not 0.0 < tail < 1.0:
        raise ValueError(f"tail must be a probability in (0, 1), got {tail}")
    counts = np.arange(m + 1)
    upper = betabinom.sf(counts - 1, m, 1 + f0, 1 + n0 - f0)  # P(X >= c) for c = 0..m
    rare = np.nonzero(upper <= tail)[0]
    return int(rare[0]) if len(rare) else m + 1


def limits(n0: int, f0, m: int, tail: float) -> np.ndarray:
    """`limit` for an array of baseline counts (one per simulated campaign); each distinct f0 is computed once."""
    f0 = np.asarray(f0, dtype=int)
    values, inverse = np.unique(f0, return_inverse=True)
    table = np.array([limit(n0, int(v), m, tail) for v in values], dtype=int)
    return table[inverse].reshape(f0.shape)


def fire_matrix(counts, n0: int, f0, m: int, span: int, tails: str | tuple[float, float] = "standard"
                ) -> dict[str, np.ndarray]:
    """Where each rule fires. `counts` is campaigns x slices (each slice exactly m runs), `f0` one baseline count
    per campaign (or one for all). Returns {"R1": bool array, "R2": ..., "R3": ...} of the same shape.

    This is the only implementation of the rules: `rules` (the chart) and eval/drift_power.py (the simulation) both
    call it, so the simulated operating characteristics cannot drift from what the chart does.
    """
    counts = np.asarray(counts, dtype=int)
    if counts.ndim != 2:
        raise ValueError("counts must be 2-D: campaigns x slices")
    if counts.size and (counts.min() < 0 or counts.max() > m):
        raise ValueError(f"every count must be between 0 and m = {m}")
    if span < 1:
        raise ValueError(f"W must be at least 1, got {span}")
    t3, t2 = _tails(tails)
    f0 = np.broadcast_to(np.asarray(f0, dtype=int), counts.shape[:1])
    r1 = counts >= limits(n0, f0, m, t3)[:, None]
    over2 = counts >= limits(n0, f0, m, t2)[:, None]
    r2 = np.zeros_like(r1)
    r2[:, 1:] = over2[:, 1:] & over2[:, :-1]
    total = np.cumsum(counts, axis=1)
    roll = total.copy()
    roll[:, span:] = total[:, span:] - total[:, :-span]          # sum of the last `span` slices, this one included
    r3 = roll >= limits(n0, f0, m * span, t3)[:, None]
    r3[:, :span - 1] = False                                     # fewer than W complete slices: R3 cannot fire
    return {"R1": r1, "R2": r2, "R3": r3}


def rules(counts, n0: int, f0: int, m: int, span: int, tails: str | tuple[float, float] = "standard"
          ) -> dict[str, list[int]]:
    """One chart: which of R1, R2, R3 fire at which slice index (0-based, in review order).

    `counts` are the counts of complete slices or windows of exactly m runs each, oldest first.
    """
    counts = np.asarray(counts, dtype=int).reshape(1, -1)
    fired = fire_matrix(counts, n0, f0, m, span, tails)
    return {name: [int(i) for i in np.nonzero(fired[name][0])[0]] for name in RULES}


def chart_limits(n0: int, f0: int, m: int, span: int, tails: str | tuple[float, float] = "standard") -> dict:
    """The three limits a chart shows: R1 (per slice), R2 (per slice, twice in a row), R3 (over W slices)."""
    t3, t2 = _tails(tails)
    return {"R1": limit(n0, f0, m, t3), "R2": limit(n0, f0, m, t2), "R3": limit(n0, f0, m * span, t3),
            "m": m, "W": span, "baseline": [f0, n0], "tails": [t3, t2]}


# ---- Step 3: chart state from records --------------------------------------------------------------------------
# Everything below works on records it is given (synthetic in the demo and the tests; in sitting 2 they come from
# the ledger and data/drift/sentinel.jsonl). The chart uses the verdict field only (plan trap 1): it never sees a
# reply's confidence or evidence, so nothing here can be tuned on them.

FLAG, PASS = "flag", "pass"
BUGGY, CLEAN = "buggy", "clean"
FRESH_WINDOW = 20                 # DESIGN.md section 9 and plan 2.3: windows of 20 fresh runs
FRESH_SPAN, FRESH_TAILS = 3, "standard"
SENTINEL_PER_HALF, SENTINEL_SPAN, SENTINEL_TAILS = 10, 3, "standard"   # 20 a day, W = 3 (plan section 4, decision 1)
WINDOW_PER_CLASS, WINDOW_CLEAN = 24, 120                               # layer C (plan 2.4, decision 5)
CLEAN_TYPES = ("control", "sham")
MEASURE_TYPE, PROBE_TYPE = "canary_measure", "canary_probe"            # canary.sealed's names (checked by a test)


@dataclass(frozen=True)
class ChartObservation:
    """One reviewed fresh calibration run as the charts need it. `order` is the review order (larger = later).
    `flagged` is the union's verdict; `unverifiable` marks a tripwire `unverifiable` result, which counts as a flag
    and is listed (plan 2.3). `failed` marks a failed first audit, which is left out."""
    run_id: str
    epoch: str
    order: int
    run_type: str
    bug_id: str | None
    tier: str | None
    flagged: bool
    unverifiable: bool = False
    failed: bool = False

    @property
    def flag(self) -> bool:
        return self.flagged or self.unverifiable


@dataclass(frozen=True)
class SentinelRecord:
    """One sentinel ask: the opening pass (`slice_index` None) or a daily slice. `verdict` is "flag" or "pass"."""
    run_id: str
    epoch: str
    order: int
    slice_index: int | None
    verdict: str
    response_id: str


@dataclass(frozen=True)
class AcceptedRun:
    """A real run the gate accepted, with its review order: what a look-back may hold."""
    run_id: str
    epoch: str
    order: int


def _evidence_start(rule: str, index: int, span: int) -> int:
    """The slice or window after which accepted runs are held (plan section 5, item 2): R1 since the previous
    in-control slice, R2 since the slice before the first of the two, R3 since the slice before its W."""
    return index - {"R1": 1, "R2": 2, "R3": span}[rule]


def _bad(o: ChartObservation, kind: str) -> bool:
    """What a fresh chart counts: a flag on a clean run (false alarm), no flag on a canary (miss)."""
    return o.flag if kind == CLEAN else not o.flag


def chart(observations: list[ChartObservation], baseline: tuple[int, int], kind: str, epoch: str,
          support: list[tuple[str, str]] | None = None, window: int = FRESH_WINDOW, span: int = FRESH_SPAN,
          tails: str | tuple[float, float] = FRESH_TAILS) -> dict:
    """A fresh-run chart for one epoch: `kind` "clean" (controls and shams; the count is the union's flags) or
    "canary" (measuring canaries of `support`; the count is the union's misses). Windows of `window` runs in review
    order, never across an epoch; an unfinished last window is shown as `partial` and enters no rule. Probes and
    failed audits are left out and counted. `baseline` is (f0, n0) from the epoch's calibration set."""
    if kind not in (CLEAN, "canary"):
        raise ValueError(f"kind must be 'clean' or 'canary', got {kind!r}")
    if kind == "canary" and not support:
        raise ValueError("the canary chart needs the supported (class, tier) variants")
    f0, n0 = baseline
    left_out = {"other_epoch": 0, "probe": 0, "failed": 0, "other_type": 0, "outside_support": 0}
    used: list[ChartObservation] = []
    allowed = set(map(tuple, support or ()))
    for o in observations:
        if o.epoch != epoch:
            left_out["other_epoch"] += 1
        elif o.run_type == PROBE_TYPE:
            left_out["probe"] += 1
        elif o.failed:
            left_out["failed"] += 1
        elif kind == CLEAN and o.run_type in CLEAN_TYPES:
            used.append(o)
        elif kind == "canary" and o.run_type == MEASURE_TYPE:
            if (o.bug_id, o.tier) in allowed:
                used.append(o)
            else:
                left_out["outside_support"] += 1
        else:
            left_out["other_type"] += 1
    used.sort(key=lambda o: o.order)
    full = len(used) // window
    windows = []
    for i in range(full):
        part = used[i * window:(i + 1) * window]
        windows.append({"index": i, "runs": [o.run_id for o in part], "count": sum(_bad(o, kind) for o in part),
                        "first_order": part[0].order, "last_order": part[-1].order,
                        "unverifiable": [o.run_id for o in part if o.unverifiable]})
    rest = used[full * window:]
    counts = [w["count"] for w in windows]
    fired = rules(counts, n0, f0, window, span, tails) if counts else {r: [] for r in RULES}
    return {"chart": f"fresh_{kind}", "epoch": epoch, "baseline": [f0, n0],
            "limits": chart_limits(n0, f0, window, span, tails), "windows": windows, "counts": counts,
            "partial": {"runs": len(rest), "count": sum(_bad(o, kind) for o in rest)},
            "fired": fired, "left_out": left_out, "in_control": not any(fired.values()),
            "slice_last_order": [w["last_order"] for w in windows], "span": span}


def sentinel_chart(records: list[SentinelRecord], references: dict[str, tuple[str, str]], epoch: str,
                   per_half: int = SENTINEL_PER_HALF, span: int = SENTINEL_SPAN,
                   tails: str | tuple[float, float] = SENTINEL_TAILS,
                   reference_responses: dict[str, str] | None = None) -> dict:
    """The sentinel chart for one epoch. `references` maps each sentinel run to (half, first stored verdict in this
    epoch), half "buggy" or "clean". The opening pass gives each half's baseline (flips of the half's size); every
    later slice is counted per half as flips against the reference, with the direction logged. Slices finish in
    order; an unfinished last slice is reported (`unfinished_slice`) and enters no rule. A response_id seen twice,
    or equal to the first audit's (`reference_responses`, run -> response_id), is refused: a provider-side cache
    would fake stability (plan trap 3). A run asked twice in one slice is refused too: it would be counted twice."""
    for run_id, (half, verdict) in references.items():
        if half not in (BUGGY, CLEAN) or verdict not in (FLAG, PASS):
            raise ValueError(f"bad reference for {run_id}: {(half, verdict)}")
    mine = [r for r in records if r.epoch == epoch]
    seen: dict[str, str] = {response: f"{run_id} (first audit)"
                            for run_id, response in (reference_responses or {}).items()}
    for r in mine:
        if r.verdict not in (FLAG, PASS):
            raise ValueError(f"{r.run_id}: verdict must be 'flag' or 'pass', got {r.verdict!r}")
        if r.run_id not in references:
            raise ValueError(f"{r.run_id} is not in the sentinel set")
        if r.response_id in seen:
            raise ValueError(f"response {r.response_id} served twice ({seen[r.response_id]} and {r.run_id}): "
                             "not a real call, not counted as stable")
        seen[r.response_id] = r.run_id
    sizes = {h: sum(1 for half, _ in references.values() if half == h) for h in (BUGGY, CLEAN)}
    opening = [r for r in mine if r.slice_index is None]
    out = {"chart": "sentinel", "epoch": epoch, "per_half": per_half, "span": span, "sizes": sizes,
           "baseline": None, "halves": {}, "unfinished_slice": None, "in_control": True, "slice_last_order": []}
    if sorted(r.run_id for r in opening) != sorted(references):
        out["status"] = "no baseline: the opening pass must ask every sentinel run exactly once"
        out["in_control"] = False      # no baseline, no control: nothing may be accepted on it
        return out
    out["status"] = "ok"
    flips0 = {h: sum(r.verdict != references[r.run_id][1] for r in opening if references[r.run_id][0] == h)
              for h in (BUGGY, CLEAN)}
    out["baseline"] = {h: [flips0[h], sizes[h]] for h in (BUGGY, CLEAN)}
    slices: dict[int, list[SentinelRecord]] = {}
    for r in mine:
        if r.slice_index is not None:
            slices.setdefault(r.slice_index, []).append(r)
    indices = sorted(slices)
    if indices != list(range(len(indices))):
        raise ValueError(f"slice indices must run 0, 1, 2, ... without gaps, got {indices}")
    complete = []
    for i in indices:
        asked = [r.run_id for r in slices[i]]
        if len(asked) != len(set(asked)):
            raise ValueError(f"slice {i} asks a run more than once")
        per = {h: [r for r in slices[i] if references[r.run_id][0] == h] for h in (BUGGY, CLEAN)}
        if any(len(per[h]) > per_half for h in (BUGGY, CLEAN)):
            raise ValueError(f"slice {i} has more than {per_half} runs in a half")
        if not all(len(per[h]) == per_half for h in (BUGGY, CLEAN)):
            if i != indices[-1]:
                raise ValueError(f"slice {i} is unfinished but a later slice exists")
            out["unfinished_slice"] = i
            break
        complete.append(per)
    out["slice_last_order"] = [max(r.order for h in (BUGGY, CLEAN) for r in per[h]) for per in complete]
    for h in (BUGGY, CLEAN):
        counts, directions = [], []
        for per in complete:
            flips = [r for r in per[h] if r.verdict != references[r.run_id][1]]
            counts.append(len(flips))
            directions.append({"flag_to_pass": sum(r.verdict == PASS for r in flips),
                               "pass_to_flag": sum(r.verdict == FLAG for r in flips)})
        fired = rules(counts, sizes[h], flips0[h], per_half, span, tails) if counts else {r: [] for r in RULES}
        out["halves"][h] = {"counts": counts, "directions": directions, "fired": fired,
                            "limits": chart_limits(sizes[h], flips0[h], per_half, span, tails)}
        out["in_control"] = out["in_control"] and not any(fired.values())
    return out


def first_alarm(state: dict) -> dict | None:
    """The earliest rule firing on one chart state (lowest slice index, then R1, R2, R3, then buggy before clean),
    as the alarm record of plan section 5 (written to the ledger in sitting 2), or None if nothing fired."""
    if state["chart"] == "sentinel":
        parts = [(h, state["halves"][h]) for h in (BUGGY, CLEAN) if h in state["halves"]]
    else:
        parts = [(None, state)]
    found = []
    for half, part in parts:
        for rank, rule in enumerate(RULES):
            for index in part["fired"][rule]:
                found.append((index, rank, 0 if half in (None, BUGGY) else 1, rule, half, part))
    if not found:
        return None
    index, _, _, rule, half, part = min(found, key=lambda x: x[:3])
    span = state["span"]
    start = _evidence_start(rule, index, span)
    first = start + 1
    return {"kind": "drift_alarm", "chart": state["chart"], "half": half, "rule": rule, "epoch": state["epoch"],
            "slice_index": index, "evidence_slices": [first, index], "counts": part["counts"][max(first, 0):index + 1],
            "limits": part["limits"], "hold_after_slice": start,
            "hold_after_order": state["slice_last_order"][start] if start >= 0 else None}


def hold_list(alarm: dict, accepted: list[AcceptedRun]) -> list[str]:
    """Real runs of the alarm's epoch accepted inside its evidence window: after the end of slice
    `hold_after_slice` (all of the epoch's accepted runs when the evidence reaches back to its start). They get a
    `held` entry in sitting 2; nothing is deleted."""
    after = alarm["hold_after_order"]
    return [a.run_id for a in sorted(accepted, key=lambda a: a.order)
            if a.epoch == alarm["epoch"] and (after is None or a.order > after)]


def calibration_window(observations: list[ChartObservation], support: list[tuple[str, str]], epoch: str,
                       per_class: int = WINDOW_PER_CLASS, clean: int = WINDOW_CLEAN) -> dict:
    """Layer C: what the gate's trust numbers use. The most recent observations of this epoch, newest first: up to
    `per_class` measuring canaries per supported class and `clean` controls and shams. Older ones of the epoch stay
    in the report (`outside`), as do other epochs' (`other_epochs`) and what is left out (probes, failed audits,
    variants outside the support); the window itself never crosses an epoch."""
    allowed = set(map(tuple, support))
    taken = {bug: 0 for bug in sorted({bug for bug, _ in allowed})}
    newest = sorted(observations, key=lambda o: o.order, reverse=True)
    window, outside, other_epochs = [], [], []
    left_out = {"probe": [], "failed": [], "outside_support": [], "other_type": []}
    clean_taken = 0
    for o in newest:
        if o.epoch != epoch:
            other_epochs.append(o.run_id)
        elif o.run_type == PROBE_TYPE:
            left_out["probe"].append(o.run_id)
        elif o.failed:
            left_out["failed"].append(o.run_id)
        elif o.run_type in CLEAN_TYPES:
            if clean_taken < clean:
                window.append(o)
                clean_taken += 1
            else:
                outside.append(o.run_id)
        elif o.run_type == MEASURE_TYPE:
            if (o.bug_id, o.tier) not in allowed:
                left_out["outside_support"].append(o.run_id)
            elif taken[o.bug_id] < per_class:
                window.append(o)
                taken[o.bug_id] += 1
            else:
                outside.append(o.run_id)
        else:
            left_out["other_type"].append(o.run_id)
    return {"epoch": epoch, "window": window, "per_class": taken, "clean": clean_taken,
            "limits": {"per_class": per_class, "clean": clean},
            "short": {bug: per_class - n for bug, n in taken.items() if n < per_class}, "outside": outside,
            "other_epochs": other_epochs, "left_out": left_out}


# ---- The demo (plan step 3, done when) ---------------------------------------------------------------------------

def _flip(verdict: str) -> str:
    return PASS if verdict == FLAG else FLAG


def _demo_sentinel(epoch: str, buggy: list[int], clean: list[int], opening: tuple[int, int] = (1, 0)):
    """Synthetic sentinel records: 30 buggy runs (references: 23 flag, 7 pass) and 30 clean (all pass); the
    opening pass flips `opening` runs per half; slice i asks the next 10 of each half and flips the first
    buggy[i] / clean[i] of them. Two real runs are accepted after every slice."""
    refs = {f"s-b{i:02d}": (BUGGY, PASS if i % 4 == 3 and i < 28 else FLAG) for i in range(30)}
    refs.update({f"s-c{i:02d}": (CLEAN, PASS) for i in range(30)})
    ids = {BUGGY: [f"s-b{i:02d}" for i in range(30)], CLEAN: [f"s-c{i:02d}" for i in range(30)]}
    records: list[SentinelRecord] = []
    accepted: list[AcceptedRun] = []
    order = 0

    def ask(run_id: str, slice_index: int | None, flip: bool) -> None:
        nonlocal order
        order += 1
        verdict = _flip(refs[run_id][1]) if flip else refs[run_id][1]
        records.append(SentinelRecord(run_id, epoch, order, slice_index, verdict, f"resp-{order:04d}"))

    for h, n in zip((BUGGY, CLEAN), opening):
        for j, run_id in enumerate(ids[h]):
            ask(run_id, None, j < n)
    for i, (fb, fc) in enumerate(zip(buggy, clean)):
        for h, n in ((BUGGY, fb), (CLEAN, fc)):
            for j in range(SENTINEL_PER_HALF):
                ask(ids[h][(i * SENTINEL_PER_HALF + j) % 30], i, j < n)
        for a in "ab":
            order += 1
            accepted.append(AcceptedRun(f"real-{i}{a}", epoch, order))
    return records, refs, accepted


def _demo_fresh(epoch: str, counts: list[int], partial: int = 7):
    """Synthetic fresh clean runs: one window of 20 per count (that many flagged; one unverifiable), a probe after
    each window, a failed audit, a partial last window and three runs of an older epoch; two real runs accepted
    after every window."""
    obs: list[ChartObservation] = []
    accepted: list[AcceptedRun] = []
    order = 0
    for k in range(3):
        order += 1
        obs.append(ChartObservation(f"old-{k}", "e0", order, "control", None, None, True))
    for i, c in enumerate(counts):
        for j in range(FRESH_WINDOW):
            order += 1
            unverifiable = i == len(counts) - 1 and j == 0     # inside a window that has flags
            obs.append(ChartObservation(f"f{i}-{j:02d}", epoch, order, "control" if j % 2 else "sham", None, None,
                                        j < c and not unverifiable, unverifiable=unverifiable))
        order += 1
        obs.append(ChartObservation(f"probe-{i}", epoch, order, PROBE_TYPE, "B01", "obvious", False))
        for a in "ab":
            order += 1
            accepted.append(AcceptedRun(f"real-{i}{a}", epoch, order))
    order += 1
    obs.append(ChartObservation("failed-0", epoch, order, "control", None, None, True, failed=True))
    for j in range(partial):
        order += 1
        obs.append(ChartObservation(f"p-{j}", epoch, order, "control", None, None, False))
    return obs, accepted


def fired_list(state: dict) -> list[tuple[str, str | None, int]]:
    """Every (rule, half, index) that fired on one chart state; half is None for a fresh chart."""
    parts = state["halves"].items() if state["chart"] == "sentinel" else [(None, state)]
    return [(rule, half, i) for half, part in parts for rule in RULES for i in part["fired"][rule]]


def demo_scenarios() -> list[tuple[str, str, dict, list[AcceptedRun]]]:
    """(rule expected, title, chart state, accepted runs): each built so that exactly that rule fires, once."""
    out = []
    records, refs, accepted = _demo_sentinel("e1", buggy=[0, 1, 0, 0], clean=[0, 0, 0, 6])
    out.append(("R1", "sentinel, clean half: the LLM starts to flag clean runs (6 of 10 flip on slice 3)",
                sentinel_chart(records, refs, "e1"), accepted))
    records, refs, accepted = _demo_sentinel("e1", buggy=[0, 1, 4, 4], clean=[0, 0, 0, 0])
    out.append(("R2", "sentinel, buggy half: the LLM's recall slips (4 and 4 flips on slices 2 and 3)",
                sentinel_chart(records, refs, "e1"), accepted))
    obs, accepted = _demo_fresh("e1", counts=[0, 0, 4, 2, 4])
    out.append(("R3", "fresh clean chart (union), bank baseline 3 of 160: false alarms creep up (4, 2, 4 of 20 on windows 2 to 4)",
                chart(obs, (3, 160), CLEAN, "e1"), accepted))
    return out


def demo() -> list[str]:
    """Each rule firing once on synthetic records, with the alarm record and the hold list (plan step 3)."""
    lines = ["Canary drift demo (synthetic records; no ledger, no model, no sealed table)", ""]
    for expected, title, state, accepted in demo_scenarios():
        fired = fired_list(state)
        if [f[0] for f in fired] != [expected]:
            raise AssertionError(f"demo {expected}: expected exactly one {expected}, got {fired}")
        if state["chart"] == "sentinel":
            shown = "; ".join(f"{h} half: baseline {state['baseline'][h][0]} of {state['baseline'][h][1]}, flips "
                              f"per slice {state['halves'][h]['counts']}" for h in (BUGGY, CLEAN))
            limits = state["halves"][fired[0][1]]["limits"]
        else:
            shown = (f"windows of 20: counts {state['counts']} (one flag is a tripwire 'unverifiable'), partial "
                     f"{state['partial']}, left out {state['left_out']}")
            limits = state["limits"]
        alarm = first_alarm(state)
        held = hold_list(alarm, accepted)
        lines += [f"[{expected}] {title}",
                  f"  {shown}",
                  f"  limits: R1 {limits['R1']} of {limits['m']}, R2 {limits['R2']} twice in a row, R3 {limits['R3']}"
                  f" over {limits['W']} x {limits['m']} (baseline {limits['baseline'][0]} of {limits['baseline'][1]})",
                  f"  fired: {expected} at index {fired[0][2]}, once; no other rule fired",
                  "  alarm record: " + ", ".join(f"{k}={alarm[k]}" for k in
                                                 ("kind", "chart", "half", "rule", "epoch", "slice_index",
                                                  "evidence_slices", "counts", "hold_after_slice",
                                                  "hold_after_order")),
                  f"  hold list (accepted after slice {alarm['hold_after_slice']} ended): {held}",
                  f"  accepted earlier, not held: {[a.run_id for a in accepted if a.run_id not in held]}", ""]
    records, refs, _ = _demo_sentinel("e1", buggy=[0, 1], clean=[0, 0])
    state = sentinel_chart(records[:-3], refs, "e1")
    lines.append(f"[slice] unfinished: unfinished_slice={state['unfinished_slice']}, complete slices "
                 f"{len(state['halves'][BUGGY]['counts'])}; the unfinished one enters no rule")
    last = records[-1]
    twice = records[:-1] + [SentinelRecord(last.run_id, "e1", last.order, last.slice_index, last.verdict,
                                           records[-2].response_id)]
    try:
        sentinel_chart(twice, refs, "e1")
        lines.append("[trap 3] a repeated response_id was NOT refused")
    except ValueError as err:
        lines.append(f"[trap 3] refused: {err}")
    support = [("B01", "obvious"), ("B01", "subtle"), ("B02", "subtle")]
    obs = [ChartObservation(f"k{i:03d}", "e1", i, MEASURE_TYPE, "B01" if i % 4 else "B02",
                            "subtle" if i % 2 or i % 4 == 0 else "obvious", True) for i in range(80)]
    obs.append(ChartObservation("k-b02-obvious", "e1", 90, MEASURE_TYPE, "B02", "obvious", True))
    obs += [ChartObservation(f"c{i:03d}", "e1", 100 + i, "control", None, None, False) for i in range(130)]
    obs += [ChartObservation("old", "e0", 0, "sham", None, None, False),
            ChartObservation("probe", "e1", 300, PROBE_TYPE, "B01", "obvious", True)]
    window = calibration_window(obs, support, "e1")
    left = {k: len(v) for k, v in window["left_out"].items()}
    lines.append(f"[layer C] rolling window, newest first: per class {window['per_class']} (at most 24), clean "
                 f"{window['clean']} (at most 120), short {window['short']}; still reported: older "
                 f"{len(window['outside'])}, other epochs {len(window['other_epochs'])}, left out {left}")
    return lines


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m canary.drift", description=__doc__.split("\n")[0])
    parser.add_argument("--demo", action="store_true", help="each rule firing once on synthetic records")
    args = parser.parse_args(argv)
    if not args.demo:
        parser.print_help()
        return 2
    print("\n".join(demo()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
