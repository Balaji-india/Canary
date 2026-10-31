---
description: "Analyze the reviewer's blind spots and propose hardening"
argument-hint: "[model or 'all']"
---
Analyze blind spots for: $ARGUMENTS (default: all reviewer models).

Use the canary results: miss rate by bug class × tier × model, with Beta intervals; the shams' false-alarm rate;
example misses (show the blinded code snippet and the Skeptic's evidence). Explain *why* each blind spot likely
happens. Propose hardening (prompt hint, tripwire, or jury) and how to test it on held-out canaries without
overfitting.
