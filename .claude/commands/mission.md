---
description: "Run one mission end to end: plan, build, test, prove it works, log, commit"
argument-hint: "[mission id, e.g. 2.3]"
---
Run Mission $ARGUMENTS from `CLAUDE.md` section 7.

1. Read the mission, the referenced sections of `docs/DESIGN.md`, `PROGRESS.md`, and the existing code it touches.
2. Show a short plan (files, functions, tests), then build it without stopping for small confirmations.
3. Write or update tests for the pure logic; `pytest -q` must pass.
4. Run the mission's "done when" check and show the real output.
5. Update `PROGRESS.md`: tick the mission, paste a 2-line summary of the check output, note decisions and issues.
6. Git commit "Mission $ARGUMENTS: <summary>". Then tell me the result and the next mission.
If you must stop early, write "stopped at: <exact point>" under the mission in `PROGRESS.md` and commit.
