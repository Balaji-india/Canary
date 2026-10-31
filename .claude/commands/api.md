---
description: "Add or switch an LLM provider or model through the single wrapper"
argument-hint: "[provider or model]"
---
Integrate: $ARGUMENTS

Only inside `canary/llm.py` and `config/models.yaml`, keeping the same interface, JSON output, cache and model
queue. Read the provider's current docs. Keys only in `.env` (add the name to `.env.example`). Keep the Skeptic a
different model family from the Scientist. Add a mocked test and a smoke command.
