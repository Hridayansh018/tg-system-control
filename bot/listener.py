"""Telegram polling listener. Receives messages and executes commands via Hermes Agent.

Threads:
- polling thread (this loop): receives updates, handles /stop, /task, button presses and
  answers to agent questions immediately, so they work even while something else is running.
- command worker: runs normal commands one at a time, in order.
- computer agent worker: runs /agent tasks (core/computer_agent.py).
"""
import queue
import re
import threading
import time
import sys
import uuid
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
from bot import telegram_client
from core.hermes_agent import HermesAgent, llm_status_line, parse_local
from core import computer_agent
from core import memory_logger
from core import os_bridge
from core import system_lifecycle

OFFSET_FILE = config.TEMP_DIR / ".last_update_id"

# Commands that are safe to run while the agent is using the mouse/keyboard.
READ_ONLY_COMMANDS = {"status", "screenshot", "processes", "help", "windows", "clipboard_get", "send_file",
                      "send_latest_download", "agent", "grid", "where", "unblock", "remote"}


def load_last_offset() -> int:
    if OFFSET_FILE.exists():
        try:
            return int(OFFSET_FILE.read_text().strip())
        except Exception:
            pass
    return 0


def save_last_offset(offset: int):
    try:
        OFFSET_FILE.write_text(str(offset))
    except Exception:
        pass


def is_authorized(chat_id, user_id=None) -> bool:
    """Only the configured chat may control the PC. In a private chat the sender must match too."""
    allowed = str(config.TELEGRAM_CHAT_ID).strip()
    if not allowed or str(chat_id) != allowed:
        return False
    if user_id is not None and not allowed.startswith("-") and str(user_id) != allowed:
        return False
    return True


def send_result(chat_id: str, result: dict):
    """Sends {"text", "files"} (and the legacy {"photo"} key) back to Telegram."""
    files = list(result.get("files") or [])
    if result.get("photo"):
        files.append({"kind": "photo", "path": result["photo"], "caption": ""})
    text = (result.get("text") or "").strip()
    if text and len(files) == 1 and len(text) < 900 and not files[0].get("caption"):
        files[0]["caption"] = text
        text = ""
    if text:
        telegram_client.send_message(chat_id, text)
    for f in files:
        sender = telegram_client.send_photo if f.get("kind") == "photo" else telegram_client.send_document
        res = sender(chat_id, f["path"], caption=f.get("caption", ""))
        if not res.get("ok"):
            telegram_client.send_message(chat_id, f"⚠️ Could not send `{Path(f['path']).name}`: {res.get('description') or res.get('error')}")


# ----------------------------------------------------------------------
# Approvals & questions
# ----------------------------------------------------------------------
class ApprovalManager:
    """Shows ✅ Approve / ❌ Cancel cards and blocks the calling (worker) thread until answered."""

    def __init__(self, chat_id: str, timeout_sec: int):
        self.chat_id = chat_id
        self.timeout = timeout_sec
        self.pending = {}  # key -> {"event", "approved", "msg_id", "title"}
        self.lock = threading.Lock()

    def request(self, title: str, details: str, cancel: Optional[threading.Event] = None) -> bool:
        key = uuid.uuid4().hex[:10]
        entry = {"event": threading.Event(), "approved": False, "msg_id": None, "title": title}
        with self.lock:
            self.pending[key] = entry
        res = telegram_client.send_approval_card(self.chat_id, title, details + f"\n⏳ Auto-cancels in {self.timeout // 60} min.", key)
        entry["msg_id"] = (res.get("result") or {}).get("message_id")
        deadline = time.time() + self.timeout
        while not entry["event"].is_set() and time.time() < deadline:
            if cancel is not None and cancel.is_set():
                break
            entry["event"].wait(0.5)
        with self.lock:
            self.pending.pop(key, None)
        approved = entry["event"].is_set() and entry["approved"]
        if not entry["event"].is_set() and entry["msg_id"]:
            telegram_client.edit_message(self.chat_id, entry["msg_id"], f"⌛ *Not approved (timed out / stopped):* {title}")
        return approved

    def resolve(self, key: str, approved: bool) -> Optional[str]:
        with self.lock:
            entry = self.pending.get(key)
        if not entry:
            return None
        entry["approved"] = approved
        entry["event"].set()
        if entry["msg_id"]:
            telegram_client.edit_message(self.chat_id, entry["msg_id"],
                                         f"{'✅ *Approved:*' if approved else '❌ *Cancelled:*'} {entry['title']}")
        return entry["title"]

    def cancel_all(self):
        with self.lock:
            entries = list(self.pending.values())
        for e in entries:
            e["approved"] = False
            e["event"].set()


