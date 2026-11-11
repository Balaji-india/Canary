"""The reviewer study: a second reviewer role re-audits a finished batch, and a shuffled-order diagnostic for Skeptic A.

The model is faked. These tests cover that roles do not interfere, that the baseline prompt and numbers stay exactly
as they were, and that the new evaluations compute what they say.
"""
import copy
import hashlib
import json
import types

import pytest

from canary import config, ledger, llm, mixer, prompts, review_tasks, sealed, skeptic, trust
from canary.ledger import Ledger
from canary.saboteur.transforms import TRANSFORMS
from eval import compare_reviewers, position_bias, rq1
from tests.test_llm import CFG, FakeProvider
from tests.test_mixer import load_state
from tests.test_skeptic import FLAG_REPLY, PASS_REPLY, add_ran_run

STUDY_CFG = copy.deepcopy(CFG)
STUDY_CFG["roles"]["skeptic_a_shuffled"] = {"use_role": "skeptic_a"}
BUGS = sorted(config.load_yaml("bug_classes.yaml"))


@pytest.fixture
def led(tmp_path):
    return Ledger(tmp_path / "ledger.db")


def client_for(tmp_path, replies):
    provider = FakeProvider(list(replies))
    return llm.LLM(STUDY_CFG, {"fake": provider}, tmp_path / f"cache{len(replies)}{id(provider)}.db"), provider


# --- roles do not interfere ------------------------------------------------------------------------------------------

