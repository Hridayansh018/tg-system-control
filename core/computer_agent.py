"""Computer-use agent: "do anything on this PC" from Telegram.

Loop for each task:
    screenshot -> downscale -> vision model picks ONE next action (strict JSON)
    -> validate -> safety check (approval card if risky) -> execute -> repeat
until the model says done / fail, the user sends /stop, or AGENT_MAX_STEPS is reached.

The model is behind the `Brain` interface so other providers can be plugged in later.
The Telegram side is behind the `AgentUI` interface (implemented in bot/listener.py).
"""
import base64
import io
import json
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import config
from . import agent_safety
from . import llm_router
from . import memory_logger
from . import os_bridge

AGENT_VISION_MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"]
MAX_IMAGE_SIDE = 1568

COORD_ACTIONS = {"click", "double_click", "right_click", "move"}
ACTIONS = {
    "click", "double_click", "right_click", "move", "drag", "scroll", "type_text", "press_key", "hotkey",
    "open_app", "close_app", "focus_window", "open_url", "run_shell", "read_file", "list_dir", "wait",
    "clipboard_get", "clipboard_set", "volume", "media", "send_screenshot", "send_file_to_user",
    "upload_file", "done", "fail", "ask_user",
}

ACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "thought": {"type": "STRING"},
        "action": {"type": "STRING", "enum": sorted(ACTIONS)},
        "x": {"type": "INTEGER"}, "y": {"type": "INTEGER"},
        "x2": {"type": "INTEGER"}, "y2": {"type": "INTEGER"},
        "text": {"type": "STRING"}, "key": {"type": "STRING"},
        "amount": {"type": "INTEGER"}, "app": {"type": "STRING"}, "url": {"type": "STRING"},
        "command": {"type": "STRING"}, "path": {"type": "STRING"}, "seconds": {"type": "NUMBER"},
        "risky": {"type": "BOOLEAN"}, "risk_reason": {"type": "STRING"},
        "summary": {"type": "STRING"}, "question": {"type": "STRING"},
    },
    "required": ["thought", "action"],
}

SYSTEM_PROMPT = """You are a careful computer-use agent operating the user's {os_name} PC on their behalf.
Each turn you get a screenshot ({w}x{h} pixels, origin top-left), the task, the open windows and your
previous steps. Reply with exactly ONE next action as JSON.

Actions and fields:
- click / double_click / right_click / move: x, y (pixel coordinates in THIS screenshot)
- drag: x, y -> x2, y2
- scroll: amount (negative = down, positive = up, notches), optional x, y to scroll over
- type_text: text (types into the focused field; click the field first)
- press_key: key (enter, tab, esc, backspace, up, down, f5 ...)
- hotkey: key (e.g. "ctrl+l", "ctrl+t", "alt+tab", "ctrl+shift+o")
- open_app: app (installed app or website name, e.g. "edge", "notepad", "youtube studio")
- close_app: app
- focus_window: text (part of the window title)
- open_url: url
- run_shell: command ({shell}). Prefer read-only commands. Never use it to bypass the GUI for risky things.
- read_file: path (text files only) / list_dir: path
- wait: seconds (max 15) for pages/apps to load
- clipboard_get / clipboard_set: text
- volume: key = up|down|mute ; media: key = play|next|prev
- send_screenshot: send the current screen to the user (text = caption)
- send_file_to_user: path (send a file from the PC to the user's phone)
- upload_file: path. To upload a file to a website/app: FIRST click its Upload / Choose file / attach
  button so the Windows "Open" file picker appears, THEN use upload_file with the full path.
  Files the user sent from their phone are in: {inbox}
- ask_user: question (when you need information or the user must act, e.g. log in)
- done: summary (task finished - say what you did and the result)
- fail: summary (explain why it cannot be done)

Rules:
- Look at the screenshot carefully before clicking; target the centre of buttons and fields.
- One small step at a time. After opening apps or pages, use wait if the screen is still loading.
- NEVER type passwords, PINs, one-time codes, card numbers or other secrets: use ask_user so the user does it.
- Set risky=true (with risk_reason) BEFORE anything that sends messages/emails/posts, buys or pays,
  deletes or moves files, installs or uninstalls software, changes settings or accounts, or can lose work.
- If the same thing fails twice, try another way; if stuck, ask_user or fail.
- Use the user's language for ask_user/done/fail text (Hinglish is fine).
"""