class QuestionBox:
    """Lets the agent ask a question; the user's next normal message is the answer."""

    def __init__(self, chat_id: str, timeout_sec: int):
        self.chat_id = chat_id
        self.timeout = timeout_sec
        self.event = None
        self.answer = None

    def waiting(self) -> bool:
        return self.event is not None

    def ask(self, question: str, cancel: threading.Event) -> Optional[str]:
        self.answer, self.event = None, threading.Event()
        telegram_client.send_message(self.chat_id, question + "\n\n_Reply with your answer, or /stop to cancel._")
        deadline = time.time() + self.timeout
        while not self.event.is_set() and not cancel.is_set() and time.time() < deadline:
            self.event.wait(0.5)
        answer = self.answer if self.event.is_set() else None
        self.event = None
        return answer

    def deliver(self, text: str) -> bool:
        ev = self.event
        if ev is None:
            return False
        self.answer = text
        ev.set()
        return True


class TelegramAgentUI(computer_agent.AgentUI):
    def __init__(self, chat_id: str, approvals: ApprovalManager, questions: QuestionBox):
        self.chat_id, self.approvals, self.questions = chat_id, approvals, questions

    def send_text(self, text):
        res = telegram_client.send_message(self.chat_id, text)
        return (res.get("result") or {}).get("message_id")

    def edit_text(self, message_id, text):
        telegram_client.edit_message(self.chat_id, message_id, text)

    def send_photo(self, path, caption=""):
        telegram_client.send_photo(self.chat_id, path, caption)

    def send_document(self, path, caption=""):
        telegram_client.send_document(self.chat_id, path, caption)

    def request_approval(self, title, details, cancel):
        return self.approvals.request(title, details, cancel)

    def ask_user(self, question, cancel):
        return self.questions.ask(question, cancel)


