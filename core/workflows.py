"""Ready-made workflows built on the computer agent (real Edge, works like a person):

  /thumbnails [video | idea]   ChatGPT in Edge -> generate thumbnails -> download -> save into the video's
                               thumbnail folder (+ 1280x720 JPG <= 2 MB for YouTube) -> send to the phone
  /ytupload [folder | check]   METADATA_COPY_PASTE.txt -> validate -> ✅ -> YouTube Studio upload: file, title,
                               description, thumbnail, audience, tags, schedule -> ✅ before the final click

The video pipeline is never modified except that new thumbnail images are ADDED to the video's
thumbnail folder. The AI-disclosure ("altered content") setting is left to the owner.
"""
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
DOWNLOADS = Path.home() / "Downloads"


def _vs() -> Path:
    return Path(config.VIDEOSTUDIO_DIR)


# ----------------------------------------------------------------------
# Finding videos
# ----------------------------------------------------------------------
def _norm_words(text: str) -> list:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in {"video", "the", "ka", "ke", "ki", "for", "of"}]


def video_dirs() -> list:
    root = _vs()
    out = []
    for vj in root.glob("*/*/video.json"):
        out.append(vj.parent)
    for vj in root.glob("*/video.json"):
        out.append(vj.parent)
    return out


def find_video_dir(query: str) -> Optional[Path]:
    """Best pipeline video folder for a name like 'luffy marineford p2' or 'zoro' (None if no match)."""
    words = _norm_words(query)
    if not words:
        return None
    best, best_score = None, 0
    for d in video_dirs():
        name = d.name.lower().replace("_", " ") + " " + d.parent.name.lower().replace("_", " ")
        score = sum(1 for w in words if w in name.split() or w in name)
        if score > best_score or (score == best_score and best and d.stat().st_mtime > best.stat().st_mtime):
            best, best_score = d, score
    # need most of the query to match, so ordinary prompt text isn't mistaken for a video name
    return best if best_score >= max(1, (len(words) + 1) // 2) else None


def video_title(video_dir: Path) -> str:
    for f in [video_dir / "final" / "UPLOAD.md", video_dir / "final" / "PACKAGING.md"]:
        if f.exists():
            t = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"(?im)^\s*(?:#+\s*)?(?:\d+\.\s*)?title[^\n]*\n+\s*[-*>\s]*(.+)", t)
            if m and len(m.group(1).strip()) > 5:
                return m.group(1).strip().strip("*`\"")
    return video_dir.name.replace("_", " ").title()


# ----------------------------------------------------------------------
# Thumbnails
# ----------------------------------------------------------------------
THUMB_COUNT = 5
THUMB_STYLE_RULES = (
    "anime style, 16:9 landscape YouTube thumbnail (1280x720), cinematic lighting, one strong focal character "
    "with an intense expression, bold composition; any text on the image must be SHORT (max 4 words) and only "
    "in WHITE / LIGHT GREY and RED"
)


def antigravity_prompts_request(video_dir: Optional[Path], idea: str, out_file: Path) -> str:
    """Asked to Antigravity (it knows the script): write 5 prompts into out_file and send them to the owner."""
    what = (f"the video in {video_dir.relative_to(_vs()) if video_dir and _vs() in video_dir.parents else video_dir}"
            f" - read its script / notes / thumbnail folder first" if video_dir else f"this idea: {idea}")
    extra = f" Owner's extra wishes: {idea}." if (video_dir and idea) else ""
    return (
        "[Request from the owner's PC bot - thumbnails]\n"
        f"Write {THUMB_COUNT} different YouTube thumbnail image prompts for {what}.{extra}\n"
        f"Each prompt: {THUMB_STYLE_RULES}. Make the {THUMB_COUNT} ideas clearly different, true to the story "
        "(no official anime frames/logos, minors never suggestive - GEMINI.md rule 10).\n"
        f"Save them to this file, exactly {THUMB_COUNT} lines, each line '<n>. <full prompt>' and nothing else:\n"
        f"{out_file}\n"
        "Then send them to the owner with tools/telegram_bot.py send. Do NOT generate images - the PC bot does that "
        "in ChatGPT one by one."
    )


