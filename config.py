"""Configuration loader for tg-system-control."""
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR / ".env"


def parse_env_file(path: Path) -> dict:
    env_vars = {}
    if not path.exists():
        return env_vars
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    env_vars[key] = val
    except Exception as e:
        print(f"[Config] Error reading .env: {e}")
    return env_vars


_ENV = parse_env_file(ENV_FILE)

# Bot credentials
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or _ENV.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or _ENV.get("TELEGRAM_CHAT_ID", "")

# LLM settings
LLM_PROVIDER = (os.environ.get("LLM_PROVIDER") or _ENV.get("LLM_PROVIDER", "offline")).lower()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or _ENV.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or _ENV.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY") or _ENV.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL") or _ENV.get("OPENROUTER_MODEL", "nousresearch/hermes-3-llama-3.1-70b")

# Temp and screenshot paths
TEMP_DIR = ROOT_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR = ROOT_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
