"""Tripwires: deterministic checks of a run's chain of custody (Mission 5.1; design in
docs/plans/mission_5_1_tripwires.md).

Built so far (plan section 10, step 2): the pair arithmetic every check will use. The checks themselves come in
steps 3 and 5.

Rows are followed by content. A *pair* is (row fingerprint, label); `canary.probe.row_fingerprints` makes the
fingerprints. Pairs are always counted as multisets (`Counter`), never as sets, because identical rows are normal
(`blood-transfusion` has 246 duplicate feature rows, `pc1` 161) and identical rows can carry different labels.

Per seed (one `train_test_split` call), the split gives a training and a test multiset of pairs, a *stage* each.
A row-preserving call (`transform`, `fit_transform`: same number of rows, row j of the output is row j of the input)
maps every input fingerprint to one output fingerprint, so a stage whose rows all enter that call is pushed forward
through it: each pair keeps its label and takes its row's new fingerprint. That gives the training and test pairs "at
every stage". Pushing forward is unambiguous even when two different raw rows become identical (after imputation, say):
both map to the same new fingerprint and are counted twice.

`relate(context, pairs)` then says how any multiset of pairs seen at a call relates to the split: `test`,
`test_subset`, `train`, `train_subset`, `needs_test_rows` (with how many pairs only test rows explain) or `unknown`.

What a tripwire may never see: the sealed table, the twins, the ledger, the bug catalog, the saboteur or any reviewer
output. This module imports none of them (guard tests, plan step 4).
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

TEST = "test"
TEST_SUBSET = "test_subset"
TRAIN = "train"
TRAIN_SUBSET = "train_subset"
NEEDS_TEST_ROWS = "needs_test_rows"
UNKNOWN = "unknown"

SIDE_TRAIN, SIDE_TEST = "train", "test"
FIT_METHODS = ("fit", "fit_transform", "fit_predict")
ROW_PRESERVING = ("transform", "fit_transform")
SPLIT_SPACE = ("split",)
_NAN_LABEL = "<nan>"  # NaN != NaN, so a NaN label would never match itself in a Counter


def _label(value):
    """Make a label usable as a Counter key."""
    if isinstance(value, float) and math.isnan(value):
        return _NAN_LABEL
    if isinstance(value, list):
        return tuple(_label(v) for v in value)
    return value


def pairs_of(x: dict | None, y: dict | None = None) -> list[tuple] | None:
    """The (fingerprint, label) pairs of a described data argument and its labels, in order.

    Without labels every label is None. Returns None when the rows or the labels were not recorded, or their counts
    differ: the pairs are then unknown, not empty.
    """
    if not x or "fp" not in x:
        return None
    fps = x["fp"]
    if y is None:
        return [(fp, None) for fp in fps]
    labels = y.get("values")
    if labels is None or len(labels) != len(fps):
        return None
    return [(fp, _label(label)) for fp, label in zip(fps, labels)]


@dataclass(eq=False)
class Stage:
    """The training or the test pairs of one seed as they look at one point of the computation.

    `space` says whose coordinates the fingerprints are in: ("split",) for the rows as the split returned them, or
    ("call", object number, fit generation) after a row-preserving call of that fitted object.
    """

    side: str
    space: tuple
    pairs: Counter  # never changed after the stage is made, so the two counts below are computed once
    origin: int  # seq of the event that produced this stage
    fps: Counter = field(init=False, repr=False)  # the same rows, labels left out
    size: int = field(init=False, repr=False)

    def __post_init__(self):
        self.fps = Counter()
        for (fp, _), n in self.pairs.items():
            self.fps[fp] += n
        self.size = sum(self.pairs.values())


@dataclass(frozen=True)
class Relation:
    """How a multiset of pairs relates to a seed's split. `count` is the number of pairs missing from the matched stage
    (the subsets) or the number of pairs only test rows explain (`needs_test_rows`); 0 otherwise. `ambiguous` is set
    when the pairs are part of a test stage *and* part of a training stage (possible with natural duplicates): the
    answer is then `test_subset`, and a check must not name a class from it alone."""

    kind: str
    count: int = 0
    stage: Stage | None = None
    ambiguous: bool = False


@dataclass
class SeedContext:
    """One seed: its split event, the events after it (until the next split) and its stages."""

    index: int
    split: dict
    events: list[dict]
    stages: list[Stage] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # why something could not be followed

    def side(self, side: str) -> list[Stage]:
        return [s for s in self.stages if s.side == side]


@dataclass
class TraceContext:
    """A whole trace, cut into seeds. `preamble` holds the events before the first split."""

    preamble: list[dict]
    seeds: list[SeedContext]


def _split_stages(event: dict) -> tuple[list[Stage], list[str]]:
    """The training and test stages a `train_test_split` event produced.

    The first array is the features and the last one-dimensional array the labels (the call returns a training and a
    test part of each array, in order). Anything else is a problem to report, not a guess.
    """
    inputs, outputs = event.get("inputs") or [], event.get("out") or []
    if len(inputs) < 1 or len(outputs) != 2 * len(inputs):
        return [], [f"split {event.get('seq')}: {len(inputs)} arrays in, {len(outputs)} out"]
    label_index = len(inputs) - 1 if len(inputs) >= 2 and len((inputs[-1] or {}).get("shape", [])) == 1 else None
    label_train = outputs[2 * label_index] if label_index is not None else None
    label_test = outputs[2 * label_index + 1] if label_index is not None else None
    stages, problems = [], []
    for side, x, y in ((SIDE_TRAIN, outputs[0], label_train), (SIDE_TEST, outputs[1], label_test)):
        pairs = pairs_of(x, y)
        if pairs is None:
            problems.append(f"split {event.get('seq')}: the {side} rows or labels were not recorded")
        else:
            stages.append(Stage(side, SPLIT_SPACE, Counter(pairs), event["seq"]))
    return stages, problems


def _row_map(event: dict) -> dict | None:
    """Input fingerprint -> output fingerprint of a row-preserving call, or None when the call is not row by row
    (other row counts, or one input row giving two different output rows)."""
    x, out = event.get("X"), event.get("out")
    if not x or not out or "fp" not in x or "fp" not in out or len(x["fp"]) != len(out["fp"]):
        return None
    mapping: dict = {}
    for before, after in zip(x["fp"], out["fp"]):
        if mapping.setdefault(before, after) != after:
            return None
    return mapping


def _same_stage(a: Stage, b: Stage) -> bool:
    return a.side == b.side and a.space == b.space and a.pairs == b.pairs


def call_spaces(events: list[dict]) -> dict[int, tuple]:
    """For each estimator event (by seq), the space its output is in: (object, fit generation).

    A fit starts a new generation of its object; transform and predict use the current one. So a preprocessor's
    `fit_transform` on the training rows and its later `transform` on the test rows are in the same space.
    """
    generation: Counter = Counter()
    spaces = {}
    for event in events:
        if event.get("kind") != "estimator":
            continue
        if event.get("method") in FIT_METHODS:
            generation[event["obj"]] += 1
        spaces[event["seq"]] = ("call", event["obj"], generation[event["obj"]])
    return spaces


def build_context(trace: dict) -> TraceContext:
    """Cut a trace into seeds and push each seed's training and test pairs through its row-preserving calls."""
    events = sorted(trace.get("events", []), key=lambda e: e["seq"])
    spaces = call_spaces(events)
    split_positions = [i for i, e in enumerate(events) if e.get("kind") == "split"]
    preamble = events[:split_positions[0]] if split_positions else list(events)
    seeds = []
    for index, start in enumerate(split_positions):
        end = split_positions[index + 1] if index + 1 < len(split_positions) else len(events)
        stages, problems = _split_stages(events[start])
        seed = SeedContext(index, events[start], events[start + 1:end], stages, problems)
        for event in seed.events:
            if event.get("kind") != "estimator" or event.get("method") not in ROW_PRESERVING or "raised" in event:
                continue
            mapping = _row_map(event)
            if mapping is None:
                continue
            for stage in list(seed.stages):
                if not all(fp in mapping for fp in stage.fps):
                    continue
                moved: Counter = Counter()
                for (fp, label), n in stage.pairs.items():
                    moved[(mapping[fp], label)] += n
                new = Stage(stage.side, spaces[event["seq"]], moved, event["seq"])
                if not any(_same_stage(new, s) for s in seed.stages):
                    seed.stages.append(new)
        seeds.append(seed)
    return TraceContext(preamble, seeds)


