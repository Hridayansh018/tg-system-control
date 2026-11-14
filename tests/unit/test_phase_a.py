import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

import sys; sys.stdout.reconfigure(encoding="utf-8")
# test-memory-isolation
import tempfile as _tf, pathlib as _pl
from core import conversation_memory as _cm
_d = _pl.Path(_tf.mkdtemp(prefix='tgmem_')); _cm.DATA_DIR, _cm.CONV_FILE, _cm.NOTES_FILE = _d, _d / 'conversation.jsonl', _d / 'notes.json'
from core import ui_actions as _ua; _ua._auto = None  # tests use fake element positions: never act on real controls
import os, subprocess
from core import os_bridge as ob, translator
fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not cond: fails.append(name)

# --- launch_app routing (nothing is started: starters are replaced by recorders) ---
started = []
ob._start_appid = lambda label, appid: (started.append(("APPID", label, appid)), ob._ok())[1]
ob._start_exe = lambda label, exe: (started.append(("EXE", label, exe)), ob._ok())[1]
ob._open_url = lambda url, app_mode=False, browser="": (started.append(("URL", url, app_mode, browser)), ob._ok())[1]
real_refresh = ob.refresh_installed_apps_cache
ob.refresh_installed_apps_cache = lambda: ob._APPS_CACHE  # no PowerShell during tests
os.startfile = lambda *a: started.append(("STARTFILE",) + a)
def launch(q):
    started.clear(); r = ob.launch_app(q); return (started[0] if started else None), r
cases = {
  "python": lambda s, r: s and s[0] == "APPID" and "python" in s[1],
  "google chrome": lambda s, r: s and s[0] in ("APPID", "EXE") and "chrome" in str(s).lower() and "google.com" not in str(s),
  "youtube": lambda s, r: s and s[0] == "URL" and "youtube.com" in s[1],
  "youtube studio": lambda s, r: s and s[0] == "URL" and "studio.youtube.com" in s[1],
  "edge gmail app": lambda s, r: s and s[0] == "URL" and "mail.google.com" in s[1] and s[2] is True,
  "notepad": lambda s, r: s and "notepad" in str(s).lower(),
  "edge": lambda s, r: s and "edge" in str(s).lower(),
  "hotmail": lambda s, r: not (s and s[0] == "URL"),
  "telegram": lambda s, r: not (s and s[0] == "URL"),
  "spotifyxyz123": lambda s, r: s is None and r["exit_code"] != 0 and "not found" in r["stderr"],
}
for q, ok in cases.items():
    s, r = launch(q)
    check(f"launch_app({q!r})", ok(s, r), f"{s} {r['stderr'][:60]}")

# --- close_app name resolution + read-only process lookup ---
for target, expect in [("edge", ["msedge"]), ("code", ["Code"]), ("calc", ["CalculatorApp", "Calculator"]),
                       ("explorer", []), ("msedgewebview2", []), ("python", []), ("Notepad.exe", ["Notepad", "notepad"])]:
    got = ob.resolve_process_names(target)
    check(f"resolve_process_names({target!r})", got == expect, str(got))
for target in ["edge", "code", "window", "calc"]:
    names = ob.resolve_process_names(target)
    if names:
        q = ",".join(ob.ps_quote(n) for n in names)
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
              f"(Get-Process -Name @({q}) -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ProcessName -Unique) -join ','"],
              capture_output=True, text=True).stdout.strip()
    else:
        out = "(protected / not looked up)"
    print(f"INFO close {target!r}: would match processes -> {out or 'none (reply: not running)'}")
check("close 'window' maps to Alt+F4 path", "window" in ob.CLOSE_WINDOW_WORDS and "" in ob.CLOSE_WINDOW_WORDS)
check("ps_quote escapes quotes", ob.ps_quote("a'; Remove-Item x; '") == "'a''; Remove-Item x; '''")

# --- hotkey parser ---
VK_CTRL, VK_SHIFT, VK_ALT, VK_WIN = 0x11, 0x10, 0x12, 0x5B
hk = {"ctrl+w": ([VK_CTRL], ord("W")), "ctrl+shift+o": ([VK_CTRL, VK_SHIFT], ord("O")),
      "win+m": ([VK_WIN], ord("M")), "win+d": ([VK_WIN], ord("D")), "alt+f4": ([VK_ALT], 0x73),
      "alt+tab": ([VK_ALT], 0x09), "f5": ([], 0x74), "enter": ([], 0x0D), "Ctrl + Shift + T": ([VK_CTRL, VK_SHIFT], ord("T")),
      "win": ([], VK_WIN), "ctrl+bogus": None, "": None}
for combo, expect in hk.items():
    check(f"parse_hotkey({combo!r})", ob.parse_hotkey(combo) == expect, str(ob.parse_hotkey(combo)))

# --- translator validation (model output is never trusted) ---
v = translator.validate({"kind": "commands", "commands": [{"command": "exec", "arg": "rm -rf /"}, {"command": "open", "arg": "spotify"}]})
check("translator drops non-menu 'exec'", v["kind"] == "commands" and v["commands"] == [("open", "spotify")], str(v))
v = translator.validate({"kind": "commands", "commands": [{"command": "type"}]})
check("translator drops arg-less 'type'", v["kind"] == "chat", str(v))
v = translator.validate({"kind": "commands", "commands": [{"command": "open", "arg": str(i)} for i in range(20)]})
check("translator caps at 6 commands", len(v["commands"]) == 6)
v = translator.validate({"kind": "agent_task", "agent_task": "do x"})
check("translator agent_task", v == {"kind": "agent_task", "task": "do x", "english": ""}, str(v))
check("translator garbage -> error", translator.validate("hello")["kind"] == "error")
from core import llm_router
check("extract_json fenced", llm_router.extract_json('sure ```json\n{"kind":"chat"}\n``` ok') == {"kind": "chat"})
check("extract_json prose", llm_router.extract_json('Here: {"a": [1, 2]} thanks') == {"a": [1, 2]})
import config
old = (config.LLM_PROVIDER, config.GEMINI_API_KEY)
config.LLM_PROVIDER, config.GEMINI_API_KEY = "gemini", ""
check("missing key -> offline", llm_router.active_provider() == "offline")
config.LLM_PROVIDER, config.GEMINI_API_KEY = old
# Gemini request shape (no network: requests.post replaced)
import requests
sent = {}
class R:
    def json(self): return {"candidates": [{"content": {"parts": [{"text": '{"kind":"chat","reply":"hi"}'}]}}]}
requests.post = lambda url, **kw: (sent.update(url=url, **kw), R())[1]
config.LLM_PROVIDER, config.GEMINI_API_KEY = "gemini", "TESTKEY"
out = llm_router.route_json("hi", "sys", {"type": "OBJECT"})
check("gemini JSON mode request", sent["json"]["generationConfig"]["responseMimeType"] == "application/json" and out == {"data": {"kind": "chat", "reply": "hi"}}, str(out))
check("gemini key not in URL path", "TESTKEY" not in sent["url"] and sent["params"]["key"] == "TESTKEY")
config.LLM_PROVIDER, config.GEMINI_API_KEY = old
print("\nFAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