def parse_prompts(text: str) -> list:
    """'1. ...' lines -> [prompt1, ...] (multi-line prompts are joined)."""
    prompts, cur = [], None
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(?:\*\*)?(\d+)[.)]\s*(?:\*\*)?\s*(.+)$", line)
        if m:
            if cur:
                prompts.append(cur.strip())
            cur = m.group(2)
        elif cur and line.strip():
            cur += " " + line.strip()
    if cur:
        prompts.append(cur.strip())
    clean = [re.sub(r"\s+", " ", p.replace("**", "").replace("`", "")).strip() for p in prompts]
    return [p for p in clean if len(p) > 15][:THUMB_COUNT]


def image_task(n: int, prompt: str, first: bool, retry: bool = False) -> str:
    if retry:
        return (
            f"In the ChatGPT chat open in Microsoft Edge, image {n} was generated but its download did not arrive "
            "(or the wrong image was saved). Download the NEWEST image in the chat now: RIGHT-CLICK it and choose "
            "'Save image as', then in the Save dialog press_key enter. (If there is no such menu item, click the "
            "image to open it and click its Download button, then press_key esc.) Do NOT send any message. Then done."
        )
    where = ("1. open_url https://chatgpt.com, wait until it has loaded, and start a NEW chat ('New chat' button "
             "or hotkey ctrl+shift+o).\n" if first else
             "1. Use the ChatGPT chat that is ALREADY open in Edge (do NOT start a new chat; if the page was lost, "
             "click the newest chat in ChatGPT's left sidebar).\n")
    return (
        "Generate ONE YouTube thumbnail with ChatGPT in Microsoft Edge (the user is signed in).\n" + where +
        "2. Click the message box, type_text the MESSAGE below exactly, press_key enter. Send it only ONCE.\n"
        "3. Wait (15 s at a time) until the image is completely finished.\n"
        "4. Download it: RIGHT-CLICK the NEW image and choose 'Save image as', then in the Save dialog press_key "
        "enter. (If there is no such menu item, click the image to open it, click its Download button, then "
        "press_key esc.)\n"
        "5. Finish with done. If ChatGPT shows a limit or asks to log in, ask_user.\n\n"
        f"MESSAGE:\nGenerate this image, 16:9 landscape: {prompt}"
    )


def downloads_snapshot() -> dict:
    if not DOWNLOADS.exists():
        return {}
    return {p.name: p.stat().st_mtime for p in DOWNLOADS.iterdir() if p.is_file()}


def new_images(snapshot: dict, since: float) -> list:
    if not DOWNLOADS.exists():
        return []
    out = []
    for p in DOWNLOADS.iterdir():
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXT:
            continue
        mt = p.stat().st_mtime
        if mt >= since - 2 and (p.name not in snapshot or snapshot[p.name] != mt):
            out.append(p)
    return sorted(out, key=lambda p: p.stat().st_mtime)


def youtube_jpeg(src: Path, dest: Path, max_bytes: int = 2 * 1024 * 1024) -> Path:
    """1280x720 JPEG (centre crop to 16:9) under YouTube's 2 MB thumbnail limit."""
    from PIL import Image
    img = Image.open(src).convert("RGB")
    w, h = img.size
    target = 16 / 9
    if w / h > target:  # too wide -> crop sides
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    elif w / h < target:  # too tall -> crop top/bottom
        nh = int(w / target)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    img = img.resize((1280, 720), Image.LANCZOS)
    for q in (92, 88, 84, 80, 75, 70, 60):
        img.save(dest, "JPEG", quality=q, optimize=True)
        if dest.stat().st_size <= max_bytes:
            break
    return dest


def thumbnails_folder(video_dir: Optional[Path]) -> Path:
    d = (video_dir / "thumbnail") if video_dir else Path(config.INBOX_DIR) / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_thumbnail(src: Path, dest_dir: Path, name: str) -> tuple:
    copy = dest_dir / f"{name}{src.suffix.lower()}"
    shutil.copy2(src, copy)
    return copy, youtube_jpeg(copy, dest_dir / f"{name}_1280.jpg")


