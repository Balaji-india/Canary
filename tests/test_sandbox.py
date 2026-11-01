import json
import time

import pytest
import yaml

from canary import codegen, sandbox
from canary.config import CONFIG_DIR


def load_example(name):
    return yaml.safe_load((CONFIG_DIR / "examples" / name).read_text(encoding="utf-8"))


@pytest.fixture
def config():
    return load_example("baseline.yaml")


def good_results():
    return {
        "schema_version": 1, "dataset": "breast_cancer", "metric": "f1", "seeds": [0, 1, 2, 3, 4],
        "control": [0.9] * 5, "treatment": [0.8] * 5, "class_balance": {"0": 212, "1": 357},
        "split_sizes": {"train": [426] * 5, "test": [143] * 5}, "runtime_seconds": 1.5,
    }


def run_text(tmp_path, source, timeout_s=30):
    """Stdlib-only scripts keep these tests fast: no scikit-learn import."""
    script = tmp_path / "s.py"
    script.write_text(source, encoding="utf-8")
    return sandbox.run_script(script, tmp_path, timeout_s)


def fake_run_script(monkeypatch, source):
    """Make run_config execute a tiny script in place of the generated experiment."""
    original = sandbox.run_script

    def replace(script, cwd, timeout_s):
        script.write_text(source, encoding="utf-8")
        return original(script, cwd, timeout_s)

    monkeypatch.setattr(sandbox, "run_script", replace)


def read_record(runs_dir, record):
    return json.loads((runs_dir / record["run_id"] / sandbox.RECORD_NAME).read_text(encoding="utf-8"))


def test_clean_exit(tmp_path):
    outcome = run_text(tmp_path, "print('hi')")
    assert (outcome.returncode, outcome.timed_out) == (0, False)
    assert (tmp_path / "stdout.log").read_text().strip() == "hi"


def test_crash_keeps_the_error_text(tmp_path):
    outcome = run_text(tmp_path, "raise ValueError('boom')")
    assert outcome.returncode == 1
    assert "ValueError: boom" in outcome.stderr_tail


def test_hanging_script_is_killed_at_the_timeout(tmp_path):
    started = time.perf_counter()
    outcome = run_text(tmp_path, "import time\ntime.sleep(60)", timeout_s=0.3)
    assert outcome.timed_out and outcome.returncode is None
    assert time.perf_counter() - started < 20


def test_working_directory_is_the_run_folder(tmp_path):
    run_text(tmp_path, "open('made_here.txt', 'w').close()")
    assert (tmp_path / "made_here.txt").exists()


def test_a_file_in_the_run_folder_cannot_shadow_a_module(tmp_path):
    (tmp_path / "json.py").write_text("raise RuntimeError('shadowed')", encoding="utf-8")
    assert run_text(tmp_path, "import json").returncode == 0


