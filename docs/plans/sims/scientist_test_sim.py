"""Design-time simulation for Missions 3.1 and 3.2, written 2026-11-15 with the plan
`docs/plans/mission_3_1_3_2_memory_calibration.md`; not part of the package. Committed BEFORE its first run.

It sizes two local tests of the Scientist (no reviewer and no cloud call is involved in either):
  A. the variety test: N fresh unfocused proposals per prompt version;
  B. RQ6: K chains of L resolved predictions per arm (calibration feedback ON against OFF).
Every behaviour of the Scientist below is an ASSUMPTION for sizing. Nothing here is a measurement.

A. VARIETY TEST. 9 datasets and 4 metrics are offered. Pass marks (fixed in the plan, section 5):
     V1 at least 5 of the 9 datasets appear, and the most frequent dataset has at most 40% of the proposals;
     V2 at least 3 of the 4 metrics appear, and the most frequent metric has at most 60%.
   Proposers simulated (proposals drawn independently; real chains are not independent, said in the plan):
     uniform        every dataset and metric equally likely
     mild           one dataset 25%, one metric 40%, the rest even: uneven but acceptable
     half_dataset   one dataset 50%, the rest even; metrics even
     heavy_metric   one metric 75%, the rest even; datasets even
   RULE (fixed before the first run): N is the smallest of 18, 36, 54, 72, 90 with
     P(pass V1 and V2 | uniform) >= 0.95, P(pass V1 and V2 | mild) >= 0.90,
     P(pass V1 | half_dataset) <= 0.05 and P(pass V2 | heavy_metric) <= 0.05.
   If none qualifies, the largest N is taken and the plan states which condition failed.

B. RQ6. A prediction is the stated confidence c that the result reaches min_effect in the predicted direction; the
   outcome y is 1 if it did. Arm OFF: c = 0.80 with a little jitter (today's behaviour: nearly constant). Arm ON:
   from the sixth prediction of a chain on, c moves a fraction r of the way from 0.80 to the chain's running
   share of outcomes (r = 0: the feedback is ignored; 0.5; 1). The two arms run the same sequence of experiment
   cells, so chain k has the same true rate b_k in both arms (b_k = b + normal noise of sd 0.10, clipped).
   Statistic: per chain, Brier score over the second half of the chain, ON minus OFF; test: exact sign-flip
   test over the K chain differences, one-sided, alpha 0.05 (ON better = negative difference).
   RULE (fixed before the first run): among K in {6, 8, 10, 12} and L in {12, 20, 30}, the design with the
   smallest K * L (ties: fewer chains) that has power >= 0.80 at r = 0.5 for b = 0.2 and for b = 0.4, and a
   false-positive rate <= 0.05 at r = 0 for b = 0.2, 0.4 and 0.6. If none qualifies, the largest design is taken
   and the plan states which condition failed.

Run: python docs/plans/sims/scientist_test_sim.py   (writes scientist_test_sim.json beside this file)
"""
import itertools
import json
from pathlib import Path

import numpy as np

SEED = 3132
SIMS = 4000
DATASETS, METRICS = 9, 4
N_CANDIDATES = (18, 36, 54, 72, 90)
K_CANDIDATES, L_CANDIDATES = (6, 8, 10, 12), (12, 20, 30)
BASE_RATES, RESPONSES = (0.2, 0.4, 0.6), (0.0, 0.5, 1.0)
START, JITTER, CHAIN_SD, WARMUP = 0.80, 0.03, 0.10, 5


def shares(top: float, k: int) -> np.ndarray:
    return np.array([top] + [(1 - top) / (k - 1)] * (k - 1))


PROPOSERS = {"uniform": (shares(1 / DATASETS, DATASETS), shares(1 / METRICS, METRICS)),
             "mild": (shares(0.25, DATASETS), shares(0.40, METRICS)),
             "half_dataset": (shares(0.50, DATASETS), shares(1 / METRICS, METRICS)),
             "heavy_metric": (shares(1 / DATASETS, DATASETS), shares(0.75, METRICS))}


