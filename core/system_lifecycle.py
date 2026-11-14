"""System lifecycle manager: ONLINE / OFFLINE notifications, shutdown/logoff detection,
graceful stop requests, single-instance lock, and Telegram bot status updates.
"""
import atexit
import ctypes
import hashlib
import os
import platform
import signal
import socket
import sys
import threading
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
        requests.post(f"https://api.telegram.org/bot{token}/setMyShortDescription",
                      json={"short_description": f"{status_text} | TG-System-Control"}, timeout=5)
        requests.post(f"https://api.telegram.org/bot{token}/setMyDescription",
                      json={"description": f"Desktop Remote Controller.\n\nCurrent Status: {status_text}\nUpdated: {time.strftime('%Y-%m-%d %H:%M:%S')}"},
                      timeout=5)
    except Exception as e:
        print(f"[Lifecycle] update_bot_bio error: {e}")


def warmup_all_subsystems() -> dict:
    """Pre-loads and checks every subsystem so the first command is fast."""
    t0 = time.time()
    results = {}

    t_pkg = time.time()
    import requests as _requests  # noqa: F401
    from PIL import ImageGrab  # noqa: F401
    results["packages"] = f"OK ({int((time.time() - t_pkg) * 1000)}ms)"

    t_fs = time.time()
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    config.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    memory_logger.log_entry("WARMUP_CHECK", "Subsystem Warm-Up Started",
                            thinking="Pre-warming libraries, display, app catalog, and network before sending ONLINE.")
    results["storage"] = f"OK ({int((time.time() - t_fs) * 1000)}ms)"

    t_app = time.time()
    apps = os_bridge.get_installed_apps()
    results["app_catalog"] = f"Indexed {len(apps)} apps ({int((time.time() - t_app) * 1000)}ms)"

    t_screen = time.time()
    test_shot = config.TEMP_DIR / ".warmup_screen.jpg"
    shot_ok = os_bridge.take_screenshot(test_shot)
    try:
        test_shot.unlink()
    except Exception:
        pass
    results["screen_engine"] = f"{'Primed' if shot_ok else 'Unavailable'} ({int((time.time() - t_screen) * 1000)}ms)"

    results["input_lock"] = "Available (admin)" if os_bridge.input_lock_available() else "Not available (not running as admin)"

    t_net = time.time()
    net_ok, bot_info = False, {}
    if config.TELEGRAM_BOT_TOKEN:
        try:
            r = requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe", timeout=6).json()
            if r.get("ok"):
                net_ok, bot_info = True, r["result"]
        except Exception as e:
            results["network_error"] = str(e)
    net_ms = int((time.time() - t_net) * 1000)
    results["telegram_api"] = f"Connected to @{bot_info.get('username', 'bot')} ({net_ms}ms)" if net_ok else "Unreachable"

    results["total_warmup_ms"] = int((time.time() - t0) * 1000)
    return results


def notify_online(warmup_summary: dict = None):
    """Sent only after every subsystem is warmed up and polling is about to start."""
    stats = os_bridge.get_system_stats()
    warmup_line = ""
    if warmup_summary:
        warmup_line = (
            f"⚡ *Warm-Up:* `{warmup_summary.get('total_warmup_ms', 0)} ms`\n"
            f"📦 *Apps Indexed:* `{warmup_summary.get('app_catalog', 'Ready')}`\n"
            f"🌐 *Network API:* `{warmup_summary.get('telegram_api', 'Connected')}`\n"
        )
        if "video_studio_bot" in warmup_summary:
            vs = warmup_summary["video_studio_bot"]
            warmup_line += f"🎬 *Video Studio bot:* {'🟢' if vs == 'running' else '⚠️'} `{vs}`\n"

    online_text = (
        f"🟢 *SYSTEM ONLINE* ⚡\n\n"
        f"🖥️ *Machine:* `{stats.get('os')}` ({stats.get('architecture')})\n"
        f"🧠 *CPU:* `{stats.get('cpu_cores')} cores` | ⚡ *RAM:* `{stats.get('ram_used_pct', '?')}% used`\n"
        f"💾 *Disk Free:* `{stats.get('disk_free_gb')} GB`\n"
        f"{warmup_line}"
        f"🕒 *Connected At:* `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
        f"Send `/help` to see what I can do."
    )

    res = telegram_client.send_message(config.TELEGRAM_CHAT_ID, online_text)
    if res.get("ok"):
        msg_id = res["result"]["message_id"]
        try:
            STATUS_MSG_FILE.write_text(str(msg_id))
            requests.post(telegram_client.get_api_url("pinChatMessage"),
                          json={"chat_id": config.TELEGRAM_CHAT_ID, "message_id": msg_id, "disable_notification": True},
                          timeout=5)
        except Exception:
            pass

    update_bot_bio("🟢 System ONLINE")
    print("🟢 [ONLINE] Desktop connection notification sent to Telegram.")
    memory_logger.log_entry(
        "LIFECYCLE_EVENT", "System Came ONLINE",
        details={"os": stats.get("os"), "cpu_cores": stats.get("cpu_cores"),
                 "ram_used_pct": stats.get("ram_used_pct"), "disk_free_gb": stats.get("disk_free_gb"),
                 "warmup": warmup_summary},
        thinking="All subsystems verified and Telegram notified.",
    )


