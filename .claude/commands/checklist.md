---
description: "Check the minimum presentable version or a milestone, item by item, with evidence"
argument-hint: "[milestone or 'presentable']"
---
Check: $ARGUMENTS (default: the minimum presentable version in CLAUDE.md section 7).

For each item, actually verify it (run commands, tests, the dashboard's import, `ledger verify`, a grep for hard-coded
metrics and for sealed-table access from the Skeptic). Report item | pass/fail | evidence, then the failing items in
priority order with estimates.
