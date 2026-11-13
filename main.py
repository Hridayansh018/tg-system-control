"""Main entry point for tg-system-control."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import config
from bot.listener import run_bot_loop
from bot import telegram_client


def main():
    parser = argparse.ArgumentParser(description="TG-System-Control (Hermes Agent)")
    parser.add_argument("--test", action="store_true", help="Send a test message and verify connectivity")
    args = parser.parse_args()

    if not config.TELEGRAM_BOT_TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN is not configured in .env")
        sys.exit(1)

    if args.test:
        print("Sending test message...")
        res = telegram_client.send_message(
            config.TELEGRAM_CHAT_ID,
            "🎉 *TG-System-Control (Hermes Agent) is Online!* 🚀\n\nPC remote control bridge is active and ready."
        )
        if res.get("ok"):
            print("✅ Test message delivered successfully to Telegram!")
        else:
            print(f"❌ Failed to deliver: {res}")
        return

    # Run polling loop
    run_bot_loop()


if __name__ == "__main__":
    main()