def notify_offline(reason="Desktop shut down / Agent stopped"):
    offline_text = (
        f"🔴 *SYSTEM OFFLINE* 💤\n\n"
        f"📌 *Reason:* `{reason}`\n"
        f"🕒 *Disconnected At:* `{time.strftime('%Y-%m-%d %H:%M:%S')}`"
    )
    try:
        telegram_client.send_message(config.TELEGRAM_CHAT_ID, offline_text)
    except Exception:
        pass
    try:
        update_bot_bio("🔴 System OFFLINE")
    except Exception:
        pass
    print(f"🔴 [OFFLINE] Desktop disconnection recorded ({reason}).")
    memory_logger.log_entry("LIFECYCLE_EVENT", f"System Went OFFLINE ({reason})", details={"reason": reason})


# ----------------------------------------------------------------------
# OFFLINE exactly once
# ----------------------------------------------------------------------
_OFFLINE_LOCK = threading.Lock()
_IS_NOTIFIED_OFFLINE = False


def safe_offline(reason: str):
    """Sends the OFFLINE notification at most once per process."""
    global _IS_NOTIFIED_OFFLINE
    with _OFFLINE_LOCK:
        if _IS_NOTIFIED_OFFLINE:
            return
        _IS_NOTIFIED_OFFLINE = True
    try:
        os_bridge.release_input_lock()
    except Exception:
        pass
    notify_offline(reason)


_safe_offline = safe_offline  # backwards-compatible name

_STUDIO_SHUTDOWN_DONE = threading.Event()


def studio_offline_on_shutdown(reason: str):
    """PC shutdown / logoff: Windows kills the Video Studio bot without warning, so announce its
    🔴 OFFLINE for it (once). Not used when only this bot stops - the Video Studio bot keeps running then."""
    if _STUDIO_SHUTDOWN_DONE.is_set():
        return
    _STUDIO_SHUTDOWN_DONE.set()
    try:
        from core import studio_control
        if studio_control.status().get("running"):
            studio_control.announce_offline(f"PC: {reason}")
    except Exception as e:
        print(f"[Lifecycle] Video Studio offline notice failed: {e}")


def _exit_after_offline(reason: str, code: int = 0):
    safe_offline(reason)
    os._exit(code)


# ----------------------------------------------------------------------
# Single instance
# ----------------------------------------------------------------------
_INSTANCE_HANDLE = None


def _lock_name() -> str:
    # One instance per bot token on this machine, whichever folder/venv it runs from.
    return hashlib.sha256((config.TELEGRAM_BOT_TOKEN or "tg-system-control").encode()).hexdigest()[:16]


def acquire_single_instance_lock() -> bool:
    global _INSTANCE_HANDLE
    if IS_WINDOWS:
        try:
            k32 = ctypes.windll.kernel32
            k32.CreateMutexW.restype = ctypes.c_void_p
            handle = k32.CreateMutexW(None, False, f"Local\\TGSystemControl_{_lock_name()}")
            if not handle:
                return False
            if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                k32.CloseHandle(ctypes.c_void_p(handle))
                return False
            _INSTANCE_HANDLE = handle
            return True
        except Exception as e:
            print(f"[Lifecycle] Mutex lock failed ({e}); falling back to socket lock.")
    port = 30000 + int(_lock_name(), 16) % 2000  # below the usual ephemeral port ranges
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", port))
        s.listen(1)
        _INSTANCE_HANDLE = s
        return True
    except OSError:
        return False


