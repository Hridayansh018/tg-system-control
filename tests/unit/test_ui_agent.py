import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

import sys, time, tempfile
sys.stdout.reconfigure(encoding="utf-8")
# test-memory-isolation
import tempfile as _tf, pathlib as _pl
from core import conversation_memory as _cm
_d = _pl.Path(_tf.mkdtemp(prefix='tgmem_')); _cm.DATA_DIR, _cm.CONV_FILE, _cm.NOTES_FILE = _d, _d / 'conversation.jsonl', _d / 'notes.json'
from core import computer_agent as ca, ui_actions as ua, ui_elements as ue, os_bridge as ob, ocr, memory_logger
memory_logger.log_entry = lambda *a, **k: None
fails = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not cond: fails.append(name)


EL = [ue.UIElement(1, "Go", "Button", 100, 100, 100, 40), ue.UIElement(2, "Name box", "Edit", 100, 200, 300, 30)]
frame = ca.ScreenFrame("AAAA", 1000, 700, 0, 0, 1.0, None, list(EL))
# --- validation ---
th, acts = ca.validate_step({"thought": "t", "actions": [{"action": "click_text", "text": "Select files"}]}, frame)
check("click_text accepted", acts[0]["action"] == "click_text")
try:
    ca.validate_step({"thought": "t", "actions": [{"action": "click_text"}]}, frame); ok = False
except ca.AgentError:
    ok = True
check("click_text without text rejected", ok)
th, acts = ca.validate_step({"thought": "t", "actions": [{"action": "click", "element": 1}]}, frame)
check("element click keeps the element object for ui_actions", acts[0].get("_el") is EL[0])

# --- execution with stubs ---
class FakeUI(ca.AgentUI):
    def send_text(self, t): return 1
    def edit_text(self, i, t): pass


agent = ca.ComputerAgent(FakeUI(), None)
task = ca.AgentTask(text="x", id=1)
clicks = []
ob.mouse_click = lambda x, y, button="left", double=False: clicks.append((x, y, button, double)) or True
ob.get_virtual_screen = lambda: (-1920, 0, 3840, 1080)
ob.release_input_lock = lambda: None

# element click -> via ui_actions
calls = []
real_activate = ua.activate
ua.activate = lambda el, mouse, **kw: (calls.append(el.name), {"method": "uia-invoke", "ok": True})[1]
r = agent._execute(acts[0], frame, task)
check("element click goes through ui_actions.activate", calls == ["Go"] and r == "ok (invoke)", r)
ua.activate = lambda el, mouse, **kw: {"method": "mouse", "ok": True}
check("browser path reported as mouse", agent._execute(acts[0], frame, task) == "ok (mouse)")
ua.activate = real_activate
# coordinate click (no element) still plain mouse
th, acts2 = ca.validate_step({"thought": "t", "actions": [{"action": "click", "x": 500, "y": 300}]}, frame)
clicks.clear(); agent._execute(acts2[0], frame, task)
check("coordinate click = real mouse", clicks == [(500, 300, "left", False)], str(clicks))

# type_text messages
th, tacts = ca.validate_step({"thought": "t", "actions": [{"action": "type_text", "element": 2, "text": "hello"}]}, frame)
for res, expect in [({"method": "uia-value", "ok": True, "verified": True}, "direct, verified in the field"),
                    ({"method": "paste", "ok": True, "verified": True}, "pasted, verified in the field"),
                    ({"method": "paste", "ok": True, "verified": None}, "could not verify"),
                    ({"method": "paste", "ok": True, "verified": False}, "does NOT show this text"),
                    ({"method": "paste", "ok": False, "verified": None}, "typing stopped")]:
    ua.set_text = lambda el, text, paste, r=res: r
    out = agent._execute(tacts[0], frame, task)
    check(f"type_text result: {expect}", expect in out, out[:110])

# click_text with stubbed OCR: virtual screen starts at x=-1920
words = [{"t": "Select", "x": 640, "y": 220, "w": 70, "h": 20, "l": 0}, {"t": "files", "x": 720, "y": 220, "w": 50, "h": 20, "l": 0}]
ocr.read_words = lambda p, timeout=40: words
clicks.clear()
th, cacts = ca.validate_step({"thought": "t", "actions": [{"action": "click_text", "text": "select files"}]}, frame)
r = agent._execute(cacts[0], frame, task)
check("click_text clicks the centre of the match in real screen pixels", clicks and clicks[0][:2] == (-1920 + 640 + 65, 0 + 220 + 10), f"{clicks} | {r}")
ocr.read_words = lambda p, timeout=40: words
th, cacts2 = ca.validate_step({"thought": "t", "actions": [{"action": "click_text", "text": "publish"}]}, frame)
check("click_text not found -> clear message, no click", "not found" in agent._execute(cacts2[0], frame, task) and len(clicks) == 1)
ocr.read_words = lambda p, timeout=40: None
check("OCR unavailable -> clear message", "not available" in agent._execute(cacts[0], frame, task))
check("temp screenshot is removed", not list((ca.config.TEMP_DIR).glob("ocr_*.png")))
print("\nFAILED:", fails if fails else "none")
sys.stdout.flush()
import os; os._exit(1 if fails else 0)
