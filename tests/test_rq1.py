"""RQ1's statistics, checked against values worked out by hand from made-up audits."""
import pytest

from canary import ledger, sealed, trust
from canary.ledger import Ledger
from eval import rq1

BUGS = ["B01", "B02"]


@pytest.fixture
def stores(tmp_path):
    return sealed.SealedTable(tmp_path / "sealed.db"), Ledger(tmp_path / "ledger.db")


counter = {"n": 0}


def add(stores, run_type, verdict=None, bug=None, named=None, batch="b", failures=(), status="ok"):
    """Enter one run. `verdict` None leaves it with no opinion."""
    table, led = stores
    counter["n"] += 1
    hyp, run = f"h{counter['n']}", f"r{counter['n']}"
    table.seal(run, run_type, bug, "obvious" if bug else None, source="pool:0", details={"batch": batch, "impact": None})
    for state in (ledger.PROPOSED, ledger.PREREGISTERED):
        led.append(hyp, state, {})
    led.append(hyp, ledger.RAN, {"run_id": run, "run_status": status})
    for kind in failures:
        led.append(hyp, ledger.AUDIT_FAILED, {"run_id": run, "role": trust.DEFAULT_ROLE, "kind": kind})
    if verdict:
        led.append(hyp, ledger.AUDITED, {"run_id": run, "role": trust.DEFAULT_ROLE, "model": "m:1", "audit": {
            "verdict": verdict, "bug_class": named, "confidence": 0.5}})
    return run


def small_batch(stores):
    """6 canaries (4 B01, 2 B02), 4 clean. 5 of 10 flagged. Names: B01 x4, B02 x1."""
    for _ in range(3):
        add(stores, sealed.CANARY_MEASURE, "flag", "B01", "B01")
    add(stores, sealed.CANARY_MEASURE, "pass", "B01")
    add(stores, sealed.CANARY_MEASURE, "flag", "B02", "B01")  # caught, wrong name
    add(stores, sealed.CANARY_MEASURE, "pass", "B02")
    add(stores, sealed.CONTROL, "flag", named="B02")
    add(stores, sealed.CONTROL, "pass")
    add(stores, sealed.SHAM, "pass")
    add(stores, sealed.SHAM, "pass")


def observations(stores, batch="b"):
    return trust.collect_observations(stores[0], stores[1], batch=batch)[0]


def test_chance_baseline_matches_hand_values(stores):
    small_batch(stores)
    chance = trust.chance_baseline(observations(stores), BUGS)
    assert chance["flag_rate"] == pytest.approx(0.5)  # 5 flags of 10
    assert chance["named_share"] == {"B01": 0.8, "B02": 0.2}  # 4 and 1 of the 5 flags
    assert chance["per_class"]["B01"]["right_type_uniform"] == pytest.approx(0.25)  # 0.5 / 2
    assert chance["per_class"]["B01"]["right_type_matched"] == pytest.approx(0.4)  # 0.5 * 0.8
    assert chance["per_class"]["B02"]["right_type_matched"] == pytest.approx(0.1)  # 0.5 * 0.2
    # Pooled matched: (4 * 0.4 + 2 * 0.1) / 6 = 0.3
    assert chance["overall"]["right_type_matched"] == pytest.approx(0.3)


def test_chance_simulation_centres_on_the_flag_rate(stores):
    small_batch(stores)
    low, high = trust.chance_baseline(observations(stores), BUGS, draws=20000)["overall"]["any_flag_interval"]
    assert low < 0.5 < high and low > 0.05 and high < 0.95


@pytest.mark.slow
def test_flag_everything_reviewer_is_exactly_at_chance_and_j_is_low(stores):
    """The reason for the baseline: this reviewer has any-flag recall 1 and has learned nothing."""
    for _ in range(10):
        add(stores, sealed.CANARY_MEASURE, "flag", "B01", "B01")
        add(stores, sealed.CONTROL, "flag", named="B01")
    obs = observations(stores)
    chance = trust.chance_baseline(obs, BUGS)
    assert chance["flag_rate"] == 1.0
    assert chance["per_class"]["B01"]["right_type_matched"] == 1.0
    summary = trust.summarize(obs, ["B01"])
    # Recall Beta(11, 1), specificity Beta(1, 11): means 11/12 and 1/12, so J = 11/12 + 1/12 - 1 = 0.
    assert trust.discrimination(summary, 20000)["youden_j"] == pytest.approx(0.0, abs=0.01)


def test_discrimination_needs_both_kinds_of_run(stores):
    add(stores, sealed.CANARY_MEASURE, "flag", "B01", "B01")
    assert trust.discrimination(trust.summarize(observations(stores), BUGS)) is None


