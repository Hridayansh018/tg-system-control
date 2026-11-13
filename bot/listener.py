"""Telegram polling listener. Receives messages and executes commands via Hermes Agent."""
import json
import time
from pathlib import Path
import requests
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
from bot import telegram_client
from core.hermes_agent import HermesAgent
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


def run_bot_loop():
    print("=" * 60)
    print("🚀 TG-SYSTEM-CONTROL (Hermes Agent) is Starting...")
    print(f"🔒 Authorized Chat ID: {config.TELEGRAM_CHAT_ID or 'ANY (Warning: Unrestricted)'}")
    print(f"🧠 Active LLM Provider: {config.LLM_PROVIDER.upper()}")
    print("=" * 60)

    # 1. Warm up each and every required package, driver, and app catalog
    print("⚙️ Warming up required packages, display context, and app catalog...")
    warmup_summary = system_lifecycle.warmup_all_subsystems()
    print(f"✅ All Subsystems Primed in {warmup_summary.get('total_warmup_ms')}ms: {warmup_summary}")

    agent = HermesAgent()
    last_offset = load_last_offset()

    # 2. Pre-sync offset
    if last_offset == 0:
        try:
            init_res = requests.get(telegram_client.get_api_url("getUpdates?offset=-1"), timeout=10).json()
            if init_res.get("ok") and init_res.get("result"):
                last_offset = init_res["result"][-1]["update_id"]
                save_last_offset(last_offset)
        except Exception as e:
            print(f"[Listener] Init warning: {e}")

    # 3. Everything is verified, primed, and running: Ping Telegram ONLINE!
    system_lifecycle.notify_online(warmup_summary)

    print("🟢 Polling Telegram for messages (Press Ctrl+C to stop)...")

    while True:
        try:
            url = telegram_client.get_api_url(f"getUpdates?offset={last_offset + 1}&timeout=20")
            res = requests.get(url, timeout=25).json()

            if not res.get("ok"):
                time.sleep(2)
                continue

            for update in res.get("result", []):
                uid = update["update_id"]
                last_offset = uid
                save_last_offset(last_offset)

                # 1. Handle normal text messages
                msg = update.get("message")
                if msg and "text" in msg:
                    chat_id = str(msg.get("chat", {}).get("id"))
                    sender_name = msg.get("from", {}).get("first_name", "User")
                    user_text = msg.get("text", "").strip()

                    # Security authorization check
                    if config.TELEGRAM_CHAT_ID and chat_id != str(config.TELEGRAM_CHAT_ID):
                        print(f"⛔ Unauthorized access attempt from Chat ID {chat_id} ({sender_name})")
                        telegram_client.send_message(chat_id, "⛔ *Access Denied:* You are not authorized to control this system.")
                        continue

                    print(f"📩 [{sender_name}] {user_text}")

                    # Process via Hermes Agent safely
                    try:
                        result = agent.process_message(user_text)

                        # Send photo if returned
                        if result.get("photo"):
                            telegram_client.send_photo(chat_id, result["photo"], caption=result.get("text", ""))
                        elif result.get("text"):
                            telegram_client.send_message(chat_id, result["text"])
                    except Exception as err:
                        print(f"[Listener] Error handling '{user_text}': {err}")
                        try:
                            telegram_client.send_message(chat_id, f"⚠️ Error executing command: `{err}`")
                        except Exception:
                            pass

                # 2. Handle inline button callback queries
                cq = update.get("callback_query")
                if cq:
                    cq_id = cq.get("id")
                    chat_id = str(cq.get("message", {}).get("chat", {}).get("id"))
                    cq_data = cq.get("data", "")
                    sender_name = cq.get("from", {}).get("first_name", "User")

                    # Answer callback query to remove spinner
                    try:
                        requests.post(telegram_client.get_api_url("answerCallbackQuery"), json={"callback_query_id": cq_id, "text": "Received!"}, timeout=5)
                    except Exception:
                        pass

                    if cq_data.startswith("appr:"):
                        key = cq_data[5:]
                        print(f"✅ Approved by {sender_name}: {key}")
                        telegram_client.send_message(chat_id, f"✅ *Task Approved by {sender_name}:* `{key}`")
                    elif cq_data.startswith("canc:"):
                        key = cq_data[5:]
                        print(f"❌ Cancelled by {sender_name}: {key}")
                        telegram_client.send_message(chat_id, f"❌ *Task Cancelled:* `{key}`")

            time.sleep(0.5)

        except requests.exceptions.RequestException:
            time.sleep(2)
        except Exception as e:
            print(f"[Listener Exception] {e}")
            time.sleep(2)


if __name__ == "__main__":
    run_bot_loop()