class AgentError(Exception):
    pass


# ----------------------------------------------------------------------
# Screen capture & coordinate mapping
# ----------------------------------------------------------------------
@dataclass
class ScreenFrame:
    image_b64: str          # downscaled JPEG for the model
    width: int              # downscaled size
    height: int
    origin_x: int           # virtual-screen origin (multi-monitor can be negative)
    origin_y: int
    scale: float            # real pixels per screenshot pixel
    path: Optional[str] = None  # full-resolution JPEG for Telegram


def scale_for(real_w: int, real_h: int, max_side: int = MAX_IMAGE_SIDE) -> float:
    longest = max(real_w, real_h)
    return longest / max_side if longest > max_side else 1.0


def to_screen(frame: ScreenFrame, x: int, y: int) -> tuple:
    """Maps screenshot coordinates to real (virtual-desktop) screen coordinates."""
    return (frame.origin_x + int(round(x * frame.scale)), frame.origin_y + int(round(y * frame.scale)))


def capture_frame(save_path: Optional[Path] = None) -> ScreenFrame:
    from PIL import ImageGrab

    os_bridge.attach_to_input_desktop()
    os_bridge.ensure_dpi_aware()
    left, top, _, _ = os_bridge.get_virtual_screen()
    try:
        img = ImageGrab.grab(all_screens=True)
    except TypeError:
        img = ImageGrab.grab()
        left, top = 0, 0
    img = img.convert("RGB")
    if save_path:
        img.save(str(save_path), "JPEG", quality=80)
    scale = scale_for(*img.size)
    small = img if scale == 1.0 else img.resize((int(img.size[0] / scale), int(img.size[1] / scale)))
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=70)
    return ScreenFrame(base64.b64encode(buf.getvalue()).decode(), small.size[0], small.size[1],
                       left, top, scale, str(save_path) if save_path else None)


# ----------------------------------------------------------------------
# Action validation
# ----------------------------------------------------------------------
def _int(v, name):
    try:
        return int(v)
    except Exception:
        raise AgentError(f"'{name}' must be a number")


def validate_action(data, frame_w: int, frame_h: int) -> dict:
    """Checks the model's JSON. Unknown actions, missing fields and off-screen coordinates are rejected."""
    if not isinstance(data, dict):
        raise AgentError("Model reply is not a JSON object")
    act = str(data.get("action") or "").strip()
    if act not in ACTIONS:
        raise AgentError(f"Unknown action '{act}'")
    a = {k: v for k, v in data.items() if v not in (None, "")}
    a["action"] = act
    a["thought"] = str(data.get("thought") or "")[:500]

    def need(field_name):
        if not str(a.get(field_name) or "").strip():
            raise AgentError(f"'{act}' needs '{field_name}'")
        return str(a[field_name])

    def in_bounds(xk, yk):
        x, y = _int(a.get(xk), xk), _int(a.get(yk), yk)
        if not (0 <= x < frame_w and 0 <= y < frame_h):
            raise AgentError(f"Coordinates ({x}, {y}) are outside the {frame_w}x{frame_h} screenshot")
        a[xk], a[yk] = x, y

    if act in COORD_ACTIONS:
        in_bounds("x", "y")
    elif act == "drag":
        in_bounds("x", "y")
        in_bounds("x2", "y2")
    elif act == "scroll":
        a["amount"] = max(-20, min(20, _int(a.get("amount", -3), "amount"))) or -3
        if "x" in a or "y" in a:
            in_bounds("x", "y")
    elif act in ("type_text", "clipboard_set"):
        need("text")
    elif act in ("press_key", "hotkey"):
        key = need("key")
        if os_bridge.parse_hotkey(key) is None:
            raise AgentError(f"Unknown key '{key}'")
    elif act in ("open_app", "close_app"):
        need("app")
    elif act == "focus_window":
        need("text")
    elif act == "open_url":
        need("url")
    elif act == "run_shell":
        need("command")
    elif act in ("read_file", "list_dir", "send_file_to_user", "upload_file"):
        need("path")
    elif act == "wait":
        try:
            a["seconds"] = max(0.5, min(15.0, float(a.get("seconds", 2))))
        except Exception:
            a["seconds"] = 2.0
    elif act in ("volume", "media"):
        key = need("key").lower()
        allowed = {"volume": {"up", "down", "mute"}, "media": {"play", "pause", "next", "prev", "previous", "stop"}}[act]
        if key not in allowed:
            raise AgentError(f"'{act}' key must be one of {sorted(allowed)}")
        a["key"] = key
    elif act == "ask_user":
        need("question")
    elif act in ("done", "fail"):
        a["summary"] = str(a.get("summary") or a["thought"] or act)
    return a


