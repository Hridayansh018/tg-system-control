"""Hermes Agent: turns Telegram messages into desktop actions.

Flow for every message:
  1. Local parser  - slash commands and exact short phrases ("open edge", "screenshot",
                     "spotify band karo") run instantly, no internet needed.
  2. Translator    - anything else goes to the LLM, which may only answer with commands
                     from a fixed menu (core/translator.py). Those commands run through the
                     same local handlers below.
  3. Agent mode    - open-ended multi-step tasks are handed to the computer-use agent
                     when it is available.
"""
import re
import time
from typing import Callable, List, Optional, Tuple

import config
from . import llm_router
from . import memory_logger
from . import os_bridge
from . import translator

Command = Tuple[str, str]

# Words that mean the message is more than "open/close <app>" -> let the translator handle it.
CONNECTOR_WORDS = {
    "and", "aur", "then", "phir", "fir", "me", "mein", "main", "pe", "par", "wahan", "waha", "wha",
    "karke", "ke", "ki", "ko", "se", "after", "with", "also", "bhi", "uske", "baad",
}

HELP_TEXT = (
    "🤖 *TG-System-Control — Commands*\n\n"
    "*Quick commands (instant, work offline):*\n"
    "• `status` / `/status` — CPU, RAM, disk\n"
    "• `screenshot` / `/shot` — desktop screenshot\n"
    "• `open <app>` / `<app> kholo` — open an app or website\n"
    "• `close <app>` / `<app> band karo` — close an app\n"
    "• `close tab` · `close window` / `hatao`\n"
    "• `processes` / `/proc` — top processes\n"
    "• `lock pc` / `/lock` — lock the screen\n"
    "• `/exec <command>` — run a PowerShell/Bash command\n"
    "• `/type <text>` · `/prompt <text>` (type + Enter)\n"
    "• `/key enter` · `/hotkey ctrl+w` · `/click 500 300`\n"
    "• `/focus <window>` · `/chatgpt <prompt>`\n"
    "• `/sendfile <name>` · `/latest` (newest download)\n\n"
    "*Anything else* (Hinglish or English) is translated into these commands by the AI, "
    "e.g. _\"spotify kholo aur edge band karo\"_."
)

_END_PUNCT = re.compile(r"[\s.!?]+$")


def _norm(text: str) -> str:
    return _END_PUNCT.sub("", re.sub(r"\s+", " ", text.strip().lower()))


def _simple_target(arg: str) -> bool:
    words = arg.split()
    return 0 < len(words) <= 5 and not any(w in CONNECTOR_WORDS for w in words)


# (regex on the ORIGINAL text, command) - arguments are kept exactly as typed
RAW_PREFIX_RULES = [
    (r"^(?:/exec|/run|/cmd|run:|cmd:)\s+(.+)$", "exec"),
    (r"^(?:/prompt|prompt:|type and enter:|enter prompt:)\s*(.+)$", "type_enter"),
    (r"^(?:/type|type:|write:|type\s)\s*(.+)$", "type"),
    (r"^(?:/key|key:)\s*(.+)$", "press"),
    (r"^(?:/hotkey|hotkey:)\s*(.+)$", "hotkey"),
    (r"^(?:/open|/launch)\s+(.+)$", "open"),
    (r"^(?:/close|/kill)\s+(.+)$", "close"),
    (r"^/focus\s+(.+)$", "focus"),
    (r"^/chatgpt\s+(.+)$", "chatgpt"),
    (r"^(?:/sendfile|/file|send file:?)\s+(.+)$", "send_file"),
]

