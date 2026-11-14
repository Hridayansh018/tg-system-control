"""Computer-use agent: "do anything on this PC" from Telegram.

Loop for each task (one "turn" = one AI call):
    screenshot + list of on-screen elements (buttons, fields, links... from Windows UI Automation,
    numbered and drawn on the screenshot)  ->  AI returns 1-5 actions (strict JSON), preferably
    "click element [12]" instead of guessing pixels  ->  each action is validated, safety-checked
    (approval card if risky) and executed  ->  repeat
until the AI says done / fail, the user sends /stop, or AGENT_MAX_STEPS turns are used.

The model is behind the `Brain` interface so other providers can be plugged in later.
The Telegram side is behind the `AgentUI` interface (implemented in bot/listener.py).
"""
import base64
import io
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import config
from . import agent_safety
from . import conversation_memory
from . import llm_router
from . import memory_logger
from . import os_bridge
from . import ocr
from . import ui_actions
from . import ui_elements

# Fastest first; models that are overloaded / gone are skipped automatically by llm_router.
AGENT_VISION_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]
MAX_IMAGE_SIDE = 1280
MAX_BATCH = 5
MODEL_TIMEOUT_SEC = 25

COORD_ACTIONS = {"click", "double_click", "right_click", "move"}
ELEMENT_ACTIONS = COORD_ACTIONS | {"type_text", "scroll"}
TERMINAL_ACTIONS = {"done", "fail", "ask_user"}
# After these the screen changes a lot, so later actions in the same batch would use stale positions.
SCREEN_CHANGING = {"open_app", "open_url", "focus_window", "close_app", "upload_file"}
ACTIONS = {
    "click", "double_click", "right_click", "move", "drag", "scroll", "type_text", "press_key", "hotkey",
    "open_app", "close_app", "focus_window", "open_url", "run_shell", "read_file", "list_dir", "wait",
    "clipboard_get", "clipboard_set", "volume", "media", "send_screenshot", "send_file_to_user",
    "upload_file", "click_text", "done", "fail", "ask_user",
}

ACTION_ITEM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "action": {"type": "STRING", "enum": sorted(ACTIONS)},
        "element": {"type": "INTEGER"},
        "x": {"type": "INTEGER"}, "y": {"type": "INTEGER"},
        "x2": {"type": "INTEGER"}, "y2": {"type": "INTEGER"},
        "text": {"type": "STRING"}, "key": {"type": "STRING"},
        "amount": {"type": "INTEGER"}, "app": {"type": "STRING"}, "url": {"type": "STRING"},
        "command": {"type": "STRING"}, "path": {"type": "STRING"}, "seconds": {"type": "NUMBER"},
        "risky": {"type": "BOOLEAN"}, "risk_reason": {"type": "STRING"},
        "summary": {"type": "STRING"}, "question": {"type": "STRING"},
    },
    "required": ["action"],
}
STEP_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "thought": {"type": "STRING"},
        "actions": {"type": "ARRAY", "items": ACTION_ITEM_SCHEMA},
    },
    "required": ["thought", "actions"],
}
ACTION_SCHEMA = STEP_SCHEMA  # backwards-compatible name

