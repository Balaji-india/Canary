# Canary: a self-auditing AI scientist

Single source of truth for the project. Read it at the start of every session, together with `PROGRESS.md`.
Detailed design (maths, bug catalog, run types, research questions): `docs/DESIGN.md`. Read the relevant section
of it before working on a mission.

## 1. Context

- **Owner:** a student building this as a long-term research project (it started as an Agentic AI course idea).
  Goal: a mini AI scientist whose distinctive feature is that it **continuously measures how trustworthy its own
  reviewer is and acts on that measurement**, then grows toward a serious system that could become a workshop paper.
- **Schedule:** irregular. The student may skip days. Therefore work is split into **missions** of 60-120 minutes.
  Every mission must end with the project in a working state, tests passing, `PROGRESS.md` updated, and a git
  commit. Never leave a mission half-done without writing exactly where it stopped in `PROGRESS.md`.
- **Machine:** ASUS TUF Gaming A16, AMD Ryzen 7, NVIDIA RTX 4050 Laptop GPU (6 GB VRAM). Probably Windows.
  Use `pathlib`, `subprocess` with timeouts, and PowerShell-friendly instructions.
- **The student must be able to explain every part in a viva or paper review.** Prefer clear, small modules and
  docstrings that explain *why*.

## 2. The problem and the idea (in plain words)

