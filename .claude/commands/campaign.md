---
description: "Run a research campaign (or resume one) and interpret what happened"
argument-hint: "[options, e.g. --runs 60 --question q1]"
---
Run or resume a campaign: $ARGUMENTS

1. Check `data/runs/campaign.log` for an interrupted campaign and offer to resume it.
2. Start it in the background with progress logging; estimate the duration first (audit time per run × runs).
3. When it finishes (or on request), summarize: runs by type, Skeptic recall and specificity with intervals,
   prevalence and contamination estimates, gate decisions, drift alarms, the agent's key decisions from the trace,
   and accepted / graveyard / escalated findings.
4. Point out anything suspicious and suggest the next campaign.