SYSTEM_PROMPT = """You are a fast, careful computer-use agent operating the user's {os_name} PC.
Each turn you get: a screenshot ({w}x{h} px, origin top-left) where the active window's controls are
marked with numbered boxes, the same ELEMENTS as a numbered text list, the open windows, and your
previous steps. Reply with JSON: a short "thought" and 1-{max_batch} "actions" to run in order.

Pointing at things:
- PREFER "element": N (a number from the ELEMENTS list). It is exact. Use x, y only for things that are
  not in the list (pixel coordinates in THIS screenshot).
- To type into a field: {{"action": "type_text", "element": N, "text": "..."}} clicks field N first.

Actions and fields:
- click / double_click / right_click / move: element (or x, y)
- click_text: text (click where this text is on screen - found by OCR. Use ONLY when the control is not in the
  ELEMENTS list, e.g. a button without an accessible name)
- drag: x, y -> x2, y2
- scroll: amount (negative = down, positive = up, notches), optional element or x, y to scroll over
- type_text: text (optional element to click first)
- press_key: key (enter, tab, esc, backspace, up, down, f5 ...)
- hotkey: key (e.g. "ctrl+l", "ctrl+t", "alt+tab", "ctrl+shift+o")
- open_app: app (installed app or website name, e.g. "edge", "notepad", "youtube studio")
- open_url: url  (fastest way to reach a website page - prefer it over clicking around)
- close_app: app
- focus_window: text (part of the window title)
- run_shell: command ({shell}). Prefer read-only commands.
- read_file: path (text files only) / list_dir: path
- wait: seconds (max 15) for pages/apps to load
- clipboard_get / clipboard_set: text
- volume: key = up|down|mute ; media: key = play|next|prev
- send_screenshot: send the current screen to the user (text = caption)
- send_file_to_user: path (send a file from the PC to the user's phone)
- upload_file: path. FIRST click the site's Upload / Choose file / Attach button (one turn), THEN in the
  next turn use upload_file with the full path. Files the user sent from their phone are in: {inbox}
- ask_user: question (you need information, or the user must log in / approve something themselves)
- done: summary (task finished - say what you did and the result)
- fail: summary (explain why it cannot be done)

Speed rules:
- Batch actions that don't need to see the new screen, e.g. [type_text element 5 "luffy", press_key enter]
  or [click element 3, type_text "hello", press_key enter].
- open_app / open_url / focus_window / close_app / upload_file must be the LAST action of a batch
  (the screen changes, so element numbers become stale).
- done / fail / ask_user must be the last action.
Safety rules:
- NEVER type passwords, PINs, one-time codes, card numbers or other secrets: use ask_user.
- Set risky=true (with risk_reason) on any action that sends messages/emails/posts, buys or pays,
  deletes or moves files, installs or uninstalls software, changes settings or accounts, or can lose work.
- If the same thing fails twice, try another way; if stuck, ask_user or fail.
- Use the user's language for ask_user/done/fail text (Hinglish is fine).
"""


class AgentError(Exception):
    pass


# ----------------------------------------------------------------------
# Screen capture, element marks & coordinate mapping
# ----------------------------------------------------------------------
@dataclass
class ScreenFrame:
    image_b64: str          # downscaled JPEG for the model (with numbered element marks)
    width: int              # downscaled size
    height: int
    origin_x: int           # virtual-screen origin (multi-monitor can be negative)
    origin_y: int
    scale: float            # real pixels per screenshot pixel
    path: Optional[str] = None
    elements: list = field(default_factory=list)   # ui_elements.UIElement, real screen coordinates

    def element(self, eid: int):
        for e in self.elements:
            if e.id == eid:
                return e
        return None


def scale_for(real_w: int, real_h: int, max_side: int = MAX_IMAGE_SIDE) -> float:
    longest = max(real_w, real_h)
    return longest / max_side if longest > max_side else 1.0


def to_screen(frame: ScreenFrame, x: int, y: int) -> tuple:
    """Maps screenshot coordinates to real (virtual-desktop) screen coordinates."""
    return (frame.origin_x + int(round(x * frame.scale)), frame.origin_y + int(round(y * frame.scale)))


def _draw_marks(img, elements, origin_x, origin_y, scale):
    """Set-of-marks: outline every element and put its number on the image the model sees."""
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    for e in elements:
        x0 = (e.x - origin_x) / scale
        y0 = (e.y - origin_y) / scale
        x1 = x0 + e.w / scale
        y1 = y0 + e.h / scale
        draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 140), width=1)
        label = str(e.id)
        tw = 7 * len(label) + 4
        lx, ly = max(0, x0), max(0, y0 - 12)
        draw.rectangle([lx, ly, lx + tw, ly + 12], fill=(255, 0, 140))
        draw.text((lx + 2, ly), label, fill=(255, 255, 255))


