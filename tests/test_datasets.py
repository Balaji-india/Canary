import pandas as pd
import pytest

from canary import datasets
from canary.datasets import TARGET_COLUMN


def frame(labels):
    return pd.DataFrame({"x": range(len(labels)), TARGET_COLUMN: labels})


def test_check_frame_accepts_a_good_frame():
    assert datasets.check_frame(frame([0, 1, 0]), expected_classes=2) is None


def test_check_frame_catches_wrong_class_count():
    assert "expected 3" in datasets.check_frame(frame([0, 1]), expected_classes=3)


def test_check_frame_catches_missing_target():
    assert "no __target__" in datasets.check_frame(pd.DataFrame({"x": [1]}), expected_classes=2)


def test_sklearn_dataset_loads_offline():
    loaded = datasets.load_dataset("breast_cancer")
    assert datasets.check_frame(loaded, expected_classes=2) is None


def test_cached_dataset_round_trips(tmp_path):
    original = frame(["a", "b", "a"])
    original.to_csv(datasets.cache_path("credit-g", tmp_path), index=False)
    pd.testing.assert_frame_equal(datasets.load_dataset("credit-g", tmp_path), original)


def test_uncached_dataset_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        datasets.load_dataset("credit-g", tmp_path)


def test_unknown_dataset_raises():
    with pytest.raises(KeyError):
        datasets.load_dataset("no-such-dataset")


def test_cache_openml_keeps_going_after_a_failure(tmp_path, monkeypatch):
    def fake_fetch(entry):
        if entry["name"] == "credit-g":
            raise OSError("network down")
        return frame([0, 1])

    monkeypatch.setattr(datasets, "_fetch_openml", fake_fetch)
    report = dict(datasets.cache_openml(tmp_path))
    assert report["credit-g"].startswith("FAILED")
    assert report["diabetes"] == "cached 2 rows"
    assert datasets.cache_path("diabetes", tmp_path).exists()
