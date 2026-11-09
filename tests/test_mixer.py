"""The planner runs for real on cached datasets. Execution uses a fake sandbox, so no experiments and no real LLM run."""
import collections
import copy
import json
import random

import pytest

from canary import controls, ledger, llm, mixer, prereg, sandbox, sealed
from canary.config import load_yaml
from canary.ledger import Ledger
from canary.saboteur import impact
from canary.saboteur.classes import NotApplicable
from canary.saboteur.transforms import TRANSFORMS
from tests.test_coach_state import load_state
from tests.test_llm import CFG, FakeProvider
from tests.test_scientist import lock
from tests.test_skeptic import RESULTS

PASS_REPLY = json.dumps({"verdict": "pass", "bug_class": None, "evidence": "Fine.", "confidence": 0.7})


def base(dataset, metric, preprocessing=("standard_scaler",)):
    arm = {"model": "logistic_regression", "params": {"C": 1.0, "max_iter": 1000}, "preprocessing": list(preprocessing)}
    return {"focus": {}, "model": "sci:1", "prereg": lock(
        dataset=dataset, metric=metric, hypothesis=f"Regularization helps on {dataset}.", control_config=arm,
        treatment_config={**arm, "params": {"C": 0.1, "max_iter": 1000}})}


POOL = {"bases": [base("breast_cancer", "f1"), base("pc1", "f1"), base("wine", "accuracy"),
                  base("diabetes", "roc_auc", ())]}


@pytest.mark.parametrize("runs, expected", [(30, (20, 5, 5)), (180, (100, 40, 40)), (40, (20, 10, 10)), (31, (20, 5, 6))])
def test_split_gives_whole_rounds_of_variants(runs, expected):
    split = mixer.split_runs(runs)
    assert (split[sealed.CANARY_MEASURE], split[sealed.CONTROL], split[sealed.SHAM]) == expected


def test_too_few_runs_are_refused():
    with pytest.raises(mixer.MixerError):
        mixer.split_runs(21)


def test_plan_is_balanced_with_every_variant_equally_often():
    plan = mixer.plan_batch("b", 180, POOL, 1)
    variants = collections.Counter((s["bug_id"], s["tier"]) for s in plan["slots"] if s["bug_id"])
    assert set(variants) == set(TRANSFORMS) and set(variants.values()) == {5}
    types = collections.Counter(s["run_type"] for s in plan["slots"])
    assert types == {sealed.CANARY_MEASURE: 100, sealed.CONTROL: 40, sealed.SHAM: 40}
    assert sorted(s["slot"] for s in plan["slots"]) == list(range(180))


def test_plan_is_shuffled_and_reproducible():
    one, two = mixer.plan_batch("b", 60, POOL, 1), mixer.plan_batch("b", 60, POOL, 1)
    assert one["slots"] == two["slots"]
    types = [s["run_type"] for s in one["slots"]]
    assert types != sorted(types) and one["slots"] != mixer.plan_batch("b", 60, POOL, 2)["slots"]


def test_bugs_go_only_on_bases_where_they_are_real_bugs():
    plan = mixer.plan_batch("b", 180, POOL, 1)
    for slot in plan["slots"]:
        names = {plan["bases"][i]["prereg"]["dataset"] for i in slot["candidates"]}
        if (slot["bug_id"], slot["tier"]) == ("B06", "obvious"):
            assert names == {"pc1"}  # the only imbalanced base; B06 obvious is meaningless on the others
        if slot["bug_id"] == "B01":
            assert "diabetes" not in names  # no scaler, so B01 would change nothing


def test_clones_are_spread_over_the_usable_bases():
    plan = mixer.plan_batch("b", 180, POOL, 1)
    first_choices = {s["candidates"][0] for s in plan["slots"] if s["run_type"] == sealed.CONTROL}
    assert first_choices == set(range(len(POOL["bases"])))


def test_a_variant_with_no_base_stops_the_plan():
    """Dropping it silently would leave a class untested and look like a complete RQ1."""
    pool = {"bases": [base("breast_cancer", "f1")]}  # not imbalanced, so B06 obvious has nowhere to go
    with pytest.raises(mixer.MixerError, match="B06 obvious"):
        mixer.plan_batch("b", 30, pool, 1)


