"""The baseline guard wired into the Scientist (plan step 4). The LLM and the sandbox are faked, as in test_scientist."""
import json

import pytest

from canary import baseline_guard, codegen, ledger, prereg, sandbox, scientist, sealed, skeptic
from canary.config import load_yaml
from tests.test_baseline_guard import WEAK, ScriptedRunner
from tests.test_scientist import client, lock, proposal, reply


@pytest.fixture
def led(tmp_path):
    return ledger.Ledger(tmp_path / "ledger.db")


@pytest.fixture
def table(tmp_path):
    return sealed.SealedTable(tmp_path / "sealed.db")


def switch_guard(monkeypatch, on):
    """Change science.baseline_guard for one test, leaving the rest of config/campaign.yaml as it is."""
    real = scientist.load_yaml

    def patched(name, *args, **kwargs):
        loaded = real(name, *args, **kwargs)
        if name == "campaign.yaml":
            loaded["science"] = {**loaded["science"], "baseline_guard": on}
        return loaded

    monkeypatch.setattr(scientist, "load_yaml", patched)


def guard_log() -> list[dict]:
    path = baseline_guard.LOG_PATH
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


CONFOUNDED = {"control_config": {"model": "logistic_regression", "params": {"max_iter": 1}, "preprocessing": []},
              "treatment_config": {"model": "logistic_regression", "params": {}, "preprocessing": ["standard_scaler"]}}


def test_the_guard_is_on_in_the_campaign_config():
    assert load_yaml("campaign.yaml")["science"]["baseline_guard"] is True
    assert scientist.guard_enabled()


def test_a_guard_rejection_is_fed_back_and_the_retry_is_accepted(tmp_path, led, table):
    fake_client, provider = client(tmp_path, [reply(**CONFOUNDED), reply()])
    locked, _ = scientist.propose(fake_client, "q1", led, table)
    assert locked["control_config"] == proposal()["control_config"]
    assert "the arms differ in max_iter and preprocessing" in provider.calls[1]["prompt"]
    assert [line["guard"]["rule"] for line in guard_log()] == [baseline_guard.G1, baseline_guard.G6]


def test_three_guard_rejections_raise_proposal_rejected(tmp_path, led, table):
    fake_client, _ = client(tmp_path, [reply(**CONFOUNDED)] * 3)
    with pytest.raises(scientist.ProposalRejected, match="one thing only"):
        scientist.propose(fake_client, "q1", led, table)
    assert len(guard_log()) == 3


def test_the_guard_runs_only_after_the_other_checks_pass(tmp_path, led, table):
    fake_client, _ = client(tmp_path, [reply(predicted_effect=0.001), reply()])
    scientist.propose(fake_client, "q1", led, table)
    assert len(guard_log()) == 1  # the proposal below min_effect never reached the guard


def run_flow(tmp_path, led, monkeypatch, locked, model="sci:1"):
    """run_locked with a fake sandbox that writes the rendered script and full results, so the run can be blinded."""
    runs = tmp_path / "runs"

    def fake_run(config, runs_dir, timeout_s):
        run_dir = runs_dir / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / codegen.SCRIPT_NAME).write_text(codegen.render_script(config), encoding="utf-8")
        n = len(config["seeds"])
        results = {"schema_version": 1, "dataset": config["dataset"], "metric": config["metric"],
                   "seeds": config["seeds"], "control": [0.80] * n, "treatment": [0.85] * n,
                   "class_balance": {"0": 357, "1": 212}, "split_sizes": {"train": [426] * n, "test": [143] * n},
                   "runtime_seconds": 1.0}
        (run_dir / sandbox.RESULTS_NAME).write_text(json.dumps(results), encoding="utf-8")
        return {"run_id": "run-1", "status": sandbox.STATUS_OK, "reason": None}

    monkeypatch.setattr(sandbox, "run_config", fake_run)
    outcome = scientist.run_locked(locked, model, led, sealed.SealedTable(tmp_path / "sealed.db"), runs)
    return outcome, runs


