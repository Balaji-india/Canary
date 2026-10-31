"""Canary status line: always-visible bar with the next mission and a command tip.

Claude Code pipes session JSON on stdin and shows each printed line as a row.
Must be fast and must never crash (a crash just blanks the bar).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from coach_state import next_mission, pick_tip, project_root

    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    ws = data.get("workspace") or {}
    root = project_root(ws.get("project_dir") or ws.get("current_dir") or data.get("cwd"))
    ctx = (data.get("context_window") or {}).get("used_percentage")
    ctx = float(ctx) if ctx is not None else None

    nm = next_mission(root)
    mission = f"next: Mission {nm[0]} {nm[1]}" if nm else "all missions done"
    ctx_txt = f" | context {ctx:.0f}%" if ctx is not None else ""
    print(f"Canary | {mission}{ctx_txt}")
    print(f"TIP > {pick_tip(root, ctx)}")
except Exception:
    print("Canary | TIP > /where for a recap, /next to continue")
