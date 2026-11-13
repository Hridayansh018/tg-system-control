"""Cross-platform OS bridge for Windows and Mac/Linux.
Executes shell commands, collects system metrics, captures screenshots, and controls processes.
"""
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


def run_command(cmd: str, cwd: str = None, timeout: int = 45) -> dict:
    """Executes a shell command (PowerShell on Windows, Bash on Mac/Linux)."""
    try:
        if IS_WINDOWS:
            shell_cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd]
        else:
            shell_cmd = ["/bin/bash", "-c", cmd]

        res = subprocess.run(
            shell_cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "exit_code": res.returncode,
            "stdout": res.stdout.strip(),
            "stderr": res.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}


def get_system_stats() -> dict:
    """Returns CPU count, RAM, Disk, and OS details."""
    stats = {
        "os": f"{platform.system()} {platform.release()}",
        "architecture": platform.machine(),
        "cpu_cores": os.cpu_count() or 1,
    }

    # Disk stats (Standard Library cross-platform)
    try:
        drive = "C:\\" if IS_WINDOWS else "/"
        total, used, free = shutil.disk_usage(drive)
        stats["disk_total_gb"] = round(total / (1024 ** 3), 1)
        stats["disk_used_gb"] = round(used / (1024 ** 3), 1)
        stats["disk_free_gb"] = round(free / (1024 ** 3), 1)
        stats["disk_used_pct"] = round((used / total) * 100, 1)
    except Exception:
        pass

    # RAM stats
    if IS_WINDOWS:
        res = run_command("(Get-CimInstance Win32_OperatingSystem) | Select-Object TotalVisibleMemorySize, FreePhysicalMemory | ConvertTo-Json")
        if res["exit_code"] == 0 and res["stdout"]:
            try:
                import json
                m = json.loads(res["stdout"])
                tot = m.get("TotalVisibleMemorySize", 0) / (1024 * 1024)
                free = m.get("FreePhysicalMemory", 0) / (1024 * 1024)
                stats["ram_total_gb"] = round(tot, 1)
                stats["ram_free_gb"] = round(free, 1)
                stats["ram_used_gb"] = round(tot - free, 1)
                stats["ram_used_pct"] = round(((tot - free) / tot) * 100, 1) if tot else 0
            except Exception:
                pass
    elif IS_MAC:
        res = run_command("sysctl -n hw.memsize")
        if res["exit_code"] == 0 and res["stdout"]:
            try:
                tot = int(res["stdout"]) / (1024 ** 3)
                stats["ram_total_gb"] = round(tot, 1)
            except Exception:
                pass

    return stats


def take_screenshot(output_path: Path) -> bool:
    """Captures desktop screen and saves it as JPEG."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Method 1: Pillow ImageGrab
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        if img:
            img.save(str(output_path), "JPEG", quality=85)
            return True
    except Exception:
        pass

    # Method 2: OS Specific Native Fallback
    if IS_WINDOWS:
        ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap $screen.Width, $screen.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bitmap.Save('{str(output_path).replace('\\', '\\\\')}', [System.Drawing.Imaging.ImageFormat]::Jpeg)
$graphics.Dispose()
$bitmap.Dispose()
"""
        res = run_command(ps_script, timeout=10)
        return output_path.exists() and output_path.stat().st_size > 0

    elif IS_MAC:
        res = run_command(f"screencapture -x '{str(output_path)}'", timeout=10)
        return output_path.exists() and output_path.stat().st_size > 0

    return False


WEB_SHORTCUTS = {
    "gmail": "https://mail.google.com",
    "mail": "https://mail.google.com",
    "google": "https://google.com",
    "youtube": "https://youtube.com",
    "yt": "https://youtube.com",
    "youtube studio": "https://studio.youtube.com",
    "yt studio": "https://studio.youtube.com",
    "chatgpt": "https://chatgpt.com",
    "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
    "hark": "https://hark.com",
    "muse": "https://muse.ai",
}


