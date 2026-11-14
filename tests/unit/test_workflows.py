import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

import sys, time, tempfile, shutil
sys.stdout.reconfigure(encoding="utf-8")
# test-memory-isolation
import tempfile as _tf, pathlib as _pl
from core import conversation_memory as _cm
_d = _pl.Path(_tf.mkdtemp(prefix='tgmem_')); _cm.DATA_DIR, _cm.CONV_FILE, _cm.NOTES_FILE = _d, _d / 'conversation.jsonl', _d / 'notes.json'
from core import ui_actions as _ua; _ua._auto = None  # tests use fake element positions: never act on real controls
from pathlib import Path
from datetime import datetime
from core import workflows as wf, hermes_agent, memory_logger, agent_safety as sf
memory_logger.log_entry = lambda *a, **k: None
fails = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not cond: fails.append(name)


# --- real metadata file ---
meta = wf.parse_metadata(wf.default_metadata_file())
check("title parsed", meta.get("title", "").startswith("What If Zoro"), meta.get("title"))
check("video path parsed", meta.get("video", "").endswith("zoro_shells_town_subbed.mp4"), meta.get("video"))
check("thumbnail parsed", meta.get("thumbnail", "").endswith("thumb_t2.jpg"))
check("description has chapters + disclaimer", "0:00" in meta.get("description", "") and "Fan-fiction" in meta.get("description", ""))
check("description excludes TAGS section", "5. TAGS" not in meta.get("description", "") and "one piece, what if" not in meta.get("description", ""))
check("tags parsed", meta.get("tags", "").startswith("one piece, what if") and len(meta["tags"].split(",")) == 20, str(len(meta.get("tags", "").split(","))))
check("schedule parsed", meta.get("schedule_at") == datetime(2026, 11, 15, 2, 0), str(meta.get("schedule_at")))
check("location parsed", meta.get("location", "").strip() == "United States")
errs, warns = wf.validate_metadata(meta)
check("real metadata passes validation", errs == [], str(errs))
task = wf.upload_task(meta)
check("upload task: no AI disclosure change", "Do NOT touch the 'Altered content'" in task and "altered content\": yes" not in task.lower())
check("upload task: schedule date/time", "Nov 15, 2026" in task and "02:00 AM" in task)
check("upload task: exact title/description/tags included", meta["title"] in task and meta["description"][:200] in task)

# validation failures
bad = dict(meta, title="x" * 101, schedule_at=datetime(2020, 1, 1), thumbnail=r"C:\nope.jpg")
errs, _ = wf.validate_metadata(bad)
check("too-long title / past schedule / missing thumb rejected", len(errs) == 3, str(errs))

# --- video lookup + thumbnail prompt ---
d = wf.find_video_dir("luffy marineford p2")
check("find 'luffy marineford p2'", d is not None and d.name == "luffy_marineford_p2", str(d))
check("find 'zoro'", (wf.find_video_dir("zoro") or Path("x")).name == "zoro_shells_town")
check("prompt text is not mistaken for a video", wf.find_video_dir("dark epic samurai sunset with dragon") is None)
req = wf.antigravity_prompts_request(d, "", Path(r"C:\x\prompts.txt"))
check("Antigravity request: 5 prompts, script-aware, file + telegram, no images",
      "5 different" in req and "read its script" in req and "prompts.txt" in req and "telegram_bot.py send" in req and "Do NOT generate images" in req)
req2 = wf.antigravity_prompts_request(None, "Luffy vs Akainu", Path(r"C:\x\p.txt"))
check("idea-only request", "Luffy vs Akainu" in req2)
check("style rules: anime + white/grey + red text", "anime style" in wf.THUMB_STYLE_RULES and "RED" in wf.THUMB_STYLE_RULES)