def capture_frame(save_path: Optional[Path] = None, with_elements: bool = True) -> ScreenFrame:
    from PIL import ImageGrab

    os_bridge.attach_to_input_desktop()
    os_bridge.ensure_dpi_aware()
    left, top, vw, vh = os_bridge.get_virtual_screen()
    img = None
    for attempt in range(4):  # a grab can fail for a moment (desktop switch, display wake, UAC) - retry, don't crash
        try:
            img = ImageGrab.grab(all_screens=True)
            break
        except TypeError:
            img = ImageGrab.grab()
            left, top = 0, 0
            break
        except OSError:
            time.sleep(0.6 * (attempt + 1))
            os_bridge.attach_to_input_desktop()
            if attempt == 2:  # last resorts: primary screen only
                try:
                    img = ImageGrab.grab()
                    left, top = 0, 0
                    break
                except OSError:
                    pass
    if img is None:
        raise OSError("screen grab failed (screen locked or display off?)")
    img = img.convert("RGB")
    if save_path:
        img.save(str(save_path), "JPEG", quality=80)
    elements = []
    if with_elements:
        try:
            elements = ui_elements.list_elements(screen_bounds=(left, top, img.size[0], img.size[1]))
        except Exception as e:
            print(f"[Agent] element list failed: {e}")
    scale = scale_for(*img.size)
    small = img if scale == 1.0 else img.resize((int(img.size[0] / scale), int(img.size[1] / scale)))
    if elements:
        _draw_marks(small, elements, left, top, scale)
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=70)
    return ScreenFrame(base64.b64encode(buf.getvalue()).decode(), small.size[0], small.size[1],
                       left, top, scale, str(save_path) if save_path else None, elements)


# ----------------------------------------------------------------------
# Action validation
# ----------------------------------------------------------------------
def _int(v, name):
    try:
        return int(v)
    except Exception:
        raise AgentError(f"'{name}' must be a number")


def validate_action(data, frame_w: int, frame_h: int, frame: Optional[ScreenFrame] = None) -> dict:
    """Checks one action. Unknown actions, missing fields, unknown element numbers and
    off-screen coordinates are rejected."""
    if not isinstance(data, dict):
        raise AgentError("Action is not a JSON object")
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

    if "element" in a:
        if act not in ELEMENT_ACTIONS:
            a.pop("element")
        else:
            eid = _int(a["element"], "element")
            el = frame.element(eid) if frame else None
            if el is None:
                raise AgentError(f"Element [{eid}] is not in the ELEMENTS list")
            a["element"] = eid
            a["_screen"] = el.center
            a["_el"] = el
            a["_label"] = f"[{eid}] {el.type} \"{el.name[:40]}\""

    if act in COORD_ACTIONS:
        if "_screen" not in a:
            in_bounds("x", "y")
    elif act == "drag":
        in_bounds("x", "y")
        in_bounds("x2", "y2")
    elif act == "scroll":
        a["amount"] = max(-20, min(20, _int(a.get("amount", -3), "amount"))) or -3
        if "_screen" not in a and ("x" in a or "y" in a):
            in_bounds("x", "y")
    elif act in ("type_text", "clipboard_set"):
        need("text")
    elif act in ("press_key", "hotkey"):
        key = need("key")
        if os_bridge.parse_hotkey(key) is None:
            raise AgentError(f"Unknown key '{key}'")
    elif act in ("open_app", "close_app"):
        need("app")
    elif act == "click_text":
        need("text")
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


def validate_step(data, frame: ScreenFrame) -> tuple:
    """Validates a whole AI reply -> (thought, [actions]). Accepts the old single-action format too.
    Batches are cut after a screen-changing or final action, and to MAX_BATCH actions."""
    if not isinstance(data, dict):
        raise AgentError("Model reply is not a JSON object")
    thought = str(data.get("thought") or "")[:500]
    raw = data.get("actions")
    if raw is None and "action" in data:
        raw = [data]
    if not isinstance(raw, list) or not raw:
        raise AgentError("Model reply has no actions")
    actions = []
    for item in raw[:MAX_BATCH]:
        if isinstance(item, dict) and not item.get("thought"):
            item = dict(item, thought=thought)
        a = validate_action(item, frame.width, frame.height, frame)
        actions.append(a)
        if a["action"] in TERMINAL_ACTIONS or a["action"] in SCREEN_CHANGING:
            break
    return thought, actions


def describe(a: dict) -> str:
    act = a["action"]
    if a.get("_label"):
        extra = f": {str(a['text'])[:60]}" if act == "type_text" and a.get("text") else ""
        return f"{act} {a['_label']}{extra}"
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
    last_seconds = None

    def next_action(self, task: str, frame: ScreenFrame, history: List[str], windows: List[str]) -> dict:
        raise NotImplementedError


