"""Controls must be clean, shams cosmetic, and neither distinguishable from the other by anything but the cosmetic edit."""
import ast
import json
import random

import pytest

from canary import blinding, codegen, controls, prereg, sandbox, sealed
from canary.saboteur.classes import NotApplicable
from canary.saboteur.transforms import sabotage


def config(**changes):
    arm = {"model": "decision_tree", "params": {"max_depth": 3}, "preprocessing": ["standard_scaler"]}
    treatment = {"model": "decision_tree", "params": {"max_depth": 5}, "preprocessing": ["standard_scaler"]}
    return {"dataset": "breast_cancer", "metric": "f1", "seeds": [0, 1], "test_size": 0.25, "control": arm,
            "treatment": treatment, **changes}


def base_prereg(cfg, hypothesis="A deeper tree improves the F1 score."):
    return {"hypothesis": hypothesis, "dataset": cfg["dataset"], "metric": cfg["metric"], "seeds": cfg["seeds"],
            "test_size": cfg["test_size"], "control_config": cfg["control"], "treatment_config": cfg["treatment"],
            "direction": "increase", "min_effect": 0.01, "predicted_effect": 0.02, "confidence": 0.7, "alpha": 0.05,
            "question": "q"}


CONFIGS = [config(), config(dataset="wine", metric="balanced_accuracy"),
           config(metric="roc_auc", control={"model": "svm", "params": {"C": 1.0}, "preprocessing": []}),
           config(control={"model": "knn", "params": {"n_neighbors": 3}, "preprocessing": ["minmax_scaler"]})]


# ---- Clean by construction ----

def test_a_normal_experiment_is_clean():
    assert controls.why_not_clean(config()) is None


def test_accuracy_on_imbalanced_data_is_not_clean():
    """It would be labelled clean here and buggy as a B06 canary."""
    assert "B06" in controls.why_not_clean(config(dataset="blood-transfusion-service-center", metric="accuracy"))


def test_accuracy_on_balanced_data_is_clean():
    assert controls.why_not_clean(config(metric="accuracy")) is None


def test_crippled_control_is_not_clean():
    arm = {"model": "decision_tree", "params": {"max_depth": 1}, "preprocessing": []}
    assert "B09" in controls.why_not_clean(config(control=arm))


def test_control_script_is_the_template_unchanged(tmp_path, monkeypatch):
    table = sealed.SealedTable(tmp_path / "s.db")
    seen = {}
    monkeypatch.setattr(sandbox, "run_config",
                        lambda cfg, runs, script=None: seen.update(script=script) or {"run_id": "r", "status": "ok"})
    controls.run_control(config(), table, tmp_path)
    assert seen["script"] is None
    assert table.get("r").run_type == sealed.CONTROL


def test_sham_is_sealed_with_the_edits_it_made(tmp_path, monkeypatch):
    table = sealed.SealedTable(tmp_path / "s.db")
    seen = {}
    monkeypatch.setattr(sandbox, "run_config",
                        lambda cfg, runs, script=None: seen.update(script=script) or {"run_id": "r", "status": "ok"})
    controls.run_sham(config(), table, random.Random(0), tmp_path)
    truth = table.get("r")
    assert truth.run_type == sealed.SHAM and truth.details["renames"]
    assert seen["script"] == controls.make_sham(config(), random.Random(0)).script


@pytest.mark.parametrize("run", [
    lambda cfg, table, path: controls.run_control(cfg, table, path),
    lambda cfg, table, path: controls.run_sham(cfg, table, random.Random(0), path),
    lambda cfg, table, path: controls.run_canary(cfg, "B03", "obvious", table, path, path),
])
def test_an_unclean_base_is_refused_before_anything_runs(run, tmp_path):
    table = sealed.SealedTable(tmp_path / "s.db")
    arm = {"model": "decision_tree", "params": {"max_depth": 1}, "preprocessing": []}
    with pytest.raises(NotApplicable):
        run(config(control=arm), table, tmp_path)
    assert table.all() == []


# ---- Shams: cosmetic, and visible after blinding ----

def test_sham_survives_blinding_because_a_plain_control_would_test_nothing_extra():
    cfg = config()
    sham = controls.make_sham(cfg, random.Random(0))
    assert blinding.blind_script(sham.script) != blinding.blind_script(codegen.render_script(cfg))


def test_same_rng_gives_the_same_sham_and_another_gives_another():
    cfg = config()
    assert controls.make_sham(cfg, random.Random(1)) == controls.make_sham(cfg, random.Random(1))
    assert controls.make_sham(cfg, random.Random(1)).script != controls.make_sham(cfg, random.Random(2)).script


def test_every_rename_applies_to_the_current_template():
    """If the template changes, this fails here and not as a rare failure in the middle of a campaign."""
    tree = ast.parse(codegen.render_script(config()))
    controls._rename(tree, controls.SHAM_RENAMES)
    ast.parse(ast.unparse(tree))


