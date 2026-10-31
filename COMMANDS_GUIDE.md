# Canary commands guide

Project commands live in `.claude/commands/` and were written for Canary (several are based on the "Claude
Command" cheat sheet, made real). Built-in commands come with Claude Code; type `/` to see what your version has.
Typed at the **start** of a message, a command runs its procedure file; the text after it is its argument.

**The full cheat-sheet vocabulary is written into `CLAUDE.md` section 8**, so Claude Code also understands
`/commands` in the middle of a message and several combined, for example:
`explain canary/trust.py /simple /bullet /tldr` or `/campaign --runs 60 /forecast`.
All 81 commands have files in `.claude/commands/`; the extra ones not listed below are the cheat sheet's
writing and format helpers (/edit, /rewrite, /shorten, /expand, /improve, /summarize, /paraphrase, /structure,
/bullet, /numbered, /table, /key-points, /mindmap, /details, /define, /recommend, /new, /upload, /paste, /scan,
/convert, /forecast, /clean, /workflow, /automate, /integrate, /trigger, /toolkit, /preferences, /tone, /style,
/length, /format, /reset, /search, /resources, /share, /present, /download, /email, /template).

## Session control (made for an irregular schedule)
| Command | What it does |
|---|---|
| `/project` | First run: reads everything, checks the machine, explains the project back, runs Mission 1.1 |
| `/next [minutes]` | Continues with the next unfinished mission (or a clean part of it that fits your time) |
| `/where` | 8-line recap after a break: what works, what's half-done, what's next |
| `/mission X.Y` | Runs one mission end to end: plan → build → test → prove → log → commit |
| `/priorities <time>` | Re-plans for your time or deadline (steers to the minimum presentable version) |
| `/summary` | Updates PROGRESS.md and shows the next 3 actions |

## Research operations
| Command | What it does |
|---|---|
| `/campaign [options]` | Runs or resumes a research campaign in the background and interprets it |
| `/blindspots [model]` | Miss rates by bug class × tier × model, with examples and hardening ideas |
| `/evaluate [rq]` | Runs the research-question evaluations (RQ1-RQ7) and explains the results honestly |
| `/analyze-data` | Data-quality check of runs, ledger and campaigns |
| `/visualize` | Paper-quality charts with uncertainty |
| `/report` | Results section of the report from result files |
| `/novelty` | Re-checks the web for new related work and updates Related Work |

## Think & solve
| Command | Cheat-sheet equivalent | What it does |
|---|---|---|
| `/analyze` | /analyze | Root-cause analysis before acting |
| `/compare` | /compare, /recommend | Trade-off table and one recommendation |
| `/pros-cons` | /pros-cons | Quick verdict on one approach |
| `/brainstorm` | /brainstorm | Ideas ranked by value and effort |
| `/solve` | /solve, /debug | Reproduce → root cause → failing test → fix (the built-in `/debug` debugs Claude Code itself) |
| `/challenge` | /challenge | Attacks the design like a tough paper reviewer |
| `/clarify` | /clarify | Claude asks you questions before building |
| `/assumptions` | /assumptions | Hidden assumptions, especially statistical ones |
| `/constraints` | /constraints | Audits the code against the project rules (including ground-truth sealing) |
| `/examples` | /examples | Test fixtures and sample runs |

## Code & tech
| Command | What it does |
|---|---|
| `/code <feature>` | Plan → implement → test → verify |
| `/test <module>` | Tests, including statistics checked against hand-computed values |
| `/refactor`, `/optimize`, `/documentation` | Cleaner code, measured speed-ups, docstrings |
| `/api <provider or model>` | Adds or switches a model through the single LLM wrapper |
| Built-in `/review`, `/simplify` | Code review and cleanup of recent changes |

## Write, learn & present
| Command | What it does |
|---|---|
| `/write <section>` | Report or README sections from real code and results |
| `/proofread <file>` | Language fixes plus fact-checks against code and results |
| `/outline`, `/flowchart` | Outline first; Mermaid architecture diagram |
| `/explain <file>` | Simple explanation of a file or statistic |
| `/learn <concept>` | Beginner lesson with a worked example and self-test |
| `/tldr` | 5-bullet summary of a file or diff |
| `/viva` | 20 likely questions with answers from your code and results |
| `/demo` | 5-minute demo script, dry-run tested |
| `/research <topic>` | Checks current docs or papers before building |

## Useful built-ins
| Built-in | Use it for |
|---|---|
| `/clear` | Start each session fresh (PROGRESS.md carries the memory) |
| `/compact <what to keep>` | Shrink a long session without losing the thread |
| `/context` | See how full the context is |
| `/rewind` | Undo Claude's last changes (code and conversation) |
| `/plan` or Shift+Tab | Plan mode: approve a plan before edits (good for statistics-heavy missions) |
| `/goal <condition>` | Keep working until a condition holds, e.g. `/goal Mission 2.1 tests pass` |
| `/memory` | Edit CLAUDE.md |
| `/usage` | Your Claude usage (the cheat sheet's /stats) |
