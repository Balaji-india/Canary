---
description: "Implement a feature following CLAUDE.md: plan, code, test, verify"
argument-hint: "[feature]"
---
Implement: $ARGUMENTS

5-line plan → implement in small steps → tests for pure logic (LLM and network mocked) → `pytest -q` → run the
relevant CLI command and show real output → short list of changed files → update `PROGRESS.md`.
