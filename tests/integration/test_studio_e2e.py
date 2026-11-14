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
STATE = {"updates": [], "sent": [], "reactions": [], "next": 1000, "getupdates_calls": 0}
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
    # 1. No token configured -> clear refusal
    cfg_file.write_text(json.dumps({"bot_token": "", "chat_id": str(OWNER), "api_base": BASE}))
    r = say("/studio start")
    check("start refused without token", "no bot_token" in r, r.splitlines()[0])

    # 2. Revoked/invalid token -> service reports the reason
    cfg_file.write_text(json.dumps({"bot_token": "123:revoked", "chat_id": str(OWNER), "api_base": BASE}))
    r = say("/studio start")
    check("invalid token reported", "rejected the token" in r or "Unauthorized" in r, r.splitlines()[0])

    # 3. Valid (fake) token -> running
    cfg_file.write_text(json.dumps({"bot_token": "777:fake-token", "chat_id": str(OWNER), "api_base": BASE}))
    r = say("/studio start")
    check("/studio start -> running", "started" in r and "running" in r, r.replace("\n", " | "))
    check("/studio status", "running" in say("/studio status"))
    check("second start says already running", "already running" in say("/studio start"))

    # 4. Owner messages are queued silently (👀), strangers ignored, /remember saved
    owner_msg("/remember thumbnails always 1280x720")
    owner_msg("naya One Piece video shuru karo")
    add_update({"message": {"message_id": 8, "chat": {"id": 999}, "from": {"id": 999, "first_name": "Stranger"}, "text": "hack"}})
    time.sleep(3)
    queue = sorted(p.name for p in (FAKE / "tools" / ".telegram_queue").glob("msg_*.json"))
    check("owner message queued, stranger + /remember not queued", len(queue) == 1, str(queue))
    replies = [t for t in STATE["sent"] if "VIDEO STUDIO BOT ONLINE" not in t and "VIDEO STUDIO BOT OFFLINE" not in t]
    check("no canned text replies sent (status notices only)", replies == [], str(STATE["sent"]))
    check("reactions used instead of replies (✍ note, 💤 = no listener in this test)", STATE["reactions"][:2] == ["✍", "💤"], str(STATE["reactions"]))
    notes = json.loads((FAKE / "tools" / ".telegram_memory.json").read_text(encoding="utf-8"))["notes"]
    check("/remember stored note", notes and "1280x720" in notes[0]["text"])

    # 5. Antigravity's wait_for_telegram_msg gets the message + memory, without touching Telegram
    calls_before = STATE["getupdates_calls"]
    out = subprocess.run([VPY, "-I", str(FAKE / "tools" / "wait_for_telegram_msg.py")], capture_output=True, text=True,
                         encoding="utf-8", timeout=30).stdout
    first = out.splitlines()[0] if out else ""
    check("wait_for_telegram_msg: same first line format", first == "TELEGRAM_INCOMING: [Hridayansh] naya One Piece video shuru karo", first)
    check("wait_for_telegram_msg: memory lines included", "TELEGRAM_MEMORY" in out and "1280x720" in out, out[-200:])

    # 6. Approval button -> ask_approval (pipeline code) gets it from the service queue
    def tap_later():
        time.sleep(4)
        add_update({"callback_query": {"id": "cb1", "data": "appr:script:onepiece_whatif/test",
                                       "from": {"id": OWNER, "first_name": "Hridayansh"},
                                       "message": {"message_id": 9, "chat": {"id": OWNER}}}})
    threading.Thread(target=tap_later, daemon=True).start()
    code = subprocess.run([VPY, "-I", "-c", "import sys; sys.path.insert(0, r'%s'); from tools.telegram_bot import ask_approval; "
                           "sys.exit(0 if ask_approval('onepiece_whatif/test', 'script', timeout_sec=40) else 1)" % FAKE],
                          cwd=str(FAKE), capture_output=True, text=True, timeout=60)
    approved = (FAKE / "tools" / "approved.txt")
    check("approval button handled via service queue", code.returncode == 0 and approved.exists() and "approve onepiece_whatif/test script" in approved.read_text(),
          (code.stdout + code.stderr)[-300:])

    # 7. History (memory) has both directions
    hist = (FAKE / "tools" / ".telegram_inbox.jsonl").read_text(encoding="utf-8")
    check("history logged in + out", '"dir": "in"' in hist and '"dir": "out"' in hist)

    # 8. Hinglish via translator -> studio command (stub the AI translator)
    from core import translator
    translator.translate = lambda *a, **k: {"kind": "commands", "commands": [("studio", "status")], "english": "video studio bot status"}
    check("Hinglish 'video studio bot ka status batao' -> studio status", "running" in say("video studio bot ka status batao"))

    # 9. Stop
    r = say("/studio stop")
    check("/studio stop -> stopped", "stopped" in r.lower() and "running" not in sc.status_text(), r.replace("\n", " | "))
    check("heartbeat says stopped", sc.status().get("running") is False)
    print("\n--- service log ---\n" + sc.logs(12))
finally:
    try: sc.stop()
    except Exception: pass
    srv.shutdown()

print("\nFAILED:", fails if fails else "none")
sys.stdout.flush()
os._exit(1 if fails else 0)