class GeminiBrain(Brain):
    name = "gemini"

    def __init__(self):
        override = [m.strip() for m in (config.AGENT_MODEL or "").split(",") if m.strip()]
        self.models = override + [m for m in AGENT_VISION_MODELS if m not in override]

    def next_action(self, task, frame, history, windows):
        os_name = "Windows" if os_bridge.IS_WINDOWS else ("macOS" if os_bridge.IS_MAC else "Linux")
        system = SYSTEM_PROMPT.format(os_name=os_name, w=frame.width, h=frame.height, max_batch=MAX_BATCH,
                                      shell="PowerShell" if os_bridge.IS_WINDOWS else "bash",
                                      inbox=str(config.INBOX_DIR))
        inbox = recent_inbox_files()
        elements = ui_elements.format_for_model(frame.elements) or "(none found - use x, y coordinates)"
        notes = conversation_memory.notes_text()
        prompt = (
            f"TASK: {task}\n\n"
            + (f"USER'S SAVED NOTES (facts and preferences to respect):\n{notes}\n\n" if notes else "") +
            f"OPEN WINDOWS: {', '.join(windows[:25]) or 'unknown'}\n\n"
            + (f"FILES RECENTLY SENT BY THE USER (newest first): {', '.join(inbox)}\n\n" if inbox else "") +
            f"ELEMENTS of the active window (number -> control):\n{elements}\n\n"
            f"PREVIOUS STEPS (oldest first):\n" + ("\n".join(history[-20:]) or "(none yet)") +
            "\n\nWhat are the next actions?"
        )
        res = llm_router.call_gemini(prompt, system, json_schema=STEP_SCHEMA,
                                     image_parts=[{"mime_type": "image/jpeg", "data": frame.image_b64}],
                                     models=self.models, timeout=MODEL_TIMEOUT_SEC)
        if "error" in res:
            raise AgentError(f"Gemini: {res['error']}")
        self.last_seconds = res.get("seconds")
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


class _LatestEdit:
    """Sends progress-message edits in the background (only the newest one matters),
    so Telegram round-trips never slow the agent down."""

    def __init__(self, ui: AgentUI):
        self.ui = ui
        self.pending = None
        self.cv = threading.Condition()
        threading.Thread(target=self._run, name="agent-progress", daemon=True).start()

    def post(self, msg_id, text):
        with self.cv:
            self.pending = (msg_id, text)
            self.cv.notify()

    def _run(self):
        while True:
            with self.cv:
                while self.pending is None:
                    self.cv.wait()
                msg_id, text = self.pending
                self.pending = None
            try:
                self.ui.edit_text(msg_id, text)
            except Exception as e:
                print(f"[Agent] progress edit failed: {e}")

    def flush(self, timeout: float = 5.0):
        end = time.time() + timeout
        while self.pending is not None and time.time() < end:
            time.sleep(0.05)


@dataclass
class AgentTask:
    text: str
    id: int
    created: float = field(default_factory=time.time)
    step: int = 0
    status: str = "queued"
    cancel: threading.Event = field(default_factory=threading.Event)
    max_steps: Optional[int] = None          # per-task turn limit (long workflows like YouTube upload)
    on_done: Optional[object] = None         # callback(ok: bool, final_text: str) after the task ends
    allowed_paths: set = field(default_factory=set)  # files pre-approved for upload_file/send_file_to_user
    label: str = ""                          # short name shown in progress ("YouTube upload", ...)
    confirm_buttons: tuple = ()              # button names that ALWAYS need the user's ✅ (e.g. "schedule")
    expected_words: tuple = ()               # risky words that are this task's normal job (e.g. "send" a prompt)


