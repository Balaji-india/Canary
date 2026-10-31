---
description: "Fix a bug or error: reproduce, root cause, failing test, fix, prove"
argument-hint: "[error message or symptom]"
---
Problem: $ARGUMENTS

1. Reproduce it with the smallest command and show the output.
2. State the root cause in one sentence.
3. Write a failing test when it is testable offline.
4. Apply the smallest fix that addresses the cause.
5. Run that test and `pytest -q`; show both.
6. Add a line under "Fixes" in `PROGRESS.md`.
