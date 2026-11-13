"""Telegram polling listener. Receives messages and executes commands via Hermes Agent."""
import time
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
from bot import telegram_client
from core.hermes_agent import HermesAgent, llm_status_line
from core import memory_logger
from core import system_lifecycle

OFFSET_FILE = config.TEMP_DIR / ".last_update_id"


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


class Listener:
    """Long-polls Telegram and dispatches updates. Subclass hooks keep the loop reusable."""

    def __init__(self):
        self.agent = HermesAgent()
        self.network_down_since = None
        self.conflict_logged = False

    # --- hooks ---------------------------------------------------------
    def handle_text(self, chat_id: str, sender_name: str, text: str):
        print(f"📩 [{sender_name}] {text}")
        try:
            telegram_client.send_chat_action(chat_id)
            result = self.agent.process_message(text)
            send_result(chat_id, result)
        except Exception as err:
            print(f"[Listener] Error handling '{text}': {err}")
            telegram_client.send_message(chat_id, f"⚠️ Error executing command: `{err}`")

    def handle_message(self, msg: dict):
        chat_id = str(msg.get("chat", {}).get("id"))
        sender = msg.get("from", {}) or {}
        if "text" in msg:
            self.handle_text(chat_id, sender.get("first_name", "User"), msg.get("text", "").strip())
        elif any(k in msg for k in ("document", "photo", "video", "audio", "voice")):
            telegram_client.send_message(chat_id, "📎 File uploads aren't supported in this version.")

    def handle_callback(self, cq: dict):
        telegram_client.answer_callback(cq.get("id"), "No pending request")

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
        print("=" * 60)

        print("⚙️ Warming up packages, display context, and app catalog...")
        warmup_summary = system_lifecycle.warmup_all_subsystems()
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
