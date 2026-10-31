"""The LLM and the sandbox are faked here: these tests cover the order of steps and the rules, not real runs."""
import copy
import json

import pytest

from canary import ledger, llm, prereg, sandbox, scientist
from canary.config import load_yaml
from canary.ledger import Ledger
from tests.test_llm import CFG, FakeProvider


def proposal(**changes):
    base = {
        "hypothesis": "Stronger regularization raises f1.",
        "dataset": "breast_cancer",
        "metric": "f1",
        "control_config": {"model": "logistic_regression", "params": {"C": 1.0, "max_iter": 1000},
                           "preprocessing": ["standard_scaler"]},
        "treatment_config": {"model": "logistic_regression", "params": {"C": 0.1, "max_iter": 1000},
                             "preprocessing": ["standard_scaler"]},
        "direction": "increase",
        "min_effect": 0.01,
        "predicted_effect": 0.02,
        "confidence": 0.6,
    }
    return {**base, **changes}


def reply(**changes):
    return json.dumps(proposal(**changes))


@pytest.fixture
def led(tmp_path):
    return Ledger(tmp_path / "ledger.db")


def client(tmp_path, replies):
    provider = FakeProvider(replies)
    return llm.LLM(CFG, {"fake": provider}, tmp_path / "cache.db"), provider


def fake_results(locked):
    n = len(locked["seeds"])
    return {"control": [0.80] * n, "treatment": [0.85] * n, "split_sizes": {"train": [426] * n, "test": [143] * n}}


def lock(**changes):
    campaign = load_yaml("campaign.yaml")
    return prereg.build_prereg(proposal(**changes), "q?", campaign["science"], campaign["seeds_per_arm"])


def test_code_not_the_llm_sets_seeds_split_and_alpha():
    campaign = load_yaml("campaign.yaml")
    locked = lock()
    assert locked["seeds"] == list(range(campaign["seeds_per_arm"]))
    assert locked["test_size"] == campaign["science"]["test_size"]
    assert locked["alpha"] == campaign["science"]["alpha"]


def test_llm_cannot_supply_a_verdict_or_seeds():
    schema = scientist.proposal_schema(0.005)
    for field in ("verdict", "outcome", "seeds", "alpha", "test_size"):
        assert field not in schema["properties"]
    assert llm.schema_problem(proposal(verdict="supported"), schema) is not None


def test_valid_proposal_fits_the_schema():
    assert llm.schema_problem(proposal(), scientist.proposal_schema(0.005)) is None


def test_trivially_small_min_effect_is_rejected_by_the_schema():
    assert "at least" in llm.schema_problem(proposal(min_effect=0.0001), scientist.proposal_schema(0.005))


@pytest.mark.parametrize("changes, expected", [
    ({"hypothesis": "  "}, "empty"),
    ({"predicted_effect": 0.001}, "below min_effect"),
    ({"dataset": "wine", "metric": "roc_auc"}, "two-class"),
    ({"treatment_config": proposal()["control_config"]}, "identical"),
])
def test_proposal_problems(changes, expected):
    assert expected in scientist.proposal_problem(lock(**changes), set())


def test_garbled_param_key_from_the_real_run_is_rejected_by_the_schema():
    """qwen3:4b really wrote this under an open params object, and it crashed the experiment."""
    arm = proposal()["control_config"]
    garbled = {**arm, "params": {"C": 1.0, ": ": 'class_weight": "balanced"'}}
    problem = llm.schema_problem(proposal(control_config=garbled), scientist.proposal_schema(0.005))
    assert "fits none" in problem


def test_param_of_another_model_is_rejected_by_the_schema():
    """qwen3:4b really gave gradient_boosting the parameters of knn under one shared parameter list."""
    arm = {"model": "gradient_boosting", "params": {"n_neighbors": 5}, "preprocessing": []}
    assert "fits none" in llm.schema_problem(proposal(control_config=arm), scientist.proposal_schema(0.005))


def test_every_model_with_its_own_params_fits_the_schema():
    from canary import codegen
    schema = scientist.proposal_schema(0.005)
    samples = {"number": 1.0, "integer": 1}
    for model, names in codegen.MODEL_PARAMS.items():
        params = {n: samples.get(codegen.PARAM_SCHEMAS[n].get("type")) or codegen.PARAM_SCHEMAS[n]["enum"][0]
                  for n in names}
        arm = {"model": model, "params": params, "preprocessing": []}
        assert llm.schema_problem(proposal(control_config=arm), schema) is None, model


def test_every_allowed_param_has_a_type_and_every_model_is_listed():
    from canary import codegen
    assert set(codegen.MODEL_PARAMS) == codegen.MODELS
    assert {p for params in codegen.MODEL_PARAMS.values() for p in params} == set(codegen.PARAM_SCHEMAS)


def test_allowed_params_exist_in_scikit_learn():
    """Our table must not offer a name that would crash every experiment using it."""
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.naive_bayes import GaussianNB
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.svm import SVC
    from sklearn.tree import DecisionTreeClassifier

    from canary import codegen
    classes = {"logistic_regression": LogisticRegression, "random_forest": RandomForestClassifier,
               "gradient_boosting": GradientBoostingClassifier, "svm": SVC, "knn": KNeighborsClassifier,
               "decision_tree": DecisionTreeClassifier, "gaussian_nb": GaussianNB}
    for name, params in codegen.MODEL_PARAMS.items():
        assert set(params) <= set(classes[name]().get_params()), name


def test_good_proposal_has_no_problem():
    assert scientist.proposal_problem(lock(), set()) is None


