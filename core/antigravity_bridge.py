"""Antigravity bridge: Video Studio bot messages -> Antigravity DESKTOP app -> reply via the Video Studio bot.

Bot 2 (tools/videostudio_bot.py, in the pipeline folder) only queues the owner's messages. This bridge
(running inside bot 1, the PC controller) types each queued message into a dedicated conversation of the
pipeline project in the Antigravity desktop app. Antigravity (following GEMINI.md and the pipeline rules)
does the work and answers the owner itself with:  python -I tools/telegram_bot.py send "<reply>"

So every answer still comes from Antigravity (TELEGRAM_SETUP.md Rule 1). The bridge never edits pipeline
files; it only reads/removes queue files and types into the Antigravity window.

The bridge stays out of the way when an Antigravity session is already listening by itself
(tools/wait_for_telegram_msg.py running) and while bot 1's own agent is using the mouse/keyboard.
"""
import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import config
from . import memory_logger
from . import os_bridge
from . import ui_elements

POLL_SEC = 3
UI_LOCK = threading.Lock()  # one writer into the Antigravity window at a time (bridge + /studio session)
BUSY_WORDS = ("stop", "cancel")  # Antigravity shows a Stop/Cancel button while the agent is working


def _tools() -> Path:
    return Path(config.VIDEOSTUDIO_DIR) / "tools"


def _state_file() -> Path:
    return _tools() / ".antigravity_bridge.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        _state_file().write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def _pid_alive(pid) -> bool:
    try:
        from . import studio_control
        return studio_control._pid_alive(pid)
    except Exception:
        return False


def ide_listener_active() -> bool:
    """True if an Antigravity session is already waiting on Telegram itself (wait_for_telegram_msg.py)."""
    try:
        d = json.loads((_tools() / ".telegram_listener.json").read_text(encoding="utf-8"))
        return _pid_alive(d.get("pid"))
    except Exception:
        return False


def pending_messages() -> list:
    q = _tools() / ".telegram_queue"
    return sorted(q.glob("msg_*.json")) if q.exists() else []


def _memory_context() -> str:
    """The pipeline's own memory text (notes + recent messages), loaded from its helper module."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("vs_tq_bridge", str(_tools() / "telegram_queue.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.memory_context(history_n=8)
    except Exception:
        return ""


BOOTSTRAP = (
    "TELEGRAM SESSION — Video Studio bot.\n"
    "You are the owner's video-pipeline assistant on Telegram for this session. He is away from the PC. His "
    "Telegram messages to the Video Studio bot are typed into this conversation automatically by his PC-control "
    "bot. FIRST run  python -I tools/telegram_session.py start  (GEMINI.md rule 0). Never stop the Video Studio "
    "bot, also not when the video is finished - only the owner or his PC bot does that.\n"
    "Work exactly as you normally do in this project:\n"
    "- Follow GEMINI.md, the workflows in .agent/workflows, the stage gates (tools/gate.py) and every pipeline "
    "rule. Use the pipeline's normal CLI commands; do not change tools or gate numbers.\n"
    "- ★ approvals: ask with  python -I tools/telegram_bot.py approve <video> <stage> --async [--img <preview>]  "
    "(returns at once; he taps ✅/❌ on his phone, the bot records it with gate.py and sends you a message "
    "'[APPROVAL APPROVED/REJECTED] ...'). Never wait blocking for it and never record an approval he did not give.\n"
    "- Do not edit files in tools/ on your own; if a tool is broken, tell him on Telegram what and why and wait for "
    "his OK.\n"
    "Talk to him ONLY through tools/telegram_bot.py (he cannot see this window):\n"
    "  text:        python -I tools/telegram_bot.py send \"<message>\"\n"
    "  image:       python -I tools/telegram_bot.py photo <path> \"<caption>\"\n"
    "  any file:    python -I tools/telegram_bot.py document <path> \"<caption>\"   (<= 50 MB)\n"
    "  screenshot:  python -I tools/telegram_bot.py screenshot \"<caption>\"\n"
    "Be a proactive assistant: reply to every message; send a short update when you start and finish each stage, "
    "with real numbers and file names; send contact sheets / thumbnails / previews when useful; if something fails "
    "or needs his decision, tell him right away. Keep messages short, Hinglish is fine, no canned phrases.\n"
    "PC tasks outside this pipeline (opening other apps, YouTube upload) belong to his PC bot — tell him to send "
    "them there. His notes and recent chat come with the first message; more with "
    "python -I tools/telegram_memory.py show\n"
    "Never print or send tokens, keys or .secrets.env contents.\n"
)


def build_prompt(item: dict, first: bool) -> str:
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.get("t", time.time())))
    msg = f"[Telegram from {item.get('from', 'Owner')}, {when}]\n{item.get('text', '')}"
    if first:
        ctx = _memory_context()
        return BOOTSTRAP + ("\n" + ctx + "\n" if ctx else "") + "\n" + msg
    return msg + "\n\n(Reply via tools/telegram_bot.py send.)"


# ----------------------------------------------------------------------
# Antigravity window driving
# ----------------------------------------------------------------------
def _exe() -> str:
    return config.ANTIGRAVITY_EXE or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe")


def _process_name(hwnd) -> str:
    import ctypes
    from ctypes import wintypes
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def _window():
    """The Antigravity desktop (Agent Manager) window, found by its program - its title changes with
    the open conversation. If there are several Antigravity windows, the one with a message box wins."""
    candidates = [h for h, _ in os_bridge.list_windows() if _process_name(h).lower() == "antigravity.exe"]
    if len(candidates) > 1:
        for h in candidates:
            if any(e.name == "Message input" for e in _elements(h)):
                return h
    return candidates[0] if candidates else None


def _elements(hwnd):
    return ui_elements.list_elements(hwnd=hwnd, max_items=400, screen_bounds=os_bridge.get_virtual_screen())


def _find(els, type_=None, name=None, contains=None):
    for e in els:
        if type_ and e.type != type_:
            continue
        n = e.name.lower()
        if name is not None and n != name.lower():
            continue
        if contains is not None and contains.lower() not in n:
            continue
        return e
    return None


def ensure_window(timeout: float = 40):
    hwnd = _window()
    if hwnd:
        return hwnd
    try:
        os.startfile(_exe())
    except Exception as e:
        raise RuntimeError(f"can't start Antigravity ({e})")
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(1)
        hwnd = _window()
        if hwnd:
            time.sleep(3)
            return hwnd
    raise RuntimeError("Antigravity did not open")


def antigravity_busy(els) -> bool:
    return any(e.type == "Button" and e.name.lower().startswith(BUSY_WORDS) for e in els)


def _project_row(els, project: str):
    proj = _find(els, "Button", name=project)
    if not proj:
        return None, None
    # "New Conversation in Project" sits on the same row as the project button
    new_btn = next((e for e in els if e.name == "New Conversation in Project" and abs(e.center[1] - proj.center[1]) < 12), None)
    return proj, new_btn


def _project_conversations(els, project: str) -> list:
    """Conversation links listed under the project: between its row and the next project's row."""
    proj = _find(els, "Button", name=project)
    if not proj:
        return []
    y0 = proj.center[1]
    next_rows = [e.center[1] for e in els if e.name == "Project options" and e.center[1] > y0 + 5]
    settings = _find(els, "Button", name="Settings")
    y1 = min(next_rows + ([settings.center[1]] if settings else []) + [10 ** 9])
    return [e for e in els if e.type == "Hyperlink" and e.name != "New Conversation in Project"
            and y0 < e.center[1] < y1 and e.center[0] < 420]


