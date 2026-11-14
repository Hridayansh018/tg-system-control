"""Start / stop / check the Video Studio bot (bot 2) from tg-system-control (bot 1).

The Video Studio bot lives in the video pipeline folder (VIDEOSTUDIO_DIR, default D:\\VideoStudio_Mac)
as tools/videostudio_bot.py. This module never touches the pipeline's content, gates or rules:
it only launches/stops that service and reads its heartbeat and log.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import config

IS_WINDOWS = os.name == "nt"


def _root() -> Path:
    return Path(config.VIDEOSTUDIO_DIR)


def _tools() -> Path:
    return _root() / "tools"


def _python() -> str:
    if config.VIDEOSTUDIO_PYTHON:
        return config.VIDEOSTUDIO_PYTHON
    venv = _root() / ".venv" / ("Scripts/pythonw.exe" if IS_WINDOWS else "bin/python3")
    return str(venv) if venv.exists() else (sys.executable if not IS_WINDOWS else "pythonw")


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    if IS_WINDOWS:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def status() -> dict:
    hb_file = _tools() / ".videostudio_bot.json"
    if not (_tools() / "videostudio_bot.py").exists():
        return {"running": False, "state": "not installed", "error": f"{_tools() / 'videostudio_bot.py'} not found"}
    try:
        hb = json.loads(hb_file.read_text(encoding="utf-8"))
    except Exception:
        return {"running": False, "state": "never started"}
    age = time.time() - float(hb.get("beat", 0))
    hb["beat_age"] = int(age)
    hb["running"] = hb.get("state") == "running" and age < 45 and _pid_alive(hb.get("pid"))
    if hb.get("state") == "running" and not hb["running"]:
        hb["state"] = "stopped (no heartbeat)"
    return hb


def _config_ready() -> str:
    """'' if the Video Studio bot has a token + chat id configured, else the problem (never the values)."""
    cfg_file = _tools() / ".telegram_config.json"
    try:
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    except Exception:
        return f"{cfg_file} is missing or not valid JSON"
    if not str(cfg.get("bot_token") or "").strip():
        return f"no bot_token in {cfg_file}"
    if not str(cfg.get("chat_id") or "").strip():
        return f"no chat_id in {cfg_file}"
    return ""


def start(wait_sec: float = 20) -> dict:
    st = status()
    if st.get("running"):
        return {"ok": True, "msg": f"Video Studio bot is already running (@{st.get('bot', '?')}, since {st.get('since', '?')})."}
    problem = _config_ready()
    if problem:
        return {"ok": False, "msg": f"Can't start: {problem}."}
    flags = 0
    if IS_WINDOWS:
        flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    for stale in (".videostudio_bot.stop", ".videostudio_bot.json"):  # old stop flag / status of a dead run
        try:
            (_tools() / stale).unlink()
        except FileNotFoundError:
            pass
    started_at = time.time()
    subprocess.Popen([_python(), "-I", str(_tools() / "videostudio_bot.py")], cwd=str(_root()),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, close_fds=True)
    deadline = started_at + wait_sec
    while time.time() < deadline:
        time.sleep(0.5)
        st = status()
        if st.get("running"):
            return {"ok": True, "msg": f"Video Studio bot started (@{st.get('bot', '?')})."}
        if st.get("state") == "error":
            return {"ok": False, "msg": f"Video Studio bot failed to start: {st.get('error')}"}
    return {"ok": False, "msg": "Video Studio bot did not report in within 20 s - see /studio logs."}


def stop(wait_sec: float = 10) -> dict:
    st = status()
    if not st.get("running"):
        return {"ok": True, "msg": "Video Studio bot is not running."}
    (_tools() / ".videostudio_bot.stop").write_text("stop")
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        time.sleep(0.5)
        if not _pid_alive(st.get("pid")):
            return {"ok": True, "msg": "Video Studio bot stopped."}
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(st.get("pid")), "/F"], capture_output=True)
    else:
        try:
            os.kill(int(st.get("pid")), 9)
        except Exception:
            pass
    return {"ok": True, "msg": "Video Studio bot force-stopped (it did not exit in time)."}


def restart() -> dict:
    stop()
    return start()


def _pipeline_queue_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vs_telegram_queue_mod", str(_tools() / "telegram_queue.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def queue_request(text: str, sender: str = "PC bot") -> None:
    """Puts a request for Antigravity into the Video Studio message queue. The Antigravity bridge types it
    into the active pipeline session like any other Telegram message (so Antigravity answers on Telegram)."""
    mod = _pipeline_queue_module()
    mod.enqueue_message(10 ** 11 + int(time.time()) % 10 ** 9, sender, text)


def announce_offline(reason: str) -> bool:
    """Posts 🔴 OFFLINE in the Video Studio bot chat on its behalf - for cases the service can't
    announce itself (crash, force-kill, PC shutdown). Uses the pipeline's own announce code."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("vs_telegram_queue", str(_tools() / "telegram_queue.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return bool(mod.announce_status(False, reason))
    except Exception as e:
        print(f"[Studio] announce_offline failed: {e}")
        return False


def watch(on_unexpected_stop, interval: float = 15.0):
    """Background watcher: calls on_unexpected_stop(reason) when the Video Studio bot goes from
    running to not running WITHOUT announcing it itself (crash, kill, token revoked)."""
    import threading

    def loop():
        last = bool(status().get("running"))
        while True:
            time.sleep(interval)
            try:
                st = status()
                now = bool(st.get("running"))
                if last and not now and st.get("state") != "stopped":
                    on_unexpected_stop(st.get("error") or "stopped responding (crashed or was killed)")
                last = now
            except Exception as e:
                print(f"[Studio] watcher error: {e}")

    threading.Thread(target=loop, name="studio-watch", daemon=True).start()


def logs(n: int = 15) -> str:
    log = _tools() / "videostudio_bot.log"
    if not log.exists():
        return "(no log yet)"
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    return "\n".join(lines)


def status_text() -> str:
    st = status()
    if st.get("running"):
        extra = f"\n⚠️ {st['warning']}" if st.get("warning") else ""
        return f"🎬 Video Studio bot: 🟢 running (@{st.get('bot', '?')}) since {st.get('since', '?')}{extra}"
    detail = f" — {st['error']}" if st.get("error") else ""
    return f"🎬 Video Studio bot: 🔴 {st.get('state', 'stopped')}{detail}"
