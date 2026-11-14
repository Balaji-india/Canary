"""Pair arithmetic of the tripwires (Mission 5.1, plan step 2): fast, on small hand-written traces.

Each test builds a trace the way the probe would (the events hold `probe.describe` of the data), then asks
`tripwires.relate` how some pairs relate to the split. Every expected answer and count is worked out by hand in the
test's comment.
"""
import numpy as np

from canary import probe, tripwires as tw

D = probe.describe

# Eight distinct rows; labels 0/1. Rows 0-5 are training rows, rows 6-7 test rows (in that order).
X = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0], [4.0, 40.0], [5.0, 50.0], [6.0, 60.0], [7.0, 70.0], [8.0, 80.0]])
Y = np.array([0, 1, 0, 1, 0, 1, 0, 1])
TRAIN_IDX, TEST_IDX = [0, 1, 2, 3, 4, 5], [6, 7]


def split_event(seq, X, y, train_idx, test_idx):
    return {"seq": seq, "kind": "split", "inputs": [D(X), D(y)], "kwargs": {},
            "out": [D(X[train_idx]), D(X[test_idx]), D(y[train_idx]), D(y[test_idx])]}


def call(seq, method, obj, x_in, x_out=None, y=None):
    out = D(x_out) if x_out is not None else {"returns_self": True}
    return {"seq": seq, "kind": "estimator", "method": method, "obj": obj, "cls": "test.Thing",
            "X": D(x_in), "y": D(y) if y is not None else None, "out": out}


def seed_of(*events, X=X, y=Y, train_idx=TRAIN_IDX, test_idx=TEST_IDX):
    trace = {"events": [split_event(0, X, y, train_idx, test_idx), *events]}
    return tw.build_context(trace).seeds[0]


def relate(seed, x, y=None):
    return tw.relate(seed, tw.pairs_of(D(x), D(y) if y is not None else None))


def test_the_test_pairs_are_test_and_the_training_pairs_train():
    seed = seed_of()
    assert relate(seed, X[TEST_IDX], Y[TEST_IDX]).kind == tw.TEST
    assert relate(seed, X[TRAIN_IDX], Y[TRAIN_IDX]).kind == tw.TRAIN


def test_a_joint_reorder_of_rows_and_labels_is_still_test():
    order = [1, 0]
    assert relate(seed_of(), X[TEST_IDX][order], Y[TEST_IDX][order]).kind == tw.TEST


def test_a_label_roll_is_not_test():
    # Test pairs (row 6, 0), (row 7, 1); rolled: (row 6, 1), (row 7, 0): neither pair exists anywhere in the split.
    relation = relate(seed_of(), X[TEST_IDX], np.roll(Y[TEST_IDX], 1))
    assert relation.kind == tw.UNKNOWN


def test_dropped_test_rows_are_a_subset_with_the_count():
    # 2 test pairs, 1 scored: one is missing.
    relation = relate(seed_of(), X[[7]], Y[[7]])
    assert (relation.kind, relation.count) == (tw.TEST_SUBSET, 1)


def test_a_test_sized_slice_of_training_rows_is_a_training_subset():
    # 2 of the 6 training pairs: 4 missing.
    relation = relate(seed_of(), X[[0, 1]], Y[[0, 1]])
    assert (relation.kind, relation.count) == (tw.TRAIN_SUBSET, 4)


def test_training_rows_plus_test_rows_need_the_test_rows_with_the_test_count():
    seed = seed_of()
    assert (relate(seed, X, Y).kind, relate(seed, X, Y).count) == (tw.NEEDS_TEST_ROWS, 2)
    unlabelled = relate(seed, X)  # a preprocessing fit has no labels: compared by fingerprint only
    assert (unlabelled.kind, unlabelled.count) == (tw.NEEDS_TEST_ROWS, 2)


def test_rows_the_dataset_never_had_are_unknown():
    assert relate(seed_of(), np.array([[99.0, 99.0]]), np.array([0])).kind == tw.UNKNOWN


def test_natural_duplicates_across_the_split_are_not_test_rows():
    # Row 6 is a copy of row 0 with the same label: the same pair is in both parts.
    X_dup, y_dup = X.copy(), Y.copy()
    X_dup[6], y_dup[6] = X_dup[0], y_dup[0]
    seed = seed_of(X=X_dup, y=y_dup)
    assert relate(seed, X_dup[TRAIN_IDX], y_dup[TRAIN_IDX]).kind == tw.TRAIN
    # All 8 rows: the multiset difference with the 6 training pairs leaves 2 pairs, not 1, so both test rows count.
    everything = relate(seed, X_dup, y_dup)
    assert (everything.kind, everything.count) == (tw.NEEDS_TEST_ROWS, 2)


def test_pairs_that_fit_inside_both_parts_are_marked_ambiguous():
    # Row 6 (test) is a copy of row 0 (training) with the same label: that one pair is part of both parts.
    X_dup, y_dup = X.copy(), Y.copy()
    X_dup[6], y_dup[6] = X_dup[0], y_dup[0]
    relation = relate(seed_of(X=X_dup, y=y_dup), X_dup[[6]], y_dup[[6]])
    assert (relation.kind, relation.count, relation.ambiguous) == (tw.TEST_SUBSET, 1, True)
    assert not relate(seed_of(), X[[7]], Y[[7]]).ambiguous