def file_hash(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ThumbnailJob:
    """Thumbnails in two parts:
    1. Antigravity (it has the script) writes 5 prompts into a file - requested through the Video Studio
       queue, so it arrives in the Antigravity session as a normal Telegram message.
    2. ChatGPT in Edge generates them ONE AT A TIME. After each image the code checks that a NEW, different
       image really arrived in Downloads (a duplicate of an earlier image counts as 'not downloaded'),
       retries the download once, saves it in the video's thumbnail folder and sends it to the phone."""

    def __init__(self, video_dir: Optional[Path], idea: str, submit, notify, request_prompts,
                 poll_sec: float = 5.0, prompts_timeout: float = 900.0, image_timeout: float = 1500.0):
        self.video_dir, self.idea = video_dir, idea
        self.submit, self.notify, self.request_prompts = submit, notify, request_prompts
        self.poll_sec, self.prompts_timeout, self.image_timeout = poll_sec, prompts_timeout, image_timeout
        self.dest = thumbnails_folder(video_dir)
        self.stamp = time.strftime("%Y%m%d_%H%M")
        self.prompts_file = self.dest / f"antigravity_{self.stamp}_prompts.txt"
        self.done_files, self.hashes = [], set()
        self.stopped = False

    def start(self):
        import threading
        threading.Thread(target=self._run, name="thumbnail-job", daemon=True).start()

    # --- helpers --------------------------------------------------------
    def _run_agent(self, text: str, label: str, steps: int):
        """Runs one agent task and waits for it. Returns (ok, final_text)."""
        import threading
        done, box = threading.Event(), []
        self.submit(text, max_steps=steps, label=label, expected_words=("send", "submit", "post"),
                    on_done=lambda ok, t: (box.append((ok, t)), done.set()))
        done.wait(self.image_timeout)
        ok, t = box[0] if box else (False, "timed out")
        if "stopped by you" in (t or "").lower():
            self.stopped = True
        return ok, t

    def _wait_for_prompts(self) -> list:
        end = time.time() + self.prompts_timeout
        last_size = -1
        while time.time() < end:
            if self.prompts_file.exists():
                size = self.prompts_file.stat().st_size
                if size and size == last_size:  # file stopped growing -> Antigravity finished writing it
                    prompts = parse_prompts(self.prompts_file.read_text(encoding="utf-8", errors="replace"))
                    if len(prompts) >= THUMB_COUNT:
                        return prompts
                last_size = size
            time.sleep(self.poll_sec)
        return []

    # --- the job --------------------------------------------------------
    def _run(self):
        try:
            self._request_and_generate()
        except Exception as e:
            self.notify({"text": f"⚠️ Thumbnail job crashed: `{e}`", "files": []})

    def _request_and_generate(self):
        try:  # never mistake an old file for Antigravity's fresh answer
            self.prompts_file.unlink()
        except FileNotFoundError:
            pass
        self.request_prompts(antigravity_prompts_request(self.video_dir, self.idea, self.prompts_file))
        self.notify({"text": f"📝 Asked Antigravity to write {THUMB_COUNT} thumbnail prompts (it knows the script). "
                             f"I'll start generating when they're ready.", "files": []})
        prompts = self._wait_for_prompts()
        if not prompts:
            self.notify({"text": "⚠️ Antigravity didn't write the thumbnail prompts in time. Is the Antigravity session "
                                 "running (`/studio session`)? Send `/thumbnails` again when it is.", "files": []})
            return
        self.notify({"text": f"🎨 Got {len(prompts)} prompts from Antigravity — generating one by one in ChatGPT…",
                     "files": []})
        for n, prompt in enumerate(prompts[:THUMB_COUNT], 1):
            if self.stopped:
                break
            self._one(n, prompt)
        head = "🛑 Thumbnail job stopped" if self.stopped else "🎨 Thumbnail job finished"
        self.notify({"text": f"{head}: {len(self.done_files)}/{THUMB_COUNT} downloaded, saved in `{self.dest}` "
                             f"(originals + YouTube-ready `_1280.jpg` under 2 MB).", "files": []})

    def _fresh_image(self, snapshot: dict, since: float):
        """Newest downloaded image whose CONTENT is new (not a re-download of an earlier thumbnail)."""
        for p in reversed(new_images(snapshot, since)):
            try:
                if file_hash(p) not in self.hashes:
                    return p
            except OSError:
                continue
        return None

    def _one(self, n: int, prompt: str):
        snapshot, since = downloads_snapshot(), time.time()
        ok, text = self._run_agent(image_task(n, prompt, first=(n == 1 and not self.done_files)),
                                   f"Thumbnail {n}/{THUMB_COUNT}", 30)
        if self.stopped:
            return
        img = self._fresh_image(snapshot, since)
        if img is None:  # generated but not (newly) downloaded: one retry with 'Save image as'
            ok2, text2 = self._run_agent(image_task(n, prompt, first=False, retry=True),
                                         f"Thumbnail {n}/{THUMB_COUNT} (download retry)", 12)
            if self.stopped:
                return
            img = self._fresh_image(snapshot, since)
            text = text2 or text
        if img is None:
            self.notify({"text": f"⚠️ Thumbnail {n}: no NEW image arrived in Downloads ({(text or '')[:160]}).",
                         "files": []})
            if not ok:  # e.g. ChatGPT limit / login: no point in continuing
                self.stopped = True
            return
        self.hashes.add(file_hash(img))
        copy, yt = store_thumbnail(img, self.dest, f"chatgpt_{self.stamp}_{n}")
        self.done_files.append(yt)
        self.notify({"text": "", "files": [{"kind": "photo", "path": str(yt),
                                            "caption": f"🖼️ Thumbnail {n}/{THUMB_COUNT} · `{yt.name}`"}]})


def collect_thumbnails(snapshot: dict, since: float, video_dir: Optional[Path]) -> list:
    """Copies newly downloaded images into the video's thumbnail folder (or the inbox) and makes
    YouTube-ready JPEGs. Returns [(original_copy, youtube_jpg)]."""
    dest = (video_dir / "thumbnail") if video_dir else Path(config.INBOX_DIR) / "thumbnails"
    dest.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M")
    out = []
    for i, src in enumerate(new_images(snapshot, since), 1):
        copy = dest / f"chatgpt_{stamp}_{i}{src.suffix.lower()}"
        shutil.copy2(src, copy)
        yt = youtube_jpeg(copy, dest / f"chatgpt_{stamp}_{i}_1280.jpg")
        out.append((copy, yt))
    return out


# ----------------------------------------------------------------------
# YouTube upload metadata
# ----------------------------------------------------------------------
# most specific first: "VIDEO LOCATION" must not be read as "VIDEO"
_KEYS = [("video location", "location"), ("location", "location"), ("video file", "video"), ("video", "video"),
         ("thumbnail", "thumbnail"), ("title", "title"), ("description", "description"), ("tags", "tags"),
         ("schedule", "schedule"), ("audience", "audience"), ("visibility", "visibility"), ("altered", "altered")]


def default_metadata_file() -> Path:
    return _vs() / "READY_TO_UPLOAD" / "METADATA_COPY_PASTE.txt"


def parse_metadata(path: Path) -> dict:
    """Reads the pipeline's METADATA_COPY_PASTE.txt (numbered sections: 1. VIDEO FILE: ... 3. TITLE ...)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    heads = list(re.finditer(r"(?m)^\s*\d+\.\s*([A-Z][A-Za-z0-9 ()/&,'-]*?)\s*:?\s*$", text))
    meta = {}
    for i, m in enumerate(heads):
        head = m.group(1).lower()
        key = next((k for word, k in _KEYS if head.startswith(word)), None)
        if not key or key in meta:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end]
        body = re.split(r"(?m)^={5,}", body)[0].strip()
        meta[key] = body
    for k in ("video", "thumbnail"):
        if k in meta:
            first = next((l.strip() for l in meta[k].splitlines() if l.strip()), "")
            meta[k] = first.strip('"')
    if "title" in meta:
        meta["title"] = next((l.strip() for l in meta["title"].splitlines() if l.strip()), "")
    if "tags" in meta:
        meta["tags"] = ", ".join(t.strip() for t in re.split(r"[,\n]", meta["tags"]) if t.strip())
    if "schedule" in meta:
        meta["schedule_at"] = parse_schedule(meta["schedule"])
    meta["source"] = str(path)
    return meta


def parse_schedule(text: str) -> Optional[datetime]:
    d = re.search(r"(?i)date\s*:\s*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})", text)
    t = re.search(r"(?i)time\s*:\s*(\d{1,2}:\d{2}\s*[AP]M)", text)
    if not d:
        return None
    ds = d.group(1).replace(".", "").replace(",", "")
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            day = datetime.strptime(ds, fmt)
            break
        except ValueError:
            day = None
    if not day:
        return None
    if t:
        tm = datetime.strptime(t.group(1).replace(" ", "").upper(), "%I:%M%p")
        day = day.replace(hour=tm.hour, minute=tm.minute)
    return day


def validate_metadata(meta: dict) -> tuple:
    """(errors, warnings) using YouTube's limits."""
    errors, warnings = [], []
    title = meta.get("title", "")
    if not title:
        errors.append("no TITLE")
    elif len(title) > 100:
        errors.append(f"title is {len(title)} characters (YouTube max 100)")
    if any(c in title + meta.get("description", "") for c in "<>"):
        errors.append("title/description contain < or > (YouTube rejects them)")
    if len(meta.get("description", "")) > 5000:
        errors.append(f"description is {len(meta['description'])} characters (max 5000)")
    tags = meta.get("tags", "")
    if len(tags) > 500:
        errors.append(f"tags are {len(tags)} characters (max ~500)")
    v = Path(meta.get("video", "") or "?")
    if not v.is_file():
        errors.append(f"video file not found: {v}")
    th = meta.get("thumbnail")
    if th:
        tp = Path(th)
        if not tp.is_file():
            errors.append(f"thumbnail not found: {tp}")
        elif tp.stat().st_size > 2 * 1024 * 1024:
            errors.append(f"thumbnail is {tp.stat().st_size / 1e6:.1f} MB (YouTube max 2 MB)")
        elif tp.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".bmp"):
            errors.append("thumbnail must be JPG/PNG/GIF/BMP")
    else:
        warnings.append("no thumbnail - YouTube will pick a frame")
    when = None if meta.get("force_private") else meta.get("schedule_at")
    if meta.get("schedule") and not when and not meta.get("force_private"):
        warnings.append("could not read the schedule date/time - it will upload as PRIVATE")
    elif when and when <= datetime.now():
        errors.append(f"schedule time {when:%d %b %Y %I:%M %p} is in the past")
    if not when and not meta.get("force_private"):
        warnings.append("no schedule - video will be saved as PRIVATE (you publish it later)")
    return errors, warnings


