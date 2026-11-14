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
    "• `/key enter` · `/hotkey ctrl+w`\n\n"
    "*🖥️ Remote desktop:*\n"
    "• `/grid` — screenshot with x/y ruler (🔴 = mouse) · `/shot` · `/where`\n"
    "• `click 960 540` · `rclick X Y` · `dclick X Y` · `click` (here)\n"
    "• `move X Y` · `drag X1 Y1 X2 Y2` · `scroll down 5`\n"
    "• `/uploadfile <name>` — fill an open website file picker (send the file to me first)\n"
    "• `/block 10` · `/unblock` — lock the PC's own mouse/keyboard (admin mode)\n"
    "• `/remote off|on` — screenshot after every mouse/keyboard command\n\n"
    "• `/focus <window>` · `/chatgpt <prompt>`\n"
    "• `/sendfile <name>` · `/latest` (newest download)\n\n"
    "*Anything else* (Hinglish or English) is translated into these commands by the AI, "
    "e.g. _\"spotify kholo aur edge band karo\"_."
)

AGENT_HELP = (
    "\n\n🧠 *Automate anything (agent mode):*\n"
    "• `/agent <task>` or `/do <task>` — the AI looks at the screen and clicks/types step by step\n"
    "  e.g. `/agent chatgpt me luffy ke 3 thumbnail banao aur download karke bhejo`\n"
    "• `/task` — progress · `/stop` — cancel immediately\n"
    "• Risky steps (sending, buying, deleting, installing, shell changes) ask for ✅/❌ first\n\n"
    "🧰 *More:* send a photo/file → saved to the PC inbox · `/get <path>` · `/clip` · `/clip <text>` · "
    "`/volume up|down|mute` · `/media play|next|prev` · `/scroll up|down` · `/windows` · "
    "`/sleep` · `/restart` · `/shutdown` (with approval)"
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
    (r"^(?:/agent|/do)\s+(.+)$", "agent"),
    (r"^/get\s+(.+)$", "get_file"),
    (r"^/clip\s+(.+)$", "clipboard_set"),
    (r"^/volume\s+(up|down|mute)$", "volume"),
    (r"^/media\s+(play|pause|next|prev|previous|stop)$", "media"),
    (r"^(?:/uploadfile|/upload|upload file:?)\s+(.+)$", "upload_file"),
    (r"^/block(?:\s+(\d+(?:\.\d+)?))?\s*(?:m|min|mins|minutes)?$", "block"),
    (r"^/remote\s+(on|off)$", "remote"),
]