def test_identical_rows_with_different_labels_are_told_apart_by_their_label():
    # Rows 0 and 6 are identical; row 0 (training) has label 0, row 6 (test) label 1.
    X_dup, y_dup = X.copy(), Y.copy()
    X_dup[6], y_dup[0], y_dup[6] = X_dup[0], 0, 1
    seed = seed_of(X=X_dup, y=y_dup)
    assert relate(seed, X_dup[TRAIN_IDX], y_dup[TRAIN_IDX]).kind == tw.TRAIN
    swapped = y_dup[TRAIN_IDX].copy()
    swapped[0] = 1  # the training row now carries the test copy's label: only the test pair explains it
    relation = relate(seed, X_dup[TRAIN_IDX], swapped)
    assert (relation.kind, relation.count) == (tw.NEEDS_TEST_ROWS, 1)
    assert relate(seed, X_dup[TEST_IDX], y_dup[TEST_IDX]).kind == tw.TEST


def test_pairs_are_pushed_through_a_preprocessor_into_one_space():
    scale = lambda rows: rows * 2.0 + 1.0  # noqa: E731  (row by row, like a fitted scaler)
    seed = seed_of(call(1, "fit_transform", 7, X[TRAIN_IDX], scale(X[TRAIN_IDX])),
                   call(2, "transform", 7, X[TEST_IDX], scale(X[TEST_IDX])))
    spaces = {(s.side, s.space) for s in seed.stages}
    assert spaces == {("train", tw.SPLIT_SPACE), ("test", tw.SPLIT_SPACE), ("train", ("call", 7, 1)),
                      ("test", ("call", 7, 1))}
    assert relate(seed, scale(X[TEST_IDX]), Y[TEST_IDX]).kind == tw.TEST
    assert relate(seed, scale(X[TRAIN_IDX]), Y[TRAIN_IDX]).kind == tw.TRAIN
    # A model fit on the scaled training and test rows together needs the 2 test rows, in the scaled space.
    both = relate(seed, scale(X), Y)
    assert (both.kind, both.count, both.stage.space) == (tw.NEEDS_TEST_ROWS, 2, ("call", 7, 1))


def test_two_rows_that_become_identical_are_still_counted_twice():
    # Test rows 6 and 7 both map to [0, 0]; give them the same label so they become one pair counted twice.
    y_same = Y.copy()
    y_same[7] = y_same[6]
    collapsed = np.zeros((2, 2))
    seed = seed_of(call(1, "transform", 3, X[TEST_IDX], collapsed), y=y_same)
    pushed = [s for s in seed.stages if s.space == ("call", 3, 0)]
    assert len(pushed) == 1 and list(pushed[0].pairs.values()) == [2]
    assert relate(seed, collapsed, y_same[TEST_IDX]).kind == tw.TEST
    assert relate(seed, collapsed[:1], y_same[TEST_IDX][:1]).kind == tw.TEST_SUBSET  # one copy is not both


def test_a_call_that_is_not_row_by_row_pushes_nothing():
    # Input rows 6 and 6 again (duplicates) give two different outputs: no function from rows to rows.
    x_in = X[[6, 6]]
    seed = seed_of(call(1, "transform", 3, x_in, np.array([[0.0, 0.0], [1.0, 1.0]])))
    assert all(s.space == tw.SPLIT_SPACE for s in seed.stages)
    other_count = seed_of(call(1, "transform", 3, X[TEST_IDX], np.zeros((1, 2))))
    assert all(s.space == tw.SPLIT_SPACE for s in other_count.stages)


def test_each_split_starts_a_seed_and_events_before_the_first_are_the_preamble():
    early = call(0, "fit", 1, X, y=Y)
    first = split_event(1, X, Y, TRAIN_IDX, TEST_IDX)
    first_fit = call(2, "fit", 2, X[TRAIN_IDX], y=Y[TRAIN_IDX])
    second = split_event(3, X, Y, [2, 3, 4, 5, 6, 7], [0, 1])
    second_fit = call(4, "fit", 3, X[[2, 3, 4, 5, 6, 7]], y=Y[[2, 3, 4, 5, 6, 7]])
    context = tw.build_context({"events": [second_fit, first, early, second, first_fit]})  # order comes from seq
    assert [e["seq"] for e in context.preamble] == [0]
    assert [[e["seq"] for e in s.events] for s in context.seeds] == [[2], [4]]
    assert relate(context.seeds[1], X[[0, 1]], Y[[0, 1]]).kind == tw.TEST
    assert relate(context.seeds[0], X[[0, 1]], Y[[0, 1]]).kind == tw.TRAIN_SUBSET


def test_unrecorded_or_mismatched_labels_are_unknown_not_empty():
    assert tw.pairs_of(D(X), D(Y[:3])) is None
    assert tw.pairs_of(None) is None
    assert tw.relate(seed_of(), None).kind == tw.UNKNOWN


def test_a_split_without_recorded_rows_is_reported_as_a_problem():
    event = split_event(0, X, Y, TRAIN_IDX, TEST_IDX)
    del event["out"][1]["fp"]
    seed = tw.build_context({"events": [event]}).seeds[0]
    assert [s.side for s in seed.stages] == ["train"] and "test rows" in seed.problems[0]
