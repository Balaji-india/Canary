---
description: "Draft a section of the report or README from the real code and results"
argument-hint: "[section name]"
---
Write: $ARGUMENTS

Target `docs/REPORT.md` (paper style) or `README.md`. Base every statement on the code, `eval/results/*.json` and
the ledger; numbers only from those files. Clear, plain English. If a result is missing, write
`TODO: run /evaluate rqN` instead of a number.
