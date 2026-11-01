"""Pre-registration: lock the prediction and the thresholds before the run, then let code compute the verdict.

Why: if thresholds could move after seeing the results, any result could be called a success. Hashing the record
before the run and storing that hash in the ledger makes a later change detectable. No LLM touches the verdict.
"""
from __future__ import annotations

import hashlib
import json
import math
import random

SEED_RANGE = 100_000
SUPPORTED = "supported"
NOT_SUPPORTED = "not_supported"
INCONCLUSIVE = "inconclusive"


def canonical_json(value: object) -> str:
    """One exact text for one value, so that hashes do not depend on key order or spacing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prereg_hash(prereg: dict) -> str:
    return sha256_text(canonical_json(prereg))


def draw_seeds(count: int, rng: random.Random | None = None) -> list[int]:
    """Random seeds, drawn the same way for real runs and for clones.

    Fixed seeds on real runs would force a choice: clones either repeat their source's text (the same cached review,
    counted twice) or use other seeds, which would mark them as clones.
    """
    return sorted((rng or random).sample(range(SEED_RANGE), count))


def build_prereg(proposal: dict, question: str, science_cfg: dict, seeds_per_arm: int,
                 rng: random.Random | None = None) -> dict:
    """Add what the Scientist must not choose: seeds come from code, split size and alpha from config, not from the LLM."""
    return {
        **proposal,
        "question": question,
        "seeds": draw_seeds(seeds_per_arm, rng),
        "test_size": science_cfg["test_size"],
        "alpha": science_cfg["alpha"],
    }


def to_run_config(prereg: dict) -> dict:
    """The experiment config that codegen needs, taken from the locked record."""
    return {
        "dataset": prereg["dataset"],
        "metric": prereg["metric"],
        "seeds": prereg["seeds"],
        "test_size": prereg["test_size"],
        "control": prereg["control_config"],
        "treatment": prereg["treatment_config"],
    }


def compute_verdict(prereg: dict, results: dict) -> dict:
    """Compare results with the locked thresholds. Pure code: same inputs, same verdict.

    The effect is treatment minus control per seed, with its sign flipped if the direction is "decrease", so a
    positive effect always means "as predicted". With the confidence interval of its mean:
      supported:     mean >= min_effect and the interval lies above 0 (large enough and clearly real)
      not_supported: the whole interval lies below min_effect (the predicted size is ruled out)
      inconclusive:  anything else (these seeds cannot decide)

    The interval uses the Nadeau-Bengio correction: variance factor 1/n + n_test/n_train instead of 1/n. Random
    splits of one dataset overlap, so seeds are not independent, and a plain t interval would be too narrow.
    """
    from scipy import stats  # imported here because it is slow and most CLI commands never need it

    sign = 1 if prereg["direction"] == "increase" else -1
    effects = [sign * (t - c) for t, c in zip(results["treatment"], results["control"])]
    n = len(effects)
    mean = sum(effects) / n
    verdict = {"outcome": INCONCLUSIVE, "mean_effect": mean, "ci_low": None, "ci_high": None, "n_seeds": n,
               "min_effect": prereg["min_effect"], "alpha": prereg["alpha"]}
    if n < 2:
        return verdict  # one seed gives no estimate of the spread
    sample_variance = sum((e - mean) ** 2 for e in effects) / (n - 1)
    train, test = results["split_sizes"]["train"], results["split_sizes"]["test"]
    test_train_ratio = (sum(test) / n) / (sum(train) / n)
    half_width = stats.t.ppf(1 - prereg["alpha"] / 2, n - 1) * math.sqrt((1 / n + test_train_ratio) * sample_variance)
    low, high = mean - half_width, mean + half_width
    if mean >= prereg["min_effect"] and low > 0:
        outcome = SUPPORTED
    elif high < prereg["min_effect"]:
        outcome = NOT_SUPPORTED
    else:
        outcome = INCONCLUSIVE
    return {**verdict, "outcome": outcome, "ci_low": low, "ci_high": high}


def failed_run_verdict(status: str, reason: str | None) -> dict:
    """A run that gave no usable results says nothing about the hypothesis."""
    return {"outcome": INCONCLUSIVE, "mean_effect": None, "ci_low": None, "ci_high": None, "n_seeds": 0,
            "reason": f"run failed: {status} ({reason})"}
