---
description: "Inspect runs, ledger and campaign data for quality problems"
argument-hint: "[campaign or 'latest']"
---
Analyze the data of: $ARGUMENTS (default: the latest campaign).

Report: runs by type and status, crash rate, audit failures (invalid JSON), runtime per stage, class balance of
canaries, duplicate hypotheses, ledger chain validity, and anything that could bias the RQ results. Suggest fixes;
ask before changing code.