def variety(rng) -> dict:
    rows = {}
    for n in N_CANDIDATES:
        row = {}
        for name, (p_data, p_metric) in PROPOSERS.items():
            d = rng.multinomial(n, p_data, SIMS)
            m = rng.multinomial(n, p_metric, SIMS)
            v1 = ((d > 0).sum(axis=1) >= 5) & (d.max(axis=1) <= 0.40 * n)
            v2 = ((m > 0).sum(axis=1) >= 3) & (m.max(axis=1) <= 0.60 * n)
            row[name] = {"V1": float(v1.mean()), "V2": float(v2.mean()), "both": float((v1 & v2).mean())}
        row["qualifies"] = bool(row["uniform"]["both"] >= 0.95 and row["mild"]["both"] >= 0.90
                                and row["half_dataset"]["V1"] <= 0.05 and row["heavy_metric"]["V2"] <= 0.05)
        rows[str(n)] = row
    ok = [n for n in N_CANDIDATES if rows[str(n)]["qualifies"]]
    return {"by_n": rows, "chosen_n": ok[0] if ok else N_CANDIDATES[-1], "a_candidate_qualifies": bool(ok)}


def rq6_power(rng, k: int, length: int, base: float, response: float) -> float:
    """Share of simulated studies in which the sign-flip test says ON is better."""
    b = np.clip(base + rng.normal(0, CHAIN_SD, (SIMS, k)), 0.02, 0.98)
    half = length // 2
    score = {}
    for arm in ("off", "on"):
        y = rng.random((SIMS, k, length)) < b[:, :, None]
        c = np.clip(START + rng.normal(0, JITTER, (SIMS, k, length)), 0.01, 0.99)
        if arm == "on" and response > 0:
            seen = np.cumsum(y, axis=2) - y                      # outcomes before prediction t
            t = np.arange(length)[None, None, :]
            running = (1 + seen) / (2 + t)                       # running share with a flat prior
            moved = c + response * (running - START)
            c = np.where(t >= WARMUP, np.clip(moved, 0.01, 0.99), c)
        score[arm] = ((c - y) ** 2)[:, :, half:].mean(axis=2)
    diff = score["on"] - score["off"]                            # sims x chains; negative = ON better
    signs = np.array(list(itertools.product((1.0, -1.0), repeat=k)))
    observed = diff.mean(axis=1)
    flipped = diff @ signs.T / k                                 # sims x 2^k
    p = (flipped <= observed[:, None] + 1e-12).mean(axis=1)
    return float((p <= 0.05).mean())


def rq6(rng) -> dict:
    rows = []
    for k in K_CANDIDATES:
        for length in L_CANDIDATES:
            cell = {"K": k, "L": length, "predictions_per_arm": k * length, "power": {}}
            for base in BASE_RATES:
                for response in RESPONSES:
                    cell["power"][f"b{base}_r{response}"] = rq6_power(rng, k, length, base, response)
            cell["qualifies"] = bool(cell["power"]["b0.2_r0.5"] >= 0.80 and cell["power"]["b0.4_r0.5"] >= 0.80
                                     and all(cell["power"][f"b{b}_r0.0"] <= 0.05 for b in BASE_RATES))
            rows.append(cell)
    ok = sorted((c for c in rows if c["qualifies"]), key=lambda c: (c["predictions_per_arm"], c["K"]))
    chosen = ok[0] if ok else max(rows, key=lambda c: (c["predictions_per_arm"], c["K"]))
    return {"designs": rows, "chosen": {"K": chosen["K"], "L": chosen["L"]}, "a_candidate_qualifies": bool(ok)}


def main() -> None:
    rng = np.random.default_rng(SEED)
    out = {"assumed": {"start_confidence": START, "jitter": JITTER, "chain_sd": CHAIN_SD, "warmup": WARMUP,
                       "proposers": {k: [list(map(float, v[0])), list(map(float, v[1]))] for k, v in PROPOSERS.items()}},
           "sims": SIMS, "seed": SEED, "variety": variety(rng), "rq6": rq6(rng)}
    path = Path(__file__).with_suffix(".json")
    path.write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")
    print("variety: chosen N", out["variety"]["chosen_n"], "qualifies:", out["variety"]["a_candidate_qualifies"])
    for n, row in out["variety"]["by_n"].items():
        print(" ", n, {k: (round(v["both"], 3), round(v["V1"], 3), round(v["V2"], 3)) for k, v in row.items() if k != "qualifies"},
              row["qualifies"])
    print("rq6: chosen", out["rq6"]["chosen"], "qualifies:", out["rq6"]["a_candidate_qualifies"])
    for c in out["rq6"]["designs"]:
        print(" ", c["K"], c["L"], {k: round(v, 3) for k, v in c["power"].items()}, c["qualifies"])
    print("wrote", path)


if __name__ == "__main__":
    main()