def launch_app(app_name: str) -> dict:
    """Launches an application or website on the user's interactive desktop."""
    app_lower = app_name.lower().strip()

    # 1. Check for Web / URL / Website requests (e.g. 'edge : open gmail app' or 'open youtube')
    target_url = None
    for site_key, site_url in WEB_SHORTCUTS.items():
        if site_key in app_lower:
            target_url = site_url
            break

    # If direct URL passed
    if "http://" in app_lower or "https://" in app_lower:
        for part in app_name.split():
            if part.startswith(("http://", "https://")):
                target_url = part
                break

    if target_url:
        is_app_mode = any(w in app_lower for w in ["app", "gui", "standalone", "pwa"])
        if IS_WINDOWS:
            try:
                if is_app_mode:
                    # Launch standalone native PWA window via Edge
                    subprocess.Popen(f'cmd.exe /c start msedge --app="{target_url}"', shell=True)
                else:
                    os.startfile(f"microsoft-edge:{target_url}")
                return {"exit_code": 0, "stdout": f"Opened {target_url} in Edge", "stderr": ""}
            except Exception as e:
                return {"exit_code": -1, "stdout": "", "stderr": str(e)}
        elif IS_MAC:
            app_flag = "-a 'Google Chrome'" if "chrome" in app_lower else ("-a 'Microsoft Edge'" if "edge" in app_lower else "")
            return run_command(f'open {app_flag} "{target_url}"')

    # 2. Local Applications Map (Using Windows ShellExecute via os.startfile for direct GUI display)
    if IS_WINDOWS:
        app_exec_map = {
            "edge": "msedge.exe",
            "msedge": "msedge.exe",
            "chrome": "chrome.exe",
            "notepad": "notepad.exe",
            "calc": "calc.exe",
            "calculator": "calc.exe",
            "explorer": "explorer.exe",
            "taskmgr": "taskmgr.exe",
            "task manager": "taskmgr.exe",
            "antigravity": os.path.expandvars(r"%LOCALAPPDATA%\Programs\antigravity\Antigravity.exe"),
            "vscode": "code.cmd",
        }
        for k, target_exe in app_exec_map.items():
            if k in app_lower.split() or k == app_lower:
                try:
                    os.startfile(target_exe)
                    return {"exit_code": 0, "stdout": f"Launched {k} on desktop", "stderr": ""}
                except Exception as e:
                    # Fallback to shell start
                    return run_command(f'start "" "{target_exe}"')

        # Generic launch fallback
        try:
            os.startfile(app_name)
            return {"exit_code": 0, "stdout": f"Started {app_name}", "stderr": ""}
        except Exception:
            return run_command(f'start "" "{app_name}"')

    elif IS_MAC:
        app_map = {
            "chrome": "open -a 'Google Chrome'",
            "edge": "open -a 'Microsoft Edge'",
            "safari": "open -a 'Safari'",
            "terminal": "open -a 'Terminal'",
        }
        for k, cmd in app_map.items():
            if k in app_lower.split():
                return run_command(cmd)

        cmd = app_map.get(app_lower, f"open -a '{app_name}'")
        return run_command(cmd)

    return {"exit_code": -1, "stdout": "", "stderr": "Unsupported platform"}


def lock_workstation() -> dict:
    """Locks the workstation."""
    if IS_WINDOWS:
        return run_command("rundll32.exe user32.dll,LockWorkStation")
    elif IS_MAC:
        return run_command("pmset displaysleepnow")
    return {"exit_code": -1, "stdout": "", "stderr": "Unsupported platform"}


def list_top_processes(limit: int = 10) -> str:
    """Returns formatted list of top running processes."""
    if IS_WINDOWS:
        cmd = f"Get-Process | Sort-Object CPU -Descending | Select-Object -First {limit} Id, ProcessName, CPU, WorkingSet64 | Format-Table -AutoSize | Out-String -Width 120"
        res = run_command(cmd)
        return res["stdout"] if res["exit_code"] == 0 else res["stderr"]
    elif IS_MAC:
        cmd = f"ps -eo pid,pcpu,pmem,comm | sort -k 2 -r | head -n {limit}"
        res = run_command(cmd)
        return res["stdout"] if res["exit_code"] == 0 else res["stderr"]
    return "Unsupported platform"


# ----------------------------------------------------------------------
# GUI AUTOMATION: Direct Native OS Mouse & Hardware Keyboard Keystrokes
# ----------------------------------------------------------------------

def set_user_input_blocked(blocked: bool) -> bool:
    """Blocks or unblocks physical user mouse and keyboard input on Windows.
    Used during precise interactive GUI automation sequences.
    """
    if IS_WINDOWS:
        try:
            import ctypes
            res = ctypes.windll.user32.BlockInput(bool(blocked))
            return bool(res)
        except Exception as e:
            print(f"[GUI] BlockInput error: {e}")
    return False


class UserInputLock:
    """Context manager to safely lock physical user input during GUI operations
    and guarantee restoration even if an error occurs.
    """
    def __init__(self, action_name="GUI Action"):
        self.action_name = action_name

    def __enter__(self):
        set_user_input_blocked(True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        set_user_input_blocked(False)


def mouse_move(x: int, y: int) -> bool:
    """Moves the mouse cursor directly on the physical display."""
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
            return True
        except Exception:
            pass
    elif IS_MAC:
        res = run_command(f"osascript -e 'tell application \"System Events\" to set the position of the mouse cursor to {{{int(x)}, {int(y)}}}'")
        return res["exit_code"] == 0
    return False


def mouse_click(x: int = None, y: int = None, button: str = "left", double: bool = False) -> bool:
    """Performs direct hardware mouse click on active screen."""
    if x is not None and y is not None:
        mouse_move(x, y)
        time.sleep(0.05)

    btn = button.lower()
    if IS_WINDOWS:
        try:
            import ctypes
            down = 0x0008 if btn == "right" else 0x0002
            up = 0x0010 if btn == "right" else 0x0004
            ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)
            if double:
                time.sleep(0.08)
                ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
                ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)
            return True
        except Exception as e:
            print(f"[GUI] mouse_click error: {e}")

    elif IS_MAC:
        click_type = "double click" if double else "click"
        res = run_command(f"osascript -e 'tell application \"System Events\" to {click_type}'")
        return res["exit_code"] == 0

    return False


