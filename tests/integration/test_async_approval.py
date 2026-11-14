"""End-to-end: tg-system-control /studio start|status|stop drives the REAL Video Studio bot service
(scratch copy of the pipeline tools) against a FAKE Telegram server. No real Telegram, no real tokens."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))
_PIPE = Path(os.environ.get("VIDEOSTUDIO_DIR", r"D:\VideoStudio_Mac"))
if not (_PIPE / "tools" / "telegram_bot.py").exists():
    print("SKIPPED: Video Studio pipeline not found (set VIDEOSTUDIO_DIR)"); raise SystemExit(0)

import sys, os, json, time, shutil, threading, subprocess, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

# ---------------- fake Telegram ----------------
OWNER = 555
STATE = {"updates": [], "sent": [], "reactions": [], "next": 1000, "getupdates_calls": 0, "methods": [], "descr": [], "edits": []}
LOCK = threading.Lock()


def add_update(u):
    with LOCK:
        STATE["next"] += 1
        u["update_id"] = STATE["next"]
        STATE["updates"].append(u)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _reply(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _handle(self, body):
        u = urlparse(self.path); method = u.path.rsplit("/", 1)[-1]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if "fake-token" not in u.path:
            return self._reply({"ok": False, "error_code": 401, "description": "Unauthorized"})
        STATE["methods"].append(method)
        if method == "editMessageText":
            STATE["edits"].append(body.get("text", ""))
        if method == "setMyShortDescription":
            STATE["descr"].append(body.get("short_description", ""))
        if method == "getMe":
            return self._reply({"ok": True, "result": {"id": 42, "is_bot": True, "username": "videostudio_test_bot"}})
        if method == "getUpdates":
            STATE["getupdates_calls"] += 1
            off = int(q.get("offset", 0)); t_end = time.time() + min(float(q.get("timeout", 0)), 2)
            while True:
                with LOCK:
                    res = [x for x in STATE["updates"] if x["update_id"] >= off]
                if res or time.time() > t_end:
                    return self._reply({"ok": True, "result": res})
                time.sleep(0.1)
        if method == "sendMessage":
            STATE["sent"].append(body.get("text", "")); return self._reply({"ok": True, "result": {"message_id": 9}})
        if method == "setMessageReaction":
            STATE["reactions"].append(body["reaction"][0]["emoji"]); return self._reply({"ok": True, "result": True})
        return self._reply({"ok": True, "result": True})

    def do_GET(self): self._handle({})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(n) if n else b"{}"
        try: body = json.loads(raw)
        except Exception: body = {}
        self._handle(body)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"

# ---------------- scratch copy of the pipeline tools ----------------
FAKE = Path(tempfile.mkdtemp(prefix="vstudio_"))
(FAKE / "tools").mkdir()
for f in ["telegram_queue.py", "videostudio_bot.py", "telegram_bot.py", "wait_for_telegram_msg.py", "telegram_memory.py"]:
    shutil.copy((_PIPE / "tools") / f, FAKE / "tools" / f)
(FAKE / "tools" / "gate.py").write_text("import sys, pathlib; pathlib.Path(__file__).with_name('approved.txt').write_text(' '.join(sys.argv[1:]))")
cfg_file = FAKE / "tools" / ".telegram_config.json"
VPY = str(_PIPE / ".venv" / "Scripts" / "python.exe")

import config
config.VIDEOSTUDIO_DIR = str(FAKE)
config.VIDEOSTUDIO_PYTHON = VPY
from core import studio_control as sc, hermes_agent, memory_logger
memory_logger.log_entry = lambda *a, **k: None
agent = hermes_agent.HermesAgent()
fails = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""), flush=True)
    if not cond: fails.append(name)


def say(cmd):
    return agent.process_message(cmd)["text"]


def owner_msg(text):
    add_update({"message": {"message_id": 7, "chat": {"id": OWNER}, "from": {"id": OWNER, "first_name": "Hridayansh"}, "text": text}})


try:
    cfg_file.write_text(json.dumps({"bot_token": "777:fake-token", "chat_id": str(OWNER), "api_base": BASE}))
    PY = VPY
    TB = str(FAKE / "tools" / "telegram_bot.py")

    def approve_async(video, stage):
        return subprocess.run([PY, "-I", TB, "approve", video, stage, "--async"], cwd=str(FAKE), capture_output=True,
                              text=True, encoding="utf-8", timeout=60)

    # 1. async approval refused while the bot service is NOT running
    r = approve_async("onepiece_whatif/t", "script")
    check("--async refused when the Video Studio bot is off", r.returncode == 1 and "not running" in r.stdout, r.stdout[:120])
    check("no approval card sent when refused", not any("GATE APPROVAL" in t for t in STATE["sent"]))

    # 2. start the service; reactions: no listener -> 💤, bridge heartbeat -> 👀
    say("/studio start"); time.sleep(1.5)
    owner_msg("pehla message"); time.sleep(2.5)
    (FAKE / "tools" / ".antigravity_bridge_alive.json").write_text(json.dumps({"pid": os.getpid(), "beat": time.time()}))
    owner_msg("doosra message"); time.sleep(2.5)
    check("💤 when nobody listens, 👀 when the bridge is alive", STATE["reactions"][-2:] == ["💤", "👀"], str(STATE["reactions"]))
    stale = {"pid": os.getpid(), "beat": time.time() - 120}
    (FAKE / "tools" / ".antigravity_bridge_alive.json").write_text(json.dumps(stale))
    owner_msg("teesra message"); time.sleep(2.5)
    check("stale heartbeat counts as nobody listening", STATE["reactions"][-1] == "💤", str(STATE["reactions"]))
    for p in (FAKE / "tools" / ".telegram_queue").glob("msg_*.json"): p.unlink()

    # 3. async approval: card sent immediately, tap recorded by the service
    t0 = time.time()
    r = approve_async("onepiece_whatif/test", "script")
    check("--async returns immediately with exit 0", r.returncode == 0 and time.time() - t0 < 20, f"{time.time()-t0:.1f}s {r.stdout[-80:]}")
    check("card with ✅/❌ was sent", any("GATE APPROVAL" in t for t in STATE["sent"]))
    check("gate not touched before the tap", not (FAKE / "tools" / "approved.txt").exists())
    add_update({"callback_query": {"id": "cbA", "data": "appr:script:onepiece_whatif/test", "from": {"id": OWNER, "first_name": "Hridayansh"},
                                   "message": {"message_id": 9, "chat": {"id": OWNER}}}})
    time.sleep(4)
    ap = FAKE / "tools" / "approved.txt"
    check("tap recorded with gate.py approve + note", ap.exists() and "approve onepiece_whatif/test script --note Approved via Telegram by Hridayansh" in ap.read_text(), ap.read_text() if ap.exists() else "missing")
    check("card edited to APPROVED", any("APPROVED" in e for e in STATE["edits"]), str(STATE["edits"][-1:]))
    q = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((FAKE / "tools" / ".telegram_queue").glob("msg_*.json"))]
    check("Antigravity gets '[APPROVAL APPROVED] ... Recorded in gate.py.'", any("[APPROVAL APPROVED] onepiece_whatif/test" in m["text"] and "Recorded in gate.py" in m["text"] for m in q), str([m["text"][:90] for m in q]))
    # second tap on the same card (button spam) is ignored
    qn = len(q)
    add_update({"callback_query": {"id": "cbA2", "data": "appr:script:onepiece_whatif/test", "from": {"id": OWNER, "first_name": "Hridayansh"},
                                   "message": {"message_id": 9, "chat": {"id": OWNER}}}})
    time.sleep(3)
    q2 = list((FAKE / "tools" / ".telegram_queue").glob("msg_*.json")) + list((FAKE / "tools" / ".telegram_queue").glob("cb_*.json"))
    check("a repeated tap is not recorded twice", len([p for p in q2 if p.name.startswith("msg_")]) == qn and len([p for p in q2 if p.name.startswith("cb_")]) == 1)
    for p in (FAKE / "tools" / ".telegram_queue").glob("*.json"): p.unlink()

    # 4. reject: nothing recorded in gate, Antigravity told
    ap.unlink()
    approve_async("onepiece_whatif/test2", "images"); time.sleep(1)
    add_update({"callback_query": {"id": "cbR", "data": "rejc:images:onepiece_whatif/test2", "from": {"id": OWNER, "first_name": "Hridayansh"},
                                   "message": {"message_id": 9, "chat": {"id": OWNER}}}})
    time.sleep(3)
    q = [json.loads(p.read_text(encoding="utf-8")) for p in (FAKE / "tools" / ".telegram_queue").glob("msg_*.json")]
    check("reject: gate NOT called, card edited, Antigravity told", not ap.exists() and any("REJECTED" in e for e in STATE["edits"]) and
          any("[APPROVAL REJECTED] onepiece_whatif/test2" in m["text"] for m in q))

    # 5. a stranger cannot press the buttons
    approve_async("onepiece_whatif/test3", "script"); time.sleep(1)
    add_update({"callback_query": {"id": "cbX", "data": "appr:script:onepiece_whatif/test3", "from": {"id": 999, "first_name": "X"},
                                   "message": {"message_id": 9, "chat": {"id": 999}}}})
    time.sleep(3)
    check("stranger's tap ignored (no gate call)", not ap.exists())
finally:
    try: sc.stop()
    except Exception: pass
    srv.shutdown()

print("FAILED:", fails if fails else "none")
sys.stdout.flush()
os._exit(1 if fails else 0)