AI scientists (Sakana's AI Scientist, Agent Laboratory, and newer systems) use an AI reviewer to catch their
mistakes, but they do not measure whether that reviewer works. Published audits show reviewers miss many planted
errors, and agents ship results even after noticing flaws.

Canary borrows **laboratory quality control**: it mixes known-buggy experiments (canaries), known-clean ones
(controls) and cosmetic-only ones (shams) into its research, blinded, so it always knows its reviewer's real
catch rate and false-alarm rate. From those it estimates how many of its *own* accepted findings are probably
buggy, gates what it accepts, watches for reviewer drift, finds the reviewer's blind spots, and hardens it.

## 3. What makes Canary unique (keep these central)

1. **Blinded positive controls, negative controls and shams inside the research loop**, not a one-off benchmark.
2. **Trust as numbers with uncertainty:** per-bug-class recall and specificity as Beta posteriors.
3. **Contamination estimate of the findings ledger:** the expected % of accepted findings that are buggy, with an
   interval (Rogan–Gladen prevalence + Bayes, Monte Carlo).
4. **Trust gate + control chart:** acceptance depends on measured trust; drift alarms (Westgard-style rules)
   tighten the gate and make the agent recalibrate.
5. **The agent decides when to stop doing science and re-check its checker** (budgeted campaign loop).
6. **Adaptive saboteur:** Thompson sampling plus LLM-written mutant bugs map the reviewer's blind spots;
   **self-hardening** adds checklist hints, evaluated on held-out canaries.
7. **Defense in depth, measured:** LLM reviewer vs deterministic tripwires vs a cross-family jury.
8. **Sealed pre-registration + hash-chained ledger + graveyard + calibration tracking** (Brier score, fed back to
   the Scientist).
9. **"Beat the Skeptic"** game: humans vs the AI reviewer on blinded runs (an interactive demo).

## 4. Tech stack (ask before adding anything)

- Python 3.11+, `scikit-learn`, `numpy`, `pandas`, `scipy`, `sqlite3`, `pyyaml`, `python-dotenv`,
  `sentence-transformers` (`all-MiniLM-L6-v2`), `matplotlib`, `streamlit`, `pytest`, `ollama` (Python client).
- **Local models via Ollama (defaults in `config/models.yaml`; verify tags with `ollama list`, then the fallbacks):**
  - Scientist: `qwen2.5-coder:7b` (fallback `qwen3:4b`)
  - Skeptic A: `gemma3:4b`, a different model family from the Scientist on purpose. It runs as the fallback:
    `models.yaml` still prefers `gemma4:e4b`, which must not be pulled here (6.13 GB will not fit in 6 GB VRAM)
  - Skeptic B (jury, Mission 5): `phi4-mini` (fallback `llama3.2:3b`)
- **Optional cloud Scientist** (`LLM_PROVIDER` + key in `.env`) only if the student asks. The Skeptic must always
  be a different model family from the Scientist.
- One LLM wrapper `canary/llm.py`: model per role, JSON-schema output, temperature 0.2 (0 for Skeptics), 2 retries,
  SQLite cache keyed by hash(model + prompt), and a **model-batching queue** (one model loaded at a time: 6 GB VRAM).
- Datasets: scikit-learn built-ins plus a few OpenML datasets cached locally on first use (`config/datasets.yaml`),
  including imbalanced ones (needed for bug class B06). Experiments must run offline once cached.

## 5. Architecture

```
                       ┌──────────────── Campaign agent (budgeted loop, trace) ────────────────┐
 research question ──▶ │ decide: do science │ recalibrate │ replicate │ harden │ stop          │
                       └───────┬───────────────────────────────────────────────────────────────┘
                               ▼
 Scientist ─▶ pre-registration (SHA-256 lock) ─▶ codegen from template ─▶ run mixer
                                                                        │ real / canary / control / sham
                                       Saboteur (10 bug classes, adaptive) ┘
                                                                        ▼
                                        sandbox run ─▶ blinding (ast.unparse) ─▶ Skeptic / jury / tripwires
                                                                        ▼
                     trust stats (Beta posteriors, Rogan–Gladen, contamination, control chart)
                                                                        ▼
                trust gate ─▶ accept │ escalate (tripwires → replication → human queue) │ graveyard
                                                                        ▼
                   hash-chained ledger ─▶ grounded report + Lab Monitor dashboard + Beat the Skeptic
```

### Module layout
```
canary/
  config.py llm.py prompts.py datasets.py
  templates/experiment.py.tmpl   codegen.py   sandbox.py
  scientist.py prereg.py ledger.py graveyard.py calibration.py
  saboteur/ classes.py transforms.py adaptive.py mutants.py
  controls.py blinding.py skeptic.py tripwires.py
  trust.py gate.py replicate.py campaign.py report.py cli.py
app/            Streamlit Lab Monitor (multi-page)
eval/           rq1.py … rq7.py, results/ (JSON), figures/
tests/          pytest, fast, no network, LLM mocked
config/         models.yaml datasets.yaml bug_classes.yaml campaign.yaml
data/           canary.db, cache/, runs/<run_id>/
docs/           DESIGN.md REPORT.md architecture.md VIVA_PREP.md DEMO_SCRIPT.md
```

## 6. Rules

- **Ground truth is sacred:** run types live in a sealed table; the Skeptic code path must never read it (add a
  test that fails if `skeptic.py` or `blinding.py` imports or queries it).
- **No LLM decides a verdict or a number.** LLMs propose and review; code computes verdicts, trust, gates, metrics.
- **No hand-typed numbers** in any report: all come from `eval/results/*.json` or the ledger.
- Tests never call the network or a real LLM (mock `llm.py`). Keep the suite under 30 s.
- Each mission: plan briefly → build → `pytest -q` → the mission's "done when" command → update `PROGRESS.md`
  → git commit "Mission X.Y: <summary>".
- Long LLM campaigns (many runs) go in the background with progress logged to `data/runs/campaign.log`; the
  student can resume them (`canary campaign --resume`).
- Ask before expensive or irreversible decisions; otherwise use sensible defaults and note them in `PROGRESS.md`.

## 7. Milestones and missions

Each mission says what to build and how to prove it works. Details in `docs/DESIGN.md` (section numbers in
brackets).

**M1 Foundations: the honest core loop**
- 1.1 Setup: venv, requirements, `.env.example`, `.gitignore`, git, configs, Ollama + model checks, dataset cache.
  *Done when:* `python -m canary.cli doctor` reports Python, models and datasets OK.
- 1.2 Template + codegen + sandbox [3]. *Done when:* `canary.cli run-config config/examples/baseline.yaml` writes a
  valid results.json; the crash is recorded for a deliberately broken config.
- 1.3 LLM wrapper with roles, JSON schema, cache, model queue. *Done when:* `canary.cli llm-smoke` gets valid JSON
  from every configured model.
- 1.4 Scientist + pre-registration lock + code-computed verdict + hash-chained ledger [11]. *Done when:*
  `canary.cli science --hypotheses 2` produces two locked, run, verdicted ledger entries; `canary.cli ledger
  verify` passes, and fails after a manual edit.
- 1.5 Blinding + Skeptic (single model) [5, 6]. *Done when:* every run in 1.4 has a Skeptic audit stored.

**M2 Controls and trust**
- 2.1 Saboteur: 10 bug classes × 2 tiers as transforms, each with a test proving the bug is present [4].
- 2.2 Controls and shams [1, 2]; the sealed run-type table; the blinding indistinguishability test.
- 2.3 Trust statistics: Beta posteriors per class, specificity, overall/worst recall [7].
- 2.4 Run mixer + `canary.cli calibrate --runs N` (canaries/controls/shams only) + `eval/rq1.py`. *Done when:* RQ1
  table and figure exist for Skeptic A.

**M3 Memory and calibration**
- 3.1 Graveyard with similarity check before proposing [11].
- 3.2 Brier score, reliability diagram, calibration feedback to the Scientist [11]; `eval/rq6.py` scaffold.

**M4 How much should we trust our findings?**
- 4.1 Rogan–Gladen prevalence + contamination with Monte Carlo intervals [7]; trust gate [8].
- 4.2 Hidden-truth validation campaign + `eval/rq4.py` (estimate vs truth at 3+ prevalence levels).
- 4.3 Control chart + drift alarms + gate tightening [9].
- 4.4 Campaign agent loop with decisions and trace [12]. *Done when:* a campaign trace shows the agent choosing to
  recalibrate at least once.

**M5 Defense in depth**
- 5.1 Tripwires for the classes in [6]. 5.2 Skeptic B + jury rules. 5.3 Replication gate [11].
- 5.4 `eval/rq2.py` (LLM vs tripwires vs jury vs union) and `eval/rq3.py` (gate ON vs OFF contamination).

**M6 Adaptive saboteur and self-hardening**
- 6.1 Thompson-sampling probes (never mixed into recall estimates) [10].
- 6.2 LLM mutants with oracle validation; mutant library.
- 6.3 Blind-spot map (class × tier × model heatmap).
- 6.4 Self-hardening hints with held-out evaluation + `eval/rq5.py`.

**M7 Lab Monitor and the game**
- 7.1 Streamlit pages: Overview (trust gauges, contamination banner), Control chart, Blind-spot map, Ledger (verify
  button), Graveyard, Calibration, Campaign trace, Escalation queue.
- 7.2 "Beat the Skeptic": 8 blinded runs; the human flags bug/clean + class; compare with the Skeptic;
  leaderboard; results feed `eval/rq7.py`.

**M8 Results and write-up**
- 8.1 Full evaluation runs (background, resumable) for RQ1-RQ7. 8.2 Figures.
- 8.3 `docs/REPORT.md` in paper style (abstract, related work, method, experiments, results, limitations), plus
  README, `docs/architecture.md` (Mermaid), `docs/DEMO_SCRIPT.md` (a 5-minute demo), `docs/VIVA_PREP.md`.
- 8.4 Re-check novelty on the web against the newest work and update Related Work.

**M9 Stretch (only after M8)**
- Novelty auditor (Semantic Scholar/arXiv search before accepting a hypothesis); more domains (small CNNs);
  cloud Scientist comparison; tree search over experiments with Canary auditing every branch.

**Minimum presentable version:** M1 + M2 + M4.1 + M7.1 (Overview only). If the student needs a demo early, steer
toward that first.

## 8. Slash-command prompting (the student's command vocabulary)

The student prompts with `/commands` from a cheat sheet. Treat them as precise instructions:

- **At the start of a message**, a `/command` runs its file in `.claude/commands/` (full procedure there).
- **Anywhere else in a message**, a `/word` is still an instruction: apply the meaning from the table below.
  Example: "explain the trust gate /simple /bullet /tldr" = explain it simply, as bullets, and end with a TL;DR.
- **Several commands combine.** Apply all of them; content commands (what to do) first, then format commands
  (how to present it). If two conflict (e.g. /shorten and /expand), ask which one wins.
- A `/word` that is not in the table: infer the intent from the word, follow it, and say in one line how you read it.
- When suggesting next steps, name the matching `/command` so the student learns the vocabulary.
- **Command coach (the student asked for reminders; they forget commands):** end every reply that finishes a step,
  answers a question or hits a problem with ONE line in this form:
  `💡 Next: /command <args> (why, in a few words)`. Pick the single most useful command for that moment, e.g.
  after a mission → `/summary` then `/clear`; after an error → `/solve`; after new code → `/explain <file>`;
  before a statistics mission → `/assumptions` or `/learn <concept>`; long campaign ahead → `/forecast`.
- A status-line tip bar and pop-up hooks also remind the student (`.claude/statusline.py`,
  `.claude/hooks/coach_hook.py`, `.claude/coach_state.py`, wired in `.claude/settings.json`). Keep them working;
  don't change them unless asked. When missions change, update the tips in `coach_state.py` to match.
- A few names are also **Claude Code built-ins** (marked ⚙). Typed at the start of a message they run the built-in;
  used mid-message, they mean what the table says.

| Command | Meaning in Canary |
|---|---|
| **Session** | |
| /project | First run: read everything, check the machine, run Mission 1.1 |
| /next [min] | Continue with the next unfinished mission (or a clean part that fits the time) |
| /where | Short recap after a break |
| /mission X.Y | Run one mission end to end (plan, build, test, prove, log, commit) |
| /priorities [time] | Re-plan for the time or deadline available |
| /new [task] | Save state, then start a fresh task (the student types ⚙ /clear) |
| **Start & create** | |
| /upload, /paste | Use the attached or pasted file/text as input for the current task |
| /scan [folder] | Map of the codebase: modules, links, tests, TODOs, dead code |
| /template | Scaffold a new module or bug class from the project patterns, with its test |
| ⚙ /import, ⚙ /voice | Built-ins (import settings from other tools; voice dictation). Mid-message, /import = read that file |
| **Focus & context** | |
| ⚙ /focus | Mid-message: answer only the exact question, nothing extra |
| ⚙ /context | Mid-message: take the background I give into account before answering |
| /details | Go deeper with exact names, numbers, edge cases, and an example |
| /examples | Make fixtures or worked examples |
| /clarify | Ask me up to 5 questions (with defaults) before building |
| /define [term] | One-paragraph definition plus a Canary example |
| /assumptions | List and verify hidden assumptions (statistical ones first) |
| /priorities | Rank what matters most given the time left |
| /constraints | Check against CLAUDE.md rules (sealed ground truth, no LLM verdicts, no hand-typed numbers) |
| **Think & solve** | |
| /analyze | Root-cause analysis before acting |
| /compare | Trade-off table, then one recommendation |
| /pros-cons | Pros, cons, verdict |
| /evaluate | Run the RQ evaluations and interpret them honestly |
| /recommend | One recommendation with reason, risk, and what would change it |
| /brainstorm | 8-10 ideas ranked by value and effort |
| /solve | Reproduce, root cause, failing test, fix, prove |
| /challenge | Attack the work like a strict paper reviewer |
| **Write & edit** | |
| /write | Draft report or README sections from real code and results |
| /edit | Change only what was asked |
| /rewrite | Same facts, clearer |
| /shorten | About half the length, every key fact kept |
| /expand | Add explanation, an example, reasoning |
| /improve | Better quality (docs: clarity; code: readability, tests still pass) |
| /summarize | 5-8 bullet summary |
| /paraphrase | Same meaning, new wording |
| /proofread | Language fixes plus fact-check against code and results |
| **Organize & structure** | |
| /outline, /structure | Outline or structure first; wait for OK |
| /bullet, /numbered, /table | Present the answer as bullets / numbered steps / a table |
| /summary | Update PROGRESS.md and show the next 3 actions |
| /key-points | At most 5 one-line key points |
| /mindmap, /flowchart | Mermaid mind map / architecture diagram from the real code |
| /tldr | At most 5 bullets, plain words (as a format modifier: end the answer with a TL;DR line) |
| **Code & tech** | |
| /code | Plan, implement, test, verify one feature |
| ⚙ /debug | Mid-message: same as /solve (the built-in debugs Claude Code itself) |
| /explain | Explain simply, with a small worked example (viva prep) |
| /optimize | Measure, speed up, measure again |
| /refactor | Clearer code, same behaviour, tests before and after |
| /test | Write and run tests (statistics checked against hand-computed values) |
| /convert | Convert code/data, with a check that nothing changed |
| /documentation | Docstrings and README sections |
| ⚙ /review | Built-in code review of recent changes |
| **Data & analysis** | |
| /analyze-data | Quality check of runs, ledger and campaign data |
| /visualize | Paper-quality charts with uncertainty |
| ⚙ /insights, ⚙ /stats | Built-ins about Claude usage. Mid-message: give the key statistics of the results |
| /forecast | Time estimate from measured numbers, as a range |
| /report | Results section from result files |
| /clean | Safe cleanup (never the ledger, results or sealed table); ask first |
| **Automate & integrate** | |
| /workflow, /automate | Repeatable workflow / a script for a recurring task |
| /api, /integrate | Add a model or provider through the single wrapper / connect two parts cleanly |
| ⚙ /schedule | Built-in cloud routines. Mid-message: suggest when to run long campaigns |
| /trigger | Run something on an event (e.g. a git hook for tests) |
| /toolkit | The commands and scripts for a job, in order of use |
| /checklist | Verify a milestone or the minimum presentable version, with evidence |
| **Personalize & control** | |
| /preferences | Save a working preference at the end of CLAUDE.md |
| /tone, /style, /length, /format | Set tone / explanation style / answer length / output format for this session |
| /reset | Back to default tone, style, length, format |
| ⚙ /memory, ⚙ /clear | Built-ins: edit CLAUDE.md; empty the conversation |
| **Learn & research** | |
| /search | Web search, 3-5 sources, answer with links |
| /research | Check current docs or papers before building |
| /learn | Beginner lesson with analogy, worked example, self-test |
| /resources | 5-8 best learning resources with links |
| /novelty | Re-check related work on the web; update Related Work |
| /viva | Likely examiner questions with answers from the real code |
| **Collaborate & share** | |
| /share | Make something self-contained and secret-free for sharing |
| /present | Slide outline (8-12 slides) with figures |
| /download | Package outputs into `dist/<date>/` and zip |
| /email | Draft an email (never send) |
| ⚙ /copy, ⚙ /export | Built-ins: copy the last answer; export the conversation |
| /demo | 5-minute demo script, dry-run tested |
| **Canary research operations** | |
| /campaign | Run or resume a campaign and interpret it |
| /blindspots | The reviewer's blind spots with examples and hardening ideas |

Power habits from the cheat sheet, applied here: combine commands for better results; give context early (paste
errors and files); be specific; iterate (/improve, /challenge); and save what works (/preferences, /workflow).
