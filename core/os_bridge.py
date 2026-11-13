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


def launch_app(app_name: str) -> dict:
    """Launches an application by common name or executable path."""
    app_lower = app_name.lower().strip()
    if IS_WINDOWS:
        app_map = {
            "chrome": "start chrome",
            "edge": "start msedge",
            "antigravity": r'start "" "$env:LOCALAPPDATA\Programs\antigravity\Antigravity.exe"',
            "antigravity ide": r'start "" "$env:LOCALAPPDATA\Programs\Antigravity IDE\Antigravity IDE.exe"',
            "vscode": "code",
            "notepad": "notepad",
            "calc": "calc",
            "calculator": "calc",
            "explorer": "explorer",
            "taskmgr": "taskmgr",
            "task manager": "taskmgr",
        }
        cmd = app_map.get(app_lower, f"start '{app_name}'")
        return run_command(cmd)
    elif IS_MAC:
        app_map = {
            "chrome": "open -a 'Google Chrome'",
            "edge": "open -a 'Microsoft Edge'",
            "safari": "open -a 'Safari'",
            "terminal": "open -a 'Terminal'",
        }
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
# GUI AUTOMATION: Mouse Movement, Clicks, Keystrokes & Hotkeys
# ----------------------------------------------------------------------

def mouse_move(x: int, y: int) -> bool:
    """Moves the mouse cursor to screen coordinates (x, y)."""
    if IS_WINDOWS:
        try:
            import ctypes
            if ctypes.windll.user32.SetCursorPos(int(x), int(y)):
                return True
        except Exception:
            pass
        ps = f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point({int(x)}, {int(y)})"
        res = run_command(ps, timeout=5)
        return res["exit_code"] == 0
    elif IS_MAC:
        res = run_command(f"osascript -e 'tell application \"System Events\" to set the position of the mouse cursor to {{{int(x)}, {int(y)}}}'")
        return res["exit_code"] == 0
    return False


def mouse_click(x: int = None, y: int = None, button: str = "left", double: bool = False) -> bool:
    """Clicks at coordinates (x, y) or current cursor position."""
    if x is not None and y is not None:
        mouse_move(x, y)
        time.sleep(0.05)

    btn = button.lower()
    if IS_WINDOWS:
        try:
            import ctypes
            # Left down/up: 0x02, 0x04 | Right down/up: 0x08, 0x10
            down = 0x0008 if btn == "right" else 0x0002
            up = 0x0010 if btn == "right" else 0x0004
            ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)
            if double:
                time.sleep(0.1)
                ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
                ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)
            return True
        except Exception:
            pass

    elif IS_MAC:
        click_type = "double click" if double else "click"
        res = run_command(f"osascript -e 'tell application \"System Events\" to {click_type}'")
        return res["exit_code"] == 0

    return False


def type_text(text: str) -> bool:
    """Types plain text into the currently focused window."""
    if IS_WINDOWS:
        # Escape characters that SendKeys treats as modifiers: + ^ % ~ ( ) { } [ ]
        safe_text = ""
        for ch in text:
            if ch in "+^%~(){}[]":
                safe_text += f"{{{ch}}}"
            else:
                safe_text += ch

        ps = f"""
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait(@'
{safe_text}
'@)
"""
        res = run_command(ps, timeout=10)
        return res["exit_code"] == 0

    elif IS_MAC:
        escaped = text.replace('\\', '\\\\').replace('"', '\\"')
        res = run_command(f'osascript -e \'tell application "System Events" to keystroke "{escaped}"\'')
        return res["exit_code"] == 0

    return False


def press_key(key_name: str) -> bool:
    """Presses a single special key (enter, tab, esc, space, backspace, up, down, left, right)."""
    k = key_name.lower().strip()
    if IS_WINDOWS:
        key_map = {
            "enter": "{ENTER}",
            "return": "{ENTER}",
            "tab": "{TAB}",
            "esc": "{ESC}",
            "escape": "{ESC}",
            "space": " ",
            "backspace": "{BS}",
            "bs": "{BS}",
            "up": "{UP}",
            "down": "{DOWN}",
            "left": "{LEFT}",
            "right": "{RIGHT}",
            "delete": "{DEL}",
            "del": "{DEL}",
        }
        send_code = key_map.get(k, f"{{{k.upper()}}}")
        ps = f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('{send_code}')"
        res = run_command(ps, timeout=5)
        return res["exit_code"] == 0

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
        res = run_command(f"osascript -e 'tell application \"System Events\" to {action}'")
        return res["exit_code"] == 0

    return False


def press_hotkey(hotkey_str: str) -> bool:
    """Presses a hotkey combination (e.g. 'ctrl+c', 'ctrl+v', 'alt+tab', 'ctrl+a', 'win+d')."""
    hk = hotkey_str.lower().strip().replace(" ", "")
    if IS_WINDOWS:
        # SendKeys representation: ^ = Ctrl, % = Alt, + = Shift
        hotkey_map = {
            "ctrl+c": "^c",
            "ctrl+v": "^v",
            "ctrl+x": "^x",
            "ctrl+a": "^a",
            "ctrl+s": "^s",
            "ctrl+z": "^z",
            "alt+tab": "%{TAB}",
            "alt+f4": "%{F4}",
            "enter": "{ENTER}",
        }
        if hk in hotkey_map:
            code = hotkey_map[hk]
            ps = f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('{code}')"
            res = run_command(ps, timeout=5)
            return res["exit_code"] == 0
        elif hk in ["win+d", "win+m"]:
            ps = "(New-Object -ComObject Shell.Application).MinimizeAll()"
            res = run_command(ps, timeout=5)
            return res["exit_code"] == 0

    elif IS_MAC:
        if hk in ["cmd+c", "ctrl+c"]:
            return run_command("osascript -e 'tell application \"System Events\" to keystroke \"c\" using command down'")["exit_code"] == 0
        elif hk in ["cmd+v", "ctrl+v"]:
            return run_command("osascript -e 'tell application \"System Events\" to keystroke \"v\" using command down'")["exit_code"] == 0
        elif hk in ["cmd+a", "ctrl+a"]:
            return run_command("osascript -e 'tell application \"System Events\" to keystroke \"a\" using command down'")["exit_code"] == 0

    return False
