---
description: "Scaffold a new Canary module or bug class from the project's patterns, with its test file"
argument-hint: "[module or bug-class name] [purpose]"
---
Scaffold: $ARGUMENTS

- New module: `canary/<name>.py` with a docstring (what it does and why it exists in the loop), type-hinted stubs,
  and a logger; plus `tests/test_<name>.py` with one meaningful test on a tiny fixture.
- New bug class: an entry in `config/bug_classes.yaml` (obvious + subtle tier), the transform in
  `canary/saboteur/transforms.py`, and a test proving the bug is present in transformed code.
- Show the public functions created in a short table.
