---
description: "List and check the hidden assumptions in a plan, analysis or the code"
argument-hint: "[file, module, plan or result]"
---
List the assumptions behind: $ARGUMENTS (if empty: the current mission's code).

Give: the assumption, where it appears (file:line), the risk (high/medium/low) and how to verify it. Pay special
attention to statistical assumptions (independence of runs, class mix of canaries vs real bugs, Se + Sp > 1,
sample sizes). Verify the high-risk ones and report what you found.
