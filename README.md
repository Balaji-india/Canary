# 🐤 Canary

### An AI scientist that keeps checking whether its own reviewer can be trusted

> *Coal miners took a canary into the mine. While it sang, the air was safe. When it went quiet, everyone got out.*
>
> Canary puts its own canaries into the research loop.

**Status (2026-11-10):** Milestones M1–M2 are complete. None of the local reviewers tested so far can be trusted.
**`llama3.1:8b` is not confirmed for use:** with no size cue left, its development AUC was weak (0.643, base 90%
[0.487, 0.778]), and confirming it would need about 400 runs, so the confirmation was stopped and never run. Next: a
cloud ceiling check (is the review task solvable at all?), then Mission 5.1 (deterministic tripwires).

---

## The problem

AI scientists are arriving. Systems like Sakana's *AI Scientist* and *Agent Laboratory* propose hypotheses, write
the experiment code, run it and write up the results. To keep themselves honest, they hand their work to an **AI
reviewer** that is supposed to catch mistakes.

These systems rarely check whether that reviewer actually catches anything. It is like a laboratory that never runs
a positive control, or a smoke detector nobody has tested. Published audits suggest reviewers miss many planted
errors, and agents ship results even after they notice a flaw.

## The idea

Clinical laboratories solved this long ago with **quality control**: alongside the real samples, they run samples
whose answer is already known. If the machine gets those wrong, nobody trusts its other answers.

Canary mixes three kinds of known runs in with its real experiments, and the reviewer cannot tell which is which:

| Run type | What it is | What it measures |
|---|---|---|
| 🐤 **Canary** | A real experiment with a known bug planted in it | **Recall:** does the reviewer catch real bugs? |
| ✅ **Control** | A clean experiment, known to be correct | **Specificity:** does it stay quiet when nothing is wrong? |
| 🎭 **Sham** | A clean experiment with cosmetic edits only (renamed variables, reordered imports) | Does it react to *surface* changes instead of real bugs? |

Every script is normalised (`ast.unparse`) before the reviewer sees it, so formatting gives nothing away. Which run is
which lives in a **sealed table**; the reviewer's code may not read it, and a test fails if it ever does. So Canary
always knows its reviewer's real catch rate and false-alarm rate, with uncertainty (Beta posteriors per bug class).
The goal is an estimate AI scientists do not usually give:

> **"Of the findings I have accepted, about X% are probably wrong, with a 90% interval of [a, b]."**

## The bugs the canaries carry

Ten classes of mistake that make machine-learning results look better than they are, each in an *obvious* and a
*subtle* form (20 variants). Each variant has an **oracle**, a check that watches the running script and proves the
bug really happens. A separate impact check measures whether it also moves the numbers; a few do not.

| | Bug class | Example of the subtle form |
|---|---|---|
| B01 | Preprocessing leakage | Scaler fitted on train and test rows together, inside a helper |
| B02 | Target leakage | A noisy copy of the label hidden under an innocent feature name |
| B03 | Evaluating on training data | The test set quietly replaced by a slice of the training data |
| B04 | Tuning on the test set | Trying several settings and keeping the one with the best test score |
| B05 | Seed cherry-picking | Replacing the worst seeds' scores with the mean of the better ones |
| B06 | Metric misuse | Reporting whichever F1 averaging (binary or macro) looks better |
| B07 | Duplicates across the split | Noisy copies of rows added before the split |
| B08 | Label misalignment | `y_test` shifted by one row after a sort |
| B09 | Weak baseline | The mildest bad setting that still drags the baseline down |
| B10 | Easy test subset | Dropping the test rows the model got most confidently wrong |

## How it works

```mermaid
flowchart LR
    S[🧑‍🔬 Scientist LLM<br/>proposes a hypothesis] --> P[🔒 Pre-registration<br/>SHA-256 locked]
    P --> C[Code generated<br/>from a template]
    C --> M{Run mixer}
    SB[😈 Saboteur<br/>10 bug classes] --> M
    M -->|real · canary · control · sham| X[Sandboxed run]
    X --> B[🙈 Blinding]
    B --> K[🧐 Skeptic LLM<br/>reviews the script]
    K --> T[📊 Trust statistics<br/>Beta posteriors]
    T --> G{Trust gate}
    G -->|accept| L[⛓️ Hash-chained ledger]
    G -->|reject| GY[🪦 Graveyard]
```

<sub>Built so far: everything up to the trust statistics, and the ledger. The trust gate is Mission 4; today the
graveyard only receives crashed runs.</sub>

