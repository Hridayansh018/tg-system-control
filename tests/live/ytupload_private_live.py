"""LIVE TEST (real YouTube, real Edge, real Gemini): upload the READY_TO_UPLOAD video as PRIVATE.

Runs the same /ytupload workflow as the bot, in this process, with progress sent to your Telegram.
Safety rules of this harness (you authorised: "upload the video and make it private"):
  - only ONE approval is ever granted: the final 'Save' click, and only after a human/assistant has looked at
    the screenshot saved to temp/final_check.png and created temp/.approve_final (Private selected!).
    Create temp/.decline_final instead to refuse.
  - every other approval request is declined and reported.
  - create temp/.stop_upload to stop the run at any time.
This file does nothing unless you run it by hand:  python tests/live/ytupload_private_live.py
"""
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import config  # noqa: E402
from bot import telegram_client as tc  # noqa: E402
from core import computer_agent as ca, hermes_agent, ui_elements as ue, os_bridge as ob  # noqa: E402

CHAT = str(config.TELEGRAM_CHAT_ID)
TEMP = Path(config.TEMP_DIR)
APPROVE_FLAG, DECLINE_FLAG, STOP_FLAG = TEMP / ".approve_final", TEMP / ".decline_final", TEMP / ".stop_upload"
CHECK_PNG = TEMP / "final_check.png"
FINISHED = threading.Event()
T0 = time.time()


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class UI(ca.AgentUI):
    def send_text(self, text):
        res = tc.send_message(CHAT, text)
        log("MSG " + text[:110].replace("\n", " | "))
        return (res.get("result") or {}).get("message_id")

    def edit_text(self, message_id, text):
        tc.edit_message(CHAT, message_id, text)
        last = text.strip().split("\n")[-3:-2]
        if last:
            log("PROGRESS " + last[0][:130])

    def send_photo(self, path, caption=""):
        tc.send_photo(CHAT, path, caption=caption)
        log("PHOTO " + caption[:90].replace("\n", " | "))

    def send_document(self, path, caption=""):
        tc.send_document(CHAT, path, caption=caption)

    def request_approval(self, title, details, cancel):
        log(f"APPROVAL REQUEST: {title[:100]} | {details[:140].replace(chr(10), ' ')}")
        if "final '" not in details.lower():
            tc.send_message(CHAT, f"⛔ Upload test: declined a permission I was not authorised to give: {title[:140]}")
            return False
        ob.take_screenshot(CHECK_PNG)
        tc.send_photo(CHAT, str(CHECK_PNG), caption="🔎 About to click the final Save - verifying that *Private* is selected first.")
        for f in (APPROVE_FLAG, DECLINE_FLAG):
            f.unlink(missing_ok=True)
        log("WAITING_FINAL_CHECK (create temp/.approve_final or temp/.decline_final)")
        end = time.time() + 1500
        while time.time() < end and not cancel.is_set():
            if APPROVE_FLAG.exists():
                APPROVE_FLAG.unlink(missing_ok=True)
                log("final Save approved (Private verified)")
                return True
            if DECLINE_FLAG.exists():
                DECLINE_FLAG.unlink(missing_ok=True)
                log("final Save declined")
                return False
            time.sleep(1)
        return False

    def ask_user(self, question, cancel):
        tc.send_message(CHAT, f"❓ Upload test needs you: {question}\n(This test run can't read replies, so it stops here.)")
        log("ASK " + question[:120])
        return None


def notify(result):
    if result.get("text"):
        tc.send_message(CHAT, result["text"])
        log("RESULT " + result["text"][:200].replace("\n", " | "))
        if any(k in result["text"] for k in ("Upload confirmed", "not finished", "can't confirm")):
            FINISHED.set()
    for f in result.get("files") or []:
        (tc.send_photo if f.get("kind") == "photo" else tc.send_document)(CHAT, f["path"], caption=f.get("caption", ""))


def main():
    STOP_FLAG.unlink(missing_ok=True)
    ue.warm_up()
    agent = ca.ComputerAgent(UI(), ca.GeminiBrain())
    ha = hermes_agent.HermesAgent(agent_submit=agent.submit, notifier=notify,
                                  approver=lambda title, details: True)  # the start-of-upload question only
    ha.remote_feedback = False
    log("starting: /ytupload private")
    reply = ha.process_message("/ytupload private")["text"]
    log("COMMAND REPLY: " + reply[-160:].replace("\n", " | "))
    tc.send_message(CHAT, "🧪 Live upload test started: the video is uploading as PRIVATE. It can take a long time (large file).")

    def watch_stop():
        while not FINISHED.is_set():
            if STOP_FLAG.exists():
                STOP_FLAG.unlink(missing_ok=True)
                log("STOP requested")
                agent.stop()
            time.sleep(1)

    threading.Thread(target=watch_stop, daemon=True).start()
    FINISHED.wait(6 * 3600)
    time.sleep(3)
    log(f"FINISHED after {(time.time() - T0) / 60:.0f} min")


if __name__ == "__main__":
    main()