# (fullmatch regex on the normalised text, command, arg-or-None-for-group-1)
PHRASE_RULES = [
    (r"/help|/start|help|commands|menu", "help", ""),
    (r"/latest|send latest download|latest download( bhejo)?|last download bhejo", "send_latest_download", ""),
    (r"/shot|/screenshot|(?:(?:take|send|le|lo) )?(?:a )?(?:screenshot|screen shot|ss|screen capture)"
     r"(?: (?:bhejo|bhej do|lo|le lo|do|dikhao|please|pls|now))*|desktop dikhao|screen dikhao", "screenshot", ""),
    (r"/status|(?:pc |system |computer )?(?:status|stats|specs|health)(?: (?:batao|dikhao|check|please|pls|kya hai))*"
     r"|ram|cpu|disk|storage", "status", ""),
    (r"/proc|/processes|(?:top |running )?(?:process|processes|tasks)(?: (?:dikhao|list|batao))?|task list", "processes", ""),
    (r"/lock|lock|lock pc|lock screen|lock (?:the )?computer|(?:pc|screen) lock(?: karo| kar do)?", "lock", ""),
    (r"/close|close|close window|close this|hatao|hata do|band karo|band kar do|close karo|close kar do", "close", ""),
    (r"close tab|tab (?:band karo|band kar do|close karo|hatao)", "close", "tab"),
    (r"enter|hit enter|press enter|enter dabao", "press", "enter"),
    (r"(?:press|hit) (\S+)", "press", None),
]

# (fullmatch regex, command) whose group 1 is an app name that must pass _simple_target
TARGET_RULES = [
    (r"(?:open|launch|start|kholo|khol do) (.+)", "open"),
    (r"(.+?) (?:open karo|open kar do|kholo|khol do|chalao|chala do|start karo|launch karo|open)", "open"),
    (r"(?:close|kill|quit|exit) (.+)", "close"),
    (r"(.+?) (?:band karo|band kar do|bandh karo|close karo|close kar do|hatao|hata do|quit karo|close)", "close"),
]