# ----------------------------------------------------------------------
# Stop requests (stop_agent.bat / pkill / systemd / Ctrl+C / shutdown)
# ----------------------------------------------------------------------
def _watch_stop_flag():
    try:
        config.STOP_FLAG_FILE.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass
    while True:
        if config.STOP_FLAG_FILE.exists():
            try:
                config.STOP_FLAG_FILE.unlink()
            except Exception:
                pass
            _exit_after_offline("Stopped with stop_agent")
        time.sleep(1)


def _start_shutdown_listener_window():
    """Hidden top-level window that receives WM_QUERYENDSESSION / WM_ENDSESSION.
    Works even in pythonw (no console) mode, where console control events never arrive.
    """
    from ctypes import wintypes

    WM_QUERYENDSESSION, WM_ENDSESSION = 0x0011, 0x0016
    ENDSESSION_LOGOFF = 0x80000000
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u32.DefWindowProcW.restype = LRESULT
    u32.CreateWindowExW.restype = wintypes.HWND
    u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    k32.GetModuleHandleW.restype = wintypes.HMODULE

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_QUERYENDSESSION:
            reason = "Windows user logging off" if (lparam & ENDSESSION_LOGOFF) else "Windows shutting down / restarting"
            studio_offline_on_shutdown(reason)
            safe_offline(f"Desktop Shutdown: {reason}")
            return 1  # allow the session to end
        if msg == WM_ENDSESSION and wparam:
            safe_offline("Desktop Shutdown: session ended")
            return 0
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run():
        try:
            proc = WNDPROC(wnd_proc)
            hinst = k32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = proc
            wc.hInstance = hinst
            wc.lpszClassName = "TGSystemControlShutdownListener"
            u32.RegisterClassW(ctypes.byref(wc))
            hwnd = u32.CreateWindowExW(0, wc.lpszClassName, "TGSystemControl", 0, 0, 0, 0, 0,
                                       None, None, hinst, None)
            if not hwnd:
                print("[Lifecycle] Could not create shutdown listener window")
                return
            msg = wintypes.MSG()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))
            _ = proc  # keep callback alive
        except Exception as e:
            print(f"[Lifecycle] Shutdown listener error: {e}")

    threading.Thread(target=run, name="shutdown-listener", daemon=True).start()


_global_ctrl_handler = None


def register_lifecycle_hooks():
    """Registers graceful shutdown hooks for exit, signals, console events, shutdown and logoff."""
    atexit.register(lambda: safe_offline("Process terminated / Normal exit"))

    def _signal_handler(signum, frame):
        name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        _exit_after_offline(f"Received {name}")

    for sig_name in ("SIGTERM", "SIGBREAK", "SIGHUP"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _signal_handler)
            except Exception:
                pass

    threading.Thread(target=_watch_stop_flag, name="stop-flag-watcher", daemon=True).start()

    if IS_WINDOWS:
        _start_shutdown_listener_window()
        try:
            PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)

            def ctrl_handler(ctrl_type):
                # CTRL_C/CTRL_BREAK are handled by Python (KeyboardInterrupt / SIGBREAK).
                if ctrl_type in (2, 5, 6):
                    events = {2: "Console window closed", 5: "Windows user logging off", 6: "Windows system shutdown"}
                    if ctrl_type in (5, 6):  # the whole session ends -> the Video Studio bot dies too
                        studio_offline_on_shutdown(events[ctrl_type])
                    safe_offline(f"Desktop Shutdown: {events[ctrl_type]}")
                return False

            global _global_ctrl_handler
            _global_ctrl_handler = PHANDLER_ROUTINE(ctrl_handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_global_ctrl_handler, True)
        except Exception as e:
            print(f"[Lifecycle] SetConsoleCtrlHandler hook warning: {e}")
