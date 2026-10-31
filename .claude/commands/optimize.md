---
description: "Speed up a slow part and measure the gain"
argument-hint: "[target]"
---
Optimize: $ARGUMENTS (default: a campaign step).

Time each stage first, find the real bottleneck (often model switching or uncached LLM calls), apply the simplest
fix (batch by model, caching, shorter prompts, parallel sandbox runs on CPU), measure again, and show before/after.
Outputs must not change; run `pytest -q`.