def test_secrets_do_not_reach_the_script(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    run_text(tmp_path, "import os\nprint(os.environ.get('ANTHROPIC_API_KEY'))")
    assert (tmp_path / "stdout.log").read_text().strip() == "None"


def test_good_results_pass_validation(config):
    assert sandbox.validate_results(good_results(), config) is None


@pytest.mark.parametrize("change, message", [
    (lambda r: r.pop("control"), "keys must be"),
    (lambda r: r.update(extra=1), "keys must be"),
    (lambda r: r.update(schema_version=2), "schema_version"),
    (lambda r: r.update(metric="accuracy"), "config says"),
    (lambda r: r.update(seeds=[0]), "config says"),
    (lambda r: r.update(control=[0.9]), "control must hold"),
    (lambda r: r.update(treatment=[float("nan")] * 5), "treatment must hold"),
    (lambda r: r.update(control=[1.5] * 5), "control must hold"),
    (lambda r: r.update(class_balance={}), "class_balance"),
    (lambda r: r.update(split_sizes={"train": [1] * 5}), "split_sizes"),
    (lambda r: r["split_sizes"].update(test=[1]), "split_sizes.test"),
    (lambda r: r.update(runtime_seconds=-1.0), "runtime_seconds"),
])
def test_bad_results_are_rejected(config, change, message):
    results = good_results()
    change(results)
    assert message in sandbox.validate_results(results, config)


def test_invalid_config_is_recorded_without_running(config, tmp_path):
    config["metric"] = "nope"
    record = sandbox.run_config(config, tmp_path)
    assert record["status"] == sandbox.STATUS_INVALID_CONFIG
    assert not (tmp_path / record["run_id"] / codegen.SCRIPT_NAME).exists()
    assert read_record(tmp_path, record) == record


def test_crash_is_recorded(config, tmp_path, monkeypatch):
    fake_run_script(monkeypatch, "raise ValueError('boom')")
    record = sandbox.run_config(config, tmp_path)
    assert record["status"] == sandbox.STATUS_CRASH
    assert "ValueError: boom" in read_record(tmp_path, record)["stderr_tail"]


def test_timeout_is_recorded(config, tmp_path, monkeypatch):
    fake_run_script(monkeypatch, "import time\ntime.sleep(60)")
    assert sandbox.run_config(config, tmp_path, timeout_s=0.3)["status"] == sandbox.STATUS_TIMEOUT


def test_clean_exit_without_results_is_not_a_success(config, tmp_path, monkeypatch):
    fake_run_script(monkeypatch, "pass")
    assert sandbox.run_config(config, tmp_path)["status"] == sandbox.STATUS_INVALID_RESULTS


def test_crash_after_writing_results_is_still_a_crash(config, tmp_path, monkeypatch):
    source = f"import json\njson.dump({good_results()!r}, open('results.json', 'w'))\nraise SystemExit(3)"
    fake_run_script(monkeypatch, source)
    assert sandbox.run_config(config, tmp_path)["status"] == sandbox.STATUS_CRASH


def test_crash_rate_counts_failures_and_skips_invalid_configs(config, tmp_path, monkeypatch):
    bad = dict(config, metric="nope")
    sandbox.run_config(bad, tmp_path)
    assert sandbox.crash_rate(tmp_path) == (0, 0)
    fake_run_script(monkeypatch, "raise ValueError('boom')")
    sandbox.run_config(config, tmp_path)
    assert sandbox.crash_rate(tmp_path) == (1, 1)


def test_real_experiment_end_to_end(tmp_path):
    """Run the real template and check its numbers against a separate computation written here."""
    from sklearn.datasets import load_breast_cancer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    config = dict(load_example("baseline.yaml"), seeds=[0, 1])
    record = sandbox.run_config(config, tmp_path)
    assert record["status"] == sandbox.STATUS_OK, record
    results = json.loads((tmp_path / record["run_id"] / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))
    assert results["class_balance"] == {"0": 212, "1": 357}
    assert results["split_sizes"] == {"train": [426, 426], "test": [143, 143]}

    X, labels = load_breast_cancer(return_X_y=True)
    y = (labels == 0).astype(int)  # class 0 is the minority, so the template treats it as positive
    for arm, C in (("control", 1.0), ("treatment", 0.1)):
        for position, seed in enumerate(config["seeds"]):
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=seed, stratify=y)
            model = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=1000, random_state=seed))
            expected = f1_score(y_test, model.fit(X_train, y_train).predict(X_test))
            assert results[arm][position] == pytest.approx(expected, abs=1e-9)


def test_uncached_dataset_is_recorded_not_raised(config, tmp_path, monkeypatch):
    def missing(_name):
        raise FileNotFoundError("not cached")

    monkeypatch.setattr(codegen.datasets, "load_dataset", missing)
    assert sandbox.run_config(config, tmp_path)["status"] == sandbox.STATUS_INVALID_CONFIG


def test_deliberately_broken_example_really_is_broken(tmp_path, monkeypatch):
    """Run inside this process to save a scikit-learn import. test_crash_is_recorded covers how a crash gets stored."""
    config = load_example("broken.yaml")
    source = codegen.render_script(config)
    codegen.prepare_run(config, tmp_path, source)
    monkeypatch.chdir(tmp_path)
    namespace = {"__name__": "experiment_under_test"}
    exec(compile(source, codegen.SCRIPT_NAME, "exec"), namespace)
    with pytest.raises(Exception) as caught:
        namespace["main"]()
    assert type(caught.value).__name__ == "InvalidParameterError"