Rules built into the design:

- **No LLM decides a verdict or a number.** LLMs propose and review; plain code computes every verdict and statistic.
- **Hypotheses are locked before they run.** The prediction is hashed first, so it cannot be rewritten afterwards.
- **The findings ledger is hash-chained.** If anyone edits a past entry, `ledger verify` fails.
- **The Scientist and the Skeptic come from different model families,** so they do not share the same blind spots.
- **Everything runs locally** on a 6 GB laptop GPU through Ollama. No API keys, and no data leaves the machine.

## First finding: the canary went quiet

The first full calibration batch gave two small local reviewers 100 canaries, 40 controls and 40 shams, all blinded.
Both flagged nearly everything, clean runs included:

| Reviewer | Bugs caught | Clean runs correctly passed | Youden's J, observed (90% interval) |
|---|---|---|---|
| Skeptic A · `gemma3:4b` | 100 of 100 | **0 of 80** | 0.000 [−0.021, +0.029] |
| Skeptic B · `phi4-mini` | 97 of 100 | **5 of 80** | +0.032 [−0.020, +0.093] |

<sub>Source: `eval/results/rq1_comparison.json`. J = recall + specificity − 1: 0 is chance, 1 is perfect.</sub>

Read only the first column and the reviewers catch every bug. Against known-clean runs, they **do no better than
chance**: they say "buggy" to everything. Skeptic A named the same class (B01) every time, and shuffling the class
list showed it prefers B01 itself, not whatever is listed first (`eval/results/position_bias_skeptic_a.json`). Canary
measured this from its own data instead of assuming the reviewer works.

<p align="center">
  <img src="eval/figures/rq1_recall.png" width="48%" alt="Per-class recall of Skeptic A">
  <img src="eval/figures/rq1_specificity.png" width="48%" alt="Specificity of Skeptic A on controls and shams">
</p>

## Second finding: our own test had a cue, and we removed it

**Screen (task-dev-1, 40 runs).** Three reviewers (gemma3:4b, phi4-mini, llama3.1:8b) × three ways of asking
(original, quote-the-line, per-class checklist). **No combination passed** the screen's rule: the lower end of J's 90%
interval above 0. Ranking runs by the reviewer's own token probability, llama's checklist score looked promising: AUC 0.735
[0.58, 0.86]. But a trivial rule, **counting the script's lines**, scored 0.850 [0.75, 0.94]. Bugs are code, so planting
one adds lines. <sub>(`eval/results/task_dev_1/compare_tasks.json`; intervals resample whole experiments.)</sub>

**Fix 1, length matching.** Every script gets a never-used helper that pads it to one fixed length. That moved the
cue instead of removing it: a bug's lines take the place of helper lines, so the helper's size alone separated the
run types (AUC 0.150, i.e. 0.85 with direction ignored).

**Fix 2, decoys.** Each clean run now also gets a harmless copy of one bug's edit, in the same place and of the same
size, in the same proportions as the canaries. Decoys are tested to give exactly the clean numbers. A dry run of the
100-run plan on the first pool of experiments:

| Trivial feature | Padding only | Padding + decoys |
|---|---|---|
| Helper size (statements) | 0.150 [0.096, 0.205] | 0.500 [0.444, 0.558] |
| Statement count | 0.450 [0.420, 0.480] | 0.500 [0.456, 0.544] |
| Line and character count | 0.500 (constant) | 0.500 (constant) |

<sub>AUC, base-level 90% interval; 0.5 means no clue. Source: `eval/results/padding_v2/dry_proof.json`, which also
holds the 40-run plan and the helper's size in characters (both pass). Effect spread, which padding cannot change,
is 0.521 [0.469, 0.567] on existing runs. One cue remains: bugs really inflate the best arm's score (0.591
[0.541, 0.650]); a reviewer may notice that legitimately.</sub>

**What happens next.** The llama confirmation (`docs/plans/llama_checklist_confirmation_v2.md`) was stopped
before it ran: on task-dev-2 (40 runs, decoys, every size feature at 0.5) llama's AUC was 0.643, base 90% [0.487,
0.778], and a simulation of the plan's own analysis gave about 400 runs for 80% power at that level
(`eval/results/task_dev_2/dev_report.json`, `eval/results/confirm_llama_2/power_sim.json`). Next is a cloud ceiling
check on the same 40 runs (`docs/plans/cloud_ceiling_check_outline.md`, outline only): if a strong cloud reviewer
clearly beats llama, the task is solvable and a search for the cheapest model that clears the bar follows, each
candidate on its own fresh batch. Mission 5.1 (tripwires) comes next either way. The rule stays: every change to the
reviewer is chosen on development data and judged only on a batch it has never seen.