def describe(a: dict) -> str:
    act = a["action"]
    if act in COORD_ACTIONS:
        return f"{act} ({a['x']}, {a['y']})"
    if act == "drag":
        return f"drag ({a['x']}, {a['y']}) → ({a['x2']}, {a['y2']})"
    for k in ("text", "key", "app", "url", "command", "path", "question", "summary"):
        if a.get(k):
            v = str(a[k]).replace("\n", " ")
            return f"{act}: {v[:80]}"
    if act == "scroll":
        return f"scroll {a.get('amount')}"
    if act == "wait":
        return f"wait {a.get('seconds')}s"
    return act


# ----------------------------------------------------------------------
# Brains (vision models)
# ----------------------------------------------------------------------
class Brain:
    name = "base"

    def next_action(self, task: str, frame: ScreenFrame, history: List[str], windows: List[str]) -> dict:
        raise NotImplementedError


class GeminiBrain(Brain):
    name = "gemini"

    def __init__(self):
        override = [m.strip() for m in (config.AGENT_MODEL or "").split(",") if m.strip()]
        self.models = override + [m for m in AGENT_VISION_MODELS if m not in override]

    def next_action(self, task, frame, history, windows):
        os_name = "Windows" if os_bridge.IS_WINDOWS else ("macOS" if os_bridge.IS_MAC else "Linux")
        system = SYSTEM_PROMPT.format(os_name=os_name, w=frame.width, h=frame.height,
                                      shell="PowerShell" if os_bridge.IS_WINDOWS else "bash",
                                      inbox=str(config.INBOX_DIR))
        inbox = recent_inbox_files()
        prompt = (
            f"TASK: {task}\n\n"
            f"OPEN WINDOWS: {', '.join(windows[:25]) or 'unknown'}\n\n"
            + (f"FILES RECENTLY SENT BY THE USER (newest first): {', '.join(inbox)}\n\n" if inbox else "") +
            f"PREVIOUS STEPS (oldest first):\n" + ("\n".join(history[-15:]) or "(none yet)") +
            "\n\nWhat is the single next action?"
        )
        res = llm_router.call_gemini(prompt, system, json_schema=ACTION_SCHEMA,
                                     image_parts=[{"mime_type": "image/jpeg", "data": frame.image_b64}],
                                     models=self.models, timeout=60)
        if "error" in res:
            raise AgentError(f"Gemini: {res['error']}")
        return llm_router.extract_json(res["reply"])


def recent_inbox_files(limit: int = 8) -> List[str]:
    try:
        files = [f for f in config.INBOX_DIR.iterdir() if f.is_file()]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return [str(f) for f in files[:limit]]
    except Exception:
        return []


def default_brain() -> Optional[Brain]:
    if config.GEMINI_API_KEY:
        return GeminiBrain()
    return None


# ----------------------------------------------------------------------
# Telegram-facing interface (implemented by the listener)
# ----------------------------------------------------------------------
class AgentUI:
    def send_text(self, text: str) -> Optional[int]: ...
    def edit_text(self, message_id: int, text: str): ...
    def send_photo(self, path: str, caption: str = ""): ...
    def send_document(self, path: str, caption: str = ""): ...
    def request_approval(self, title: str, details: str, cancel: threading.Event) -> bool: ...
    def ask_user(self, question: str, cancel: threading.Event) -> Optional[str]: ...


