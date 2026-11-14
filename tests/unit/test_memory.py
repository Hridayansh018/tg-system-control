"""Bot 1 memory: notes, conversation, translator context, agent prompt. Temp data dir, AI stubbed."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

import sys, json, tempfile, os
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
from core import conversation_memory as cm, hermes_agent, translator, llm_router, memory_logger
memory_logger.log_entry = lambda *a, **k: None
tmp = Path(tempfile.mkdtemp(prefix="tgmem_"))
cm.DATA_DIR, cm.CONV_FILE, cm.NOTES_FILE = tmp, tmp / "conversation.jsonl", tmp / "notes.json"
fails = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not cond: fails.append(name)


ag = hermes_agent.HermesAgent()
r = ag.process_message("/remember my videos are in D:\\VideoStudio_Mac")["text"]
check("/remember saves note", "note #1" in r, r)
ag.process_message("yaad rakhna: upload thumbnails at 1280x720")
check("Hinglish 'yaad rakhna:' saves note", len(cm.notes()) == 2, cm.notes_text())
r = ag.process_message("/memory")["text"]
check("/memory lists notes", "VideoStudio_Mac" in r and "1280x720" in r)
check("/forget by word", "Removed 1" in ag.process_message("/forget thumbnails")["text"] and len(cm.notes()) == 1)

# conversation + translator context
cm.add_exchange("open spotify", "🚀 Opened spotify")
seen = {}


def fake_route_json(prompt, system, schema):
    seen["prompt"] = prompt
    return {"data": {"kind": "commands", "commands": [{"command": "close", "arg": "spotify"}], "english": "close spotify"}}


llm_router.route_json = fake_route_json
from core import os_bridge
os_bridge.close_app = lambda t: {"exit_code": 0, "stdout": f"Closed {t}", "stderr": ""}
ag.remote_feedback = False
r = ag.process_message("usko band karo")["text"]
check("translator gets memory (previous 'open spotify')", "open spotify" in seen.get("prompt", "") and "NEW MESSAGE TO TRANSLATE:\nusko band karo" in seen["prompt"])
check("follow-up resolved to close spotify", "close spotify" in r, r[:80])
check("notes included in translator context", "VideoStudio_Mac" in seen["prompt"])

# agent prompt gets notes
from core import computer_agent as ca
import requests
sent = {}


class R:
    status_code = 200

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"thought": "t", "actions": [{"action": "done"}]})}]}}]}


requests.post = lambda url, **kw: (sent.update(kw), R())[1]
import config
config.GEMINI_API_KEY = "TESTKEY"
ca.GeminiBrain().next_action("upload my video", ca.ScreenFrame("QUJD", 800, 600, 0, 0, 1.0), [], [])
check("agent prompt includes saved notes", "VideoStudio_Mac" in sent["json"]["contents"][0]["parts"][1]["text"])

# conversation file trimming + forget all
for i in range(1100):
    cm.add_exchange(f"m{i}", "r")
lines = cm.CONV_FILE.read_text(encoding="utf-8").splitlines()
check("conversation file stays bounded", len(lines) <= 1000, str(len(lines)))
check("/forget all", "Removed" in ag.process_message("/forget all")["text"] and cm.notes() == [])
check("memory files are git-ignored in the real project",
      os.system(f'cd /d "{ROOT}" && git check-ignore -q data/notes.json') == 0)
print("\nFAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
