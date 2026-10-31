---
description: "Make clear, paper-quality charts of results"
argument-hint: "[which results]"
---
Charts for: $ARGUMENTS (default: all of `eval/results/`).

matplotlib, saved to `eval/figures/` as PNG and PDF. One finding per chart, with the title stating it. Show
uncertainty (intervals or error bars) wherever there is an estimate. Suggested: recall by class with Beta
intervals; π estimate vs true prevalence with the y = x line (RQ4); contamination gate ON vs OFF (RQ3); control
chart; blind-spot heatmap; Brier over time. Data only from result files.
