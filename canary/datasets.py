"""Download the OpenML datasets once and load every dataset offline afterwards.

Why our own CSV cache: experiments must run with no network, and a plain CSV can be opened and checked by
hand. scikit-learn's built-in datasets ship with the library, so they never need caching.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from canary.config import CACHE_DIR, load_yaml

TARGET_COLUMN = "__target__"


def cache_path(name: str, cache_dir: Path = CACHE_DIR) -> Path:
    return cache_dir / f"{name}.csv.gz"


def load_sklearn(name: str) -> pd.DataFrame:
    from sklearn import datasets as sk

    loader = getattr(sk, f"load_{name}")
    frame = loader(as_frame=True).frame
    return frame.rename(columns={"target": TARGET_COLUMN})


def load_cached(name: str, cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """Read a cached OpenML dataset. Raises FileNotFoundError if it was never downloaded."""
    return pd.read_csv(cache_path(name, cache_dir))


def load_dataset(name: str, cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """Return a dataset as a frame whose label column is TARGET_COLUMN. Never touches the network."""
    cfg = load_yaml("datasets.yaml")
    if any(d["name"] == name for d in cfg["sklearn"]):
        return load_sklearn(name)
    if any(d["name"] == name for d in cfg["openml"]):
        return load_cached(name, cache_dir)
    raise KeyError(f"unknown dataset: {name}")


def check_frame(frame: pd.DataFrame, expected_classes: int) -> str | None:
    """Return a problem description, or None when the frame is usable."""
    if TARGET_COLUMN not in frame.columns:
        return f"no {TARGET_COLUMN} column"
    if frame.empty:
        return "no rows"
    found = frame[TARGET_COLUMN].nunique()
    if found != expected_classes:
        return f"expected {expected_classes} classes, found {found}"
    return None


def _fetch_openml(entry: dict) -> pd.DataFrame:
    """Fetch by id, and by name if the id fails (the ids in datasets.yaml are unverified until first load).

    parser="liac-arff": sklearn's default pandas parser crashes under pandas 3 on non-text nominal labels.
    """
    from sklearn.datasets import fetch_openml

    options = {"as_frame": True, "parser": "liac-arff", "n_retries": 5, "delay": 5.0}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            bunch = fetch_openml(data_id=entry["id"], data_home=tmp, **options)
            if bunch.details["name"] != entry["name"]:
                raise ValueError(f"id {entry['id']} is {bunch.details['name']}, not {entry['name']}")
        except Exception:
            bunch = fetch_openml(name=entry["name"], version=1, data_home=tmp, **options)
    frame = bunch.frame.copy()
    target = bunch.target_names[0] if bunch.target_names else frame.columns[-1]
    return frame.rename(columns={target: TARGET_COLUMN})


def cache_openml(cache_dir: Path = CACHE_DIR) -> list[tuple[str, str]]:
    """Download any missing OpenML dataset. Returns (name, status) per dataset; one failure does not stop the rest."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    report = []
    for entry in load_yaml("datasets.yaml")["openml"]:
        path = cache_path(entry["name"], cache_dir)
        if path.exists():
            report.append((entry["name"], "already cached"))
            continue
        try:
            frame = _fetch_openml(entry)
            problem = check_frame(frame, entry["classes"])
            if problem:
                report.append((entry["name"], f"FAILED: {problem}"))
                continue
            frame.to_csv(path, index=False)
            report.append((entry["name"], f"cached {len(frame)} rows"))
        except Exception as exc:  # network or OpenML errors: report them and carry on
            report.append((entry["name"], f"FAILED: {exc}"))
    return report
