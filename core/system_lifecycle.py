"""System lifecycle manager: Handles ONLINE / OFFLINE notifications,
Windows shutdown detection, and Telegram bot status updates.
"""
import atexit
import ctypes
import os
import platform
import sys
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
from bot import telegram_client
from core import os_bridge

STATUS_MSG_FILE = config.TEMP_DIR / ".status_msg_id"
IS_WINDOWS = platform.system() == "Windows"


def update_bot_bio(status_text: str):
    """Updates the Telegram Bot's short description / bio."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        return
    try:
        # Update short description (shows in profile)
        url_short = f"https://api.telegram.org/bot{token}/setMyShortDescription"
        requests.post(url_short, json={"short_description": f"{status_text} | TG-System-Control"}, timeout=5)

        # Update about description
        url_desc = f"https://api.telegram.org/bot{token}/setMyDescription"
        requests.post(url_desc, json={"description": f"Desktop Remote Controller.\n\nCurrent Status: {status_text}\nUpdated: {time.strftime('%Y-%m-%d %H:%M:%S')}"}, timeout=5)
    except Exception as e:
        print(f"[Lifecycle] update_bot_bio error: {e}")


def notify_online():
    """Triggered when the agent starts and desktop is online."""
    stats = os_bridge.get_system_stats()
    online_text = (
        f"🟢 *SYSTEM ONLINE* ⚡\n\n"
        f"Desktop successfully connected and listening.\n"
        f"🖥️ *Machine:* `{stats.get('os')}` ({stats.get('architecture')})\n"
        f"🧠 *CPU:* `{stats.get('cpu_cores')} cores` | ⚡ *RAM:* `{stats.get('ram_used_pct')}% used`\n"
        f"💾 *Disk Free:* `{stats.get('disk_free_gb')} GB`\n"
        f"🕒 *Connected At:* `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
        f"Send `status`, `screenshot` or any command to begin."
    )

    # 1. Send chat notification
    res = telegram_client.send_message(config.TELEGRAM_CHAT_ID, online_text)
    if res.get("ok"):
        msg_id = res["result"]["message_id"]
        # Save message id to pin or update later
        try:
            STATUS_MSG_FILE.write_text(str(msg_id))
            # Try to pin the status message
            pin_url = telegram_client.get_api_url("pinChatMessage")
            requests.post(pin_url, json={"chat_id": config.TELEGRAM_CHAT_ID, "message_id": msg_id, "disable_notification": True}, timeout=5)
        except Exception:
            pass

    # 2. Update Bot Profile Status
    update_bot_bio("🟢 System ONLINE")
    print("🟢 [ONLINE] Desktop connection notification sent to Telegram.")


def notify_offline(reason="Desktop shut down / Agent stopped"):
    """Triggered on script exit, SIGTERM, or Windows shutdown."""
    offline_text = (
        f"🔴 *SYSTEM OFFLINE* 💤\n\n"
        f"Desktop connection closed.\n"
        f"📌 *Reason:* `{reason}`\n"
        f"🕒 *Disconnected At:* `{time.strftime('%Y-%m-%d %H:%M:%S')}`"
    )

    # Send offline notification
    try:
        telegram_client.send_message(config.TELEGRAM_CHAT_ID, offline_text)
    except Exception:
        pass

    # Update Bot Profile Status
    try:
        update_bot_bio("🔴 System OFFLINE")
    except Exception:
        pass

    print(f"🔴 [OFFLINE] Desktop disconnection recorded ({reason}).")


# ----------------------------------------------------------------------
# Windows Shutdown & Signal Hooks
# ----------------------------------------------------------------------
_IS_NOTIFIED_OFFLINE = False


def _safe_offline(reason):
    global _IS_NOTIFIED_OFFLINE
    if not _IS_NOTIFIED_OFFLINE:
        _IS_NOTIFIED_OFFLINE = True
        notify_offline(reason)


def register_lifecycle_hooks():
    """Registers graceful shutdown hooks for Windows shutdown, logoff, and exit."""
    atexit.register(lambda: _safe_offline("Process terminated / Normal exit"))

    if IS_WINDOWS:
        try:
            # Console control handler for Windows (close event, shutdown, logoff)
            PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)

            def ctrl_handler(ctrl_type):
                events = {
                    0: "CTRL_C received",
                    1: "CTRL_BREAK received",
                    2: "Console window closed",
                    5: "Windows user logging off",
                    6: "Windows system shutdown",
                }
                reason = events.get(ctrl_type, f"Windows Event {ctrl_type}")
                _safe_offline(f"Desktop Shutdown: {reason}")
                return False

            global _global_ctrl_handler
            _global_ctrl_handler = PHANDLER_ROUTINE(ctrl_handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_global_ctrl_handler, True)
        except Exception as e:
            print(f"[Lifecycle] SetConsoleCtrlHandler hook warning: {e}")