def parse_local(user_text: str) -> Optional[List[Command]]:
    """Returns commands for messages that can be handled without the LLM, else None."""
    text = user_text.strip()
    if not text:
        return None

    for pattern, cmd in RAW_PREFIX_RULES:
        m = re.match(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            return [(cmd, m.group(1).strip())]

    m = re.fullmatch(r"/?click\s+(\d+)\s*,?\s*(\d+)", text, re.IGNORECASE)
    if m:
        return [("click", f"{m.group(1)} {m.group(2)}")]

    norm = _norm(text)
    for pattern, cmd, arg in PHRASE_RULES:
        m = re.fullmatch(pattern, norm)
        if m:
            return [(cmd, m.group(1) if arg is None else arg)]

    for pattern, cmd in TARGET_RULES:
        m = re.fullmatch(pattern, norm)
        if m and _simple_target(m.group(1)):
            return [(cmd, m.group(1).strip())]

    return None


def _result(text: str = "", files: list = None) -> dict:
    return {"text": text, "files": files or []}


class HermesAgent:
    def __init__(self, agent_hook: Optional[Callable[[str], dict]] = None):
        # agent_hook(task) -> result dict; set by the listener when agent mode is available.
        self.agent_hook = agent_hook

    # ------------------------------------------------------------------
    def process_message(self, user_text: str) -> dict:
        """Returns {"text": str, "files": [{"kind": "photo"|"document", "path": str, "caption": str}]}"""
        local = parse_local(user_text)
        if local is not None:
            return self.run_commands(local, user_text)

        tr = translator.translate(user_text, agent_available=self.agent_hook is not None)
        kind = tr.get("kind")

        if kind == "offline":
            return _result(
                "🤖 *Offline mode* — no AI key configured, so only exact commands work.\n\n" + HELP_TEXT
                + "\n\n💡 Add `GEMINI_API_KEY` to `.env` to use Hinglish / free text."
            )
        if kind == "error":
            memory_logger.log_entry("TRANSLATOR_ERROR", "Translator failed", details={"error": tr["error"][:300]},
                                    thinking=f"Could not translate: {user_text[:200]}")
            return _result(f"⚠️ *AI translator error:* {tr['error']}\n\nTry an exact command — send `/help`.")
        if kind == "chat":
            memory_logger.log_entry("CHAT", "Replied without executing", details={"message": user_text[:200]},
                                    thinking="Message was conversation/feedback, not an instruction.")
            return _result(tr["reply"])
        if kind == "agent_task":
            if self.agent_hook is None:
                return _result(
                    f"🧠 Understood as a multi-step task: _{tr['task']}_\n\n"
                    "⚠️ Agent mode isn't available, so I can't do multi-step screen tasks. "
                    "Send the steps as separate commands (see /help)."
                )
            return self.agent_hook(tr["task"])

        commands = tr["commands"]
        understood = " → ".join(f"{c} {a}".strip() for c, a in commands)
        res = self.run_commands(commands, user_text)
        res["text"] = f"🧠 *Understood as:* `{understood}`\n\n" + res["text"]
        return res

    # ------------------------------------------------------------------
    def run_commands(self, commands: List[Command], original: str) -> dict:
        texts, files = [], []
        for i, (cmd, arg) in enumerate(commands):
            if i > 0:
                time.sleep(1.5 if commands[i - 1][0] in ("open", "focus") else 0.3)
            try:
                res = self.execute(cmd, arg)
            except Exception as e:
                res = _result(f"⚠️ `{cmd}` failed: {e}")
            memory_logger.log_entry(
                "COMMAND", f"{cmd} {arg[:120]}".strip(),
                details={"result": res["text"][:250], "files": [f["path"] for f in res["files"]]},
                thinking=f"From message: {original[:200]}",
            )
            if res["text"]:
                texts.append(res["text"])
            files.extend(res["files"])
        return _result("\n".join(texts), files)

    # ------------------------------------------------------------------
    def execute(self, cmd: str, arg: str) -> dict:
        handler = getattr(self, f"cmd_{cmd}", None)
        if handler is None:
            return _result(f"⚠️ Unknown command `{cmd}`")
        return handler(arg)

    def cmd_help(self, arg):
        return _result(HELP_TEXT)

    def cmd_screenshot(self, arg):
        out_file = config.SCREENSHOTS_DIR / f"shot_{int(time.time() * 1000)}.jpg"
        if os_bridge.take_screenshot(out_file) and out_file.exists():
            return _result("", [{"kind": "photo", "path": str(out_file), "caption": "📸 *Desktop Screenshot*"}])
        return _result("⚠️ Screenshot failed (screen locked, or no desktop session).")

    def cmd_status(self, arg):
        stats = os_bridge.get_system_stats()
        reply = (
            f"💻 *SYSTEM STATUS*\n\n"
            f"🖥️ *OS:* `{stats.get('os')}` ({stats.get('architecture')})\n"
            f"🧠 *CPU Cores:* `{stats.get('cpu_cores')}`\n"
        )
        if "ram_total_gb" in stats:
            reply += f"⚡ *RAM:* `{stats.get('ram_used_gb', 0)} GB` / `{stats.get('ram_total_gb')} GB` ({stats.get('ram_used_pct')} % used)\n"
        if "disk_total_gb" in stats:
            reply += f"💾 *Disk:* `{stats.get('disk_free_gb')} GB Free` / `{stats.get('disk_total_gb')} GB` ({stats.get('disk_used_pct')} % used)\n"
        reply += f"\n🕒 *Time:* `{time.strftime('%Y-%m-%d %H:%M:%S')}`"
        return _result(reply)

    def cmd_processes(self, arg):
        out = os_bridge.list_top_processes(limit=8)
        return _result(f"📋 *TOP PROCESSES:*\n```\n{out[:3500]}\n```")

    def cmd_lock(self, arg):
        res = os_bridge.lock_workstation()
        return _result("🔒 *Workstation locked.*" if res["exit_code"] == 0 else f"⚠️ Lock failed: {res['stderr']}")

    def cmd_exec(self, arg):
        res = os_bridge.run_command(arg)
        out = (res["stdout"] or res["stderr"] or "Command executed with no output.")[:3500]
        icon = "✅" if res["exit_code"] == 0 else "⚠️"
        return _result(f"{icon} *Exit code {res['exit_code']}:*\n```\n{out}\n```")

    def cmd_open(self, arg):
        res = os_bridge.launch_app(arg)
        if res["exit_code"] == 0:
            return _result(f"🚀 Opened *{arg}*")
        return _result(f"⚠️ {res['stderr'] or 'Could not open ' + arg}")

    def cmd_close(self, arg):
        res = os_bridge.close_app(arg)
        icon = "🛑" if res["exit_code"] == 0 else "⚠️"
        return _result(f"{icon} {res['stdout'] or res['stderr']}")

    def _lock_note(self, lock) -> str:
        return " (your mouse/keyboard were locked meanwhile)" if lock.locked else ""

    def cmd_type(self, arg):
        with os_bridge.UserInputLock("Keyboard Type") as lock:
            ok = os_bridge.type_text(arg)
        return _result(f"⌨️ Typed `{arg[:100]}`{self._lock_note(lock)}" if ok else "⚠️ Typing failed")

    def cmd_type_enter(self, arg):
        with os_bridge.UserInputLock("Type & Enter") as lock:
            ok = os_bridge.type_text(arg)
            time.sleep(0.3)
            os_bridge.press_key("enter")
        if not ok:
            return _result("⚠️ Typing failed")
        return _result(f"⌨️ Typed and submitted `{arg[:250]}`{self._lock_note(lock)}\n📸 Send `/shot` in a few seconds to see the result.")

    def cmd_press(self, arg):
        with os_bridge.UserInputLock(f"Key {arg}"):
            ok = os_bridge.press_key(arg or "enter")
        return _result(f"🔘 Pressed *{(arg or 'enter').upper()}*" if ok else f"⚠️ Unknown key `{arg}`")

    def cmd_hotkey(self, arg):
        with os_bridge.UserInputLock(f"Hotkey {arg}"):
            ok = os_bridge.press_hotkey(arg)
        return _result(f"⚡ Pressed *{arg.upper()}*" if ok else f"⚠️ Unknown hotkey `{arg}`")

    def cmd_click(self, arg):
        x, y = (int(v) for v in arg.split()[:2])
        with os_bridge.UserInputLock("Mouse Click") as lock:
            ok = os_bridge.mouse_click(x, y)
        return _result(f"🖱️ Clicked at *({x}, {y})*{self._lock_note(lock)}" if ok else "⚠️ Click failed")

    def cmd_focus(self, arg):
        ok = os_bridge.focus_window(arg)
        return _result(f"🪟 Focused *{arg}*" if ok else f"⚠️ No open window matching `{arg}`")

    def cmd_chatgpt(self, arg):
        res = os_bridge.automate_chatgpt(arg, new_chat=True)
        files = [{"kind": "photo", "path": res["screenshot"], "caption": "🤖 ChatGPT"}] if res.get("screenshot") else []
        note = res.get("note", "Prompt submitted. Send `/shot` later to see the answer.")
        return _result(f"🤖 *ChatGPT:* `{arg[:120]}`\n{note}", files)

    def cmd_send_latest_download(self, arg):
        f = os_bridge.latest_download()
        if not f:
            return _result("⚠️ Downloads folder is empty.")
        return _result("", [{"kind": "document", "path": str(f), "caption": f"📥 {f.name}"}])

    def cmd_send_file(self, arg):
        f = os_bridge.find_file(arg)
        if not f:
            return _result(f"⚠️ File `{arg}` not found (looked in screenshots, Downloads, Desktop, Documents).")
        if f.stat().st_size > 49 * 1024 * 1024:
            return _result(f"⚠️ `{f.name}` is larger than Telegram's 50 MB bot limit.")
        return _result("", [{"kind": "document", "path": str(f), "caption": f"📄 {f.name}"}])


def llm_status_line() -> str:
    provider = llm_router.active_provider()
    return "OFFLINE (exact commands only)" if provider == "offline" else provider.upper()