# --- downloads collection + YouTube jpeg ---
tmp = Path(tempfile.mkdtemp(prefix="dl_"))
wf.DOWNLOADS = tmp
(tmp / "old.png").write_bytes(b"x")
snap, since = wf.downloads_snapshot(), time.time()
time.sleep(1.1)
from PIL import Image
Image.new("RGB", (1024, 1536), (200, 30, 30)).save(tmp / "ChatGPT Image 1.png")   # portrait
Image.new("RGB", (1792, 1024), (30, 30, 200)).save(tmp / "ChatGPT Image 2.png")   # wide
(tmp / "notes.txt").write_text("not an image")
vdir = Path(tempfile.mkdtemp(prefix="vid_"))
pairs = wf.collect_thumbnails(snap, since, vdir)
check("only new images collected", len(pairs) == 2, str(pairs))
sizes = [Image.open(y).size for _, y in pairs]
check("YouTube JPGs are 1280x720 and < 2 MB", all(s == (1280, 720) for s in sizes) and all(y.stat().st_size < 2 * 1024 * 1024 for _, y in pairs), str(sizes))
check("saved into the video's thumbnail folder", all(y.parent == vdir / "thumbnail" for _, y in pairs))

# --- commands end to end with stubbed agent / approval ---
submitted, notified = [], []
ag = hermes_agent.HermesAgent(agent_submit=lambda text, **kw: (submitted.append((text, kw)), "")[1],
                              notifier=lambda r: notified.append(r), approver=lambda t, d: False)
ag.remote_feedback = False
r = ag.process_message("/ytupload check")["text"]
check("/ytupload check shows summary + passes", "All checks passed" in r and "Schedule 15 Nov 2026" in r, r[-200:])
r = ag.process_message("/ytupload")["text"]
check("/ytupload declined -> nothing submitted", "cancelled" in r and not submitted)
ag.approver = lambda t, d: True
r = ag.process_message("/ytupload")["text"]
kw = submitted[-1][1] if submitted else {}
check("/ytupload approved -> agent task with limits + confirm buttons + pre-approved files",
      submitted and kw.get("max_steps") == 200 and "schedule" in kw.get("confirm_buttons", ()) and
      any(p.endswith(".mp4") for p in kw.get("allowed_paths", [])), str(kw.keys()))
submitted.clear()
wf.DOWNLOADS = tmp
from core import studio_control as sc2
asked = []
sc2.status = lambda: {"running": True}
sc2.queue_request = lambda text, sender="PC bot": asked.append((text, sender))
r = ag.process_message("/thumbnails luffy marineford p2")["text"]
time.sleep(1.0)
check("/thumbnails asks Antigravity for the prompts first", asked and "thumbnail image prompts" in asked[0][0] and "luffy_marineford_p2" in asked[0][0].replace("\\", "_"), str(asked)[:160])
check("no ChatGPT task before the prompts exist", not submitted)
check("reply explains the two steps", "Antigravity" in r and "one at a time" in r, r[:100])

# --- safety: final Schedule button always asks; radio/typing does not ---
A = lambda **kw: dict({"thought": ""}, **kw)
cb = ("schedule", "publish", "save", "post")
check("click element Button 'Schedule' needs approval",
      sf.approval_reason(A(action="click", _label='[31] Button "Schedule"'), cb) is not None)
check("click RadioButton 'Schedule' does not", sf.approval_reason(A(action="click", _label='[12] RadioButton "Schedule"'), cb) is None)
check("typing a description with 'send'/'order' words does not", sf.approval_reason(
    A(action="type_text", text="Send your order now, transfer...", thought="type the description"), cb) is None)
check("click 'Save' button needs approval", sf.approval_reason(A(action="click", _label='[40] Button "Save"'), cb) is not None)

check("upload counts only with a real YouTube link", wf.verify_upload_result(True, "Scheduled https://youtu.be/dQw4w9WgXcQ")[0] is True)
check("'done' without a link is NOT confirmed", wf.verify_upload_result(True, "Uploaded successfully")[0] is False)
check("failed upload reported", "not finished" in wf.verify_upload_result(False, "no button")[1])
shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(vdir, ignore_errors=True)
print("\nFAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