@dataclass
class AgentTask:
    text: str
    id: int
    created: float = field(default_factory=time.time)
    step: int = 0
    status: str = "queued"
    cancel: threading.Event = field(default_factory=threading.Event)


class ComputerAgent:
    """Runs one task at a time in a background thread; more tasks wait in a queue."""

    def __init__(self, ui: AgentUI, brain: Optional[Brain] = None, max_steps: int = None,
                 require_approval: bool = None, settle_sec: float = 0.8):
        self.ui = ui
        self.brain = brain
        self.max_steps = max_steps or config.AGENT_MAX_STEPS
        self.require_approval = config.AGENT_REQUIRE_APPROVAL if require_approval is None else require_approval
        self.settle_sec = settle_sec
        self.queue: "queue.Queue[AgentTask]" = queue.Queue()
        self.current: Optional[AgentTask] = None
        self._ids = 0
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._work, name="computer-agent", daemon=True)
        self._worker.start()

    # --- control from Telegram -----------------------------------------
    def available(self) -> bool:
        return self.brain is not None

    def submit(self, text: str) -> str:
        with self._lock:
            self._ids += 1
            task = AgentTask(text=text.strip(), id=self._ids)
        busy = self.current is not None or not self.queue.empty()
        self.queue.put(task)
        memory_logger.log_entry("AGENT_TASK", f"Queued task #{task.id}", details={"task": task.text[:300]})
        if busy:
            return f"🕒 Task #{task.id} queued (another task is running). /task shows progress, /stop cancels."
        return ""

    def stop(self) -> str:
        cancelled = 0
        while True:
            try:
                t = self.queue.get_nowait()
                t.cancel.set()
                cancelled += 1
            except queue.Empty:
                break
        cur = self.current
        os_bridge.release_input_lock()
        if cur:
            cur.cancel.set()
            return f"🛑 Stopping task #{cur.id}" + (f" and cleared {cancelled} queued task(s)." if cancelled else ".")
        return f"🛑 Cleared {cancelled} queued task(s)." if cancelled else "Nothing is running."

    def busy(self) -> bool:
        return self.current is not None

    def status_text(self) -> str:
        cur = self.current
        if not cur:
            return "😴 No agent task running." + (f" {self.queue.qsize()} queued." if not self.queue.empty() else "")
        mins = int((time.time() - cur.created) // 60)
        return (f"🤖 Task #{cur.id}: _{cur.text[:200]}_\n"
                f"Step {cur.step}/{self.max_steps} · {cur.status} · {mins} min · {self.queue.qsize()} queued\n"
                f"/stop to cancel")

    # --- worker ---------------------------------------------------------
    def _work(self):
        while True:
            task = self.queue.get()
            if task.cancel.is_set():
                continue
            self.current = task
            try:
                self._run(task)
            except Exception as e:
                traceback.print_exc()
                self.ui.send_text(f"⚠️ Agent crashed on task #{task.id}: `{e}`")
                memory_logger.log_entry("AGENT_ERROR", f"Task #{task.id} crashed", details={"error": str(e)[:300]})
            finally:
                os_bridge.release_input_lock()
                self.current = None

    def _progress(self, task: AgentTask, msg_id, lines: List[str]):
        text = f"🤖 *Agent task #{task.id}*\n_{task.text[:300]}_\n\n" + "\n".join(lines[-8:]) + "\n\n/stop to cancel · /task for status"
        if msg_id:
            self.ui.edit_text(msg_id, text)
        return msg_id

    def _run(self, task: AgentTask):
        if not self.brain:
            self.ui.send_text("⚠️ Agent mode needs `GEMINI_API_KEY` in `.env`.")
            return
        task.status = "running"
        lines: List[str] = ["▶️ Starting…"]
        msg_id = self.ui.send_text(f"🤖 *Agent task #{task.id}*\n_{task.text[:300]}_\n\n▶️ Starting…")
        history: List[str] = []
        invalid_streak = 0
        final_text, final_icon = None, "✅"

        for step in range(1, self.max_steps + 1):
            if task.cancel.is_set():
                final_text, final_icon = "Stopped by you.", "🛑"
                break
            task.step = step
            shot_path = config.SCREENSHOTS_DIR / f"agent_{task.id}_{step}.jpg"
            frame = capture_frame(shot_path)
            windows = [t for _, t in os_bridge.list_windows()]

            try:
                action = validate_action(self.brain.next_action(task.text, frame, history, windows), frame.width, frame.height)
                invalid_streak = 0
            except Exception as e:
                invalid_streak += 1
                history.append(f"{step}. (invalid reply: {e})")
                lines.append(f"⚠️ {step}: model reply rejected ({str(e)[:80]})")
                self._progress(task, msg_id, lines)
                if invalid_streak >= 3:
                    final_text, final_icon = f"The AI kept giving invalid answers: {e}", "⚠️"
                    break
                time.sleep(2)
                continue

            desc = describe(action)
            lines.append(f"{step}. {action['thought'][:120]}\n   ➜ `{desc}`")
            self._progress(task, msg_id, lines)
            memory_logger.log_entry("AGENT_STEP", f"Task #{task.id} step {step}: {desc}",
                                    details={"task": task.text[:200]}, thinking=action["thought"])

            if action["action"] in ("done", "fail"):
                final_text = action["summary"]
                final_icon = "✅" if action["action"] == "done" else "❌"
                break

            # Hard blocks
            if action["action"] in ("type_text", "clipboard_set"):
                blocked = agent_safety.blocked_text_reason(action.get("text", ""), action["thought"])
                if blocked:
                    history.append(f"{step}. BLOCKED {desc}: {blocked}. Ask the user to do this part.")
                    lines.append(f"⛔ Blocked: {blocked}")
                    continue

            # Approval
            reason = agent_safety.approval_reason(action) if self.require_approval else None
            if reason:
                task.status = "waiting for your approval"
                approved = self.ui.request_approval(f"Agent step {step}: {desc}", f"{reason}.\nWhy: {action['thought'][:300]}", task.cancel)
                task.status = "running"
                memory_logger.log_entry("AGENT_APPROVAL", f"Step {step} {'approved' if approved else 'declined'}",
                                        details={"action": desc, "reason": reason})
                if not approved:
                    history.append(f"{step}. {desc} -> DECLINED by user ({reason}). Do not retry it; find another way or fail.")
                    lines.append("❌ Declined")
                    if task.cancel.is_set():
                        final_text, final_icon = "Stopped by you.", "🛑"
                        break
                    continue

            if action["action"] == "ask_user":
                task.status = "waiting for your answer"
                answer = self.ui.ask_user(f"❓ *Task #{task.id} asks:* {action['question']}", task.cancel)
                task.status = "running"
                if answer is None:
                    final_text, final_icon = ("Stopped by you." if task.cancel.is_set() else "No answer received."), "🛑"
                    break
                history.append(f"{step}. ask_user: {action['question'][:150]} -> user answered: {answer[:300]}")
                continue

            try:
                result = self._execute(action, frame, task)
            except Exception as e:
                result = f"ERROR: {e}"
            finally:
                os_bridge.release_input_lock()
            history.append(f"{step}. {desc} -> {result[:400]}")

            if step % 5 == 0:
                after = config.SCREENSHOTS_DIR / f"agent_{task.id}_{step}_progress.jpg"
                if os_bridge.take_screenshot(after):
                    self.ui.send_photo(str(after), f"📸 Task #{task.id} · step {step}")

            wait = self.settle_sec * (3 if action["action"] in ("open_app", "open_url") else 1)
            if task.cancel.wait(wait):
                final_text, final_icon = "Stopped by you.", "🛑"
                break
        else:
            final_text, final_icon = f"Reached the {self.max_steps}-step limit before finishing.", "⚠️"

        task.status = "finished"
        lines.append(f"{final_icon} {final_text}")
        self._progress(task, msg_id, lines)
        end_shot = config.SCREENSHOTS_DIR / f"agent_{task.id}_final.jpg"
        caption = f"{final_icon} *Task #{task.id}:* {(final_text or '')[:900]}"
        if os_bridge.take_screenshot(end_shot):
            self.ui.send_photo(str(end_shot), caption)
        else:
            self.ui.send_text(caption)
        memory_logger.log_entry("AGENT_TASK", f"Task #{task.id} finished ({final_icon})",
                                details={"task": task.text[:300], "steps": task.step, "result": (final_text or "")[:300]})

    # --- execution ------------------------------------------------------
    def _execute(self, a: dict, frame: ScreenFrame, task: AgentTask) -> str:
        act = a["action"]
        if act in COORD_ACTIONS or act == "drag" or (act == "scroll" and "x" in a):
            x, y = to_screen(frame, a["x"], a["y"])
        if act in COORD_ACTIONS:
            with os_bridge.UserInputLock("Agent"):
                if act == "move":
                    ok = os_bridge.mouse_move(x, y)
                else:
                    ok = os_bridge.mouse_click(x, y, button="right" if act == "right_click" else "left",
                                               double=act == "double_click")
            return "ok" if ok else "failed"
        if act == "drag":
            x2, y2 = to_screen(frame, a["x2"], a["y2"])
            with os_bridge.UserInputLock("Agent"):
                return "ok" if os_bridge.mouse_drag(x, y, x2, y2) else "failed"
        if act == "scroll":
            with os_bridge.UserInputLock("Agent"):
                ok = os_bridge.mouse_scroll(dy=a["amount"], x=x if "x" in a else None, y=y if "x" in a else None)
            return "ok" if ok else "failed"
        if act == "type_text":
            with os_bridge.UserInputLock("Agent"):
                return "typed" if os_bridge.type_text(a["text"]) else "failed"
        if act == "press_key":
            with os_bridge.UserInputLock("Agent"):
                return "ok" if os_bridge.press_key(a["key"]) else "failed"
        if act == "hotkey":
            with os_bridge.UserInputLock("Agent"):
                return "ok" if os_bridge.press_hotkey(a["key"]) else "failed"
        if act == "open_app":
            r = os_bridge.launch_app(a["app"])
            return r["stdout"] or r["stderr"]
        if act == "close_app":
            r = os_bridge.close_app(a["app"])
            return r["stdout"] or r["stderr"]
        if act == "focus_window":
            return "focused" if os_bridge.focus_window(a["text"]) else "no matching window"
        if act == "open_url":
            r = os_bridge.open_url(a["url"])
            return r["stdout"] or r["stderr"]
        if act == "run_shell":
            r = os_bridge.run_command(a["command"], timeout=60)
            return f"exit {r['exit_code']}: {(r['stdout'] or r['stderr'])[:1500]}"
        if act == "read_file":
            p = Path(a["path"]).expanduser()
            if not p.is_file():
                return "file not found"
            return p.read_text(encoding="utf-8", errors="replace")[:4000]
        if act == "list_dir":
            p = Path(a["path"]).expanduser()
            if not p.is_dir():
                return "folder not found"
            items = sorted(p.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)[:60]
            return "\n".join(f"{'[dir] ' if f.is_dir() else ''}{f.name}" + ("" if f.is_dir() else f" ({f.stat().st_size} bytes)") for f in items)
        if act == "wait":
            task.cancel.wait(a["seconds"])
            return "waited"
        if act == "clipboard_get":
            return (os_bridge.get_clipboard() or "")[:2000]
        if act == "clipboard_set":
            return "ok" if os_bridge.set_clipboard(a["text"]) else "failed"
        if act in ("volume", "media"):
            return "ok" if os_bridge.media_key(a["key"]) else "failed"
        if act == "send_screenshot":
            p = config.SCREENSHOTS_DIR / f"agent_{task.id}_{task.step}_sent.jpg"
            if os_bridge.take_screenshot(p):
                self.ui.send_photo(str(p), a.get("text", "") or f"📸 Task #{task.id}")
                return "sent"
            return "screenshot failed"
        if act == "upload_file":
            r = os_bridge.upload_file_dialog(a["path"])
            return r["stdout"] or r["stderr"]
        if act == "send_file_to_user":
            p = Path(a["path"]).expanduser()
            if not p.is_file():
                return "file not found"
            if p.stat().st_size > 49 * 1024 * 1024:
                return "file larger than Telegram's 50 MB limit"
            self.ui.send_document(str(p), f"📄 {p.name}")
            return "sent"
        return f"unsupported action {act}"
