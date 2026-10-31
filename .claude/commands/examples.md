---
description: "Create small realistic fixtures or sample runs for a module or test"
argument-hint: "[module or scenario]"
---
Create small, deterministic fixtures for: $ARGUMENTS

Save them under `tests/fixtures/`. Cover the normal case and edge cases (e.g. a crash, a canary of each tier, a
sham that looks like a real change, Se + Sp ≤ 1, zero flags). One line per fixture on what it is for.
