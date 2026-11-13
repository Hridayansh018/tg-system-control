"""Main entry point for tg-system-control with Online/Offline Lifecycle management."""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import config
from bot.listener import run_bot_loop
from bot import telegram_client
from core import system_lifecycle


def main():
    parser = argparse.ArgumentParser(description="TG-System-Control (Hermes Agent)")
    parser.add_argument("--test", action="store_true", help="Send a test message and verify connectivity")
    parser.add_argument("--offline-test", action="store_true", help="Simulate offline status update")
    args = parser.parse_args()

    if not config.TELEGRAM_BOT_TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN is not configured in .env")
        sys.exit(1)

    if args.test:
        system_lifecycle.notify_online()
        return

    if args.offline_test:
        system_lifecycle.notify_offline("Manual Test Shutdown")
        return

    # 1. Register shutdown and logoff hooks
    system_lifecycle.register_lifecycle_hooks()

    # 2. Dispatch ONLINE notification & set bot bio status
    system_lifecycle.notify_online()

    # 3. Start auto-restarting supervisor loop
    while True:
        try:
            run_bot_loop()
        except KeyboardInterrupt:
            print("\nStopping TG-System-Control...")
            system_lifecycle.notify_offline("Agent stopped by user")
            break
        except Exception as e:
            print(f"[Main Supervisor] Daemon encountered error: {e}. Auto-recovering in 3s...")
            time.sleep(3)


if __name__ == "__main__":
    main()