# (fullmatch regex on the normalised text, command, arg-or-None-for-group-1)
PHRASE_RULES = [
    (r"/help|/start|help|commands|menu", "help", ""),
    (r"/grid|grid|screen grid|grid dikhao", "grid", ""),
    (r"/unblock|unblock|unlock input", "unblock", ""),
    (r"/where|where is (?:the )?mouse|mouse kaha hai|cursor", "where", ""),
    (r"/clip|clipboard( bhejo| dikhao)?", "clipboard_get", ""),
    (r"/windows|windows list|open windows", "windows", ""),
    (r"/sleep", "power", "sleep"),
    (r"/restart|/reboot", "power", "restart"),
    (r"/shutdown", "power", "shutdown"),
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

# Remote-desktop style mouse commands with coordinates (real screen pixels, see /grid)
_N = r"(-?\d+)\s*,?\s*"
MOUSE_RULES = [
    (rf"/?(?:click|tap)\s+{_N}(-?\d+)", "click"),
    (rf"/?(?:rclick|right\s*click)\s+{_N}(-?\d+)", "rclick"),
    (rf"/?(?:dclick|double\s*click)\s+{_N}(-?\d+)", "dclick"),
    (rf"/?(?:move|mouse)\s+{_N}(-?\d+)", "move"),
    (rf"/?drag\s+{_N}{_N}{_N}(-?\d+)", "drag"),
    (r"/?scroll\s+(up|down)(?:\s+(\d+))?", "scroll"),
    (r"/?(?:click|rclick|right\s*click|dclick|double\s*click)", "click_here"),
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
            return [(cmd, (m.group(1) or "").strip())]

    for pattern, cmd in MOUSE_RULES:
        m = re.fullmatch(pattern, text.strip(), re.IGNORECASE)
        if m:
            return [(cmd, " ".join(g for g in m.groups() if g))]

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


# Commands that change what's on screen -> followed by a screenshot when remote feedback is on
INPUT_COMMANDS = {"click", "rclick", "dclick", "click_here", "move", "drag", "scroll", "type", "type_enter",
                  "press", "hotkey", "upload_file", "focus", "open", "close"}


def _result(text: str = "", files: list = None) -> dict:
    return {"text": text, "files": files or []}


class HermesAgent:
    def __init__(self, agent_hook: Optional[Callable[[str], dict]] = None,
                 approver: Optional[Callable[[str, str], bool]] = None):
        # agent_hook(task) -> result dict; set by the listener when agent mode is available.
        self.agent_hook = agent_hook
        # approver(title, details) -> bool; shows Approve/Cancel buttons and waits for the user.
        self.approver = approver
        # Remote-desktop feedback: send a screenshot (cursor marked) after mouse/keyboard commands.
        self.remote_feedback = config.REMOTE_FEEDBACK

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
        if self.remote_feedback and any(c in INPUT_COMMANDS for c, _ in commands) and not any(
                f["kind"] == "photo" for f in files):
            time.sleep(0.8)  # let the screen update
            shot = config.SCREENSHOTS_DIR / f"remote_{int(time.time() * 1000)}.jpg"
            if os_bridge.screenshot_annotated(shot):
                files.append({"kind": "photo", "path": str(shot), "caption": ""})
        return _result("\n".join(texts), files)

    # ------------------------------------------------------------------
    def execute(self, cmd: str, arg: str) -> dict:
        handler = getattr(self, f"cmd_{cmd}", None)
        if handler is None:
            return _result(f"⚠️ Unknown command `{cmd}`")
        return handler(arg)

    def cmd_help(self, arg):
        return _result(HELP_TEXT + (AGENT_HELP if self.agent_hook else ""))

    def _approve(self, title: str, details: str) -> bool:
        return bool(self.approver and self.approver(title, details))

    def cmd_agent(self, arg):
        if self.agent_hook is None:
            return _result("⚠️ Agent mode is off. Set `GEMINI_API_KEY` (and `AGENT_ENABLED=true`) in `.env`, then restart the bot.")
        return self.agent_hook(arg)

    def cmd_get_file(self, arg):
        from . import agent_safety
        f = os_bridge.find_file(arg)
        if not f:
            return _result(f"⚠️ File `{arg}` not found.")
        reason = agent_safety.path_needs_approval(str(f))
        if reason and not self._approve(f"Send file {f.name} to your phone", reason):
            return _result(f"❌ Not sent: {reason}.")
        return self.cmd_send_file(str(f))

    def cmd_clipboard_get(self, arg):
        text = os_bridge.get_clipboard()
        if text is None:
            return _result("⚠️ Could not read the clipboard.")
        body = text[:3500] or "(empty)"
        return _result(f"📋 *Clipboard:*\n```\n{body}\n```")

    def cmd_clipboard_set(self, arg):
        return _result("📋 Copied to the PC clipboard." if os_bridge.set_clipboard(arg) else "⚠️ Clipboard write failed.")

    def cmd_volume(self, arg):
        return _result(f"🔊 Volume {arg}" if os_bridge.media_key(arg) else f"⚠️ Volume `{arg}` not supported here.")

    def cmd_media(self, arg):
        return _result(f"⏯️ Media {arg}" if os_bridge.media_key(arg) else f"⚠️ Media `{arg}` not supported here.")

    def cmd_scroll(self, arg):
        parts = arg.lower().split()
        direction = parts[0] if parts else "down"
        notches = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5
        ok = os_bridge.mouse_scroll(dy=notches if direction == "up" else -notches)
        return _result(f"🖱️ Scrolled {direction} {notches}" if ok else "⚠️ Scroll failed")

    def cmd_windows(self, arg):
        titles = [t for _, t in os_bridge.list_windows()]
        if not titles:
            return _result("No open windows found.")
        return _result("🪟 *Open windows:*\n" + "\n".join(f"• {t[:80]}" for t in titles[:40]))

    def cmd_power(self, arg):
        labels = {"sleep": "Put the PC to sleep", "restart": "Restart the PC (in 15 s)", "shutdown": "Shut down the PC (in 15 s)"}
        if arg not in labels:
            return _result(f"⚠️ Unknown power action `{arg}`")
        if not self._approve(labels[arg], "The PC will go offline and the bot will stop responding."):
            return _result(f"❌ {arg.capitalize()} cancelled.")
        res = os_bridge.power_action(arg)
        return _result(f"⚡ {labels[arg]}…" if res["exit_code"] == 0 else f"⚠️ {res['stderr']}")

    def cmd_screenshot(self, arg, grid: bool = False):
        out_file = config.SCREENSHOTS_DIR / f"shot_{int(time.time() * 1000)}.jpg"
        if os_bridge.screenshot_annotated(out_file, grid=grid) and out_file.exists():
            caption = ("🧭 *Screen grid* — numbers are screen pixels: send `click X Y`, `move X Y`, `drag X1 Y1 X2 Y2`"
                       if grid else "📸 *Desktop Screenshot* (🔴 = mouse)")
            return _result("", [{"kind": "photo", "path": str(out_file), "caption": caption}])
        return _result("⚠️ Screenshot failed (screen locked, or no desktop session).")

    def cmd_grid(self, arg):
        return self.cmd_screenshot(arg, grid=True)

    def cmd_where(self, arg):
        pos = os_bridge.get_cursor_pos()
        return _result(f"🖱️ Mouse is at *{pos[0]}, {pos[1]}*" if pos else "⚠️ Can't read the mouse position here.")

    def cmd_remote(self, arg):
        self.remote_feedback = arg.lower() == "on"
        return _result("📺 Remote view ON: a screenshot follows every mouse/keyboard command."
                       if self.remote_feedback else "📺 Remote view OFF: send `/shot` when you want to see the screen.")

    def cmd_block(self, arg):
        res = os_bridge.block_input_for(float(arg) if arg else 10)
        return _result(("🔒 " + res["stdout"] + "\nSend `/unblock` to release.") if res["exit_code"] == 0 else "⚠️ " + res["stderr"])

    def cmd_unblock(self, arg):
        return _result("🔓 " + os_bridge.unblock_input()["stdout"])

    def cmd_upload_file(self, arg):
        res = os_bridge.upload_file_dialog(arg)
        return _result(("📤 " + res["stdout"]) if res["exit_code"] == 0 else "⚠️ " + res["stderr"])

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

    TYPE_FAILED = ("⚠️ Typing stopped: another window took focus (or the window wasn't ready). "
                   "Click the text box first (`click X Y`, see `/grid`) and try again.")

    def cmd_type(self, arg):
        with os_bridge.UserInputLock("Keyboard Type") as lock:
            ok = os_bridge.type_text(arg)
        return _result(f"⌨️ Typed `{arg[:100]}`{self._lock_note(lock)}" if ok else self.TYPE_FAILED)

    def cmd_type_enter(self, arg):
        with os_bridge.UserInputLock("Type & Enter") as lock:
            ok = os_bridge.type_text(arg)
            if ok:
                time.sleep(0.3)
                os_bridge.press_key("enter")
        if not ok:
            return _result(self.TYPE_FAILED + "\nEnter was NOT pressed.")
        return _result(f"⌨️ Typed and submitted `{arg[:250]}`{self._lock_note(lock)}")

    def cmd_press(self, arg):
        with os_bridge.UserInputLock(f"Key {arg}"):
            ok = os_bridge.press_key(arg or "enter")
        return _result(f"🔘 Pressed *{(arg or 'enter').upper()}*" if ok else f"⚠️ Unknown key `{arg}`")

    def cmd_hotkey(self, arg):
        with os_bridge.UserInputLock(f"Hotkey {arg}"):
            ok = os_bridge.press_hotkey(arg)
        return _result(f"⚡ Pressed *{arg.upper()}*" if ok else f"⚠️ Unknown hotkey `{arg}`")

    def _xy(self, arg, n=2):
        vals = [int(v) for v in arg.replace(",", " ").split()[:n]]
        if len(vals) != n:
            raise ValueError(f"needs {n} numbers")
        return vals

    def _mouse(self, label, fn):
        with os_bridge.UserInputLock(label) as lock:
            ok = fn()
        return ok, self._lock_note(lock)

    def cmd_click(self, arg, button="left", double=False, label="Clicked"):
        x, y = self._xy(arg)
        ok, note = self._mouse(label, lambda: os_bridge.mouse_click(x, y, button=button, double=double))
        return _result(f"🖱️ {label} at *({x}, {y})*{note}" if ok else f"⚠️ {label} failed")

    def cmd_rclick(self, arg):
        return self.cmd_click(arg, button="right", label="Right-clicked")

    def cmd_dclick(self, arg):
        return self.cmd_click(arg, double=True, label="Double-clicked")

    def cmd_click_here(self, arg):
        ok, note = self._mouse("Click", lambda: os_bridge.mouse_click())
        return _result(f"🖱️ Clicked at the current mouse position{note}" if ok else "⚠️ Click failed")

    def cmd_move(self, arg):
        x, y = self._xy(arg)
        ok, note = self._mouse("Move", lambda: os_bridge.mouse_move(x, y))
        return _result(f"🖱️ Mouse moved to *({x}, {y})*" if ok else "⚠️ Move failed")

    def cmd_drag(self, arg):
        x1, y1, x2, y2 = self._xy(arg, 4)
        ok, note = self._mouse("Drag", lambda: os_bridge.mouse_drag(x1, y1, x2, y2))
        return _result(f"🖱️ Dragged *({x1}, {y1}) → ({x2}, {y2})*{note}" if ok else "⚠️ Drag failed")

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