def test_focus_grid_avoids_settings_that_are_bugs_or_impossible():
    catalog = load_yaml("datasets.yaml")
    datasets = catalog["sklearn"] + catalog["openml"]
    balance = {d["name"]: 1.0 for d in datasets} | {"pc1": 13.0}
    grid = mixer.focus_grid(datasets, ["knn", "svm"], 8, balance)
    assert len(grid) == 8 * len(datasets)
    classes = {d["name"]: d["classes"] for d in datasets}
    assert not [g for g in grid if g["metric"] == "roc_auc" and classes[g["dataset"]] != 2]
    assert not [g for g in grid if g["dataset"] == "pc1" and g["metric"] == "accuracy"]
    assert {g["metric"] for g in grid} == set(mixer.METRIC_ORDER)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A ledger, table and client, with experiments replaced by instant fake runs."""
    def fake_run(config, runs_dir, timeout_s=None, script=None):
        run_id = f"run-{len(list(runs_dir.glob('*'))) if runs_dir.exists() else 0}-{random.random()}"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "experiment.py").write_text(script or f"x = {config['seeds']}\n", encoding="utf-8")
        n = len(config["seeds"])
        results = {**RESULTS, "dataset": config["dataset"], "metric": config["metric"], "seeds": config["seeds"],
                   "control": [0.8] * n, "treatment": [0.85] * n, "split_sizes": {"train": [100] * n, "test": [30] * n}}
        (run_dir / sandbox.RESULTS_NAME).write_text(json.dumps(results), encoding="utf-8")
        record = {"run_id": run_id, "status": sandbox.STATUS_OK, "reason": None, "seconds": 0.0}
        (run_dir / sandbox.RECORD_NAME).write_text(json.dumps(record), encoding="utf-8")
        return record

    monkeypatch.setattr(sandbox, "run_config", fake_run)
    monkeypatch.setattr(mixer, "sabotage", lambda config, bug, tier: type("S", (), {"config": config})())
    monkeypatch.setattr(impact, "sabotage", lambda config, bug, tier: type("S", (), {"config": config, "script": "y = 1\n"})())
    provider = FakeProvider([PASS_REPLY] * 200)
    return {
        "client": llm.LLM(CFG, {"fake": provider}, tmp_path / "cache.db"), "provider": provider,
        "led": Ledger(tmp_path / "ledger.db"), "table": sealed.SealedTable(tmp_path / "sealed.db"),
        "runs": tmp_path / "runs", "twins": tmp_path / "twins", "plans": tmp_path / "plans", "tmp": tmp_path,
    }


SHORT = 8  # a real batch's slots, but few: each ledger write costs real time, and the suite must stay under 30 s


def short_plan():
    # Unpadded: these tests are about batch mechanics, and the fake scripts have no main() to pad.
    plan = mixer.plan_batch("b", 30, POOL, 1, length_match=False)
    return {**plan, "slots": plan["slots"][:SHORT]}


def run(world, plan):
    return mixer.run_batch(world["client"], plan, world["led"], world["table"], world["runs"], world["twins"], world["plans"])


def test_batch_runs_seals_and_reviews_every_slot(world):
    plan = short_plan()
    report = run(world, plan)
    assert len(report.audited) == SHORT and not report.failures
    truths = [t for t in world["table"].all() if t.details["batch"] == "b"]
    assert collections.Counter(t.run_type for t in truths) == collections.Counter(s["run_type"] for s in plan["slots"])
    assert {t.details["slot"] for t in truths} == {s["slot"] for s in plan["slots"]}
    assert world["led"].verify(world["runs"]) == []


def test_resume_repeats_nothing(world):
    plan = short_plan()
    run(world, plan)
    calls = len(world["provider"].calls)
    report = run(world, plan)
    assert report.audited == [] and len(world["provider"].calls) == calls
    assert len(world["table"].all()) == SHORT


def test_resume_after_a_stop_finishes_only_what_is_left(world, monkeypatch):
    plan = short_plan()
    real = mixer.execute_slot
    done = []

    def stop_part_way(*args, **kwargs):
        if len(done) == 3:
            raise KeyboardInterrupt
        done.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(mixer, "execute_slot", stop_part_way)
    with pytest.raises(KeyboardInterrupt):
        run(world, plan)
    monkeypatch.setattr(mixer, "execute_slot", real)
    assert len(mixer.finished_slots("b", world["led"], world["table"])) == 3
    assert len(run(world, plan).audited) == SHORT
    assert len(world["table"].all()) == SHORT


def test_a_refused_base_moves_to_the_next_and_leaves_no_sealed_run(world, monkeypatch):
    plan = short_plan()
    slot = next(s for s in plan["slots"] if s["run_type"] == sealed.CONTROL)
    slot["candidates"] = [0, 1]
    real = controls.clone_prereg
    refused = []

    def refuse_first(base_prereg, config):
        if not refused:
            refused.append(1)
            raise NotApplicable("the hypothesis names C")
        return real(base_prereg, config)

    monkeypatch.setattr(controls, "clone_prereg", refuse_first)
    assert mixer.execute_slot(slot, plan, world["led"], world["table"], world["runs"], world["twins"])
    assert [t.source for t in world["table"].all()] == ["pool:1"]


def test_a_slot_no_base_fits_is_reported_not_raised(world, monkeypatch):
    plan = short_plan()
    monkeypatch.setattr(controls, "clone_prereg", lambda *_: (_ for _ in ()).throw(NotApplicable("no")))
    assert mixer.execute_slot(plan["slots"][0], plan, world["led"], world["table"], world["runs"], world["twins"]) is False
    assert world["table"].all() == []


def test_the_log_never_names_a_run_type(world):
    run(world, short_plan())
    text = (world["runs"] / "campaign.log").read_text(encoding="utf-8").lower()
    for word in ("canary", "control", "sham", "b01", "obvious", "subtle"):
        assert word not in text
    assert f"audit {SHORT}/{SHORT}" in text


def test_status_line_sees_a_real_finished_batch_as_finished(world, tmp_path):
    """Ties the status-line tip to what run_batch really writes, so rewording that line fails here."""
    run(world, short_plan())
    copy_path = tmp_path / "coach" / "data" / "runs" / "campaign.log"
    copy_path.parent.mkdir(parents=True)
    copy_path.write_text((world["runs"] / "campaign.log").read_text(encoding="utf-8"), encoding="utf-8")
    assert load_state().campaign_state(tmp_path / "coach") is None


def test_clone_keeps_its_base_wording_and_gets_new_seeds(world):
    plan = short_plan()
    run(world, plan)
    locks = [e.payload["prereg"] for e in world["led"].entries(ledger.PREREGISTERED)]
    assert all(p["hypothesis"].startswith("Regularization helps on") for p in locks)
    assert len({tuple(p["seeds"]) for p in locks}) == SHORT
    assert all(prereg.prereg_hash(e.payload["prereg"]) == e.payload["prereg_sha256"] for e in world["led"].entries(ledger.PREREGISTERED))


def test_plan_can_be_saved_as_json_unchanged():
    plan = mixer.plan_batch("b", 30, POOL, 1)
    assert json.loads(json.dumps(plan)) == copy.deepcopy(plan)


def test_the_dry_gate_fails_unpadded_plans_and_passes_padded_ones():
    unpadded = mixer.dry_length_check(mixer.plan_batch("b", 30, POOL, 1, length_match=False))
    assert not unpadded["passes"] and unpadded["features"]["line_count"]["value"] > 0.6
    padded = mixer.dry_length_check(mixer.plan_batch("b", 30, POOL, 1))
    assert padded["passes"] and padded["slots_without_base"] == 0
    assert padded["features"]["line_count"]["value"] == padded["features"]["char_count"]["value"] == 0.5  # one size


@pytest.mark.slow
def test_padding_without_decoys_fails_the_gate_on_helper_size():
    """Canaries keep a smaller helper without decoys (AUC 0.15 on pool 1), and the gate now sees it."""
    no_decoys = mixer.dry_length_check(mixer.plan_batch("b", 30, POOL, 1, decoys=False))
    assert not no_decoys["passes"] and not no_decoys["features"]["helper_statements"]["contains_half"]


def test_clean_slots_get_decoys_in_the_canaries_proportions():
    plan = mixer.plan_batch("b", 100, POOL, 1)
    decoys = [tuple(s["decoy"]) for s in plan["slots"] if s["run_type"] != sealed.CANARY_MEASURE]
    canaries = [(s["bug_id"], s["tier"]) for s in plan["slots"] if s["run_type"] == sealed.CANARY_MEASURE]
    assert len(decoys) == 40 and set(decoys) == set(canaries) == set(TRANSFORMS)
    assert {decoys.count(v) for v in set(decoys)} == {2} and {canaries.count(v) for v in set(canaries)} == {3}
    assert all("decoy" not in s for s in plan["slots"] if s["run_type"] == sealed.CANARY_MEASURE)
    assert mixer.decoy_assignment(40, 1) == mixer.decoy_assignment(40, 1)  # seeded
    assert not any("decoy" in s for s in mixer.plan_batch("b", 30, POOL, 1, length_match=False)["slots"])


def test_a_failed_length_gate_stops_before_any_audit(world, monkeypatch):
    plan = {**short_plan(), "length_match": True, "role": "skeptic_a"}
    monkeypatch.setattr(mixer, "_padder", lambda *_: None)  # the fake scripts cannot be padded
    failing = {"passes": False, "features": {}, "prompts_too_large": 0}
    monkeypatch.setattr(mixer, "batch_length_check", lambda *_: failing)
    report = run(world, plan)
    assert report.stopped.startswith("length gate failed") and report.audited == []
    assert world["provider"].calls == []  # no reviewer was asked anything
    assert json.loads((world["plans"] / "b.length_check.json").read_text(encoding="utf-8")) == failing
    monkeypatch.setattr(mixer, "batch_length_check", lambda *_: {**failing, "passes": True})
    assert len(run(world, plan).audited) == SHORT  # once the gate passes, the resume audits the batch


def test_a_new_pool_must_not_repeat_the_old_one():
    assert mixer.pool_keys(POOL) and mixer.pool_keys(POOL) == mixer.pool_keys(copy.deepcopy(POOL))
    other = {"bases": [base("wine", "f1")]}
    assert not mixer.pool_keys(other) & mixer.pool_keys(POOL)