def test_the_record_from_propose_goes_into_the_proposed_entry(tmp_path, led, table, monkeypatch):
    fake_client, _ = client(tmp_path, [reply()])
    locked, model = scientist.propose(fake_client, "q1", led, table)
    run_flow(tmp_path, led, monkeypatch, locked, model)
    (entry,) = led.entries(ledger.PROPOSED)
    assert entry.payload["guard"]["rule"] == baseline_guard.G6
    assert entry.payload["guard"] == guard_log()[0]["guard"]
    assert len(guard_log()) == 1  # run_locked used the stored record, it did not check again
    assert led.verify(tmp_path / "runs") == []


def test_a_lock_that_skipped_propose_is_checked_in_run_locked(tmp_path, led, monkeypatch):
    run_flow(tmp_path, led, monkeypatch, lock())
    (entry,) = led.entries(ledger.PROPOSED)
    assert entry.payload["guard"]["outcome"] == baseline_guard.OK and len(guard_log()) == 1


def test_run_locked_refuses_a_rejected_lock_before_writing_anything(tmp_path, led, monkeypatch):
    with pytest.raises(scientist.ProposalRejected, match="G1"):
        run_flow(tmp_path, led, monkeypatch, lock(**CONFOUNDED))
    assert led.entries() == []


def test_a_queued_proposal_runs_and_carries_its_label(tmp_path, led, monkeypatch):
    monkeypatch.setattr(baseline_guard, "default_runner", lambda: ScriptedRunner(WEAK))
    stump = {"model": "decision_tree", "params": {"max_depth": 1}, "preprocessing": []}
    deep = {"model": "decision_tree", "params": {"max_depth": 8}, "preprocessing": []}
    outcome, _ = run_flow(tmp_path, led, monkeypatch, lock(control_config=stump, treatment_config=deep))
    (entry,) = led.entries(ledger.PROPOSED)
    assert entry.payload["guard"]["outcome"] == baseline_guard.HUMAN_QUEUE
    assert entry.payload["guard"]["label"] == baseline_guard.CONTROL_BELOW_DEFAULT
    assert outcome.verdict["outcome"] == prereg.SUPPORTED  # the run itself went ahead


def test_the_lock_its_hash_and_the_reviewers_text_are_the_same_with_and_without_the_guard(tmp_path, monkeypatch):
    locked = lock()
    seen = {}
    for on in (True, False):
        switch_guard(monkeypatch, on)
        folder = tmp_path / ("on" if on else "off")
        led = ledger.Ledger(folder / "ledger.db")
        outcome, runs = run_flow(folder, led, monkeypatch, locked)
        stored = led.entries(ledger.PREREGISTERED)[0].payload
        seen[on] = (stored, outcome.prereg_sha256, skeptic.blinded_run(led, "run-1", runs),
                    led.entries(ledger.PROPOSED)[0].payload)
    assert seen[True][0] == seen[False][0] and seen[True][0]["prereg"] == locked
    assert "guard" not in seen[True][0]["prereg"]
    assert seen[True][1] == seen[False][1] == prereg.prereg_hash(locked)
    assert seen[True][2] == seen[False][2]  # the blinded script, results and pre-registration the reviewer reads
    assert "guard" in seen[True][3] and "guard" not in seen[False][3]


def test_the_guard_off_gives_todays_behaviour_exactly(tmp_path, led, table, monkeypatch):
    """A proposal the guard would reject is accepted as before; no reference run, no log, no `guard` key."""
    switch_guard(monkeypatch, False)
    calls = []
    monkeypatch.setattr(baseline_guard, "default_runner", lambda: calls.append(1))
    fake_client, provider = client(tmp_path, [reply(**CONFOUNDED)])
    locked, model = scientist.propose(fake_client, "q1", led, table)
    assert locked["control_config"] == CONFOUNDED["control_config"] and len(provider.calls) == 1
    run_flow(tmp_path, led, monkeypatch, locked, model)
    (entry,) = led.entries(ledger.PROPOSED)
    assert entry.payload == {"hypothesis": locked["hypothesis"], "model": model}
    assert calls == [] and guard_log() == [] and not baseline_guard.LOG_PATH.exists()
