"""Cue-sensitivity probe: does llama-checklist's P(flag) move with the size of the padding helper, on clean code?

Why: length matching (canary/padding.py) makes every script in a batch the same length, but a canary's bug lines take
the place of helper lines, so canaries carry a smaller `describe_settings` helper (on the pool-1 dry run every clean run
gets 21 statements, B10 subtle gets 6; helper-size AUC 0.15). If the reviewer's score reacts to the helper's size, it
could look like it finds bugs while it only reacts to padding.

How: about 20 existing pool-1 controls (clean, already run, so no experiment runs here). Each is padded twice, with
the same code otherwise: "large" = the helper a clean run gets under the pool-1 batch target, "small" = the smallest
helper any run of the pool-1 dry plan gets. Both versions are blinded with the run's own results and pre-registration
and scored by the confirmation's reviewer role. The paired difference P(flag | small) - P(flag | large) is averaged
over controls, with a base-level 90% interval.

Rule, pre-registered in docs/plans/llama_checklist_confirmation.md (section 4a), decided by code:
- fewer than MIN_PAIRS controls scored in both versions, or any prompt too large: INCONCLUSIVE, stop;
- the 90% interval of the mean difference excludes 0 (either direction): CUE_LIVE, stop and redesign the padding;
- otherwise: NO_DETECTED_SENSITIVITY, the batch may go ahead.

Limit: on identical clean code the small version is also shorter in total, so the probe cannot separate "reacts to
helper size" from "reacts to script length". Either reaction would make the batch's helper-size difference a possible
cue, which is why either direction stops the batch.

Nothing here writes to the ledger, the sealed table or the LLM cache: probe runs can never enter a recall,
specificity or AUC estimate. Records go to eval/results/confirm_llama_1/cue_probe.jsonl (resumable) and the result to
cue_probe.json. Run with `python -m eval.cue_probe --dry` first (no model), then `python -m eval.cue_probe`.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from canary import blinding, config, ledger, llm, mixer, padding, prereg, review_tasks, sandbox, sealed, separation, skeptic
from canary.codegen import SCRIPT_NAME
from eval import compare_tasks
from eval.confirm import ROLE

PROBE_RUNS = 20
PROBE_SEED = 1109  # the confirmation plan's seed; also seeds the pool-1 dry plan that gives the helper sizes
PLAN_RUNS = 100
SOURCE_BATCHES = ("rq1-full", "task-dev-1")  # pool-1 calibration batches whose controls ran cleanly
MIN_PAIRS = 15
STOP_AFTER = 3  # server failures in a row, as in the batch's stop rule
SMALL, LARGE = "small", "large"
OUT_DIR = compare_tasks.RESULTS_DIR / "confirm_llama_1"
RECORDS_PATH = OUT_DIR / "cue_probe.jsonl"
RESULT_PATH = OUT_DIR / "cue_probe.json"
CUE_LIVE, NO_SENSITIVITY, INCONCLUSIVE = "CUE_LIVE", "NO_DETECTED_SENSITIVITY", "INCONCLUSIVE"


def helper_sizes(pool: dict) -> dict:
    """The pool-1 batch target and the smallest helper any run of the pool-1 dry plan gets (no run types kept)."""
    plan = mixer.plan_batch("cue-probe", PLAN_RUNS, pool, PROBE_SEED)
    counts = [r["helper_statements"] for r in mixer.dry_rows(plan)]
    return {"target": plan["length_target"], "small_statements": min(counts), "largest_statements": max(counts)}


def pad_to_statements(script: str, statements: int, rng: random.Random) -> padding.Padded:
    """Pad with exactly `statements` helper statements, aiming at the statements' average length.

    The batch always pads to one fixed total; here the total follows from the helper's size, since that is the
    only thing the probe varies.
    """
    bare_lines, bare_chars = padding.length(padding._with_helper(script, []))
    mean_chars = statistics.mean(padding._statement_chars())
    target = padding.Target(bare_lines + statements, bare_chars + round(statements * mean_chars))
    return padding.pad_script(script, target, rng)


def select_controls(table: sealed.SealedTable, led: ledger.Ledger, n: int = PROBE_RUNS, seed: int = PROBE_SEED,
                    batches: tuple[str, ...] = SOURCE_BATCHES) -> list[sealed.Truth]:
    """n controls that ran cleanly, spread over as many bases as possible: one per base in turn, seeded order."""
    ok = {e.payload["run_id"] for e in led.entries(ledger.RAN) if e.payload.get("run_status") == sandbox.STATUS_OK}
    candidates = sorted((t for t in table.all() if t.run_type == sealed.CONTROL and t.run_id in ok
                         and t.details.get("batch") in batches), key=lambda t: t.run_id)
    rng = random.Random(seed)
    rng.shuffle(candidates)
    by_base: dict[str, list[sealed.Truth]] = {}
    for t in candidates:
        by_base.setdefault(t.source or t.run_id, []).append(t)
    bases = sorted(by_base)
    rng.shuffle(bases)
    picked: list[sealed.Truth] = []
    while len(picked) < n and any(by_base.values()):
        for base in bases:
            if by_base[base] and len(picked) < n:
                picked.append(by_base[base].pop(0))
    return picked


def build_jobs(controls: list[sealed.Truth], led: ledger.Ledger, sizes: dict,
               runs_dir: Path = sandbox.RUNS_DIR) -> list[dict]:
    """Two blinded versions per control, in a seeded order. Files are checked against their ledger hashes first."""
    locks = {e.hypothesis_id: e.payload for e in led.entries(ledger.PREREGISTERED)}
    ran = {e.payload["run_id"]: e for e in led.entries(ledger.RAN) if "run_id" in e.payload}
    target = padding.Target(sizes["target"]["lines"], sizes["target"]["chars"])
    rng = random.Random(f"{PROBE_SEED}:order")
    jobs = []
    for truth in controls:
        entry = ran[truth.run_id]
        lock = locks[entry.hypothesis_id]
        skeptic._prepare(entry, lock, runs_dir)  # raises ValueError if the script, results or lock were edited
        run_dir = runs_dir / truth.run_id
        script = (run_dir / SCRIPT_NAME).read_text(encoding="utf-8")
        results = json.loads((run_dir / sandbox.RESULTS_NAME).read_text(encoding="utf-8"))
        versions = {
            LARGE: padding.pad_script(script, target, random.Random(f"{PROBE_SEED}:{truth.run_id}:{LARGE}")),
            SMALL: pad_to_statements(script, sizes["small_statements"],
                                     random.Random(f"{PROBE_SEED}:{truth.run_id}:{SMALL}")),
        }
        order = [SMALL, LARGE] if rng.random() < 0.5 else [LARGE, SMALL]
        for size in order:
            padded = versions[size]
            blinded = blinding.blind_run(padded.script, results, lock["prereg"])
            jobs.append({"run_id": truth.run_id, "base": truth.source or truth.run_id, "size": size,
                         "statements": padded.statements, "line_count": len(blinded.script.splitlines()),
                         "char_count": len(blinded.script), "blinded": blinded})
    return jobs


def ask(client, role: str, job: dict) -> dict:
    """One review of one version. Returns the record to store; raises llm.LLMError only for server failures."""
    task = skeptic.task_of(client.cfg, role)
    bugs = config.load_yaml("bug_classes.yaml")
    system, prompt, schema = review_tasks.build(task, job["blinded"], bugs, None)
    record = {k: job[k] for k in ("run_id", "base", "size", "statements", "line_count", "char_count")}
    record.update({"role": role, "task": task, "prompt_sha256": prereg.sha256_text(prompt)})
    top = client.cfg["llm"].get("review_top_logprobs") or review_tasks.TOP_LOGPROBS
    try:
        result = client.call(role, prompt, schema, system=system, top_logprobs=top, cache_write=False)
    except llm.LLMError as exc:
        if exc.kind == llm.KIND_TIMEOUT_OR_SERVER:
            raise
        return {**record, "outcome": exc.kind, "detail": str(exc)}
    score = review_tasks.score(task, result.logprobs, sorted(bugs))
    decision = review_tasks.decide(task, result.data, job["blinded"])
    return {**record, "outcome": "scored" if score else "unscored", "p_flag": score["p_flag"] if score else None,
            "verdict": decision["verdict"], "model": result.model, "seconds": round(result.seconds, 3)}


def read_records(path: Path = RECORDS_PATH) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(client, role: str, jobs: list[dict], path: Path = RECORDS_PATH, stop_after: int = STOP_AFTER,
        echo=print) -> str | None:
    """Ask every job not yet recorded, appending each record as it comes. Returns why it stopped early, or None."""
    done = {(r["run_id"], r["size"]) for r in read_records(path)}
    todo = [j for j in jobs if (j["run_id"], j["size"]) not in done]
    path.parent.mkdir(parents=True, exist_ok=True)
    started, failures = time.perf_counter(), 0
    for number, job in enumerate(todo, 1):
        try:
            record = ask(client, role, job)
        except llm.LLMError as exc:
            failures += 1
            echo(f"probe {number}/{len(todo)}: server failure ({exc}); not stored, a re-run retries it")
            if failures >= stop_after:
                return f"{failures} server failures in a row"
            continue
        failures = 0
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        p = "n/a" if record.get("p_flag") is None else f"{record['p_flag']:.3f}"
        echo(f"probe {number}/{len(todo)}: {job['size']:5s} helper {job['statements']:2d} -> P(flag) {p} "
             f"({record['outcome']}) [{time.perf_counter() - started:.0f} s so far]")
    return None


def _mean(values, _unused=None) -> float | None:
    return float(np.mean(values)) if len(values) else None


def analyse(records: list[dict], min_pairs: int = MIN_PAIRS) -> dict:
    """The pre-registered rule on stored records. Pure: the same records always give the same answer."""
    latest = {(r["run_id"], r["size"]): r for r in records}  # one record per version; a later one replaces it
    runs = sorted({run for run, _ in latest})
    pairs = []
    for run_id in runs:
        small, large = latest.get((run_id, SMALL)), latest.get((run_id, LARGE))
        if small and large and small.get("p_flag") is not None and large.get("p_flag") is not None:
            pairs.append({"run_id": run_id, "base": small["base"], "small": small["p_flag"], "large": large["p_flag"],
                          "difference": small["p_flag"] - large["p_flag"],
                          "verdict_flip": small.get("verdict") != large.get("verdict")})
    too_large = sum(r["outcome"] == llm.KIND_PROMPT_TOO_LARGE for r in latest.values())
    differences = [p["difference"] for p in pairs]
    interval = separation.base_bootstrap([(p["base"], True, p["difference"]) for p in pairs], _mean) if pairs else None
    if too_large or len(pairs) < min_pairs or interval is None:
        decision = INCONCLUSIVE
    elif interval[0] > 0 or interval[1] < 0:
        decision = CUE_LIVE
    else:
        decision = NO_SENSITIVITY
    return {
        "rule": f"mean of P(flag | small helper) - P(flag | large helper); base-level 90% interval excludes 0 -> "
                f"{CUE_LIVE}; fewer than {min_pairs} scored pairs or any prompt too large -> {INCONCLUSIVE}",
        "decision": decision, "batch_may_run": decision == NO_SENSITIVITY,
        "pairs": len(pairs), "bases": len({p["base"] for p in pairs}), "prompts_too_large": too_large,
        "versions_recorded": len(latest), "versions_unscored": sum(r.get("p_flag") is None for r in latest.values()),
        "mean_difference": _mean(differences), "interval_90_base": interval,
        "mean_p_flag": {SMALL: _mean([p["small"] for p in pairs]), LARGE: _mean([p["large"] for p in pairs])},
        "small_higher": sum(d > 0 for d in differences), "large_higher": sum(d < 0 for d in differences),
        "verdict_flips": sum(p["verdict_flip"] for p in pairs), "per_control": pairs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry", action="store_true", help="build and size-check every prompt; no model is called")
    args = parser.parse_args(argv)
    led, table = ledger.Ledger(), sealed.SealedTable()
    client = llm.LLM()
    sizes = helper_sizes(json.loads(mixer.POOL_PATH.read_text(encoding="utf-8")))
    controls = select_controls(table, led)
    jobs = build_jobs(controls, led, sizes)
    print(f"Cue probe: {len(controls)} pool-1 controls on {len({c.source for c in controls})} bases, "
          f"helper {sizes['small_statements']} vs the clean size under target {sizes['target']}; "
          f"{len(jobs)} reviews by {ROLE}.")
    if args.dry:
        task, bugs = skeptic.task_of(client.cfg, ROLE), config.load_yaml("bug_classes.yaml")
        too_large = 0
        for job in jobs:
            system, prompt, _ = review_tasks.build(task, job["blinded"], bugs, None)
            try:
                client._check_prompt_size(prompt, system, client.num_ctx(ROLE))
            except llm.LLMError:
                too_large += 1
        by_size = {s: sorted({(j["statements"], j["line_count"]) for j in jobs if j["size"] == s}) for s in (SMALL, LARGE)}
        print(f"  (statements, blinded lines) small: {by_size[SMALL]}; large: {by_size[LARGE]}")
        print(f"  prompts too large for {ROLE}: {too_large} of {len(jobs)}. "
              f"Already recorded: {len(read_records())}. Dry run: no model was called.")
        return 1 if too_large else 0
    stopped = run(client, ROLE, jobs)
    client.release()
    if stopped:
        print(f"STOPPED: {stopped}. Run the same command again to continue.")
        return 1
    result = {**analyse(read_records()), "role": ROLE, "sizes": sizes, "controls": [c.run_id for c in controls],
              "generated_at": datetime.now(timezone.utc).isoformat()}
    RESULT_PATH.write_text(json.dumps(result, indent=1), encoding="utf-8")
    iv = result["interval_90_base"]
    print(f"Cue probe: {result['pairs']} pairs on {result['bases']} bases. Mean P(flag) small "
          f"{result['mean_p_flag'][SMALL]:.3f}, large {result['mean_p_flag'][LARGE]:.3f}; difference "
          f"{result['mean_difference']:+.3f}, base 90% [{iv[0]:+.3f}, {iv[1]:+.3f}]" if iv else
          f"Cue probe: {result['pairs']} pairs, too few to measure.")
    print(f"  Decision: {result['decision']}. "
          + ("The confirmation batch may run." if result["batch_may_run"]
             else "Do not run the confirmation batch; report and propose a padding redesign."))
    print(f"Wrote {RESULT_PATH}")
    return 0 if result["batch_may_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
