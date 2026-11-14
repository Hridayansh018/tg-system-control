"""Configuration loader for tg-system-control.

Values come from real environment variables first, then from the local `.env` file.
"""
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR / ".env"

# Values shipped in .env.example that must never be treated as real credentials.
PLACEHOLDER_VALUES = {"", "your_bot_token_here", "your_telegram_chat_id"}


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


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name) or _ENV.get(name, default)


def _get_bool(name: str, default: bool) -> bool:
    raw = _get(name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def is_placeholder(value: str) -> bool:
    return (value or "").strip() in PLACEHOLDER_VALUES


# Bot credentials
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

# LLM settings
LLM_PROVIDER = _get("LLM_PROVIDER", "offline").lower()
GEMINI_API_KEY = _get("GEMINI_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL")  # optional override, tried before the built-in fallback list
GROQ_API_KEY = _get("GROQ_API_KEY")
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = _get("OPENROUTER_MODEL", "nousresearch/hermes-3-llama-3.1-70b")

# Desktop apps
HERMES_APP_PATH = _get(
    "HERMES_APP_PATH",
    r"D:\git-data\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe",
)

# Computer-use agent (/agent, /do)
AGENT_ENABLED = _get_bool("AGENT_ENABLED", True)
AGENT_MODEL = _get("AGENT_MODEL")  # optional override, tried before the built-in vision fallback list
AGENT_MAX_STEPS = max(1, _get_int("AGENT_MAX_STEPS", 30))
AGENT_REQUIRE_APPROVAL = _get_bool("AGENT_REQUIRE_APPROVAL", True)
APPROVAL_TIMEOUT_SEC = max(30, _get_int("APPROVAL_TIMEOUT_SEC", 300))
REMOTE_FEEDBACK = _get_bool("REMOTE_FEEDBACK", True)  # screenshot after mouse/keyboard commands
INBOX_DIR = Path(os.path.expandvars(os.path.expanduser(
    _get("INBOX_DIR", str(Path.home() / "Downloads" / "TelegramInbox"))
)))

# Temp and screenshot paths
TEMP_DIR = ROOT_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR = ROOT_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
STOP_FLAG_FILE = TEMP_DIR / ".stop_request"