_YT_LINK = re.compile(r"https?://(?:www\.)?(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|live/))([A-Za-z0-9_-]{11})")


def find_video_link(text: str) -> Optional[str]:
    """First real YouTube video link in the agent's final message (None if it didn't report one)."""
    m = _YT_LINK.search(text or "")
    return m.group(0) if m else None


def verify_upload_result(ok: bool, final_text: str) -> tuple:
    """(confirmed, message). An upload only counts as done when the agent finished AND reported a real video
    link - 'done' alone is not trusted (the agent can be wrong about its own success)."""
    link = find_video_link(final_text)
    if ok and link:
        return True, f"✅ *Upload confirmed* — {link}"
    if ok:
        return False, ("⚠️ The agent says the upload is finished but reported no YouTube link, so I can't confirm it. "
                       "Please check YouTube Studio → Content before assuming it worked.")
    return False, f"❌ *Upload not finished:* {(final_text or '')[:300]}"


def summary(meta: dict) -> str:
    v = Path(meta.get("video", ""))
    size = f"{v.stat().st_size / 1e9:.2f} GB" if v.is_file() else "missing"
    when = None if meta.get("force_private") else meta.get("schedule_at")
    return (
        f"🎬 *Title:* {meta.get('title', '')}\n"
        f"📼 *Video:* `{v.name}` ({size})\n"
        f"🖼️ *Thumbnail:* `{Path(meta['thumbnail']).name if meta.get('thumbnail') else '—'}`\n"
        f"📝 *Description:* {len(meta.get('description', ''))} chars · 🏷️ *Tags:* {len(meta.get('tags', '').split(','))}\n"
        f"📅 *Visibility:* {('Schedule ' + when.strftime('%d %b %Y, %I:%M %p')) if when else 'Private'}\n"
        f"👶 *Audience:* not made for kids · 🤖 *AI disclosure:* left for you"
    )