def test_a_second_role_can_review_a_run_the_first_already_audited(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    client, provider = client_for(tmp_path, [FLAG_REPLY, PASS_REPLY])
    skeptic.audit_pending(client, led, runs)
    report = skeptic.audit_pending(client, led, runs, role="skeptic_b")
    assert [a["role"] for a in report.audited] == ["skeptic_b"]
    assert [c["model"] for c in provider.calls] == ["ska:1", "skb:1"]
    assert led.verify(runs) == []


def test_another_roles_failure_does_not_reopen_the_run_for_the_first(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    client, provider = client_for(tmp_path, [FLAG_REPLY] + ["junk"] * 3)
    skeptic.audit_pending(client, led, runs)
    assert skeptic.audit_pending(client, led, runs, role="skeptic_b").failures
    assert led.entries()[-1].status == ledger.AUDIT_FAILED
    assert skeptic.audit_pending(client, led, runs).audited == []  # skeptic_a already gave its opinion
    assert len(provider.calls) == 4


def test_a_role_that_failed_still_waits_after_another_role_audits(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    client, _ = client_for(tmp_path, ["junk"] * 3 + [FLAG_REPLY, PASS_REPLY])
    skeptic.audit_pending(client, led, runs, role="skeptic_b")
    skeptic.audit_pending(client, led, runs)
    assert len(skeptic.audit_pending(client, led, runs, role="skeptic_b").audited) == 1


def test_run_ids_limit_the_pass_and_a_resume_skips_finished_runs(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs, "h1", "r1")
    add_ran_run(led, runs, "h2", "r2", script="y = 2\n")
    client, provider = client_for(tmp_path, [PASS_REPLY, PASS_REPLY])
    assert [a["run_id"] for a in skeptic.audit_pending(client, led, runs, role="skeptic_b", run_ids={"r1"}).audited] == ["r1"]
    assert skeptic.audit_pending(client, led, runs, role="skeptic_b", run_ids={"r1"}).audited == []
    assert [a["run_id"] for a in skeptic.audit_pending(client, led, runs, role="skeptic_b").audited] == ["r2"]
    assert len(provider.calls) == 2


def test_alias_roles_are_not_checked_for_a_family_of_their_own():
    assert config.family_clashes(STUDY_CFG) == []


# --- prompt and schema order -----------------------------------------------------------------------------------------

def test_default_prompt_is_byte_identical_to_the_baseline():
    """The hash was taken from the prompt code before the order option existed: Skeptic B sees the baseline's text."""
    blinded = types.SimpleNamespace(prereg="PRE", script="x = 1", results="{}")
    text = prompts.skeptic_prompt(blinded, {"B02": {"name": "b_two"}, "B01": {"name": "a_one"}})
    assert hashlib.sha256(text.encode()).hexdigest() == "2f464dfa9214e24650d1fd5ed3c4d1fcf09f5af40bf387b0f82bd8458cb9ff1a"


def test_prompt_and_schema_are_shuffled_the_same_way_and_the_order_is_stored(tmp_path, led, monkeypatch):
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    order = list(reversed(BUGS))
    schemas = []
    real_schema = review_tasks.baseline_schema
    monkeypatch.setattr(review_tasks, "baseline_schema", lambda ids: schemas.append(list(ids)) or real_schema(ids))
    client, provider = client_for(tmp_path, [PASS_REPLY])
    skeptic.audit_pending(client, led, runs, role="skeptic_a_shuffled", class_order=lambda run_id: order)
    listed = [line.split(":")[0][2:] for line in provider.calls[0]["prompt"].splitlines() if line.startswith("- B")]
    assert listed == order and schemas[-1] == order
    stored = led.entries(ledger.AUDITED)[0].payload
    assert stored["class_order"] == order and provider.calls[0]["model"] == "ska:1"


def test_an_order_that_drops_a_class_is_refused(tmp_path, led):
    runs = tmp_path / "runs"
    add_ran_run(led, runs)
    client, _ = client_for(tmp_path, [PASS_REPLY])
    with pytest.raises(ValueError, match="reordering"):
        skeptic.audit_pending(client, led, runs, role="skeptic_a_shuffled", class_order=lambda run_id: BUGS[1:])


def test_the_shuffle_is_fixed_per_run_and_is_a_reordering():
    first = mixer.shuffled_order(BUGS, 0, "run-1")
    assert first == mixer.shuffled_order(BUGS, 0, "run-1") and sorted(first) == BUGS
    assert len({tuple(mixer.shuffled_order(BUGS, 0, f"run-{i}")) for i in range(20)}) > 15


# --- the diagnostic's sample -----------------------------------------------------------------------------------------

def seal_batch(table, led, batch="b", per_variant=2, clean=12, crash_cell=None):
    """Sealed runs with ledger RAN entries. `crash_cell` gets only a crashed run."""
    n = 0

    def add(run_type, bug=None, tier=None, ok=True):
        nonlocal n
        n += 1
        run, hyp = f"{batch}-r{n:03d}", f"{batch}-h{n:03d}"
        table.seal(run, run_type, bug, tier, source="pool:0", details={"batch": batch, "impact": None})
        led.append(hyp, ledger.PROPOSED, {})
        led.append(hyp, ledger.PREREGISTERED, {})
        led.append(hyp, ledger.RAN, {"run_id": run, "run_status": "ok" if ok else "crash",
                                     "results_sha256": "x" if ok else None})
        return run

    for bug, tier in sorted(TRANSFORMS):
        for _ in range(per_variant):
            add(sealed.CANARY_MEASURE, bug, tier, ok=(bug, tier) != crash_cell)
    for run_type in (sealed.CONTROL, sealed.SHAM):
        for _ in range(clean):
            add(run_type)


@pytest.fixture
def stores(tmp_path):
    return sealed.SealedTable(tmp_path / "sealed.db"), Ledger(tmp_path / "ledger.db")


@pytest.mark.slow  # 0.6-2.4 s (2026-11-11 durations); keeps the default run under 30 s
def test_sample_has_one_canary_per_cell_and_ten_of_each_clean_type(stores):
    table, led = stores
    seal_batch(table, led)
    seal_batch(table, led, batch="other")
    sample = mixer.position_sample(table, led, "b", seed=3)
    truths = [table.get(r) for r in sample["run_ids"]]
    cells = [(t.bug_id, t.tier) for t in truths if t.run_type == sealed.CANARY_MEASURE]
    assert sorted(cells) == sorted(TRANSFORMS) and sample["missing"] == []
    assert sum(t.run_type == sealed.CONTROL for t in truths) == 10 and sum(t.run_type == sealed.SHAM for t in truths) == 10
    assert all(t.details["batch"] == "b" for t in truths)
    assert sample == mixer.position_sample(table, led, "b", seed=3)


@pytest.mark.slow  # 0.6-2.4 s (2026-11-11 durations); keeps the default run under 30 s
def test_a_cell_with_only_a_crashed_run_is_reported_not_skipped(stores):
    table, led = stores
    cell = sorted(TRANSFORMS)[0]
    seal_batch(table, led, crash_cell=cell)
    sample = mixer.position_sample(table, led, "b", seed=0)
    assert sample["missing"] == [f"canary {cell[0]} {cell[1]}: no reviewable run"] and len(sample["run_ids"]) == 39


def test_reaudit_reviews_only_the_batch_and_logs_like_a_batch(tmp_path, stores):
    table, led = stores
    runs = tmp_path / "runs"
    for i in range(3):
        add_ran_run(led, runs, f"h{i}", f"r{i}", script=f"x = {i}\n")
        table.seal(f"r{i}", sealed.CONTROL if i else sealed.SHAM, source="pool:0", details={"batch": "b" if i < 2 else "c"})
    client, provider = client_for(tmp_path, [PASS_REPLY] * 2)
    log = tmp_path / "coach" / "data" / "runs" / "campaign.log"
    report = mixer.reaudit(client, led, table, "b", "skeptic_b", runs_dir=runs, log_path=log)
    assert sorted(a["run_id"] for a in report.audited) == ["r0", "r1"]
    text = log.read_text(encoding="utf-8")
    for word in ("control", "sham", "canary"):
        assert word not in text.lower()
    assert load_state().campaign_state(tmp_path / "coach") is None  # the tip sees a finished batch
    assert mixer.reaudit(client, led, table, "b", "skeptic_b", runs_dir=runs, log_path=log).audited == []


# --- RQ1 for another role --------------------------------------------------------------------------------------------

def test_another_roles_audits_leave_skeptic_a_numbers_unchanged(stores, monkeypatch):
    from tests.test_rq1 import small_batch

    monkeypatch.setattr(rq1, "model_digests", lambda models: {m: "digest" for m in models})
    table, led = stores
    small_batch(stores)
    before = rq1.build_results(table, led, "b", trust.DEFAULT_ROLE, ["B01", "B02"], 300)
    for entry in led.entries(ledger.RAN):
        led.append(entry.hypothesis_id, ledger.AUDIT_FAILED, {"run_id": entry.payload["run_id"], "role": "skeptic_b", "kind": "x"})
        led.append(entry.hypothesis_id, ledger.AUDITED, {"run_id": entry.payload["run_id"], "role": "skeptic_b", "model": "b:1",
                                                         "audit": {"verdict": "flag", "bug_class": "B02", "confidence": 1}})
    after = rq1.build_results(table, led, "b", trust.DEFAULT_ROLE, ["B01", "B02"], 300)
    for result in (before, after):
        result.pop("generated_at"), result.pop("excluded")
    assert before == after
    assert rq1.build_results(table, led, "b", "skeptic_b", ["B01", "B02"], 300)["flag_rate"] == 1.0


def test_other_roles_never_write_to_the_baseline_figure_paths(tmp_path, monkeypatch):
    assert rq1.figures_dir("skeptic_a") == rq1.FIGURES_DIR
    assert rq1.figures_dir("skeptic_b") == rq1.FIGURES_DIR / "skeptic_b"
    assert rq1.figures_dir("skeptic_b", "_pilot") == rq1.FIGURES_DIR / "skeptic_b" / "pilot"
    written = []
    monkeypatch.setattr(rq1, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(rq1.sealed, "SEALED_DB_PATH", tmp_path)  # exists
    monkeypatch.setattr(rq1.sealed, "SealedTable", lambda: None)
    monkeypatch.setattr(rq1.ledger, "Ledger", lambda: None)
    monkeypatch.setattr(rq1, "build_results", lambda *a: {"reviewed": 1})
    monkeypatch.setattr(rq1, "print_tables", lambda r: None)
    monkeypatch.setattr(rq1, "make_figures", lambda r, d: written.append(d) or [])
    assert rq1.main(["--batch", "rq1-full", "--role", "skeptic_b"]) == 0
    assert written == [rq1.FIGURES_DIR / "skeptic_b"] and (tmp_path / "rq1_skeptic_b.json").exists()


def test_a_batch_other_than_rq1_full_never_writes_the_baseline_names(tmp_path, monkeypatch):
    """The review-task screen runs skeptic_a on task-dev-1: it must not replace rq1_skeptic_a.json or its figures."""
    written = []
    monkeypatch.setattr(rq1, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(rq1.sealed, "SEALED_DB_PATH", tmp_path)
    monkeypatch.setattr(rq1.sealed, "SealedTable", lambda: None)
    monkeypatch.setattr(rq1.ledger, "Ledger", lambda: None)
    monkeypatch.setattr(rq1, "build_results", lambda *a: {"reviewed": 1})
    monkeypatch.setattr(rq1, "print_tables", lambda r: None)
    monkeypatch.setattr(rq1, "make_figures", lambda r, d: written.append(d) or [])
    assert rq1.main(["--batch", "task-dev-1", "--role", "skeptic_a"]) == 0
    assert not (tmp_path / "rq1_skeptic_a.json").exists()
    assert (tmp_path / "task_dev_1" / "rq1_skeptic_a.json").exists()
    assert written == [rq1.FIGURES_DIR / "task_dev_1" / "skeptic_a"] and written[0] != rq1.FIGURES_DIR


# --- the evaluations' arithmetic -------------------------------------------------------------------------------------

def share(successes, n):
    return position_bias._post([True] * successes + [False] * (n - successes))


def test_reading_rules_match_the_ones_fixed_before_the_run():
    assert position_bias.reading(share(20, 30), share(3, 30), 0.1) == "position bias"
    assert position_bias.reading(share(3, 30), share(28, 30), 0.1) == "prefers B01 itself, not its position"
    assert position_bias.reading(share(3, 30), share(3, 30), 0.1) == "no consistent order effect"
    assert position_bias.reading(share(0, 0), share(0, 0), 0.1) == "no flags: nothing to read"


def test_position_shares_are_counted_from_the_stored_order(stores):
    table, led = stores
    bugs = ["B01", "B02"]
    rows = [("B01", ["B02", "B01"]), ("B02", ["B02", "B01"]), ("B01", ["B01", "B02"]), (None, ["B01", "B02"])]
    for i, (named, order) in enumerate(rows):
        run, hyp = f"r{i}", f"h{i}"
        table.seal(run, sealed.CONTROL, source="pool:0", details={"batch": "b"})
        for state in (ledger.PROPOSED, ledger.PREREGISTERED):
            led.append(hyp, state, {})
        led.append(hyp, ledger.RAN, {"run_id": run})
        led.append(hyp, ledger.AUDITED, {"run_id": run, "role": "skeptic_a", "audit": {"verdict": "flag", "bug_class": "B01"}})
        led.append(hyp, ledger.AUDITED, {"run_id": run, "role": position_bias.ROLE, "class_order": order,
                                         "audit": {"verdict": "flag" if named else "pass", "bug_class": named}})
    r = position_bias.build_results(table, led, "b", bugs)
    assert r["reviewed"] == 4 and r["flag_rate"]["successes"] == 3
    assert (r["first_listed_share"]["successes"], r["first_listed_share"]["n"]) == (2, 3)  # B02 first, B01 first
    assert r["b01_share"]["successes"] == 2 and r["named_mix"] == {"B01": 2, "B02": 1}
    assert r["baseline_same_runs"]["same_verdict"] == 3 and r["chance_share"] == 0.5


def fake_rq1(role, flags):
    """A minimal RQ1 file: `flags` is a list of (run_type, flagged, named)."""
    p = {"raw": 0.5, "mean": 0.5, "interval_90": [0.1, 0.9], "successes": 1, "n": 2}
    return {"batch": "b", "role": role, "models": {"m": None}, "generated_at": "t", "reviewed": len(flags),
            "overall": {"any_flag_pooled": p, "right_type_pooled": p, "chance": {
                "any_flag": 0.5, "any_flag_interval": [0, 1], "right_type_uniform": 0.1, "right_type_matched": 0.1,
                "right_type_matched_interval": [0, 1]}},
            "specificity": {"controls": p, "shams": p, "combined": p}, "discrimination": {"youden_j": 0.0, "interval": [-0.1, 0.1]},
            "flag_rate": 0.5, "named_share": {}, "failures": {"by_type": {"control": {"failure_kinds": {"x": 2}}}},
            "records": [{"run_id": f"r{i}", "run_type": t, "flagged": f, "named_class": n, "seconds": 2.0 + i, "cached": False}
                        for i, (t, f, n) in enumerate(flags)]}


def test_paired_agreement_and_kappa_match_hand_values():
    a = fake_rq1("skeptic_a", [("canary_measure", True, "B01"), ("canary_measure", True, "B01"), ("control", True, "B01"), ("control", False, None)])
    b = fake_rq1("skeptic_b", [("canary_measure", True, "B01"), ("canary_measure", False, None), ("control", False, None), ("control", False, None)])
    c = compare_reviewers.build(a, b)
    p = c["paired"]
    # Agreement 2/4. Flag rates 3/4 and 1/4, so chance agreement is 3/16 + 3/16 = 3/8, and kappa = (1/2 - 3/8) / (5/8) = 0.2.
    assert (p["both_flag"], p["both_pass"], p["only_a_flags"], p["only_b_flags"]) == (1, 1, 2, 0)
    assert p["cohen_kappa"] == pytest.approx(0.2) and p["same_named_class_when_both_flag"] == 1
    assert c["reviewers"]["skeptic_a"]["failed_audits"] == 2
    assert c["reviewers"]["skeptic_a"]["seconds_per_audit"]["median"] == pytest.approx(3.5)
    with pytest.raises(ValueError):
        compare_reviewers.build(a, {**b, "batch": "other"})
