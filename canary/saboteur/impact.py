"""Canary records: which bug was planted, and how far it moved the numbers from its clean twin.

Why measure this: a canary breaks the method whether or not the score moves. A reviewer who misses a bug that changed
nothing did less damage than one who misses a bug that faked a result, so recall is reported for each group.

Why a twin: both runs use the same seeds and splits, so the difference comes from the bug and not from sampling.

This must stay out of the run folder and away from reviewers: an impact value says the run is a canary. These records
are stored in the sealed table by controls.run_canary.
"""
from __future__ import annotations

import copy
import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from canary import sandbox
from canary.config import load_yaml
from canary.saboteur.classes import OBVIOUS
from canary.saboteur.transforms import sabotage

HARMFUL = "harmful"
HARMLESS = "harmless"
UNMEASURED = "unmeasured"


@dataclass(frozen=True)
class CanaryRecord:
    bug_id: str
    tier: str
    run_id: str
    twin_run_id: str
    config: dict
    status: str  # sandbox status of the canary, or of the twin if that is what failed
    reason: str | None
    impact: dict | None  # None when a run failed, so no comparison exists

    def to_dict(self) -> dict:
        return asdict(self)


def twin_config(config: dict, planted_config: dict, bug_id: str, tier: str) -> dict:
    """The clean experiment to compare with. It must use the canary's metric whenever that makes sense.

    B06 subtle moves the experiment to f1, so its twin is honest f1 on the same data. B06 obvious is different: its
    only change is the metric, so a twin with that metric would be the same run. It keeps the original metric instead,
    and compute_impact marks the numbers as not comparable.
    """
    return copy.deepcopy(planted_config if (bug_id, tier) == ("B06", "subtle") else config)


def compute_impact(clean: dict, planted: dict, comparable: bool = True, threshold: float | None = None) -> dict:
    """Change from the clean twin, per arm and in the treatment-minus-control effect.

    `effect` is kept because a verdict depends on it: a bug can shift both arms equally and leave it unchanged, and
    B09 changes it only through the control. `size` is the largest of the three, ignoring sign, because a bug that
    lowers a score has also falsified the result. The default threshold is the smallest effect a verdict can count.
    """
    threshold = load_yaml("campaign.yaml")["science"]["min_effect_floor"] if threshold is None else threshold
    control = statistics.fmean(planted["control"]) - statistics.fmean(clean["control"])
    treatment = statistics.fmean(planted["treatment"]) - statistics.fmean(clean["treatment"])
    effect = treatment - control
    return {"control": control, "treatment": treatment, "effect": effect,
            "size": max(abs(control), abs(treatment), abs(effect)), "threshold": threshold, "comparable": comparable}


def impact_class(impact: dict | None) -> str:
    """Which recall group this canary belongs to. Numbers on two different metrics say nothing about harm."""
    if impact is None or not impact["comparable"]:
        return UNMEASURED
    return HARMFUL if impact["size"] >= impact["threshold"] else HARMLESS


def _results(record: dict, runs_dir: Path) -> dict:
    return json.loads((runs_dir / record["run_id"] / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))


def run_canary(config: dict, bug_id: str, tier: str, runs_dir: Path = sandbox.RUNS_DIR,
               twin_dir: Path | None = None) -> CanaryRecord:
    """Plant the bug, run the canary and its clean twin, and return the record. Failures are recorded, not raised.

    `twin_dir` defaults to `runs_dir`; controls.run_canary passes a separate folder for real campaigns.
    """
    twin_dir = runs_dir if twin_dir is None else twin_dir
    planted = sabotage(config, bug_id, tier)
    twin = sandbox.run_config(twin_config(config, planted.config, bug_id, tier), twin_dir)
    run = sandbox.run_config(planted.config, runs_dir, script=planted.script)
    failed = next((r for r in (run, twin) if r["status"] != sandbox.STATUS_OK), None)
    found = None
    if failed is None:
        comparable = (bug_id, tier) != ("B06", OBVIOUS)
        found = compute_impact(_results(twin, twin_dir), _results(run, runs_dir), comparable)
    return CanaryRecord(bug_id, tier, run["run_id"], twin["run_id"], planted.config,
                        failed["status"] if failed else sandbox.STATUS_OK, failed["reason"] if failed else None, found)
