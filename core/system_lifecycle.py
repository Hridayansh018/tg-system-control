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
from core import memory_logger

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


def warmup_all_subsystems() -> dict:
    """Pre-loads, initializes and validates every required subsystem and dependency.
    Ensures zero latency when commands arrive from Telegram.
    """
    t0 = time.time()
    results = {}

    # 1. Package verification
    t_pkg = time.time()
    import requests
    from PIL import ImageGrab
    import ctypes
    results["packages"] = f"OK ({int((time.time() - t_pkg)*1000)}ms)"

    # 2. File system & memory logger
    t_fs = time.time()
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    config.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    memory_logger.log_entry(
        "WARMUP_CHECK",
        "Subsystem Warm-Up Started",
        thinking="Pre-warming all libraries, display drivers, app catalog, and network bridges before sending ONLINE status."
    )
    results["storage"] = f"OK ({int((time.time() - t_fs)*1000)}ms)"

    # 3. Universal App Catalog Indexing (Zero latency for app open/close)
    t_app = time.time()
    apps = os_bridge.get_installed_apps()
    results["app_catalog"] = f"Indexed {len(apps)} apps ({int((time.time() - t_app)*1000)}ms)"

    # 4. Display & Screenshot Capture Context
    t_screen = time.time()
    test_shot = config.TEMP_DIR / ".warmup_screen.jpg"
    shot_ok = os_bridge.take_screenshot(test_shot)
    if test_shot.exists():
        try:
            test_shot.unlink()
        except Exception:
            pass
    results["screen_engine"] = f"{'Primed' if shot_ok else 'Fallback'} ({int((time.time() - t_screen)*1000)}ms)"

    # 5. OS Input & Hardware Hook Bridge
    t_input = time.time()
    with os_bridge.UserInputLock("Warmup"):
        pass
    results["input_bridge"] = f"Primed ({int((time.time() - t_input)*1000)}ms)"

    # 6. Telegram API Connectivity & Latency Benchmark
    t_net = time.time()
    net_ok = False
    bot_info = {}
    if config.TELEGRAM_BOT_TOKEN:
        try:
            r = requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe", timeout=6).json()
            if r.get("ok"):
                net_ok = True
                bot_info = r["result"]
        except Exception as e:
            results["network_error"] = str(e)
    net_ms = int((time.time() - t_net) * 1000)
    results["telegram_api"] = f"Connected to @{bot_info.get('username', 'bot')} ({net_ms}ms)" if net_ok else "Unreachable"

    total_time_ms = int((time.time() - t0) * 1000)
    results["total_warmup_ms"] = total_time_ms
    return results


def notify_online(warmup_summary: dict = None):
    """Triggered only after all required packages, scripts, and listeners are 100% warmed up."""
    stats = os_bridge.get_system_stats()
    warmup_line = ""
    if warmup_summary:
        warmup_line = (
            f"⚡ *Zero-Latency Warm-Up:* `{warmup_summary.get('total_warmup_ms', 0)} ms`\n"
            f"📦 *Apps Indexed:* `{warmup_summary.get('app_catalog', 'Ready')}`\n"
            f"🌐 *Network API:* `{warmup_summary.get('telegram_api', 'Connected')}`\n"
        )

    online_text = (
        f"🟢 *SYSTEM ONLINE* ⚡\n\n"
        f"Desktop successfully connected and listening with *Zero Latency*.\n"
        f"🖥️ *Machine:* `{stats.get('os')}` ({stats.get('architecture')})\n"
        f"🧠 *CPU:* `{stats.get('cpu_cores')} cores` | ⚡ *RAM:* `{stats.get('ram_used_pct')}% used`\n"
        f"💾 *Disk Free:* `{stats.get('disk_free_gb')} GB`\n"
        f"{warmup_line}"
        f"🕒 *Connected At:* `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
        f"Send `open <app>`, `close <app>`, `status`, or `screenshot` to begin."
    )

    # 1. Send chat notification
    res = telegram_client.send_message(config.TELEGRAM_CHAT_ID, online_text)
    if res.get("ok"):
        msg_id = res["result"]["message_id"]
        try:
            STATUS_MSG_FILE.write_text(str(msg_id))
            pin_url = telegram_client.get_api_url("pinChatMessage")
            requests.post(pin_url, json={"chat_id": config.TELEGRAM_CHAT_ID, "message_id": msg_id, "disable_notification": True}, timeout=5)
        except Exception:
            pass

    # 2. Update Bot Profile Status
    update_bot_bio("🟢 System ONLINE")
    print("🟢 [ONLINE] Desktop connection notification sent to Telegram.")
    memory_logger.log_entry(
        "LIFECYCLE_EVENT",
        "System Came ONLINE (Zero-Latency Primed)",
        details={
            "os": stats.get("os"),
            "cpu_cores": stats.get("cpu_cores"),
            "ram_used_pct": stats.get("ram_used_pct"),
            "disk_free_gb": stats.get("disk_free_gb"),
            "warmup": warmup_summary
        },
        thinking="All packages verified, drivers primed, App catalog indexed, and Telegram notification dispatched."
    )


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
    memory_logger.log_entry(
        "LIFECYCLE_EVENT",
        f"System Went OFFLINE ({reason})",
        details={"reason": reason, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")},
        thinking="System shutdown, process interrupt, or user logoff detected. Cleaning up and notifying Telegram."
    )


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