def test_rewording_does_not_hide_a_repeated_experiment():
    key = scientist._experiment_key(lock())
    assert "already run" in scientist.proposal_problem(lock(hypothesis="Same thing, other words."), {key})


def test_propose_feeds_the_problem_back(tmp_path, led):
    bad = reply(predicted_effect=0.001)
    fake_client, provider = client(tmp_path, [bad, reply()])
    locked, model = scientist.propose(fake_client, "q1", led)
    assert model == "sci:1" and locked["predicted_effect"] == 0.02
    assert "below min_effect" in provider.calls[1]["prompt"]


def test_propose_gives_up_after_the_allowed_attempts(tmp_path, led):
    """The same rejection twice must still reach the model: a repeated prompt would only replay the cached reply."""
    fake_client, provider = client(tmp_path, [reply(predicted_effect=0.001)] * 3)
    with pytest.raises(scientist.ProposalRejected, match="3 attempts"):
        scientist.propose(fake_client, "q1", led)
    assert len(provider.calls) == 3


def test_earlier_hypotheses_appear_in_the_prompt(tmp_path, led, monkeypatch):
    run_with_fake_sandbox(tmp_path, led, monkeypatch)
    fake_client, provider = client(tmp_path, [reply(dataset="wine")])
    scientist.propose(fake_client, "q1", led)
    assert "Stronger regularization raises f1." in provider.calls[0]["prompt"]


def run_with_fake_sandbox(tmp_path, led, monkeypatch, status=sandbox.STATUS_OK, locked=None):
    locked = locked or lock()
    runs = tmp_path / "runs"
    seen_at_run = {}

    def fake_run(config, runs_dir, timeout_s):
        seen_at_run["statuses"] = [e.status for e in led.entries()]
        seen_at_run["config"] = config
        run_dir = runs_dir / "run-1"
        run_dir.mkdir(parents=True)
        if status == sandbox.STATUS_OK:
            (run_dir / sandbox.RESULTS_NAME).write_text(json.dumps(fake_results(locked)), encoding="utf-8")
        return {"run_id": "run-1", "status": status, "reason": None if status == sandbox.STATUS_OK else "exit code 1"}

    monkeypatch.setattr(sandbox, "run_config", fake_run)
    return scientist.run_locked(locked, "sci:1", led, runs), seen_at_run, runs


def test_lock_is_in_the_ledger_before_the_run_starts(tmp_path, led, monkeypatch):
    _, seen, _ = run_with_fake_sandbox(tmp_path, led, monkeypatch)
    assert seen["statuses"] == [ledger.PROPOSED, ledger.PREREGISTERED]


def test_full_flow_records_a_verdict_and_a_verifiable_chain(tmp_path, led, monkeypatch):
    outcome, _, runs = run_with_fake_sandbox(tmp_path, led, monkeypatch)
    assert [e.status for e in led.entries()] == [ledger.PROPOSED, ledger.PREREGISTERED, ledger.RAN]
    ran = led.entries(ledger.RAN)[0].payload
    assert ran["verdict"]["outcome"] == prereg.SUPPORTED == outcome.verdict["outcome"]
    assert led.verify(runs) == []


def test_stored_lock_matches_its_hash_and_the_run_config(tmp_path, led, monkeypatch):
    outcome, seen, _ = run_with_fake_sandbox(tmp_path, led, monkeypatch)
    stored = led.entries(ledger.PREREGISTERED)[0].payload
    assert prereg.prereg_hash(stored["prereg"]) == stored["prereg_sha256"] == outcome.prereg_sha256
    assert seen["config"] == prereg.to_run_config(stored["prereg"])


def test_editing_results_after_the_verdict_is_detected(tmp_path, led, monkeypatch):
    _, _, runs = run_with_fake_sandbox(tmp_path, led, monkeypatch)
    (runs / "run-1" / sandbox.RESULTS_NAME).write_text("{}", encoding="utf-8")
    assert led.verify(runs)


def test_crashed_run_is_recorded_as_inconclusive(tmp_path, led, monkeypatch):
    outcome, _, runs = run_with_fake_sandbox(tmp_path, led, monkeypatch, status=sandbox.STATUS_CRASH)
    assert outcome.verdict["outcome"] == prereg.INCONCLUSIVE
    ran = led.entries(ledger.RAN)[0].payload
    assert ran["run_status"] == sandbox.STATUS_CRASH and ran["results_sha256"] is None
    assert led.verify(runs) == []


def test_real_sandbox_result_gets_a_verdict(tmp_path, led):
    """No fake here: a real experiment run from a locked record, with a two-seed config to keep it quick."""
    locked = copy.deepcopy(lock())
    locked["seeds"] = [0, 1]
    outcome = scientist.run_locked(locked, "sci:1", led, tmp_path / "runs")
    assert outcome.run_status == sandbox.STATUS_OK
    assert outcome.verdict["outcome"] in {prereg.SUPPORTED, prereg.NOT_SUPPORTED, prereg.INCONCLUSIVE}
    assert outcome.verdict["ci_low"] is not None
    assert led.verify(tmp_path / "runs") == []


def test_scientist_prompt_contains_the_choices_and_the_feedback():
    from canary import prompts
    text = prompts.scientist_prompt("Q?", [{"name": "wine", "classes": 3}], {"knn": ["n_neighbors"]}, ["f1"],
                                    ["minmax_scaler"], 0.005, ["old idea"], "too small")
    for piece in ("Q?", "wine", "n_neighbors", "minmax_scaler", "0.005", "old idea", "too small"):
        assert piece in text