def type_text(text: str) -> bool:
    """Types plain text directly into whatever window is currently active/focused."""
    if IS_WINDOWS:
        try:
            import ctypes
            u32 = ctypes.windll.user32
            KEYEVENTF_UNICODE = 0x0004
            KEYEVENTF_KEYUP = 0x0002

            for ch in text:
                code = ord(ch)
                u32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
                u32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
                time.sleep(0.005)
            return True
        except Exception as e:
            print(f"[GUI] type_text error: {e}")

    elif IS_MAC:
        escaped = text.replace('\\', '\\\\').replace('"', '\\"')
        res = run_command(f'osascript -e \'tell application "System Events" to keystroke "{escaped}"\'')
        return res["exit_code"] == 0

    return False


def press_key(key_name: str) -> bool:
    """Presses a single hardware key (enter, tab, esc, space, backspace, etc.)."""
    k = key_name.lower().strip()
    if IS_WINDOWS:
        try:
            import ctypes
            u32 = ctypes.windll.user32
            KEYEVENTF_KEYUP = 0x0002

            vk_map = {
                "enter": 0x0D,
                "return": 0x0D,
                "tab": 0x09,
                "esc": 0x1B,
                "escape": 0x1B,
                "space": 0x20,
                "backspace": 0x08,
                "bs": 0x08,
                "up": 0x26,
                "down": 0x28,
                "left": 0x25,
                "right": 0x27,
                "delete": 0x2E,
                "del": 0x2E,
            }
            if k in vk_map:
                vk = vk_map[k]
                u32.keybd_event(vk, 0, 0, 0)
                time.sleep(0.02)
                u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
                return True
        except Exception as e:
            print(f"[GUI] press_key error: {e}")

    elif IS_MAC:
        mac_key_map = {
            "enter": "key code 36",
            "return": "key code 36",
            "tab": "key code 48",
            "esc": "key code 53",
            "space": "key code 49",
            "backspace": "key code 51",
            "up": "key code 126",
            "down": "key code 125",
            "left": "key code 123",
            "right": "key code 124",
        }
        action = mac_key_map.get(k, f'keystroke "{k}"')
        return run_command(f"osascript -e 'tell application \"System Events\" to {action}'")["exit_code"] == 0

    return False


def press_hotkey(hotkey_str: str) -> bool:
    """Presses hardware hotkey combinations (win+d, ctrl+c, ctrl+v, alt+tab, etc.)."""
    hk = hotkey_str.lower().strip().replace(" ", "")
    if IS_WINDOWS:
        try:
            import ctypes
            u32 = ctypes.windll.user32
            KEYEVENTF_KEYUP = 0x0002

            VK_LWIN = 0x5B
            VK_CONTROL = 0x11
            VK_MENU = 0x12  # Alt
            VK_TAB = 0x09

            if hk in ["win+d", "win+m"]:
                u32.keybd_event(VK_LWIN, 0, 0, 0)
                u32.keybd_event(0x44, 0, 0, 0)  # 'D'
                time.sleep(0.02)
                u32.keybd_event(0x44, 0, KEYEVENTF_KEYUP, 0)
                u32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
                return True

            elif hk == "alt+tab":
                u32.keybd_event(VK_MENU, 0, 0, 0)
                u32.keybd_event(VK_TAB, 0, 0, 0)
                time.sleep(0.05)
                u32.keybd_event(VK_TAB, 0, KEYEVENTF_KEYUP, 0)
                u32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                return True

            elif hk in ["ctrl+c", "ctrl+v", "ctrl+a", "ctrl+z", "ctrl+s", "ctrl+x"]:
                char_key = ord(hk[-1].upper())
                u32.keybd_event(VK_CONTROL, 0, 0, 0)
                u32.keybd_event(char_key, 0, 0, 0)
                time.sleep(0.02)
                u32.keybd_event(char_key, 0, KEYEVENTF_KEYUP, 0)
                u32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return True

        except Exception as e:
            print(f"[GUI] press_hotkey error: {e}")

    elif IS_MAC:
        if hk in ["cmd+c", "ctrl+c"]:
            return run_command("osascript -e 'tell application \"System Events\" to keystroke \"c\" using command down'")["exit_code"] == 0
        elif hk in ["cmd+v", "ctrl+v"]:
            return run_command("osascript -e 'tell application \"System Events\" to keystroke \"v\" using command down'")["exit_code"] == 0
        elif hk in ["cmd+a", "ctrl+a"]:
            return run_command("osascript -e 'tell application \"System Events\" to keystroke \"a\" using command down'")["exit_code"] == 0

    return False
