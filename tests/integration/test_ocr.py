import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

import sys, time, os
sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image, ImageDraw, ImageFont
from core import ocr

S = str(FIXTURES)
img = Image.new("RGB", (1000, 500), (245, 245, 245))
d = ImageDraw.Draw(img)
font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 28)
d.text((60, 80), "Upload videos", fill=(0, 0, 0), font=font)
d.rectangle([600, 200, 840, 260], fill=(30, 100, 220)); d.text((640, 214), "Select files", fill=(255, 255, 255), font=font)
d.text((60, 330), "Schedule", fill=(0, 0, 0), font=font)
p = str(Path(os.environ.get("TEMP", ".")) / "ocr_input.png"); img.save(p)
fails = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""), flush=True)
    if not cond: fails.append(name)


t0 = time.perf_counter(); words = ocr.read_words(p); dt = time.perf_counter() - t0
check("Windows OCR available and returns words", bool(words), f"{dt:.1f}s {[w['t'] for w in (words or [])]}")
if words:
    m = ocr.find_text(words, "select files")
    check("finds 'Select files' (two words) at the button", len(m) == 1 and 590 < m[0]["x"] + m[0]["w"] // 2 < 850 and 195 < m[0]["y"] + m[0]["h"] // 2 < 265, str(m))
    m = ocr.find_text(words, "SCHEDULE")
    check("case-insensitive single word", len(m) == 1 and m[0]["y"] > 300, str(m))
    check("missing text -> no match", ocr.find_text(words, "publish now") == [])
    check("words must be on the same line", ocr.find_text(words, "videos select") == [])
print("FAILED:", fails if fails else "none"); sys.stdout.flush(); os._exit(1 if fails else 0)
