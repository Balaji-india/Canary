# START HERE: building Canary with Claude Code

Canary is built in **missions** of 60-120 minutes each. You can stop after any mission and come back days later:
`PROGRESS.md` remembers everything, and every mission ends in a working state with a git commit.

## 1. One-time setup (20 minutes)
1. You already have Python, Git, Claude Code and Ollama from NewsLens.
2. Pull the three models (one download at a time is fine):
   ```
   ollama pull qwen3.5:4b
   ollama pull gemma4:e4b
   ollama pull phi4-mini
   ```
   If a tag isn't found, Claude will pick a fallback from `config/models.yaml` in Mission 1.1.
3. Unzip this folder, e.g. to `C:\projects\canary`, then:
   ```
   cd C:\projects\canary
   claude
   ```
4. Press **Shift+Tab** until the bar says *accept edits*.
5. Type `/project`.

### Use the plain terminal, not VS Code
Run Claude Code in **Windows Terminal or PowerShell**. You don't need VS Code. The command reminders (the tip bar
at the bottom) show in the terminal version. If you like, open the folder in VS Code *as well*, just to read
files and diffs.

### Your command reminders
You'll get three kinds:
- **Tip bar** at the bottom of Claude Code, always visible: the next mission, context use, and a `/command` tip
  that changes with the situation (e.g. "context almost full: /summary, then /clear").
- **Pop-ups** at key moments: when a session starts (where you left off), when you describe an error in normal
  words (suggests `/solve`), when a mission finishes, and before the conversation is compacted.
- **💡 Next:** a line at the end of Claude's replies naming the best command for that moment.

The first time, Claude Code may ask whether to trust this folder's settings: say yes (they're the reminder
scripts). If the tip bar stays empty, your Python command may be `py` rather than `python`: ask
Claude "change python to py in .claude/settings.json", then restart Claude Code.

## 2. Every session after that
| You want to… | Type |
|---|---|
| Continue where you stopped | `/next` (or `/next 60` if you only have 60 minutes) |
| Remember where you were after a break | `/where` |
| Do a specific mission | `/mission 2.3` |
| Fix an error | `/solve <paste the error>` |
| Run a long experiment (e.g. overnight) | `/campaign --runs 100` |
| See what the reviewer misses | `/blindspots` |
| Understand a concept | `/learn Rogan-Gladen` |
| Understand a file | `/explain canary/trust.py` |
| You have a demo or deadline coming | `/priorities 6 hours` |

**Tip:** start each new session with `/clear` (or a fresh Claude Code window), then `/next`. A clean context
works better than one long conversation.

## 3. The road map
| Milestone | What you get | Sessions (rough) |
|---|---|---|
| M1 Foundations | An AI scientist that proposes, pre-registers, runs, gets reviewed, and logs to a tamper-evident ledger | 4-5 |
| M2 Controls and trust | Canaries, controls and shams; the Skeptic's real catch rate (first real result: RQ1) | 3-4 |
| M3 Memory and calibration | Graveyard and confidence tracking | 2 |
| M4 Trusting findings | Contamination estimate, trust gate, drift alarms, the campaign agent (**the headline feature**) | 4 |
| M5 Defense in depth | Tripwires, a two-model jury, replication | 3 |
| M6 Adaptive saboteur | Blind-spot map and a self-hardening reviewer | 3-4 |
| M7 Lab Monitor | Dashboard and the "Beat the Skeptic" game | 2-3 |
| M8 Write-up | Paper-style report, figures, demo script | 3 |

**Need something to show early?** The minimum presentable version is M1 + M2 + Mission 4.1 + the dashboard
overview (about 10-12 sessions). Type `/priorities` with your deadline and Claude will steer there first.

## 4. Long experiments
Campaigns with many runs can take an hour or more on your laptop (each audit runs a local model). Start one before
dinner or overnight with `/campaign`. If it's interrupted, `/campaign` offers to resume it.