def _counts(stage: Stage, labelled: bool) -> Counter:
    return stage.pairs if labelled else stage.fps


def _is_sub(small: Counter, big: Counter) -> bool:
    return not (small - big)


def relate(seed: SeedContext, pairs: list[tuple] | None) -> Relation:
    """Say how a multiset of pairs relates to this seed's split.

    Order of the answers: exactly a test stage; exactly a training stage; part of a test stage; part of a training
    stage; training rows plus some test rows of one space (`needs_test_rows`, counting the pairs no training row
    explains, matched multiset-wise so natural duplicates across the split are not counted); otherwise `unknown`.
    Pairs without labels (label None) are compared by fingerprint only.
    """
    if pairs is None:
        return Relation(UNKNOWN)
    labelled = all(label is not None for _, label in pairs)
    wanted = Counter(pairs) if labelled else Counter(fp for fp, _ in pairs)
    total = sum(wanted.values())
    tests, trains = seed.side(SIDE_TEST), seed.side(SIDE_TRAIN)
    for kind, candidates in ((TEST, tests), (TRAIN, trains)):
        for stage in candidates:
            if _counts(stage, labelled) == wanted:
                return Relation(kind, 0, stage)
    in_test = next((s for s in tests if _is_sub(wanted, _counts(s, labelled))), None)
    in_train = next((s for s in trains if _is_sub(wanted, _counts(s, labelled))), None)
    if in_test is not None:
        return Relation(TEST_SUBSET, in_test.size - total, in_test, ambiguous=in_train is not None)
    if in_train is not None:
        return Relation(TRAIN_SUBSET, in_train.size - total, in_train)
    best = None
    for train in trains:
        rest = wanted - _counts(train, labelled)
        n_rest = sum(rest.values())
        for test in tests:
            if test.space == train.space and _is_sub(rest, _counts(test, labelled)):
                if best is None or n_rest < best.count:
                    best = Relation(NEEDS_TEST_ROWS, n_rest, test)
    return best or Relation(UNKNOWN)