def test_rename_refuses_names_that_exist_or_would_collide():
    with pytest.raises(controls.ShamError):
        controls._rename(ast.parse("x = 1"), {"missing": "y"})
    with pytest.raises(controls.ShamError):
        controls._rename(ast.parse("x = y"), {"x": "y"})


def test_sham_leaves_the_config_keywords_and_result_keys_alone():
    source = controls.make_sham(config(), random.Random(3)).script
    constant = next(n.value for n in ast.parse(source).body
                    if isinstance(n, ast.Assign) and n.targets[0].id == "CONFIG")
    assert ast.literal_eval(constant) == config()
    assert '"control"' in source.replace("'", '"') and "stratify=" in source and "test_size=" in source


def test_new_names_do_not_announce_anything():
    text = " ".join(controls.SHAM_RENAMES.values()).lower()
    for cue in ("sham", "fake", "bug", "leak", "cosmetic", "canary", "clean", "gold", "planted"):
        assert cue not in text


def test_main_stays_last_and_the_docstring_first():
    tree = ast.parse(controls.make_sham(config(), random.Random(5)).script)
    functions = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert functions[-1] == "main" and ast.get_docstring(tree)


def results_of_script(script, cfg, folder, monkeypatch):
    """Run a script on real data inside this process: a subprocess per run would import scikit-learn each time."""
    codegen.prepare_run(cfg, folder, script)
    monkeypatch.chdir(folder)
    namespace = {"__name__": "experiment_under_test"}
    exec(compile(script, "experiment.py", "exec"), namespace)
    namespace["main"]()
    results = json.loads((folder / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))
    del results["runtime_seconds"]
    return results


@pytest.mark.parametrize("cfg", CONFIGS[1:], ids=["wine", "svm_auc", "knn"])
def test_sham_gives_exactly_the_control_numbers(cfg, tmp_path, monkeypatch):
    """The real proof that the edits are cosmetic: both run on real data and agree to the last digit."""
    expected = results_of_script(codegen.render_script(cfg), cfg, tmp_path / "control", monkeypatch)
    for seed in range(3):
        sham = controls.make_sham(cfg, random.Random(seed))
        assert results_of_script(sham.script, cfg, tmp_path / f"sham{seed}", monkeypatch) == expected


# ---- The blinding test from DESIGN section 5 ----

@pytest.mark.parametrize("cfg", CONFIGS)
@pytest.mark.parametrize("seed", range(4))
def test_control_and_sham_have_one_length_class_and_one_key_set(cfg, seed):
    control_text = blinding.blind_script(codegen.render_script(cfg))
    sham_text = blinding.blind_script(controls.make_sham(cfg, random.Random(seed)).script)
    assert blinding.length_class(control_text) == blinding.length_class(sham_text)
    # Exactly equal line counts, so a boundary between two classes can never separate them.
    assert len(control_text.splitlines()) == len(sham_text.splitlines())
    assert abs(len(control_text) - len(sham_text)) / len(control_text) < 0.03
    results = {"schema_version": 1, "dataset": cfg["dataset"], "metric": cfg["metric"], "seeds": cfg["seeds"],
               "control": [0.8, 0.8], "treatment": [0.9, 0.9], "class_balance": {"a": 1}, "runtime_seconds": 1.0,
               "split_sizes": {"train": [3, 3], "test": [1, 1]}}
    assert list(json.loads(blinding.blind_results(results))) == list(blinding.RESULT_KEYS)


def test_length_class_groups_by_tens_of_lines():
    assert blinding.length_class("x\n" * 9) == 0
    assert blinding.length_class("x\n" * 10) == 1
    assert blinding.length_class("x\n" * 25) == 2


@pytest.mark.parametrize("bug_id, tier", [("B09", "obvious"), ("B03", "subtle")])
def test_a_canary_prereg_has_the_same_keys_in_the_same_order(bug_id, tier):
    cfg = config()
    locked = controls.clone_prereg(base_prereg(cfg, "A deeper tree helps."), sabotage(cfg, bug_id, tier).config)
    assert list(json.loads(blinding.blind_prereg(locked))) == list(blinding.PREREG_KEYS)


# ---- Fresh seeds: no duplicate reviews, and no seed cue ----

def test_clone_gets_new_seeds_of_the_same_count_and_changes_nothing_else():
    cfg = config(seeds=[0, 1, 2, 3, 4])
    clone = controls.clone_config(cfg, random.Random(0))
    assert len(clone["seeds"]) == 5 and clone["seeds"] != cfg["seeds"]
    assert {**clone, "seeds": None} == {**cfg, "seeds": None}


def test_clone_does_not_change_its_source():
    cfg = config()
    controls.clone_config(cfg, random.Random(0))["control"]["params"]["max_depth"] = 99
    assert cfg == config()


