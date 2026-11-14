"""Integration test: real Listener + ComputerAgent + HermesAgent, fake Telegram and fake desktop."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

import sys, time, threading
sys.stdout.reconfigure(encoding="utf-8")
# test-memory-isolation
import tempfile as _tf, pathlib as _pl
from core import conversation_memory as _cm
_d = _pl.Path(_tf.mkdtemp(prefix='tgmem_')); _cm.DATA_DIR, _cm.CONV_FILE, _cm.NOTES_FILE = _d, _d / 'conversation.jsonl', _d / 'notes.json'
from core import ui_actions as _ua; _ua._auto = None  # tests use fake element positions: never act on real controls
from pathlib import Path
import tempfile
import config
config.TELEGRAM_CHAT_ID = "1111"
config.INBOX_DIR = Path(tempfile.mkdtemp(prefix="tginbox_"))
config.APPROVAL_TIMEOUT_SEC = 30
from bot import telegram_client as tc
from core import memory_logger, os_bridge as ob, computer_agent as ca
memory_logger.log_entry = lambda *a, **k: None

sent = []          # (kind, text)
cards = {}         # key -> title
lock = threading.Lock()
mid = [100]


def _msg(chat, text, **k):
    with lock:
        sent.append(("msg", text))
        mid[0] += 1
        return {"ok": True, "result": {"message_id": mid[0]}}


tc.send_message = _msg
tc.edit_message = lambda chat, m, text, **k: sent.append(("edit", text)) or {"ok": True}
tc.send_photo = lambda chat, p, caption="", **k: sent.append(("photo", caption)) or {"ok": True}
tc.send_document = lambda chat, p, caption="", **k: sent.append(("doc", caption)) or {"ok": True}
tc.answer_callback = lambda cid, text="": sent.append(("cb", text)) or {"ok": True}
tc.send_chat_action = lambda *a, **k: {"ok": True}


def _card(chat, title, details, key):
    cards[key] = title
    return _msg(chat, f"APPROVAL {title}")


tc.send_approval_card = _card


def _download(file_id, dest):
    Path(dest).write_bytes(b"hello")
    return Path(dest)


tc.download_file = _download

# fake desktop
did = []
for name in ["mouse_click", "type_text", "press_key", "press_hotkey", "focus_window"]:
    setattr(ob, name, (lambda n: (lambda *a, **k: did.append(n) or True))(name))
ob.launch_app = lambda app: did.append(("launch_app", app)) or {"exit_code": 0, "stdout": "ok", "stderr": ""}
ob.close_app = lambda app: did.append(("close_app", app)) or {"exit_code": 0, "stdout": "closed", "stderr": ""}
ob.take_screenshot = lambda p, **k: (Path(p).write_bytes(b"x"), True)[1]
ob.get_system_stats = lambda: {"os": "TestOS", "cpu_cores": 4}
ob.list_windows = lambda: []
ob.power_action = lambda a: did.append(("power", a)) or {"exit_code": 0, "stdout": "", "stderr": ""}
ca.capture_frame = lambda save_path=None: ca.ScreenFrame("AAAA", 1000, 800, 0, 0, 1.0, None)


class SlowBrain(ca.Brain):
    """Script: ask a question, then a risky close (needs approval), then wait a lot."""
    name = "fake"

    def __init__(self):
        self.i = 0
        self.history = []

    def next_action(self, task, frame, history, windows):
        self.history = list(history)
        self.i += 1
        time.sleep(0.1)
        if "quick" in task:
            return {"thought": "done", "action": "done", "summary": "quick done"}
        if self.i == 1:
            return {"thought": "need info", "action": "ask_user", "question": "Which file?"}
        if self.i == 2:
            return {"thought": "close word", "action": "close_app", "app": "word"}
        return {"thought": "waiting", "action": "wait", "seconds": 1}


brain = SlowBrain()
ca.default_brain = lambda: brain
from bot import listener as L

lst = L.Listener()
fails = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not cond:
        fails.append(name)


def text(t, chat=1111, frm=1111):
    lst.dispatch({"update_id": 1, "message": {"chat": {"id": chat}, "from": {"id": frm, "first_name": "T"}, "text": t}})


def press(key, approve=True, frm=1111):
    lst.dispatch({"update_id": 1, "callback_query": {"id": "c", "data": ("appr:" if approve else "canc:") + key,
                                                     "from": {"id": frm}, "message": {"chat": {"id": 1111}}}})


def wait_for(pred, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.05)
    return False


def msgs():
    return [t for k, t in list(sent) if k in ("msg", "photo")]


# 1. /help shows agent section; status works
text("/help")
check("help includes agent mode", wait_for(lambda: any("/agent" in (m or "") for m in msgs())))

# 2. /agent starts a task; agent asks a question; answer is delivered
text("/agent open my report and close word")
check("agent asks question", wait_for(lambda: any("Which file?" in (m or "") for m in msgs())))
check("/task shows waiting", (text("/task") or True) and wait_for(lambda: any("waiting for your answer" in (m or "") for m in msgs())))
text("/open notepad")  # while busy: an input command must be refused...
text("report.docx")   # ...but this plain text is the answer to the question
check("answer delivered to agent", wait_for(lambda: any("report.docx" in h for h in brain.history)))
check("busy agent: non-read-only command refused", any("using the mouse/keyboard" in (m or "") for m in msgs()))

# 3. risky step -> approval card -> stranger can't approve -> owner approves
check("approval card shown", wait_for(lambda: len(cards) == 1))
key = next(iter(cards))
press(key, approve=True, frm=2222)
time.sleep(0.3)
check("stranger cannot approve", not any(d == ("close_app", "word") for d in did) and ("cb", "Not authorized") in sent)
press(key, approve=True)
check("owner approval executes step", wait_for(lambda: ("close_app", "word") in did))

# 4. read-only command allowed while busy
text("screenshot")
check("screenshot allowed while agent busy", wait_for(lambda: any(k == "photo" and "Desktop Screenshot" in (t or "") for k, t in sent)))

# 5. /stop cancels the running task
text("/stop")
check("/stop stops task", wait_for(lambda: any("Stopped by you" in (m or "") for m in msgs())) and wait_for(lambda: not lst.computer.busy()))

# 6. after stop, normal commands work again; translator agent_task path queues a task
text("/agent quick task")
check("new task runs after stop", wait_for(lambda: any("quick done" in (m or "") for m in msgs())))

# 7. upload from phone saved to inbox
lst.dispatch({"update_id": 1, "message": {"chat": {"id": 1111}, "from": {"id": 1111},
                                          "document": {"file_id": "f", "file_name": "notes.txt", "file_size": 5}}})
saved = config.INBOX_DIR / "notes.txt"
check("upload saved to inbox", saved.exists() and any("Saved to" in (m or "") for m in msgs()), str(saved))
lst.dispatch({"update_id": 1, "message": {"chat": {"id": 1111}, "from": {"id": 1111},
                                          "document": {"file_id": "f", "file_name": "notes.txt", "file_size": 5}}})
check("duplicate upload name gets a new name", (config.INBOX_DIR / "notes (1).txt").exists())

# 8. /shutdown needs approval; declining does nothing
cards.clear()
text("/shutdown")
check("shutdown asks approval", wait_for(lambda: len(cards) == 1))
press(next(iter(cards)), approve=False)
check("declined shutdown not executed", wait_for(lambda: any("cancelled" in (m or "").lower() for m in msgs())) and not any(d == ("power", "shutdown") for d in did))

# 9. stranger messages rejected
before = len(did)
text("/exec whoami", chat=2222, frm=2222)
check("stranger rejected", any("Access Denied" in (m or "") for m in msgs()) and len(did) == before)

print("\nFAILED:", fails if fails else "none")
import os
sys.stdout.flush()
os._exit(1 if fails else 0)