# ----------------------------------------------------------------------
# Listener
# ----------------------------------------------------------------------
class Listener:
    def __init__(self):
        chat_id = str(config.TELEGRAM_CHAT_ID)
        self.chat_id = chat_id
        self.approvals = ApprovalManager(chat_id, config.APPROVAL_TIMEOUT_SEC)
        self.questions = QuestionBox(chat_id, config.APPROVAL_TIMEOUT_SEC)
        self.computer = None
        brain = computer_agent.default_brain() if config.AGENT_ENABLED else None
        if brain is not None:
            self.computer = computer_agent.ComputerAgent(TelegramAgentUI(chat_id, self.approvals, self.questions), brain)
        self.agent = HermesAgent(agent_hook=self._agent_hook if self.computer else None,
                                 approver=lambda title, details: self.approvals.request(title, details))
        self.commands: "queue.Queue[tuple]" = queue.Queue()
        threading.Thread(target=self._command_worker, name="command-worker", daemon=True).start()
        self.network_down_since = None
        self.conflict_logged = False

    # --- agent glue ---------------------------------------------------
    def _agent_hook(self, task: str) -> dict:
        note = self.computer.submit(task)
        return {"text": note, "files": []}

    def _command_worker(self):
        while True:
            chat_id, text = self.commands.get()
            try:
                telegram_client.send_chat_action(chat_id)
                send_result(chat_id, self.agent.process_message(text))
            except Exception as err:
                print(f"[Listener] Error handling '{text}': {err}")
                telegram_client.send_message(chat_id, f"⚠️ Error executing command: `{err}`")

    # --- updates --------------------------------------------------------
    def handle_text(self, chat_id: str, sender_name: str, text: str):
        print(f"📩 [{sender_name}] {text}")
        low = text.strip().lower()

        if low in ("/stop", "stop", "ruko", "ruk jao", "band karo agent"):
            self.approvals.cancel_all()
            msg = self.computer.stop() if self.computer else "Nothing is running."
            if self.questions.waiting():
                self.questions.deliver(None)
            os_bridge.release_input_lock()
            memory_logger.log_entry("AGENT_CONTROL", "/stop", details={"result": msg})
            telegram_client.send_message(chat_id, msg)
            return
        if low in ("/task", "/tasks", "task status"):
            telegram_client.send_message(chat_id, self.computer.status_text() if self.computer else "Agent mode is off.")
            return

        if self.questions.waiting() and not text.startswith("/"):
            self.questions.deliver(text)
            telegram_client.send_message(chat_id, "👍 Got it, continuing…")
            return

        if self.computer and self.computer.busy():
            local = parse_local(text)
            if not local or any(cmd not in READ_ONLY_COMMANDS for cmd, _ in local):
                telegram_client.send_message(
                    chat_id,
                    "🤖 The agent is using the mouse/keyboard right now.\n"
                    "Send `/task` for progress, `/stop` to cancel, `/agent <task>` to queue another task, "
                    "or read-only commands like `status` / `screenshot`.")
                return

        self.commands.put((chat_id, text))

    def handle_upload(self, chat_id: str, msg: dict):
        doc = msg.get("document") or msg.get("video") or msg.get("audio") or msg.get("voice")
        photo = (msg.get("photo") or [None])[-1]
        item = doc or photo
        if not item:
            return
        if item.get("file_size", 0) > 20 * 1024 * 1024:
            telegram_client.send_message(chat_id, "⚠️ Telegram bots can only download files up to 20 MB.")
            return
        name = (doc or {}).get("file_name") or f"photo_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "file"
        dest = config.INBOX_DIR / name
        n = 1
        while dest.exists():
            dest = config.INBOX_DIR / f"{Path(name).stem} ({n}){Path(name).suffix}"
            n += 1
        try:
            telegram_client.download_file(item["file_id"], dest)
        except Exception as e:
            telegram_client.send_message(chat_id, f"⚠️ Upload failed: `{e}`")
            return
        memory_logger.log_entry("UPLOAD", f"Saved {dest.name}", details={"path": str(dest), "bytes": dest.stat().st_size})
        telegram_client.send_message(
            chat_id,
            f"📥 Saved to `{dest}`\n\n"
            f"To upload it to a website: open the site's *Upload / Choose file* button "
            f"(e.g. `click X Y`, see `/grid`), then send `/uploadfile {dest.name}`.\n"
            f"Or let the agent do it: `/agent upload {dest.name} to <site>`")
        caption = (msg.get("caption") or "").strip()
        if caption:
            self.handle_text(chat_id, "caption", caption.replace("{file}", str(dest)))

    def handle_message(self, msg: dict):
        chat_id = str(msg.get("chat", {}).get("id"))
        sender = msg.get("from", {}) or {}
        if "text" in msg:
            self.handle_text(chat_id, sender.get("first_name", "User"), msg.get("text", "").strip())
        elif any(k in msg for k in ("document", "photo", "video", "audio", "voice")):
            self.handle_upload(chat_id, msg)

    def handle_callback(self, cq: dict):
        data = cq.get("data", "")
        if data.startswith(("appr:", "canc:")):
            title = self.approvals.resolve(data[5:], data.startswith("appr:"))
            telegram_client.answer_callback(cq.get("id"), ("Approved" if data.startswith("appr:") else "Cancelled") if title else "This request has expired")
            return
        telegram_client.answer_callback(cq.get("id"), "Unknown button")

    # --- loop ----------------------------------------------------------
    def _authorized_update(self, update: dict) -> bool:
        msg = update.get("message")
        if msg:
            chat_id = msg.get("chat", {}).get("id")
            sender = msg.get("from", {}) or {}
            if not is_authorized(chat_id, sender.get("id")):
                print(f"⛔ Unauthorized access attempt from Chat ID {chat_id} ({sender.get('first_name')})")
                memory_logger.log_entry("SECURITY", "Rejected unauthorized message",
                                        details={"chat_id": chat_id, "from": sender.get("id")})
                telegram_client.send_message(str(chat_id), "⛔ *Access Denied:* You are not authorized to control this system.")
                return False
            return True
        cq = update.get("callback_query")
        if cq:
            chat_id = cq.get("message", {}).get("chat", {}).get("id")
            if not is_authorized(chat_id, cq.get("from", {}).get("id")):
                telegram_client.answer_callback(cq.get("id"), "Not authorized")
                memory_logger.log_entry("SECURITY", "Rejected unauthorized button press",
                                        details={"chat_id": chat_id, "from": cq.get("from", {}).get("id")})
                return False
            return True
        return False

    def dispatch(self, update: dict):
        if not self._authorized_update(update):
            return
        if update.get("message"):
            self.handle_message(update["message"])
        elif update.get("callback_query"):
            self.handle_callback(update["callback_query"])

    def _network_down(self, reason: str):
        if self.network_down_since is None:
            self.network_down_since = time.time()
            print(f"[Listener] Network problem: {reason}")
            memory_logger.log_entry("NETWORK", "Telegram connection lost", details={"reason": reason[:200]})

    def _network_up(self):
        if self.network_down_since is not None:
            secs = int(time.time() - self.network_down_since)
            self.network_down_since = None
            print(f"[Listener] Network restored after {secs}s")
            memory_logger.log_entry("NETWORK", "Telegram connection restored", details={"down_for_sec": secs})

    def run(self):
        print("=" * 60)
        print("🚀 TG-SYSTEM-CONTROL (Hermes Agent) is Starting...")
        print(f"🔒 Authorized Chat ID: {config.TELEGRAM_CHAT_ID}")
        print(f"🧠 AI translator: {llm_status_line()}")
        print(f"🤖 Agent mode: {'ON (' + self.computer.brain.name + ')' if self.computer else 'OFF'}")
        print("=" * 60)

        print("⚙️ Warming up packages, display context, and app catalog...")
        warmup_summary = system_lifecycle.warmup_all_subsystems()
        warmup_summary["agent_mode"] = "ON" if self.computer else "OFF"
        print(f"✅ All Subsystems Primed in {warmup_summary.get('total_warmup_ms')}ms: {warmup_summary}")

        last_offset = load_last_offset()
        if last_offset == 0:
            try:
                init_res = requests.get(telegram_client.get_api_url("getUpdates"), params={"offset": -1}, timeout=10).json()
                if init_res.get("ok") and init_res.get("result"):
                    last_offset = init_res["result"][-1]["update_id"]
                    save_last_offset(last_offset)
            except Exception as e:
                print(f"[Listener] Init warning: {e}")

        system_lifecycle.notify_online(warmup_summary)
        print("🟢 Polling Telegram for messages (Press Ctrl+C to stop)...")

        while True:
            try:
                res = requests.get(
                    telegram_client.get_api_url("getUpdates"),
                    params={"offset": last_offset + 1, "timeout": 20},
                    timeout=30,
                ).json()

                if not res.get("ok"):
                    if res.get("error_code") == 409:
                        if not self.conflict_logged:
                            self.conflict_logged = True
                            msg = "Another program is polling this bot (409 Conflict) - replies may be duplicated or missed."
                            print(f"[Listener] {msg}")
                            memory_logger.log_entry("WARNING", "Duplicate bot poller detected", thinking=msg)
                        time.sleep(5)
                    else:
                        self._network_down(str(res.get("description")))
                        time.sleep(2)
                    continue

                self._network_up()
                self.conflict_logged = False
                for update in res.get("result", []):
                    uid = update["update_id"]
                    if uid <= last_offset:
                        continue  # already handled
                    last_offset = uid
                    save_last_offset(last_offset)
                    self.dispatch(update)

            except requests.exceptions.RequestException as e:
                self._network_down(type(e).__name__)
                time.sleep(2)
            except Exception as e:
                print(f"[Listener Exception] {e}")
                time.sleep(2)


def run_bot_loop():
    Listener().run()


if __name__ == "__main__":
    run_bot_loop()
