"""Design-time simulation for Mission 4.2 (RQ4), written 2026-11-15 with the plan; not part of the package.

One bank of reviewed runs (200 canaries, 20 per class, and 160 clean runs: the size of `tripwire-test-1`), optionally
with 30 extra B09 canaries. Many random re-splits of the bank into a calibration set (12 canaries per class, 60 clean
runs) and an audited set of 100 runs with a known share of buggy runs. Question: over re-splits of ONE bank, how often
does the 90% interval hold the truth, and how much does that share vary from bank to bank when the estimator is right?
The 5th percentile across banks is what a fair pass mark for the real bank can be.

The reviewer's true rates are ASSUMPTIONS for sizing (see trust_design_sim.py). Opus rebuilds this in
eval/rq4_power.py and re-runs it with measured numbers before the RQ4 plan is locked.
Run: python docs/plans/sims/rq4_bank_sim.py  (writes rq4_bank_sim.json beside this file)
"""
import json
from pathlib import Path

import numpy as np

DRAWS, BANKS, SPLITS = 600, 200, 100
PER_CLASS, CLEAN, CAL_PER_CLASS, CAL_CLEAN, AUDITED = 20, 160, 12, 60, 100
REVIEWERS = {"union_assumed": [0.97] * 9 + [0.17], "llm_alone_assumed": [0.94] * 8 + [0.05, 0.17]}
SP = 0.98
B09 = 9  # index of the weak class in the lists above
# (name, share of buggy runs, share of the buggy runs that are B09 or None for an even spread, extra B09 canaries)
LEVELS = [("matched", 0.0, None, 0), ("matched", 0.1, None, 0), ("matched", 0.3, None, 0), ("matched", 0.5, None, 0),
          ("b09_40pct", 0.1, 0.4, 0), ("b09_40pct", 0.2, 0.4, 0),
          ("b09_50pct_topup", 0.1, 0.5, 30), ("b09_50pct_topup", 0.3, 0.5, 30)]


def interval(rng, cal_caught, cal_n, cal_clean_pass, flags, n):
    se = rng.beta(1 + cal_caught[:, None], 1 + (cal_n - cal_caught)[:, None], (len(cal_caught), DRAWS))
    worst = se[int(np.argmin((1 + cal_caught) / (2 + cal_n)))]
    sp = rng.beta(1 + cal_clean_pass, 1 + CAL_CLEAN - cal_clean_pass, DRAWS)
    p = rng.beta(1 + flags, 1 + n - flags, DRAWS)
    out = {}
    for name, s in (("pooled", se.mean(axis=0)), ("worst", worst)):
        den = s + sp - 1
        pi = np.where(den > 0, np.clip((p + sp - 1) / np.where(den > 0, den, 1), 0, 1), 1.0)
        out[name] = (np.percentile(pi, 5), np.median(pi), np.percentile(pi, 95))
    return out


def one_level(rng, se_true, share, b09_share, extra):
    k = len(se_true)
    n_bug = round(AUDITED * share)
    if b09_share is None:
        take = np.full(k, n_bug // k)
    else:
        n_b09 = round(n_bug * b09_share)
        others = n_bug - n_b09
        take = np.full(k, others // (k - 1))
        take[B09] = n_b09
    spare = n_bug - take.sum()  # leftovers go to random other classes, one each
    cover, upper, mids = [], [], []
    for _ in range(BANKS):
        sizes = np.full(k, PER_CLASS)
        sizes[B09] += extra
        bank = [rng.random(s) < se_true[c] for c, s in enumerate(sizes)]
        clean_flag = rng.random(CLEAN) < 1 - SP
        c_cover = c_upper = 0
        for _ in range(SPLITS):
            t = take.copy()
            if spare:
                t[rng.choice([c for c in range(k) if c != B09], spare, replace=False)] += 1
            flags, cal_caught = 0, np.zeros(k, dtype=int)
            for c in range(k):
                order = rng.permutation(sizes[c])
                flags += bank[c][order[:t[c]]].sum()
                cal_caught[c] = bank[c][order[t[c]:t[c] + CAL_PER_CLASS]].sum()
            order = rng.permutation(CLEAN)
            n_clean = AUDITED - n_bug
            flags += clean_flag[order[:n_clean]].sum()
            cal_clean_pass = CAL_CLEAN - clean_flag[order[n_clean:n_clean + CAL_CLEAN]].sum()
            est = interval(rng, cal_caught, CAL_PER_CLASS, cal_clean_pass, flags, AUDITED)
            lo, mid, hi = est["pooled"]
            c_cover += lo <= share <= hi
            c_upper += share <= est["worst"][2]
            mids.append(mid)
        cover.append(c_cover / SPLITS)
        upper.append(c_upper / SPLITS)
    cover, upper = np.array(cover), np.array(upper)
    return {"pooled_cover_mean": float(cover.mean()), "pooled_cover_p05_across_banks": float(np.percentile(cover, 5)),
            "pooled_cover_p50_across_banks": float(np.percentile(cover, 50)),
            "pooled_bias": float(np.mean(mids) - share),
            "worst_upper_holds_mean": float(upper.mean()),
            "worst_upper_holds_p05_across_banks": float(np.percentile(upper, 5))}


def main():
    rng = np.random.default_rng(1115)
    rows = []
    for reviewer, se in REVIEWERS.items():
        for name, share, b09_share, extra in LEVELS:
            rows.append({"reviewer": reviewer, "mix": name, "share_buggy": share, "extra_b09": extra,
                         **one_level(rng, np.array(se), share, b09_share, extra)})
            print(rows[-1], flush=True)
    settings = {"draws": DRAWS, "banks": BANKS, "splits": SPLITS, "per_class": PER_CLASS, "clean": CLEAN,
                "cal_per_class": CAL_PER_CLASS, "cal_clean": CAL_CLEAN, "audited": AUDITED, "sp_true": SP,
                "reviewers": REVIEWERS}
    Path(__file__).with_suffix(".json").write_text(json.dumps({"settings": settings, "rows": rows}, indent=1),
                                                   encoding="utf-8")


if __name__ == "__main__":
    main()