class ComputerAgent:
    """Runs one task at a time in a background thread; more tasks wait in a queue."""

    def __init__(self, ui: AgentUI, brain: Optional[Brain] = None, max_steps: int = None,
                 require_approval: bool = None, settle_sec: float = 0.6):
        self.ui = ui
        self.brain = brain
        self.max_steps = max_steps or config.AGENT_MAX_STEPS
        self.require_approval = config.AGENT_REQUIRE_APPROVAL if require_approval is None else require_approval
        self.settle_sec = settle_sec
        self.queue: "queue.Queue[AgentTask]" = queue.Queue()
        self.current: Optional[AgentTask] = None
        self._ids = 0
        self._lock = threading.Lock()
        self._edits = _LatestEdit(ui)
        self._worker = threading.Thread(target=self._work, name="computer-agent", daemon=True)
        self._worker.start()
        if os_bridge.IS_WINDOWS:  # start the UI Automation helper now so the first task is fast
            threading.Thread(target=ui_elements.warm_up, name="uia-warmup", daemon=True).start()

    # --- control from Telegram -----------------------------------------
    def available(self) -> bool:
        return self.brain is not None

    def submit(self, text: str, max_steps: Optional[int] = None, on_done=None, allowed_paths=None,
               label: str = "", confirm_buttons=(), expected_words=()) -> str:
        with self._lock:
            self._ids += 1
            task = AgentTask(text=text.strip(), id=self._ids, max_steps=max_steps, on_done=on_done,
                             allowed_paths={str(Path(p).resolve()).lower() for p in (allowed_paths or [])},
                             label=label, confirm_buttons=tuple(b.lower() for b in confirm_buttons),
                             expected_words=tuple(w.lower() for w in expected_words))
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
                f"Turn {cur.step}/{self.max_steps} · {cur.status} · {mins} min · {self.queue.qsize()} queued\n"
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

    @staticmethod
    def _title(task: AgentTask) -> str:
        return task.label or task.text[:300]

    def _progress(self, task: AgentTask, msg_id, lines: List[str]):
        text = f"🤖 *Agent task #{task.id}*\n_{self._title(task)}_\n\n" + "\n".join(lines[-10:]) + "\n\n/stop to cancel · /task for status"
        if msg_id:
            self._edits.post(msg_id, text)
        return msg_id

    def _run(self, task: AgentTask):
        if not self.brain:
            self.ui.send_text("⚠️ Agent mode needs `GEMINI_API_KEY` in `.env`.")
            return
        task.status = "running"
        started = time.time()
        lines: List[str] = ["▶️ Starting…"]
        msg_id = self.ui.send_text(f"🤖 *Agent task #{task.id}*\n_{self._title(task)}_\n\n▶️ Starting…")
        history: List[str] = []
        invalid_streak = 0
        final_text, final_icon = None, "✅"
        n = 0  # action counter across turns
        finished = False
        limit = task.max_steps or self.max_steps

        for turn in range(1, limit + 1):
            if task.cancel.is_set():
                final_text, final_icon = "Stopped by you.", "🛑"
                break
            task.step = turn
            frame = capture_frame()
            windows = [t for _, t in os_bridge.list_windows()]

            t_ai = time.time()
            try:
                thought, actions = validate_step(self.brain.next_action(task.text, frame, history, windows), frame)
                invalid_streak = 0
            except Exception as e:
                invalid_streak += 1
                history.append(f"T{turn}. (invalid reply: {e})")
                lines.append(f"⚠️ T{turn}: AI reply rejected ({str(e)[:80]})")
                self._progress(task, msg_id, lines)
                if invalid_streak >= 3:
                    final_text, final_icon = f"The AI kept giving invalid answers: {e}", "⚠️"
                    break
                if task.cancel.wait(1):
                    final_text, final_icon = "Stopped by you.", "🛑"
                    break
                continue
            ai_sec = getattr(self.brain, "last_seconds", None) or round(time.time() - t_ai, 1)

            lines.append(f"T{turn} · 🧠 {ai_sec}s · {len(frame.elements)} elements · {thought[:110]}")
            self._progress(task, msg_id, lines)
            memory_logger.log_entry("AGENT_STEP", f"Task #{task.id} turn {turn}: {len(actions)} action(s)",
                                    details={"task": task.text[:200], "ai_seconds": ai_sec,
                                             "actions": [describe(a) for a in actions]}, thinking=thought)

            stop_turn = False
            for i, action in enumerate(actions):
                if task.cancel.is_set():
                    break
                n += 1
                desc = describe(action)
                lines.append(f"   ➜ `{desc}`")

                if action["action"] in ("done", "fail"):
                    final_text = action["summary"]
                    final_icon = "✅" if action["action"] == "done" else "❌"
                    finished = True
                    break

                if action["action"] in ("type_text", "clipboard_set"):
                    blocked = agent_safety.blocked_text_reason(action.get("text", ""), action["thought"])
                    if blocked:
                        history.append(f"T{turn}.{i + 1} BLOCKED {desc}: {blocked}. Ask the user to do this part.")
                        lines.append(f"⛔ Blocked: {blocked}")
                        break

                reason = agent_safety.approval_reason(action, task.confirm_buttons, task.expected_words) \
                    if self.require_approval else None
                if not reason and task.confirm_buttons:  # never skip the final button, even with approvals off
                    reason = agent_safety.approval_reason(action, task.confirm_buttons) if \
                        agent_safety._clicked_button_name(action) in task.confirm_buttons else None
                if reason and action["action"] in ("upload_file", "send_file_to_user") and task.allowed_paths:
                    try:  # files the user already approved for this task (e.g. /ytupload's video + thumbnail)
                        if str(Path(action.get("path", "")).resolve()).lower() in task.allowed_paths:
                            reason = None
                    except Exception:
                        pass
                if reason:
                    task.status = "waiting for your approval"
                    self._progress(task, msg_id, lines)
                    approved = self.ui.request_approval(f"Agent: {desc}", f"{reason}.\nWhy: {action['thought'][:300]}", task.cancel)
                    task.status = "running"
                    memory_logger.log_entry("AGENT_APPROVAL", f"{'Approved' if approved else 'Declined'}: {desc}",
                                            details={"reason": reason})
                    if not approved:
                        history.append(f"T{turn}.{i + 1} {desc} -> DECLINED by user ({reason}). Do not retry it; find another way or fail.")
                        lines.append("❌ Declined")
                        break

                if action["action"] == "ask_user":
                    task.status = "waiting for your answer"
                    self._progress(task, msg_id, lines)
                    answer = self.ui.ask_user(f"❓ *Task #{task.id} asks:* {action['question']}", task.cancel)
                    task.status = "running"
                    if answer is None:
                        final_text, final_icon = ("Stopped by you." if task.cancel.is_set() else "No answer received."), "🛑"
                        stop_turn = finished = True
                        break
                    history.append(f"T{turn}.{i + 1} ask_user: {action['question'][:150]} -> user answered: {answer[:300]}")
                    break

                try:
                    result = self._execute(action, frame, task)
                except Exception as e:
                    result = f"ERROR: {e}"
                finally:
                    os_bridge.release_input_lock()
                history.append(f"T{turn}.{i + 1} {desc} -> {str(result)[:400]}")
                if i < len(actions) - 1:
                    task.cancel.wait(0.25)  # tiny gap between batched actions
            self._progress(task, msg_id, lines)

            if finished or stop_turn:
                break
            if task.cancel.is_set():
                final_text, final_icon = "Stopped by you.", "🛑"
                break

            if turn % 5 == 0:
                after = config.SCREENSHOTS_DIR / f"agent_{task.id}_{turn}_progress.jpg"
                if os_bridge.screenshot_annotated(after):
                    self.ui.send_photo(str(after), f"📸 Task #{task.id} · turn {turn}")

            last = actions[-1]["action"] if actions else ""
            wait = self.settle_sec * (3 if last in ("open_app", "open_url") else 1)
            if task.cancel.wait(wait):
                final_text, final_icon = "Stopped by you.", "🛑"
                break
        else:
            final_text, final_icon = f"Reached the {limit}-turn limit before finishing.", "⚠️"

        task.status = "finished"
        took = int(time.time() - started)
        lines.append(f"{final_icon} {final_text}  ({took}s, {task.step} AI turn(s), {n} action(s))")
        self._progress(task, msg_id, lines)
        self._edits.flush()
        end_shot = config.SCREENSHOTS_DIR / f"agent_{task.id}_final.jpg"
        caption = f"{final_icon} *Task #{task.id}:* {(final_text or '')[:880]}\n⏱ {took}s"
        if os_bridge.screenshot_annotated(end_shot):
            self.ui.send_photo(str(end_shot), caption)
        else:
            self.ui.send_text(caption)
        conversation_memory.add_exchange(f"(agent task #{task.id} result) {self._title(task)}", f"{final_icon} {final_text}")
        if task.on_done:
            try:
                task.on_done(final_icon == "✅", final_text or "")
            except Exception as e:
                self.ui.send_text(f"⚠️ Follow-up step after task #{task.id} failed: `{e}`")
        memory_logger.log_entry("AGENT_TASK", f"Task #{task.id} finished ({final_icon})",
                                details={"task": task.text[:300], "turns": task.step, "actions": n,
                                         "seconds": took, "result": (final_text or "")[:300]})

    # --- execution ------------------------------------------------------
    def _point(self, a: dict, frame: ScreenFrame) -> tuple:
        if "_screen" in a:
            return a["_screen"]
        return to_screen(frame, a["x"], a["y"])

    def _execute(self, a: dict, frame: ScreenFrame, task: AgentTask) -> str:
        act = a["action"]
        if act in COORD_ACTIONS:
            x, y = self._point(a, frame)
            el = a.get("_el")
            with os_bridge.UserInputLock("Agent"):
                if act == "move":
                    ok = os_bridge.mouse_move(x, y)
                elif act == "click" and el is not None:
                    # Native Windows controls: acted on directly (no mouse). Browsers/Electron: real click.
                    res = ui_actions.activate(
                        el, lambda cx, cy, b, d: os_bridge.mouse_click(cx, cy, button=b, double=d))
                    return f"ok ({res['method'].replace('uia-', '')})" if res["ok"] else "failed"
                else:
                    ok = os_bridge.mouse_click(x, y, button="right" if act == "right_click" else "left",
                                               double=act == "double_click")
            return "ok" if ok else "failed"
        if act == "click_text":
            from PIL import ImageGrab
            os_bridge.ensure_dpi_aware()
            left, top, _, _ = os_bridge.get_virtual_screen()
            shot = Path(config.TEMP_DIR) / f"ocr_{task.id}_{task.step}.png"
            try:
                try:
                    img = ImageGrab.grab(all_screens=True)
                except TypeError:
                    img = ImageGrab.grab()
                    left, top = 0, 0
                img.convert("RGB").save(shot, "PNG")
                words = ocr.read_words(str(shot))
            finally:
                try:
                    shot.unlink()
                except OSError:
                    pass
            if words is None:
                return "OCR is not available on this PC"
            found = ocr.find_text(words, a["text"])
            if not found:
                return f"text '{a['text']}' not found on screen (OCR read {len(words)} words)"
            m = found[0]
            cx, cy = left + m["x"] + m["w"] // 2, top + m["y"] + m["h"] // 2
            with os_bridge.UserInputLock("Agent"):
                ok = os_bridge.mouse_click(cx, cy)
            more = f" ({len(found)} matches, took the top-most)" if len(found) > 1 else ""
            return f"clicked '{m['text']}' at ({cx}, {cy}){more}" if ok else "click failed"
        if act == "drag":
            x, y = to_screen(frame, a["x"], a["y"])
            x2, y2 = to_screen(frame, a["x2"], a["y2"])
            with os_bridge.UserInputLock("Agent"):
                return "ok" if os_bridge.mouse_drag(x, y, x2, y2) else "failed"
        if act == "scroll":
            has_point = "_screen" in a or "x" in a
            x, y = self._point(a, frame) if has_point else (None, None)
            with os_bridge.UserInputLock("Agent"):
                ok = os_bridge.mouse_scroll(dy=a["amount"], x=x, y=y)
            return "ok" if ok else "failed"
        if act == "type_text":
            el = a.get("_el")
            with os_bridge.UserInputLock("Agent"):
                if el is not None:
                    def paste_path():
                        os_bridge.mouse_click(*a["_screen"])
                        time.sleep(0.15)
                        return os_bridge.type_text(a["text"])
                    res = ui_actions.set_text(el, a["text"], paste_path)
                    if not res["ok"]:
                        return "typing stopped (focus changed or window not ready)"
                    how = {True: "verified in the field", False: "WARNING: the field does NOT show this text - "
                           "check the screenshot and retry", None: "could not verify"}[res["verified"]]
                    return f"typed ({res['method'].replace('uia-value', 'direct').replace('paste', 'pasted')}, {how})"
                ok = os_bridge.type_text(a["text"])
            return "typed" if ok else "typing stopped (focus changed or window not ready)"
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
            before_w, before_fg = os_bridge._visible_window_handles(), os_bridge._foreground_hwnd()
            r = os_bridge.open_url(a["url"])
            os_bridge.wait_for_new_window(before_w, before_fg, timeout=6)
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
            if os_bridge.screenshot_annotated(p):
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