def upload_task(meta: dict) -> str:
    when = None if meta.get("force_private") else meta.get("schedule_at")
    if meta.get("force_private"):
        vis = ("Visibility step: choose 'Private' - NOT Public, Unlisted or Schedule - then click the final 'Save' "
               "button.")
    elif when:
        vis = (f"Visibility step: choose 'Schedule' and set the date to {when:%b %d, %Y} and the time to "
               f"{when:%I:%M %p} (the PC's time zone). Then click the final 'Schedule' button.")
    else:
        vis = "Visibility step: choose 'Private'. Then click the final 'Save' button."
    loc = (meta.get("location") or "").strip()
    thumb = meta.get("thumbnail")
    return (
        "Upload a video to YouTube Studio in Microsoft Edge (the user is already signed in). Work step by step "
        "and check the screen after each step.\n"
        "1. open_url https://studio.youtube.com ONCE and wait until it has loaded. NEVER invent, guess or type any other URL "
        "(no channel ids, no /videos/upload links). If the page shows an error or 'Oops', press F5 and wait; do not change the "
        "address. The Studio dashboard already has an 'Upload videos' button and a CREATE button.\n"
        "2. Click CREATE (top right), then 'Upload videos'.\n"
        f"3. Click 'Select files', then use upload_file with path: {meta['video']}\n"
        "4. Details step. TITLE box: click it, hotkey ctrl+a, then type_text the TITLE below exactly. "
        "DESCRIPTION box: click it, hotkey ctrl+a, then type_text the DESCRIPTION below exactly.\n"
        + (f"5. Thumbnail: click 'Upload file' in the Thumbnail section, then upload_file with path: {thumb}\n"
           if thumb else "5. Thumbnail: skip (none provided).\n") +
        "6. Audience: select \"No, it's not made for kids\".\n"
        "7. Click 'Show more'. TAGS box: click it and type_text the TAGS below, then press_key enter. "
        + (f"Video location: set it to '{loc}' if the field is there (skip it if it is difficult). " if loc else "") +
        "\n8. Do NOT touch the 'Altered content' / AI disclosure setting - the owner sets it himself.\n"
        "9. Click Next until you reach the Visibility step (do not wait for the upload or checks to finish).\n"
        f"10. {vis} The owner will be asked to approve that final click.\n"
        "11. THE FILE IS LARGE and uploads slowly. KEEP THIS TAB OPEN: never close it, never open another page in it, "
        "never navigate away until the upload has finished and YouTube shows the final confirmation dialog with the "
        "video link. While it uploads, use wait (15 s at a time) and look at the progress text. Closing the page "
        "cancels the upload.\n"
        "12. When YouTube shows the confirmation with the video link, read the link from the dialog, "
        "send_screenshot, then finish with done and put the FULL link (https://youtu.be/...) in the summary. "
        "Without a real link do NOT say done - use fail or ask_user.\n"
        "If a step fails twice, send_screenshot and ask_user. Never change anything else in the channel.\n\n"
        f"TITLE:\n{meta.get('title', '')}\n\n"
        f"DESCRIPTION:\n{meta.get('description', '')}\n\n"
        f"TAGS:\n{meta.get('tags', '')}\n"
    )
