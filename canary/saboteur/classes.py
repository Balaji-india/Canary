"""The bug catalog, and which bugs make sense for which experiment.

Why applicability matters: a canary only measures recall if the planted bug is a real bug in that experiment. Accuracy
is a fine metric on balanced data, so "accuracy on imbalanced data" cannot be planted there. Reporting such a run as
"missed" would count the reviewer as wrong for passing a clean experiment.
"""
from __future__ import annotations

from canary import datasets
from canary.config import load_yaml

OBVIOUS = "obvious"
SUBTLE = "subtle"
TIERS = (OBVIOUS, SUBTLE)
IMBALANCE_RATIO = 3.0  # the same line docs/DESIGN.md section 6 draws for the B06 tripwire


class NotApplicable(ValueError):
    """This bug cannot be planted in this experiment. The mixer should choose another experiment or class."""


def catalog() -> dict:
    return load_yaml("bug_classes.yaml")


def class_counts(dataset: str) -> list[int]:
    """Rows per class, read from the cached dataset (the catalog does not record balance)."""
    labels = datasets.load_dataset(dataset)[datasets.TARGET_COLUMN].astype(str)
    return labels.value_counts().tolist()


def why_not_applicable(bug_id: str, tier: str, config: dict) -> str | None:
    """Return the reason this bug cannot be planted, or None when it can."""
    if bug_id not in catalog():
        raise KeyError(f"unknown bug class {bug_id!r}")
    if tier not in TIERS:
        raise KeyError(f"unknown tier {tier!r}")
    if bug_id == "B01" and not (config["control"]["preprocessing"] or config["treatment"]["preprocessing"]):
        return "with no scaler, fitting on all rows changes no value"
    if bug_id == "B05" and len(config["seeds"]) < 2:
        return "picking among seeds needs at least 2 seeds"
    if bug_id == "B06":
        counts = class_counts(config["dataset"])
        if tier == OBVIOUS:
            if config["metric"] == "accuracy":
                return "the config already uses accuracy, so nothing would be planted"
            if max(counts) / min(counts) <= IMBALANCE_RATIO:
                return f"accuracy is only misleading above a class ratio of {IMBALANCE_RATIO:g}:1"
        elif len(counts) != 2:
            return "switching between binary and macro averaging needs two classes"
    return None


def applicable(bug_id: str, tier: str, config: dict) -> bool:
    return why_not_applicable(bug_id, tier, config) is None