def _focus():
    hwnd = ensure_window()
    os_bridge.force_foreground(hwnd)
    os_bridge.wait_foreground_ready(timeout=3)
    return hwnd


def _find_session(els, state):
    """The active Telegram session's conversation link. Antigravity renames conversations after the first
    reply, so if the saved title is gone, the newest conversation that did not exist before is taken."""
    project = config.ANTIGRAVITY_PROJECT
    convs = _project_conversations(els, project)
    if state.get("conversation"):
        conv = next((c for c in convs if c.name == state["conversation"]), None)
        if conv:
            return conv
    before = set(state.get("known_before") or [])
    if before:
        fresh = [c for c in convs if c.name not in before]
        if fresh:
            state["conversation"] = fresh[0].name
            _save_state(state)
            return fresh[0]
    return next((c for c in convs if "telegram" in c.name.lower()), None)


def _wait_not_busy(hwnd):
    end = time.time() + config.ANTIGRAVITY_BUSY_WAIT_SEC
    els = _elements(hwnd)
    while antigravity_busy(els):
        if time.time() > end:
            raise RuntimeError("Antigravity is still busy with the previous message")
        time.sleep(3)
        els = _elements(hwnd)
    return els


def _type_and_send(hwnd, els, text: str):
    box = _find(els, "ComboBox", name="Message input") or _find(els, contains="message input")
    if not box:
        raise RuntimeError("Antigravity's message box was not found")
    with os_bridge.UserInputLock("Antigravity bridge"):
        os_bridge.mouse_click(*box.center)
        time.sleep(0.2)
        if not os_bridge._paste_text(text):
            raise RuntimeError("could not paste into Antigravity")
        time.sleep(0.3)
        os_bridge.press_key("enter")
    time.sleep(2.5)


