"""Canary command coach: pop-up reminders at key moments (Claude Code hooks).

Usage: python coach_hook.py <session_start|user_prompt|stop|pre_compact>
Prints a JSON object with "systemMessage" (shown to the student) or nothing.
Always exits 0, so it can never block Claude.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROMPT_HINTS = [
    (r"\b(error|traceback|exception|failed|failing|crash|broke)", "/solve <paste the error> does reproduce, root cause, fix, test"),
    (r"\b(what does|how does|explain|understand)\b", "/explain <file> or /learn <concept>"),
    (r"\b(where (were|are) we|what('s| is) next|continue|carry on)\b", "/where for a recap, /next to continue"),
    (r"\b(which is better|should i use|vs\.?|versus)\b", "/compare A vs B gives a trade-off table"),
    (r"\b(slow|faster|speed up|takes too long)\b", "/optimize measures, speeds up, measures again"),
    (r"\b(undo|go back|revert)\b", "/rewind undoes Claude's last changes"),
    (r"\b(how long|time left|deadline)\b", "/forecast or /priorities <time>"),
    (r"\b(report|write.?up|paper)\b", "/write <section>, then /proofread"),
]


# Real failure output only: a traceback header, a pytest count above zero, or a line starting "Error:".
# The word "failed" alone is not enough, because normal prose uses it ("none of the runs failed").
REAL_FAILURE = re.compile(r"^\s*Traceback \(most recent call last\)|\b[1-9]\d* failed\b|^\s*Error:", re.MULTILINE)


def emit(msg: str) -> None:
    print(json.dumps({"systemMessage": msg}))


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    from coach_state import last_done, next_mission, project_root, campaign_state

    root = project_root(data.get("cwd"))

    if event == "session_start":
        src = data.get("source", "startup")
        if src == "compact":
            emit("Canary coach: context was compacted. If Claude seems lost, type /where")
            return
        nm, ld = next_mission(root), last_done(root)
        parts = ["Canary coach:"]
        if ld:
            parts.append(f"last done Mission {ld}.")
        if nm:
            parts.append(f"Next: Mission {nm[0]} {nm[1]}.")
        if campaign_state(root) == "interrupted":
            parts.append("A campaign was interrupted: /campaign resumes it.")
        parts.append("Type /where for a recap, then /next." if ld else "First time? Type /project to begin.")
        emit(" ".join(parts))

    elif event == "user_prompt":
        prompt = (data.get("prompt") or "").strip()
        if not prompt or prompt.startswith("/") or re.search(r"(^|\s)/[a-z]", prompt):
            return  # already using commands
        low = prompt.lower()
        for pattern, hint in PROMPT_HINTS:
            if re.search(pattern, low):
                emit(f"Canary coach tip for next time: {hint}")
                return

    elif event == "stop":
        msg = data.get("last_assistant_message") or ""
        if isinstance(msg, (dict, list)):
            msg = json.dumps(msg)
        low = msg.lower()
        if REAL_FAILURE.search(msg):
            emit("Canary coach: something failed? Type /solve and paste the error.")
        elif "stopped at" in low:
            emit("Canary coach: stop point saved. Next time: /where, then /next.")
        elif re.search(r"mission \d+\.\d+", low) and re.search(r"commit", low):
            emit("Canary coach: mission done. /summary, then /clear before the next one (or /next to keep going).")

    elif event == "pre_compact":
        emit("Canary coach: compacting the conversation. Afterwards, /where if Claude seems lost.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
