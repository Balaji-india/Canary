---
description: "Audit the code against every rule in CLAUDE.md"
---
Audit the codebase against `CLAUDE.md` sections 4 and 6: allowed dependencies; one LLM wrapper with model queue;
**the sealed run-type table never reachable from the Skeptic path**; no LLM computing verdicts or numbers; no
hand-typed metrics; tests offline and fast; timeouts on subprocesses; pathlib/Windows-safe code.

Output: rule | pass/fail | evidence (file:line) | fix. Fix the failures, run `pytest -q`, show the result. $ARGUMENTS
