"""Memory for tg-system-control (bot 1).

Two kinds:
  - Conversation: your recent messages and the bot's replies (data/conversation.jsonl), so the
    AI translator understands follow-ups like "usko band karo" (= the app we just talked about).
  - Notes: things you ask it to remember (/remember ...), e.g. "my videos are in D:\\VideoStudio_Mac".
    Notes are given to the translator and to the agent with every task.

memory.md stays the append-only audit log; this is what the AI sees. Stored locally, git-ignored.
"""
import json
import threading
import time
from pathlib import Path

import config

DATA_DIR = config.ROOT_DIR / "data"
CONV_FILE = DATA_DIR / "conversation.jsonl"
NOTES_FILE = DATA_DIR / "notes.json"
MAX_CONV_LINES = 500
_LOCK = threading.Lock()


def _ensure():
    DATA_DIR.mkdir(exist_ok=True)


def add_exchange(user_text: str, bot_text: str):
    if not (user_text or bot_text):
        return
    _ensure()
    rec = {"t": time.strftime("%Y-%m-%d %H:%M"), "user": (user_text or "")[:800], "bot": (bot_text or "")[:800]}
    with _LOCK:
        with open(CONV_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        try:  # keep the file small
            lines = CONV_FILE.read_text(encoding="utf-8").splitlines()
            if len(lines) > MAX_CONV_LINES * 2:
                CONV_FILE.write_text("\n".join(lines[-MAX_CONV_LINES:]) + "\n", encoding="utf-8")
        except Exception:
            pass


def recent(n: int = 6) -> list:
    try:
        lines = CONV_FILE.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []


def notes() -> list:
    try:
        return json.loads(NOTES_FILE.read_text(encoding="utf-8")).get("notes", [])
    except Exception:
        return []


def _save_notes(items: list):
    _ensure()
    NOTES_FILE.write_text(json.dumps({"notes": items}, ensure_ascii=False, indent=1), encoding="utf-8")


def remember(text: str) -> int:
    with _LOCK:
        items = notes()
        items.append({"t": time.strftime("%Y-%m-%d %H:%M"), "text": text.strip()[:1000]})
        _save_notes(items)
        return len(items)


def forget(which: str) -> int:
    with _LOCK:
        items = notes()
        w = (which or "").strip().lower()
        if w in ("all", "sab", "everything"):
            _save_notes([])
            return len(items)
        if w.isdigit() and 1 <= int(w) <= len(items):
            items.pop(int(w) - 1)
            _save_notes(items)
            return 1
        kept = [n for n in items if w and w not in n["text"].lower()]
        removed = len(items) - len(kept)
        if removed:
            _save_notes(kept)
        return removed


def notes_text() -> str:
    items = notes()
    return "\n".join(f"{i}. {n['text']}" for i, n in enumerate(items, 1))


def context_text(n_exchanges: int = 6) -> str:
    """Context block for the AI (translator / agent). Empty string if there is nothing yet."""
    parts = []
    nt = notes_text()
    if nt:
        parts.append("USER'S SAVED NOTES:\n" + nt)
    conv = recent(n_exchanges)
    if conv:
        parts.append("RECENT CONVERSATION (oldest first):\n" + "\n".join(
            f"[{c['t']}] USER: {c['user'][:200]}\n           BOT: {c['bot'][:200]}" for c in conv))
    return "\n\n".join(parts)