def test_real_and_clone_seeds_come_from_one_function():
    """Clones cannot be told apart by their seeds if they are drawn exactly the way real runs draw them."""
    assert prereg.draw_seeds(5, random.Random(9)) == controls.clone_config(config(seeds=[0] * 5), random.Random(9))["seeds"]


def test_two_clones_of_one_experiment_get_different_review_text():
    """Identical text would return the cached review and count as a second independent observation."""
    rng = random.Random(0)
    texts = [codegen.render_script(controls.clone_config(config(), rng)) for _ in range(2)]
    assert blinding.blind_script(texts[0]) != blinding.blind_script(texts[1])


# ---- The hypothesis sentence must not contradict a sabotaged config ----

def test_metric_change_rewrites_the_sentence():
    cfg = config(metric="balanced_accuracy")
    changed = dict(cfg, metric="f1")
    locked = controls.clone_prereg(base_prereg(cfg, "Weighting raises balanced accuracy and Balanced_Accuracy."), changed)
    assert locked["hypothesis"] == "Weighting raises F1 score and F1 score."
    assert locked["metric"] == "f1"


def test_balanced_accuracy_is_replaced_whole_not_just_its_last_word():
    cfg = config(metric="f1")
    locked = controls.clone_prereg(base_prereg(cfg, "It raises balanced accuracy and ROC-AUC."), dict(cfg, metric="accuracy"))
    assert locked["hypothesis"] == "It raises accuracy and accuracy."


def test_same_metric_leaves_the_sentence_untouched():
    cfg = config()
    assert controls.clone_prereg(base_prereg(cfg, "Better accuracy."), cfg)["hypothesis"] == "Better accuracy."


@pytest.mark.parametrize("sentence", ["Raising max_depth helps.", "A larger max depth helps.", "MAX-DEPTH matters."])
def test_a_sentence_naming_a_changed_param_is_refused(sentence):
    cfg = config()
    planted = sabotage(cfg, "B09", "obvious").config
    with pytest.raises(NotApplicable, match="max_depth"):
        controls.clone_prereg(base_prereg(cfg, sentence), planted)


def test_a_sentence_about_something_else_survives_b09():
    cfg = config()
    planted = sabotage(cfg, "B09", "obvious").config
    locked = controls.clone_prereg(base_prereg(cfg, "A more complex tree helps."), planted)
    assert locked["control_config"] == planted["control"]


def test_short_param_c_needs_exact_case_and_a_whole_word():
    pattern = controls._param_pattern("C")
    assert pattern.search("Lowering C helps") and not pattern.search("a c value") and not pattern.search("Cats and SVC")


def test_clone_prereg_takes_seeds_and_settings_from_the_config_it_runs():
    cfg = config()
    clone = controls.clone_config(cfg, random.Random(0))
    locked = controls.clone_prereg(base_prereg(cfg), clone)
    assert prereg.to_run_config(locked) == clone


# ---- Sealing canaries ----

def test_canary_is_sealed_with_impact_and_twin_kept_apart(tmp_path, monkeypatch):
    calls = []

    def fake_run(cfg, folder, script=None):
        calls.append(folder)
        run_id = f"run{len(calls)}"
        (folder / run_id).mkdir(parents=True)
        value = 0.5 if script is None else 0.9
        (folder / run_id / sandbox.RESULTS_NAME).write_text(json.dumps({"control": [value] * 2, "treatment": [value] * 2}))
        return {"run_id": run_id, "status": "ok", "reason": None}

    monkeypatch.setattr(sandbox, "run_config", fake_run)
    table = sealed.SealedTable(tmp_path / "s.db")
    record = controls.run_canary(config(), "B03", "obvious", table, tmp_path / "runs", tmp_path / "twins", source="h1")
    assert calls == [tmp_path / "twins", tmp_path / "runs"]
    truth = table.get(record.run_id)
    assert (truth.run_type, truth.bug_id, truth.tier, truth.source) == (sealed.CANARY_MEASURE, "B03", "obvious", "h1")
    assert truth.details["impact"]["size"] == pytest.approx(0.4)
    assert truth.twin_run_id == record.twin_run_id
    assert table.get(record.twin_run_id) is None  # a twin is not a run anyone reviews
    assert not (tmp_path / "runs" / record.twin_run_id).exists()


def test_a_crashed_canary_is_still_sealed_without_impact(tmp_path, monkeypatch):
    def fake_run(cfg, folder, script=None):
        (folder / "x").mkdir(parents=True, exist_ok=True)
        return {"run_id": "x" if script is None else "y", "status": "crash", "reason": "boom"}

    monkeypatch.setattr(sandbox, "run_config", fake_run)
    table = sealed.SealedTable(tmp_path / "s.db")
    record = controls.run_canary(config(), "B03", "obvious", table, tmp_path, tmp_path)
    assert table.get(record.run_id).details == {"status": "crash", "reason": "boom", "impact": None}