def new_session(task: str, sender: str = "Owner") -> str:
    """Starts a NEW conversation in the pipeline project with the Telegram assistant brief + the task.
    Later Video Studio bot messages go to this session. Returns its title."""
    project = config.ANTIGRAVITY_PROJECT
    hwnd = _focus()
    els = _elements(hwnd)
    proj, new_btn = _project_row(els, project)
    if not new_btn:
        raise RuntimeError(f"project '{project}' not found in Antigravity's sidebar")
    before = [c.name for c in _project_conversations(els, project)]
    os_bridge.mouse_click(*new_btn.center)
    time.sleep(1.5)
    els = _elements(hwnd)
    ctx = _memory_context()
    when = time.strftime("%Y-%m-%d %H:%M")
    text = (BOOTSTRAP + ("\n" + ctx + "\n" if ctx else "") +
            f"\n[Telegram from {sender}, {when}] NEW SESSION. Task:\n{task.strip() or 'Wait for my instructions.'}\n\n"
            "First send me a short Telegram message that this session is ready and what you will do.")
    _type_and_send(hwnd, els, text)
    state = {"conversation": "", "known_before": before, "started": when, "task": task[:300]}
    _save_state(state)
    for _ in range(10):
        conv = _find_session(_elements(hwnd), state)
        if conv:
            return conv.name
        time.sleep(2)
    return "(new conversation)"


def start_session(task: str, sender: str = "Owner") -> str:
    """Thread-safe new_session() for bot 1's /studio session command."""
    with UI_LOCK:
        try:
            return new_session(task, sender)
        finally:
            os_bridge.release_input_lock()


def deliver(item: dict) -> str:
    """Types one Telegram message into the active session. Returns a short result text.
    Raises RuntimeError when it couldn't (the message then stays queued)."""
    hwnd = _focus()
    els = _elements(hwnd)
    state = _load_state()
    conv = _find_session(els, state)
    if conv is None:  # no session yet: start one with this message as the task
        return "started a new session: " + new_session(item.get("text", ""), item.get("from", "Owner"))
    os_bridge.mouse_click(*conv.center)
    time.sleep(1.2)
    els = _wait_not_busy(hwnd)
    _type_and_send(hwnd, els, build_prompt(item, first=False))
    return "sent"


class Bridge:
    """Background thread in bot 1: delivers queued Video Studio messages to Antigravity."""

    IDLE_NEEDED = 4.0        # seconds without keyboard/mouse use before the bridge may take the mouse
    MAX_WAIT_FOR_IDLE = 300  # a message never waits longer than this for the owner to stop using the PC

    def __init__(self, can_use_input: Callable[[], bool], notify_owner: Callable[[str], None]):
        self.can_use_input = can_use_input
        self.notify_owner = notify_owner
        self._last_error = ""
        self._lock = threading.Lock()
        self._own_input_until = 0.0   # our own typing counts as "input" for GetLastInputInfo
        self._waiting_since = 0.0

    def start(self):
        threading.Thread(target=self._loop, name="antigravity-bridge", daemon=True).start()

    def _heartbeat(self):
        """Tells the Video Studio bot service that somebody is going to answer (so it shows 👀, not 💤)."""
        try:
            tmp = _tools() / ".antigravity_bridge_alive.tmp"
            tmp.write_text(json.dumps({"pid": os.getpid(), "beat": time.time()}), encoding="utf-8")
            os.replace(tmp, _tools() / ".antigravity_bridge_alive.json")
        except Exception:
            pass

    def _user_is_busy(self) -> bool:
        """True while the owner is using the PC (so we don't grab his mouse mid-action), at most MAX_WAIT_FOR_IDLE."""
        if time.time() < self._own_input_until:
            return False
        if os_bridge.seconds_since_user_input() >= self.IDLE_NEEDED:
            self._waiting_since = 0.0
            return False
        if not self._waiting_since:
            self._waiting_since = time.time()
        if time.time() - self._waiting_since > self.MAX_WAIT_FOR_IDLE:
            return False
        return True

    def _loop(self):
        while True:
            self._heartbeat()
            time.sleep(POLL_SEC)
            try:
                self.tick()
            except Exception as e:
                print(f"[Bridge] error: {e}")

    def tick(self) -> Optional[str]:
        with UI_LOCK:
            files = pending_messages()
            if not files or ide_listener_active() or not self.can_use_input() or self._user_is_busy():
                return None
            path = files[0]
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                path.unlink(missing_ok=True)
                return None
            if item.get("text", "").strip().lower() in ("/start", "start"):
                path.unlink(missing_ok=True)
                return None
            try:
                res = deliver(item)
            except Exception as e:
                err = str(e)
                if err != self._last_error:  # tell the owner once per kind of problem
                    self._last_error = err
                    self.notify_owner(f"⚠️ Couldn't pass your Video Studio message to Antigravity: {err}. "
                                      f"I'll keep retrying.")
                memory_logger.log_entry("ANTIGRAVITY_BRIDGE", "Delivery failed", details={"error": err[:200]})
                return None
            finally:
                os_bridge.release_input_lock()
                self._own_input_until = time.time() + 8  # our typing must not look like the owner using the PC
            self._last_error = ""
            path.unlink(missing_ok=True)
            memory_logger.log_entry("ANTIGRAVITY_BRIDGE", f"Delivered to Antigravity ({res})",
                                    details={"message": item.get("text", "")[:200]})
            return res
