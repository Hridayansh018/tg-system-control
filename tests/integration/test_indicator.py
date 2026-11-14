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
STATE = {"updates": [], "sent": [], "reactions": [], "next": 1000, "getupdates_calls": 0, "methods": [], "descr": []}
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
    # 1. ONLINE on start: message + pin + profile description
    r = say("/studio start")
    time.sleep(1.5)
    check("started", "running" in r)
    check("ONLINE message posted in bot 2 chat", any("VIDEO STUDIO BOT ONLINE" in t for t in STATE["sent"]), str(STATE["sent"]))
    check("ONLINE message pinned", "pinChatMessage" in STATE["methods"])
    check("profile shows Online", any("Online" in d for d in STATE["descr"]), str(STATE["descr"]))
    # 2. OFFLINE on /studio stop (announced by bot 2 itself, exactly once)
    STATE["sent"].clear()
    say("/studio stop")
    time.sleep(1)
    off = [t for t in STATE["sent"] if "OFFLINE" in t]
    check("OFFLINE posted once on /studio stop", len(off) == 1 and "/studio stop" in off[0], str(off))
    check("profile shows Offline", "Offline" in STATE["descr"][-1], STATE["descr"][-1])
    # 3. Crash / force-kill -> bot 1 watcher announces for it
    say("/studio start"); time.sleep(1.5)
    calls = []
    sc.watch(lambda reason: (calls.append(reason), sc.announce_offline(f"Unexpected: {reason}")), interval=1)
    time.sleep(1.5)
    STATE["sent"].clear()
    pid = sc.status()["pid"]
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    time.sleep(60)  # heartbeat goes stale after 45 s
    check("watcher noticed the crash", len(calls) == 1, str(calls))
    off = [t for t in STATE["sent"] if "OFFLINE" in t]
    check("OFFLINE posted for the crashed bot", len(off) == 1 and "Unexpected" in off[0], str(off))
    # 4. PC shutdown hook
    say("/studio start"); time.sleep(1.5)
    STATE["sent"].clear()
    from core import system_lifecycle as sl
    sl.studio_offline_on_shutdown("Windows shutting down / restarting")
    sl.studio_offline_on_shutdown("again")  # must not post twice
    off = [t for t in STATE["sent"] if "OFFLINE" in t]
    check("shutdown hook posts OFFLINE once", len(off) == 1 and "shutting down" in off[0], str(off))
finally:
    try: sc.stop()
    except Exception: pass
    srv.shutdown()

print("FAILED:", fails if fails else "none")
sys.stdout.flush()
os._exit(1 if fails else 0)
