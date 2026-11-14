"""ThumbnailJob: Antigravity writes prompts -> ChatGPT generates one by one; duplicate/missing downloads caught."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

import sys, time, tempfile, threading
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
from PIL import Image
from core import workflows as wf

fails = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not cond: fails.append(name)


# ---- parse_prompts ----
txt = "1. A lone Luffy on the scaffold, red text 'NEVER'\n2) **Akainu magma** clash, white text\n   continues here on a second line\n3. x\n4. Garp stunned, grey text 'GARP'\n5. Whitebeard roar, red 'WHITEBEARD'\n"
pp = wf.parse_prompts(txt)
check("parse: numbered lines, bold, wrapped lines, too-short ignored", len(pp) == 4 and "second line" in pp[1], str(pp))

dl = Path(tempfile.mkdtemp(prefix="dl_")); wf.DOWNLOADS = dl
vdir = Path(tempfile.mkdtemp(prefix="vid_"))
tasks, notes, requests_ = [], [], []
PROMPTS = "\n".join(f"{i}. Anime thumbnail idea number {i} with white and red text, dramatic lighting" for i in range(1, 6))
# per image task label: list of results for successive attempts: ("new"|"dup"|"none")
plan = {"Thumbnail 1/5": ["new"], "Thumbnail 2/5": ["dup"], "Thumbnail 2/5 (download retry)": ["new"],
        "Thumbnail 3/5": ["none"], "Thumbnail 3/5 (download retry)": ["none"],
        "Thumbnail 4/5": ["new"], "Thumbnail 5/5": ["new"]}
state = {"last_img": None, "n": 0}


def fake_submit(text, max_steps=None, on_done=None, label="", expected_words=()):
    tasks.append((label, text))
    what = plan[label][0]
    state["n"] += 1
    if what == "new":
        im = Image.new("RGB", (1536, 1024), (state["n"] * 37 % 255, 40, 90)); p = dl / f"ChatGPT Image {state['n']}.png"
        im.save(p); state["last_img"] = p
    elif what == "dup":  # the SAME picture saved again under a new name (what happened live)
        time.sleep(0.05)
        (dl / f"ChatGPT Image {state['n']} (1).png").write_bytes(state["last_img"].read_bytes())
    threading.Timer(0.05, lambda: on_done(True, "done")).start()
    return ""


def fake_request(text):
    requests_.append(text)
    # Antigravity "writes" the file a moment later
    out = Path(text.split("exactly 5 lines, each line '<n>. <full prompt>' and nothing else:\n")[1].split("\n")[0])
    threading.Timer(0.3, lambda: out.write_text(PROMPTS, encoding="utf-8")).start()


job = wf.ThumbnailJob(vdir, "", fake_submit, notes.append, fake_request, poll_sec=0.2, prompts_timeout=20, image_timeout=10)
job.start()
for _ in range(200):
    if any("Thumbnail job finished" in n["text"] or "stopped" in n["text"].lower() for n in notes): break
    time.sleep(0.2)
time.sleep(0.3)

labels = [t[0] for t in tasks]
check("antigravity was asked (5 prompts, anime, white/grey + red, no images, owner telegram)",
      len(requests_) == 1 and "5 different" in requests_[0] and "RED" in requests_[0] and "Do NOT generate images" in requests_[0]
      and "telegram_bot.py send" in requests_[0], requests_[0][:160] if requests_ else "none")
check("one image per task, in order, with retries only when needed",
      labels == ["Thumbnail 1/5", "Thumbnail 2/5", "Thumbnail 2/5 (download retry)", "Thumbnail 3/5",
                 "Thumbnail 3/5 (download retry)", "Thumbnail 4/5", "Thumbnail 5/5"], str(labels))
check("each task carries its OWN prompt (not all in one)", "idea number 3" in tasks[3][1] and "idea number 2" not in tasks[3][1])
check("first image starts a new chat, later ones reuse it", "NEW chat" in tasks[0][1] and "ALREADY open" in tasks[1][1])
photos = [n["files"][0]["path"] for n in notes if n["files"]]
check("duplicate download rejected, retry fetched a different image", len(photos) == 4, str(len(photos)))
check("missing image reported (thumbnail 3)", any("Thumbnail 3: no NEW image" in n["text"] for n in notes))
check("final summary 4/5", "4/5 downloaded" in notes[-1]["text"], notes[-1]["text"][:90])
check("YouTube-ready 1280x720 under 2 MB", all(Image.open(p).size == (1280, 720) for p in photos) and
      all(Path(p).stat().st_size < 2 * 1024 * 1024 for p in photos))
hs = {wf.file_hash(Path(p)) for p in photos}
check("all delivered thumbnails differ", len(hs) == 4)

# no prompts in time -> clear message, no images
tasks.clear(); notes.clear()
job2 = wf.ThumbnailJob(vdir, "idea", fake_submit, notes.append, lambda t: None, poll_sec=0.1, prompts_timeout=1.0)
job2.start(); time.sleep(2)
check("no prompts -> clear warning, nothing generated", not tasks and any("didn't write the thumbnail prompts" in n["text"] for n in notes))
print("\nFAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