## Try it

Needs Python 3.11+ and [Ollama](https://ollama.com). Developed on Windows with an RTX 4050 (6 GB).

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

ollama pull qwen2.5-coder:7b   # Scientist (fallback qwen3:4b)
ollama pull gemma3:4b          # Skeptic A
ollama pull phi4-mini          # Skeptic B
ollama pull llama3.1:8b        # third reviewer, not confirmed for use (optional; heavy on RAM, close other apps)

python -m canary.cli doctor            # checks Python, packages, models, datasets
python -m canary.cli cache-datasets    # one-time download; offline afterwards
```

Then:

```powershell
python -m canary.cli run-config config/examples/baseline.yaml   # one experiment, end to end
python -m canary.cli science --hypotheses 2                      # propose, lock, run and judge
python -m canary.cli audit                                       # blinded Skeptic review
python -m canary.cli ledger verify                               # check the hash chain
python -m canary.cli calibrate --runs 30 --batch my-batch        # canaries + controls + shams, padded, with decoys
python -m canary.cli trust --batch my-batch                      # the reviewer's measured trust
python -m canary.cli reaudit --batch my-batch --role skeptic_b   # a second reviewer, same runs
python -m eval.rq1 --batch my-batch                              # RQ1 table and figures
```

Tests: `pytest -q` (fast, no network, LLMs mocked). `pytest -m slow` runs the slower end-to-end tests.

## Repository map

```
canary/      the system: scientist, prereg, ledger, saboteur/ (bugs, decoys), controls, padding, blinding, skeptic,
             trust, mixer, sandbox, llm
config/      models, datasets, bug classes, example experiment configs
eval/        research-question scripts, results/ (JSON) and figures/
tests/       pytest suite
docs/        DESIGN.md (design, maths, bug catalogue) and plans/ (pre-registrations, locked by SHA-256)
```

`PROGRESS.md` is the lab notebook: every mission, the command that proved it worked, and an honest list of known issues.

## Scope

**Done:** M1–M2, the honest core loop, the saboteur, controls and shams, trust statistics and the first reviewer
study. Then the review-task screen, length matching plus decoys, and task-dev-2 (llama not confirmed for use; its
confirmation stopped on power grounds). **Now:** a cloud ceiling check, to learn whether any reviewer can do this
task, then Mission 5.1 (tripwires).

| Milestone | What it adds |
|---|---|
| **M3 Memory and calibration** | A graveyard of failed ideas checked before new proposals; Brier scores fed back to the Scientist. |
| **M4 How much should we trust our findings?** | Rogan–Gladen **contamination estimate** of the ledger, a **trust gate**, a Westgard-style control chart for drift, and a **campaign agent** that decides when to re-check its checker. |
| **M5 Defense in depth** | Deterministic tripwires, a cross-family **jury** and a replication gate, measured head to head. |
| **M6 Adaptive saboteur** | **Thompson-sampling** probes for blind spots, LLM-written mutant bugs checked by oracles, and **self-hardening** judged on held-out canaries. |
| **M7 Lab Monitor** | A Streamlit dashboard, plus **"Beat the Skeptic"**: humans against the AI reviewer on blinded runs. |
| **M8 Write-up** | Full evaluation of seven research questions and a paper-style report. |

### The research questions

1. **RQ1:** How well does an AI reviewer catch planted bugs, per class, and how often does it raise false alarms? *(first answers above)*
2. **RQ2:** Do tripwires and a multi-model jury catch what a single LLM misses?
3. **RQ3:** Does a trust gate reduce the share of wrong findings that get accepted?
4. **RQ4:** Is the contamination estimate accurate when the true answer is known?
5. **RQ5:** Does self-hardening improve recall on bugs the reviewer has never seen?
6. **RQ6:** Is the Scientist well calibrated, and does feedback improve it?
7. **RQ7:** Who reviews better, humans or the AI Skeptic?

### The long-term goal

If AI systems are going to produce science, "the reviewer said it's fine" cannot be the standard. The aim is for
every AI-generated finding to come with a **measured error rate for its own quality control**, as clinical lab
results do. Canary is a small, local, reproducible prototype of that idea, growing toward a workshop paper.

---

<sub>Built as a student research project. Design details are in [`docs/DESIGN.md`](docs/DESIGN.md).</sub>
