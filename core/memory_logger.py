"""Append-only constructive memory logger for tg-system-control.
Strict Rule: ONLY constructive actions (append). No deletions, truncations, or overwrites.
Records every executed command, agent thinking, task completed, or interruption.
"""
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_FILE = ROOT / "memory.md"

INITIAL_HEADER = """# 🧠 TG-System-Control: Constructive Project Memory

This file serves as a permanent, append-only memory log for all interactions,
executed commands, AI reasoning thoughts, completed tasks, and system interruptions.

> **STRICT RULE:** Only constructive actions (write/append) are permitted.
> Content must NEVER be cleared, truncated, or deleted.

---

"""


def ensure_memory_file():
    """Initializes memory.md with the permanent header if it doesn't exist."""
    if not MEMORY_FILE.exists():
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(INITIAL_HEADER)


def log_entry(event_type: str, action: str, details: dict = None, thinking: str = None):
    """Appends a structured event entry to memory.md."""
    ensure_memory_file()
    t_str = time.strftime("%Y-%m-%d %H:%M:%S")

    lines = [f"\n### [{t_str}] {event_type.upper()}: {action}\n"]

    if thinking:
        lines.append(f"- **🧠 Agent Reasoning / Thinking:**\n  > {thinking.replace(chr(10), chr(10) + '  > ')}\n")

    if details:
        lines.append("- **📝 Event Details & Metrics:**\n")
        for k, v in details.items():
            lines.append(f"  - `{k}`: {v}\n")

    lines.append("\n---\n")

    # Strictly append mode ("a") - NEVER overwrite or truncate
    try:
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        print(f"[MemoryLogger] Write warning: {e}")
