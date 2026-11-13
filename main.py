"""Main entry point for tg-system-control with Online/Offline lifecycle management."""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Emoji log lines must not crash the bot when output is redirected (Windows defaults to cp1252).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
from bot.listener import run_bot_loop
from core import system_lifecycle


def main():
    parser = argparse.ArgumentParser(description="TG-System-Control (Hermes Agent)")
    parser.add_argument("--test", action="store_true", help="Send a test ONLINE message and exit")
    parser.add_argument("--offline-test", action="store_true", help="Send a test OFFLINE message and exit")
    args = parser.parse_args()

    if config.is_placeholder(config.TELEGRAM_BOT_TOKEN):
        print("❌ Error: TELEGRAM_BOT_TOKEN is not configured in .env")
        sys.exit(1)
    if config.is_placeholder(config.TELEGRAM_CHAT_ID):
        print("❌ Error: TELEGRAM_CHAT_ID is not configured in .env.")
        print("   Without it anyone who finds your bot could control this PC, so the bot will not start.")
        sys.exit(1)

    if args.test:
        system_lifecycle.notify_online()
        return
    if args.offline_test:
        system_lifecycle.notify_offline("Manual Test Shutdown")
        return

    # 1. Only one instance per bot token may poll Telegram (prevents duplicate replies)
    if not system_lifecycle.acquire_single_instance_lock():
        print("[FATAL] Another TG-System-Control instance for this bot is already running.")
        print("[FATAL] Run stop_agent.bat (or pkill -f main.py) first. Exiting.")
        sys.exit(0)

    # 2. Shutdown / logoff / signal / stop-flag hooks
    system_lifecycle.register_lifecycle_hooks()

    # 3. Auto-restarting supervisor loop
    while True:
        try:
            run_bot_loop()
        except KeyboardInterrupt:
            print("\nStopping TG-System-Control...")
            system_lifecycle.safe_offline("Agent stopped by user (Ctrl+C)")
            break
        except Exception as e:
            print(f"[Main Supervisor] Daemon encountered error: {e}. Auto-recovering in 3s...")
            time.sleep(3)


if __name__ == "__main__":
    main()