def test_failed_audit_is_neither_a_miss_nor_a_catch(stores):
    add(stores, sealed.CANARY_MEASURE, "flag", "B01", "B01")
    add(stores, sealed.CANARY_MEASURE, None, "B01", failures=["invalid_reply"])
    summary = trust.summarize(observations(stores), BUGS)
    assert (summary.per_class["B01"].successes, summary.per_class["B01"].n) == (1, 1)


def test_failures_are_counted_per_type_and_kept_apart_from_crashes(stores):
    add(stores, sealed.CANARY_MEASURE, None, "B01", failures=["invalid_reply", "invalid_reply"])
    add(stores, sealed.CANARY_MEASURE, "pass", "B01", failures=["timeout_or_server"])
    add(stores, sealed.CANARY_MEASURE, None, "B02", status="crash")
    add(stores, sealed.CONTROL, "pass")
    failures = trust.collect_failures(*stores, batch="b")
    canary = failures["by_type"][sealed.CANARY_MEASURE]
    assert (canary["sealed"], canary["audited"], canary["failed_then_recovered"]) == (3, 1, 1)
    assert (canary["never_reviewed_failed"], canary["crashed"]) == (1, 1)
    assert canary["failure_kinds"] == {"invalid_reply": 2, "timeout_or_server": 1}
    assert failures["unreviewed_canaries"] == {"B01": 1}  # the crash has no results, so nothing could be reviewed
    assert failures["by_type"][sealed.CONTROL]["audited"] == 1


def test_recall_bounds_match_hand_values(stores):
    small_batch(stores)
    # 4 caught of 6 reviewed. With 2 unreviewed: 4/8 and 6/8.
    assert trust.recall_bounds(observations(stores), 2) == (0.5, 0.75)


def test_batches_do_not_mix(stores):
    add(stores, sealed.CANARY_MEASURE, "flag", "B01", "B01", batch="pilot")
    add(stores, sealed.CANARY_MEASURE, "pass", "B01", batch="full")
    obs, excluded = trust.collect_observations(stores[0], stores[1], batch="full")
    assert [o.flagged for o in obs] == [False] and excluded["other_batch"] == 1
    assert set(trust.collect_failures(*stores, batch="pilot")["by_type"]) == {sealed.CANARY_MEASURE}


def test_results_hold_all_three_figures_side_by_side(stores, monkeypatch):
    monkeypatch.setattr(rq1, "model_digests", lambda models: {m: "digest" for m in models})
    small_batch(stores)
    r = rq1.build_results(stores[0], stores[1], "b", trust.DEFAULT_ROLE, BUGS, 500)
    row = r["per_class"]["B01"]
    assert (row["any_flag"]["successes"], row["any_flag"]["n"]) == (3, 4)
    assert row["right_type"]["successes"] == 3
    assert r["per_class"]["B02"]["right_type"]["successes"] == 0  # flagged, but named B01
    assert row["chance"]["any_flag"] == 0.5 and row["distinct_bases"] == 1
    assert r["overall"]["any_flag_pooled"]["raw"] == pytest.approx(4 / 6)
    assert r["specificity"]["combined"]["successes"] == 3 and len(r["records"]) == 10
    assert r["classes_tested"] == 2


@pytest.mark.slow
def test_figures_are_written(stores, tmp_path, monkeypatch):
    monkeypatch.setattr(rq1, "model_digests", lambda models: {m: "digest" for m in models})
    small_batch(stores)
    r = rq1.build_results(stores[0], stores[1], "b", trust.DEFAULT_ROLE, BUGS, 200)
    paths = rq1.make_figures(r, tmp_path / "figs")
    assert all(p.stat().st_size > 1000 for p in paths)


@pytest.mark.slow
def test_flag_everything_across_many_classes_is_not_scored_below_chance(stores):
    """A real bug: averaging per-class posteriors gave -0.07 here, as if the reviewer were worse than random."""
    bugs = [f"B{i:02d}" for i in range(1, 11)]
    for bug in bugs:
        for _ in range(10):
            add(stores, sealed.CANARY_MEASURE, "flag", bug, "B01")
    for _ in range(80):
        add(stores, sealed.CONTROL, "flag", named="B01")
    result = trust.discrimination(trust.summarize(observations(stores), bugs), 20000)
    assert result["observed_j"] == 0.0
    # Pooled: Beta(101, 1) mean 101/102, specificity Beta(1, 81) mean 1/82, so J = 101/102 + 1/82 - 1 = +0.0024.
    assert result["youden_j"] == pytest.approx(101 / 102 + 1 / 82 - 1, abs=0.002)
