"""Automated Setup & Environment Verification Tool for TG-System-Control.
Auto-detects OS (Windows / macOS / Linux), checks python dependencies, verifies
OS bridge operations, and tests Telegram connectivity.
"""
import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


def banner(text):
    print("\n" + "=" * 65)
    print(f"  {text}")
    print("=" * 65)


def check_step(name, status, details=""):
    mark = "✅ PASS" if status else "❌ FAIL"
    print(f"[{mark}] {name:<32} {details}")
    return status


def main():
    banner("TG-SYSTEM-CONTROL · ENVIRONMENT VERIFICATION")
    all_ok = True

    # 1. OS & Architecture Detection
    os_name = platform.system()
    os_release = platform.release()
    arch = platform.machine()
    is_win = os_name == "Windows"
    is_mac = os_name == "Darwin"
    is_linux = os_name == "Linux"

    os_label = "Windows" if is_win else ("macOS" if is_mac else "Linux")
    check_step("Operating System", True, f"{os_label} ({os_release}, {arch})")

    # 2. Python Version Check (Requires >= 3.10)
    py_ver = sys.version_info
    py_ok = py_ver.major == 3 and py_ver.minor >= 10
    all_ok &= check_step("Python Version", py_ok, f"{py_ver.major}.{py_ver.minor}.{py_ver.micro} (Requires 3.10+)")

    # 3. Python Package Dependencies
    banner("DEPENDENCY CHECKS")
    packages = ["requests", "PIL"]
    for pkg in packages:
        try:
            importlib.import_module(pkg)
            check_step(f"Package: {pkg}", True, "Installed & functional")
        except ImportError:
            all_ok &= check_step(f"Package: {pkg}", False, f"Missing! Run: pip install {pkg}")

    # Optional packages
    for opt_pkg in ["psutil"]:
        try:
            importlib.import_module(opt_pkg)
            check_step(f"Optional: {opt_pkg}", True, "Installed")
        except ImportError:
            check_step(f"Optional: {opt_pkg}", True, "Not installed (Native OS bridge will be used)")

    # 4. Configuration Check (.env) & Memory.md Initialization
    banner("CONFIGURATION & MEMORY CHECK")
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            shutil.copy(ENV_EXAMPLE, ENV_FILE)
            print("ℹ️ Created .env from .env.example")
        else:
            all_ok &= check_step(".env File", False, "Missing .env file!")

    env_data = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_data[k.strip()] = v.strip().strip('"').strip("'")

    token = env_data.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env_data.get("TELEGRAM_CHAT_ID", "")
    provider = env_data.get("LLM_PROVIDER", "offline")

    token_ok = bool(token and token != "your_bot_token_here")
    all_ok &= check_step("Telegram Bot Token", token_ok, f"{token[:8]}..." if token_ok else "Missing in .env")

    chat_ok = bool(chat_id and chat_id != "your_telegram_chat_id")
    all_ok &= check_step("Authorized Chat ID", chat_ok, chat_id if chat_ok else "Missing in .env")

    check_step("Configured LLM Brain", True, f"Provider = '{provider}'")

    # Constructive Memory Initialization
    try:
        from core import memory_logger
        memory_logger.ensure_memory_file()
        mem_exists = (ROOT / "memory.md").exists()
        gitignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
        mem_ignored = "memory.md" in gitignore_text
        all_ok &= check_step("Constructive memory.md", mem_exists, "Initialized (Append-only)")
        all_ok &= check_step("Git-ignored memory.md", mem_ignored, "Safe from Git commits")
    except Exception as e:
        all_ok &= check_step("Constructive memory.md", False, str(e))

    # 5. OS Bridge & Hardware Actions Test
    banner("HARDWARE & OS ACTIONS TEST")
    try:
        from core import os_bridge
        stats = os_bridge.get_system_stats()
        check_step("System Metrics Reader", True, f"CPU Cores: {stats.get('cpu_cores')}, Disk Free: {stats.get('disk_free_gb')} GB")
    except Exception as e:
        all_ok &= check_step("System Metrics Reader", False, str(e))

    # Test Shell Execution
    try:
        test_cmd = "echo 'TG_TEST_OK'"
        res = os_bridge.run_command(test_cmd, timeout=5)
        cmd_ok = "TG_TEST_OK" in res.get("stdout", "")
        check_step("Shell Execution Bridge", cmd_ok, f"Shell exit code: {res.get('exit_code')}")
    except Exception as e:
        all_ok &= check_step("Shell Execution Bridge", False, str(e))

    # Test Screenshot Engine
    test_shot = ROOT / "temp" / "test_shot.jpg"
    try:
        shot_ok = os_bridge.take_screenshot(test_shot)
        check_step("Desktop Screen Grabber", shot_ok, f"Saved to {test_shot.name}" if shot_ok else "Display context required (headless/locked)")
    except Exception as e:
        check_step("Desktop Screen Grabber", False, str(e))

    # 6. Telegram API Connectivity Test
    if token_ok:
        banner("TELEGRAM API CONNECTIVITY")
        try:
            import requests
            r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
            if r.get("ok"):
                bot_info = r["result"]
                check_step("Telegram Bot API", True, f"Connected to @{bot_info.get('username')}")
            else:
                all_ok &= check_step("Telegram Bot API", False, r.get("description", "Error"))
        except Exception as e:
            all_ok &= check_step("Telegram Bot API", False, str(e))

    # 7. Final Summary & Auto-Launch Advice
    banner("VERIFICATION VERDICT")
    if all_ok:
        print("🎉 ALL CORE CHECKS PASSED! Your device is ready to run TG-System-Control.")
        print("\nNext steps:")
        if is_win:
            print("  • Double click 'start_agent.bat' to launch in interactive mode.")
            print("  • Double click 'start_agent_silent.vbs' to launch silently in background.")
            print("  • Run 'install_autostart.bat' to auto-launch on every Windows boot.")
        elif is_mac or is_linux:
            print("  • Run: python3 main.py")
    else:
        print("⚠️ Some checks failed. Please fix the items marked [❌ FAIL] above before launching.")
        sys.exit(1)


if __name__ == "__main__":
    main()
