"""Main entry point for tg-system-control with Online/Offline Lifecycle management."""
import argparse
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import config
from bot.listener import run_bot_loop
from bot import telegram_client
from core import system_lifecycle

_INSTANCE_LOCK_SOCKET = None
SINGLETON_PORT = 49221


def acquire_single_instance_lock(port: int = SINGLETON_PORT) -> bool:
    """Enforce strict mutual exclusion so only ONE daemon can poll Telegram at a time.
    Prevents duplicate Telegram responses caused by multiple concurrent instances.
    """
    global _INSTANCE_LOCK_SOCKET
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(('127.0.0.1', port))
        s.listen(1)
        _INSTANCE_LOCK_SOCKET = s
        return True
    except OSError:
        return False


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

    # 1. Enforce strict single-instance mutual exclusion
    if not acquire_single_instance_lock():
        print(f"[FATAL] Another instance of TG-System-Control is already running on port {SINGLETON_PORT}.")
        print("[FATAL] Exiting immediately to prevent duplicate Telegram responses.")
        sys.exit(0)

    # 2. Register shutdown and logoff hooks
    system_lifecycle.register_lifecycle_hooks()

    # 2. Start auto-restarting supervisor loop (warm-up & ONLINE ping handled after all files/packages load)
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
