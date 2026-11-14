"""Cross-platform OS bridge for Windows, macOS and Linux.

Executes shell commands, collects system metrics, captures screenshots, opens/closes apps
and drives the mouse and keyboard.

Platform support: Windows = full, macOS = partial, Linux = basic (see README).
"""
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

try:
    import config
except ImportError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    import config

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

try:  # Optional: more precise metrics when installed
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None


def _ok(stdout: str = "") -> dict:
    return {"exit_code": 0, "stdout": stdout, "stderr": ""}


def _err(stderr: str, code: int = 1) -> dict:
    return {"exit_code": code, "stdout": "", "stderr": stderr}


# ----------------------------------------------------------------------
# Windows desktop / DPI helpers
# ----------------------------------------------------------------------
_DPI_DONE = False


def ensure_dpi_aware():
    """Make screenshot pixels and mouse coordinates use the same (physical) scale."""
    global _DPI_DONE
    if _DPI_DONE or not IS_WINDOWS:
        return
    _DPI_DONE = True
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


ensure_dpi_aware()


def attach_to_input_desktop() -> bool:
    """Attaches current thread to the interactive user desktop ('Default').
    Prevents background process isolation from rendering black screenshots and dropping input.
    """
    if IS_WINDOWS:
        try:
            import ctypes
            u32 = ctypes.windll.user32
            h_input = u32.OpenInputDesktop(0, False, 0x01FF)
            if h_input:
                u32.SetThreadDesktop(h_input)
                return True
        except Exception as e:
            print(f"[Desktop] attach_to_input_desktop error: {e}")
    return False


def get_virtual_screen() -> tuple:
    """Returns (left, top, width, height) of the whole desktop across all monitors."""
    if IS_WINDOWS:
        try:
            import ctypes
            u32 = ctypes.windll.user32
            return (u32.GetSystemMetrics(76), u32.GetSystemMetrics(77),
                    u32.GetSystemMetrics(78), u32.GetSystemMetrics(79))
        except Exception:
            pass
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        return (0, 0, img.size[0], img.size[1])
    except Exception:
        return (0, 0, 1920, 1080)


def get_primary_screen_size() -> tuple:
    if IS_WINDOWS:
        try:
            import ctypes
            u32 = ctypes.windll.user32
            return u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
        except Exception:
            pass
    _, _, w, h = get_virtual_screen()
    return w, h


# ----------------------------------------------------------------------
# Shell
# ----------------------------------------------------------------------
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


def ps_quote(value: str) -> str:
    """Quote a value as a PowerShell single-quoted string literal (no injection)."""
    return "'" + str(value).replace("'", "''") + "'"


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------
def _set_ram(stats: dict, total_bytes: float, available_bytes: float):
    if not total_bytes:
        return
    tot = total_bytes / (1024 ** 3)
    free = available_bytes / (1024 ** 3)
    stats["ram_total_gb"] = round(tot, 1)
    stats["ram_free_gb"] = round(free, 1)
    stats["ram_used_gb"] = round(tot - free, 1)
    stats["ram_used_pct"] = round(((tot - free) / tot) * 100, 1)


def get_system_stats() -> dict:
    """Returns CPU count, RAM, Disk, and OS details."""
    stats = {
        "os": f"{platform.system()} {platform.release()}",
        "architecture": platform.machine(),
        "cpu_cores": os.cpu_count() or 1,
    }

    try:
        drive = "C:\\" if IS_WINDOWS else "/"
        total, used, free = shutil.disk_usage(drive)
        stats["disk_total_gb"] = round(total / (1024 ** 3), 1)
        stats["disk_used_gb"] = round(used / (1024 ** 3), 1)
        stats["disk_free_gb"] = round(free / (1024 ** 3), 1)
        stats["disk_used_pct"] = round((used / total) * 100, 1)
    except Exception:
        pass

    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            _set_ram(stats, vm.total, vm.available)
            return stats
        except Exception:
            pass

    if IS_WINDOWS:
        res = run_command("(Get-CimInstance Win32_OperatingSystem) | Select-Object TotalVisibleMemorySize, FreePhysicalMemory | ConvertTo-Json")
        if res["exit_code"] == 0 and res["stdout"]:
            try:
                m = json.loads(res["stdout"])
                _set_ram(stats, m.get("TotalVisibleMemorySize", 0) * 1024, m.get("FreePhysicalMemory", 0) * 1024)
            except Exception:
                pass
    elif IS_MAC:
        try:
            total = int(run_command("sysctl -n hw.memsize")["stdout"] or 0)
            vm = run_command("vm_stat")["stdout"]
            page = int(re.search(r"page size of (\d+)", vm).group(1)) if "page size of" in vm else 4096

            def pages(label):
                m = re.search(rf"{label}:\s+(\d+)", vm)
                return int(m.group(1)) if m else 0

            avail = (pages("Pages free") + pages("Pages inactive") + pages("Pages speculative")) * page
            _set_ram(stats, total, avail)
        except Exception:
            pass
    elif IS_LINUX:
        try:
            info = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0]) * 1024
            _set_ram(stats, info.get("MemTotal", 0), info.get("MemAvailable", info.get("MemFree", 0)))
        except Exception:
            pass

    return stats


# ----------------------------------------------------------------------
# Screenshots
# ----------------------------------------------------------------------
def take_screenshot(output_path: Path, all_screens: bool = True) -> bool:
    """Captures the desktop and saves it as JPEG."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    attach_to_input_desktop()
    ensure_dpi_aware()

    # Method 1: Pillow ImageGrab
    try:
        from PIL import ImageGrab
        try:
            img = ImageGrab.grab(all_screens=all_screens) if (IS_WINDOWS or IS_LINUX) else ImageGrab.grab()
        except TypeError:
            img = ImageGrab.grab()
        if img and img.size[0] > 0 and img.size[1] > 0:
            img.convert("RGB").save(str(output_path), "JPEG", quality=85)
            if output_path.exists() and output_path.stat().st_size > 20000:
                return True
    except Exception:
        pass

    # Method 2: OS specific native fallback
    if IS_WINDOWS:
        ps_path = ps_quote(str(output_path))
        ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bitmap = New-Object System.Drawing.Bitmap $screen.Width, $screen.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bitmap.Save({ps_path}, [System.Drawing.Imaging.ImageFormat]::Jpeg)
$graphics.Dispose()
$bitmap.Dispose()
"""
        run_command(ps_script, timeout=10)
    elif IS_MAC:
        run_command(f"screencapture -x {shlex.quote(str(output_path))}", timeout=10)
    elif IS_LINUX:
        q = shlex.quote(str(output_path))
        for tool_cmd in (f"gnome-screenshot -f {q}", f"scrot -o {q}", f"grim {q}", f"import -window root {q}"):
            if shutil.which(tool_cmd.split()[0]):
                run_command(tool_cmd, timeout=10)
                if output_path.exists() and output_path.stat().st_size > 0:
                    break

    return output_path.exists() and output_path.stat().st_size > 0


# ----------------------------------------------------------------------
# App catalog / launching
# ----------------------------------------------------------------------
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
    "whatsapp web": "https://web.whatsapp.com",
    "hark": "https://hark.com",
    "muse": "https://muse.ai",
}

# Window-title hints used to close a website's tab.
WEB_TITLE_HINTS = {
    "gmail": "gmail", "mail": "gmail", "youtube studio": "youtube studio", "yt studio": "youtube studio",
    "youtube": "youtube", "yt": "youtube", "chatgpt": "chatgpt", "github": "github",
    "whatsapp web": "whatsapp", "google": "google",
}

_APPS_CACHE = {}
_CACHE_REFRESHED_THIS_RUN = False


def refresh_installed_apps_cache() -> dict:
    """Discovers and caches all installed applications on Windows (Win32, Store, and PWA apps)."""
    global _APPS_CACHE, _CACHE_REFRESHED_THIS_RUN
    if not IS_WINDOWS:
        return {}
    _CACHE_REFRESHED_THIS_RUN = True

    cache_file = config.TEMP_DIR / "apps_cache.json"
    apps = {}
    try:
        res = run_command("Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress", timeout=15)
        if res["exit_code"] == 0 and res["stdout"]:
            data = json.loads(res["stdout"])
            if isinstance(data, dict):
                data = [data]
            for item in data:
                name = (item.get("Name") or "").strip()
                appid = (item.get("AppID") or "").strip()
                if name and appid:
                    apps[name.lower()] = appid
    except Exception as e:
        print(f"[OS_Bridge] Warning refreshing apps cache: {e}")

    if apps:
        _APPS_CACHE = apps
        try:
            cache_file.write_text(json.dumps(apps, indent=2))
        except Exception:
            pass
    return _APPS_CACHE


def get_installed_apps() -> dict:
    """Returns cached installed apps catalog, populating it if not already loaded."""
    global _APPS_CACHE
    if _APPS_CACHE:
        return _APPS_CACHE

    cache_file = config.TEMP_DIR / "apps_cache.json"
    if cache_file.exists():
        try:
            _APPS_CACHE = json.loads(cache_file.read_text())
            if _APPS_CACHE:
                return _APPS_CACHE
        except Exception:
            pass

    return refresh_installed_apps_cache()


def _word_in(phrase: str, text: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(phrase)}(?![\w])", text) is not None


def find_app_id(query: str, exact_only: bool = False) -> Optional[str]:
    """Finds the best matching AppID for an application name (whole-word matching only)."""
    apps = get_installed_apps()
    q = query.lower().strip()
    if not q:
        return None
    if q in apps:
        return apps[q]
    if exact_only:
        return None
    # Name starts with the query as whole words ("python" -> "python 3.13")
    for name, appid in apps.items():
        if re.match(rf"{re.escape(q)}(?![\w])", name):
            return appid
    # Query appears as whole words inside the name ("edge" -> "microsoft edge")
    for name, appid in apps.items():
        if _word_in(q, name):
            return appid
    return None


def _windows_exec_map() -> dict:
    return {
        "edge": "msedge.exe", "msedge": "msedge.exe", "microsoft edge": "msedge.exe",
        "chrome": "chrome.exe", "google chrome": "chrome.exe",
        "notepad": "notepad.exe",
        "calc": "calc.exe", "calculator": "calc.exe",
        "explorer": "explorer.exe", "file explorer": "explorer.exe",
        "taskmgr": "taskmgr.exe", "task manager": "taskmgr.exe",
        "antigravity": os.path.expandvars(r"%LOCALAPPDATA%\Programs\antigravity\Antigravity.exe"),
        "hermes": config.HERMES_APP_PATH,
        "vscode": "code.cmd", "vs code": "code.cmd", "code": "code.cmd",
        "cmd": "cmd.exe", "command prompt": "cmd.exe",
        "powershell": "powershell.exe",
        "terminal": "wt.exe",
        "paint": "mspaint.exe",
    }


def _open_url(url: str, app_mode: bool = False, browser: str = "") -> dict:
    if IS_WINDOWS:
        try:
            if app_mode or browser == "edge":
                flag = f'--app="{url}"' if app_mode else f'"{url}"'
                subprocess.Popen(f'cmd.exe /c start "" msedge {flag}', shell=True)
            elif browser == "chrome":
                subprocess.Popen(f'cmd.exe /c start "" chrome "{url}"', shell=True)
            else:
                os.startfile(url)
            return _ok(f"Opened {url}")
        except Exception as e:
            return _err(str(e))
    if IS_MAC:
        app_flag = "-a 'Google Chrome' " if browser == "chrome" else ("-a 'Microsoft Edge' " if browser == "edge" else "")
        return run_command(f"open {app_flag}{shlex.quote(url)}")
    if IS_LINUX:
        return run_command(f"xdg-open {shlex.quote(url)} >/dev/null 2>&1 &")
    return _err("Unsupported platform")


def open_url(url: str) -> dict:
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return _open_url(url)


def launch_app(app_name: str, wait: bool = True) -> dict:
    """Launches an app or website and (on Windows) waits until its window is up and ready,
    so a following "type ..." goes into the new window instead of the old one."""
    if not (IS_WINDOWS and wait):
        return _launch_app(app_name)
    try:
        before_windows, before_fg = _visible_window_handles(), _foreground_hwnd()
    except Exception:
        return _launch_app(app_name)
    res = _launch_app(app_name)
    if res["exit_code"] == 0 and not wait_for_new_window(before_windows, before_fg):
        res["stdout"] += " (no new window appeared yet - it may still be loading)"
    return res


def _launch_app(app_name: str) -> dict:
    """Launches an application or website on the user's interactive desktop.

    Order: explicit URL -> exact installed app name -> website shortcut (whole words)
    -> fuzzy installed app -> known executables -> clear "not found" error.
    """
    app_lower = app_name.lower().strip()
    if not app_lower:
        return _err("No app name given")
    words = app_lower.split()
    clean_query = re.sub(r"\.(exe|app|lnk)$", "", app_lower).strip()
    browser = "chrome" if "chrome" in words else ("edge" if "edge" in words or "msedge" in words else "")

    # 1. Explicit URL
    for part in app_name.split():
        if re.match(r"^https?://", part, re.IGNORECASE):
            return _open_url(part, browser=browser)

    # 2. Exact installed app / known executable name ("google chrome" opens Chrome, not google.com)
    if IS_WINDOWS:
        exact_id = find_app_id(clean_query, exact_only=True)
        if exact_id:
            return _start_appid(app_name, exact_id)
        exe = _windows_exec_map().get(clean_query)
        if exe:
            return _start_exe(clean_query, exe)

    # 3. Website shortcuts (longest phrase first, whole words only)
    for site_key in sorted(WEB_SHORTCUTS, key=len, reverse=True):
        if _word_in(site_key, app_lower):
            is_app_mode = any(w in words for w in ["app", "gui", "standalone", "pwa"])
            return _open_url(WEB_SHORTCUTS[site_key], app_mode=is_app_mode, browser=browser)

    if IS_WINDOWS:
        # 4. Fuzzy installed-app match, refreshing the catalog once if the name isn't known
        matched = find_app_id(clean_query)
        if not matched and not _CACHE_REFRESHED_THIS_RUN:
            refresh_installed_apps_cache()
            matched = find_app_id(clean_query)
        if matched:
            return _start_appid(app_name, matched)

        # 5. Known executables mentioned as words ("edge browser")
        for k, target_exe in _windows_exec_map().items():
            if _word_in(k, clean_query):
                return _start_exe(k, target_exe)

        # 6. Something on PATH or an existing file path
        if os.path.exists(app_name) or shutil.which(clean_query):
            try:
                os.startfile(app_name if os.path.exists(app_name) else shutil.which(clean_query))
                return _ok(f"Started {app_name}")
            except Exception as e:
                return _err(str(e))
        return _err(f"App '{app_name}' not found. Check the name (e.g. 'open notepad') or install it.")

    if IS_MAC:
        mac_names = {"chrome": "Google Chrome", "edge": "Microsoft Edge", "safari": "Safari",
                     "terminal": "Terminal", "vscode": "Visual Studio Code", "code": "Visual Studio Code"}
        target = mac_names.get(clean_query, app_name)
        res = run_command(f"open -a {shlex.quote(target)}")
        if res["exit_code"] != 0:
            return _err(f"App '{app_name}' not found.")
        return res

    if IS_LINUX:
        exe = shutil.which(clean_query) or shutil.which(clean_query.replace(" ", "-"))
        if exe:
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return _ok(f"Started {exe}")
        if shutil.which("gtk-launch"):
            res = run_command(f"gtk-launch {shlex.quote(clean_query)}")
            if res["exit_code"] == 0:
                return res
        return _err(f"App '{app_name}' not found.")

    return _err("Unsupported platform")


def _start_appid(label: str, appid: str) -> dict:
    try:
        os.startfile(f"shell:AppsFolder\\{appid}")
        return _ok(f"Launched '{label}'")
    except Exception:
        res = run_command(f"explorer.exe {ps_quote('shell:AppsFolder' + chr(92) + appid)}")
        if res["exit_code"] in (0, 1):  # explorer.exe returns 1 even on success
            return _ok(f"Launched '{label}' via Explorer shell")
        return _err(f"Could not launch '{label}': {res['stderr']}")


def _start_exe(label: str, target_exe: str) -> dict:
    try:
        os.startfile(target_exe)
        return _ok(f"Launched {label}")
    except Exception:
        res = run_command(f"Start-Process -FilePath {ps_quote(target_exe)}")
        if res["exit_code"] == 0:
            return _ok(f"Launched {label}")
        return _err(f"Could not launch {label}: {res['stderr'] or 'not installed'}")


# ----------------------------------------------------------------------
# Closing apps
# ----------------------------------------------------------------------
# Friendly name -> exact process names (without .exe)
PROCESS_NAME_MAP = {
    "edge": ["msedge"], "msedge": ["msedge"], "microsoft edge": ["msedge"],
    "chrome": ["chrome"], "google chrome": ["chrome"],
    "firefox": ["firefox"], "brave": ["brave"], "opera": ["opera"],
    "notepad": ["Notepad", "notepad"],
    "calc": ["CalculatorApp", "Calculator"], "calculator": ["CalculatorApp", "Calculator"],
    "code": ["Code"], "vscode": ["Code"], "vs code": ["Code"], "visual studio code": ["Code"],
    "spotify": ["Spotify"], "discord": ["Discord"], "telegram": ["Telegram"],
    "whatsapp": ["WhatsApp"], "slack": ["slack"], "zoom": ["Zoom"],
    "teams": ["ms-teams", "Teams"], "outlook": ["olk", "OUTLOOK"],
    "word": ["WINWORD"], "excel": ["EXCEL"], "powerpoint": ["POWERPNT"],
    "paint": ["mspaint"], "terminal": ["WindowsTerminal"], "cmd": ["cmd"],
    "task manager": ["Taskmgr"], "taskmgr": ["Taskmgr"],
    "hermes": ["Hermes"], "antigravity": ["Antigravity"],
    "obs": ["obs64"], "vlc": ["vlc"], "photos": ["Photos"], "settings": ["SystemSettings"],
    "steam": ["steam"], "capcut": ["CapCut"], "claude": ["claude"],
}

# Never killed by close_app, whatever the user typed.
PROTECTED_PROCESSES = {
    "explorer", "msedgewebview2", "csrss", "winlogon", "wininit", "lsass", "services", "smss",
    "svchost", "dwm", "system", "idle", "registry", "conhost", "sihost", "fontdrvhost", "ctfmon",
    "searchhost", "startmenuexperiencehost", "shellexperiencehost", "runtimebroker", "taskhostw",
    "python", "pythonw", "python3", "powershell", "pwsh", "securityhealthservice", "msmpeng",
    "audiodg", "spoolsv", "lsaiso", "memory compression",
}

CLOSE_WINDOW_WORDS = {"", "window", "this", "this window", "active window", "current window", "it", "app", "this app"}
CLOSE_TAB_WORDS = {"tab", "this tab", "current tab", "active tab"}


def resolve_process_names(target: str) -> list:
    t = re.sub(r"\.(exe|app)$", "", target.lower().strip()).strip()
    if t in PROCESS_NAME_MAP:
        names = PROCESS_NAME_MAP[t]
    else:
        names = [t, t.replace(" ", "")]
    return [n for n in dict.fromkeys(names) if n and n.lower() not in PROTECTED_PROCESSES]


def close_active_window() -> dict:
    with UserInputLock("Close Window"):
        ok = press_hotkey("alt+f4")
    return _ok("Sent Alt+F4 to the active window") if ok else _err("Could not send Alt+F4")


def close_app(target_name: str) -> dict:
    """Closes an app by exact process name, a website tab, or the active window."""
    target_lower = target_name.lower().strip()

    if target_lower in CLOSE_WINDOW_WORDS:
        return close_active_window()

    if target_lower in CLOSE_TAB_WORDS:
        with UserInputLock("Close Tab"):
            ok = press_hotkey("ctrl+w")
        return _ok("Closed the active tab (Ctrl+W)") if ok else _err("Could not send Ctrl+W")

    names = resolve_process_names(target_lower)

    # Website tab ("close youtube studio", "close gmail") when it's not an installed app name
    if target_lower not in PROCESS_NAME_MAP:
        for site_key in sorted(WEB_TITLE_HINTS, key=len, reverse=True):
            if _word_in(site_key, target_lower):
                if focus_window(WEB_TITLE_HINTS[site_key]):
                    with UserInputLock("Close Tab"):
                        press_hotkey("ctrl+w")
                    return _ok(f"Closed the '{site_key}' tab (Ctrl+W)")
                return _err(f"No open window or tab found for '{target_name}'.")

    if not names:
        return _err(f"'{target_name}' is a protected system process and won't be closed.")

    if IS_WINDOWS:
        names_ps = ",".join(ps_quote(n) for n in names)
        ps_close = f"""
$names = @({names_ps})
$procs = @(Get-Process -Name $names -ErrorAction SilentlyContinue | Where-Object {{ $_.Id -ne $PID }})
if ($procs.Count -eq 0) {{ Write-Output 'NOT_RUNNING'; exit 0 }}
foreach ($p in $procs) {{ try {{ $null = $p.CloseMainWindow() }} catch {{}} }}
Start-Sleep -Milliseconds 1500
$killed = 0
foreach ($p in $procs) {{
    try {{ $p.Refresh(); if (-not $p.HasExited) {{ Stop-Process -Id $p.Id -Force -ErrorAction Stop; $killed++ }} }} catch {{}}
}}
Write-Output ("CLOSED " + $procs.Count + " " + $killed)
"""
        res = run_command(ps_close, timeout=15)
        out = res["stdout"].strip()
        if out.startswith("NOT_RUNNING") or not out:
            return _err(f"'{target_name}' is not running.")
        m = re.match(r"CLOSED (\d+) (\d+)", out)
        if m:
            total, forced = int(m.group(1)), int(m.group(2))
            extra = f" ({forced} had to be force-closed)" if forced else ""
            return _ok(f"Closed {target_name}: {total} process(es){extra}")
        return _ok(out)

    if IS_MAC or IS_LINUX:
        closed = False
        for n in names:
            res = run_command(f"pkill -x {shlex.quote(n)}")
            closed = closed or res["exit_code"] == 0
        return _ok(f"Closed {target_name}") if closed else _err(f"'{target_name}' is not running.")

    return _err("Unsupported platform")


# ----------------------------------------------------------------------
# Misc system actions
# ----------------------------------------------------------------------
def lock_workstation() -> dict:
    if IS_WINDOWS:
        return run_command("rundll32.exe user32.dll,LockWorkStation")
    if IS_MAC:
        return run_command("pmset displaysleepnow")
    if IS_LINUX:
        return run_command("loginctl lock-session || xdg-screensaver lock")
    return _err("Unsupported platform")


def list_top_processes(limit: int = 10) -> str:
    limit = max(1, min(int(limit), 50))
    if IS_WINDOWS:
        cmd = f"Get-Process | Sort-Object CPU -Descending | Select-Object -First {limit} Id, ProcessName, CPU, @{{n='MemMB';e={{[int]($_.WorkingSet64/1MB)}}}} | Format-Table -AutoSize | Out-String -Width 120"
    elif IS_MAC:
        cmd = f"ps -eo pid,pcpu,pmem,comm | sort -k 2 -nr | head -n {limit}"
    elif IS_LINUX:
        cmd = f"ps -eo pid,pcpu,pmem,comm --sort=-pcpu | head -n {limit + 1}"
    else:
        return "Unsupported platform"
    res = run_command(cmd)
    return res["stdout"] if res["exit_code"] == 0 else res["stderr"]


def power_action(action: str) -> dict:
    """sleep | restart | shutdown | logoff (callers must get user approval first)."""
    a = action.lower().strip()
    if IS_WINDOWS:
        cmds = {
            "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
            "restart": "shutdown /r /t 15",
            "shutdown": "shutdown /s /t 15",
            "logoff": "shutdown /l",
        }
    elif IS_MAC:
        cmds = {"sleep": "pmset sleepnow", "restart": "osascript -e 'tell app \"System Events\" to restart'",
                "shutdown": "osascript -e 'tell app \"System Events\" to shut down'",
                "logoff": "osascript -e 'tell app \"System Events\" to log out'"}
    else:
        cmds = {"sleep": "systemctl suspend", "restart": "systemctl reboot", "shutdown": "systemctl poweroff",
                "logoff": "loginctl terminate-user $USER"}
    if a not in cmds:
        return _err(f"Unknown power action '{action}'")
    return run_command(cmds[a])


def latest_download() -> Optional[Path]:
    d = Path.home() / "Downloads"
    if not d.exists():
        return None
    files = [f for f in d.iterdir() if f.is_file() and not f.name.endswith((".crdownload", ".part", ".tmp"))]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def find_file(name: str) -> Optional[Path]:
    """Finds a file by exact path, or by name in screenshots/, Downloads, Desktop, Documents."""
    name = name.strip().strip('"').strip("'")
    if not name:
        return None
    p = Path(os.path.expandvars(os.path.expanduser(name)))
    if p.is_file():
        return p
    home = Path.home()
    folders = [config.SCREENSHOTS_DIR, home / "Downloads", home / "Desktop", home / "OneDrive" / "Desktop",
               home / "Documents", config.INBOX_DIR]
    needle = name.lower()
    for folder in folders:
        if not folder.exists():
            continue
        exact = folder / name
        if exact.is_file():
            return exact
        matches = [f for f in folder.iterdir() if f.is_file() and needle in f.name.lower()]
        if matches:
            return max(matches, key=lambda f: f.stat().st_mtime)
    return None


# ----------------------------------------------------------------------
# GUI AUTOMATION: native mouse & keyboard
# ----------------------------------------------------------------------
_LOCK_STATE = threading.Lock()
_LOCK_DEPTH = 0
_LOCK_ACTIVE = False


class _InputBlocker:
    """Owns every BlockInput call on ONE long-lived thread.

    Windows only lets the thread that blocked input unblock it (and unblocks automatically if
    that thread ends), so /stop, timers and the agent all go through this thread.
    Ctrl+Alt+Del always unblocks input (Windows safety rule).
    """

    def __init__(self):
        import queue as _queue
        self._q = _queue.Queue()
        self._thread = None

    def _run(self):
        import ctypes
        while True:
            want, done, box = self._q.get()
            try:
                box.append(bool(ctypes.windll.user32.BlockInput(bool(want))))
            except Exception as e:
                print(f"[GUI] BlockInput error: {e}")
                box.append(False)
            done.set()

    def set(self, blocked: bool) -> bool:
        if not IS_WINDOWS:
            return False
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="input-blocker", daemon=True)
            self._thread.start()
        done, box = threading.Event(), []
        self._q.put((blocked, done, box))
        done.wait(5)
        return bool(box and box[0])


_BLOCKER = _InputBlocker()
_LONG_BLOCK = {"until": 0.0, "timer": None}


def set_user_input_blocked(blocked: bool) -> bool:
    """Blocks or unblocks physical mouse/keyboard on Windows (needs admin rights to block)."""
    return _BLOCKER.set(blocked)


def long_block_active() -> bool:
    return _LONG_BLOCK["until"] > time.time()


def block_input_for(minutes: float) -> dict:
    """Blocks the local mouse/keyboard for N minutes (remote use only). Needs admin.
    Unblocks automatically, with /unblock, or with Ctrl+Alt+Del at the PC."""
    if not IS_WINDOWS:
        return _err("Input blocking is only available on Windows.")
    if not input_lock_available():
        return _err("Blocking the local mouse/keyboard needs the bot to run as administrator. "
                    "Run install_autostart_admin.bat once (see README → Run as administrator).")
    minutes = max(0.5, min(float(minutes), 120.0))
    if not set_user_input_blocked(True):
        return _err("Windows refused to block input.")
    if _LONG_BLOCK["timer"]:
        _LONG_BLOCK["timer"].cancel()
    _LONG_BLOCK["until"] = time.time() + minutes * 60
    t = threading.Timer(minutes * 60, unblock_input)
    t.daemon = True
    t.start()
    _LONG_BLOCK["timer"] = t
    return _ok(f"Local mouse & keyboard blocked for {minutes:g} min (Ctrl+Alt+Del at the PC always unblocks).")


def unblock_input() -> dict:
    if _LONG_BLOCK["timer"]:
        _LONG_BLOCK["timer"].cancel()
    _LONG_BLOCK.update(until=0.0, timer=None)
    release_input_lock()
    return _ok("Local mouse & keyboard unblocked.")


class UserInputLock:
    """Re-entrant context manager that blocks physical input during GUI automation
    (only works when running as admin) and always restores it.
    `.locked` tells whether the block actually took effect.
    """

    def __init__(self, action_name="GUI Action"):
        self.action_name = action_name
        self.locked = False

    def __enter__(self):
        global _LOCK_DEPTH, _LOCK_ACTIVE
        with _LOCK_STATE:
            if long_block_active():
                self.locked = True  # a /block is already holding the input
                return self
            if _LOCK_DEPTH == 0:
                _LOCK_ACTIVE = set_user_input_blocked(True) if input_lock_available() else False
            _LOCK_DEPTH += 1
            self.locked = _LOCK_ACTIVE
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _LOCK_DEPTH, _LOCK_ACTIVE
        with _LOCK_STATE:
            if long_block_active():
                return
            _LOCK_DEPTH = max(0, _LOCK_DEPTH - 1)
            if _LOCK_DEPTH == 0 and _LOCK_ACTIVE:
                set_user_input_blocked(False)
                _LOCK_ACTIVE = False


def release_input_lock():
    """Emergency unlock (used by /stop and on errors). Keeps an explicit /block in place."""
    global _LOCK_DEPTH, _LOCK_ACTIVE
    with _LOCK_STATE:
        _LOCK_DEPTH = 0
        _LOCK_ACTIVE = False
    if not long_block_active():
        set_user_input_blocked(False)


def input_lock_available() -> bool:
    """True when BlockInput can actually be used (process is elevated on Windows)."""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def mouse_move(x: int, y: int) -> bool:
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
            return True
        except Exception:
            return False
    if IS_LINUX and shutil.which("xdotool"):
        return run_command(f"xdotool mousemove {int(x)} {int(y)}")["exit_code"] == 0
    if IS_MAC and shutil.which("cliclick"):
        return run_command(f"cliclick m:{int(x)},{int(y)}")["exit_code"] == 0
    return False


_MOUSE_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}


def mouse_click(x: int = None, y: int = None, button: str = "left", double: bool = False) -> bool:
    if x is not None and y is not None:
        mouse_move(x, y)
        time.sleep(0.05)
    btn = (button or "left").lower()
    if IS_WINDOWS:
        try:
            import ctypes
            down, up = _MOUSE_FLAGS.get(btn, _MOUSE_FLAGS["left"])
            for i in range(2 if double else 1):
                ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
                ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)
                if double and i == 0:
                    time.sleep(0.08)
            return True
        except Exception as e:
            print(f"[GUI] mouse_click error: {e}")
            return False
    if IS_LINUX and shutil.which("xdotool"):
        b = {"left": 1, "middle": 2, "right": 3}.get(btn, 1)
        return run_command(f"xdotool click --repeat {2 if double else 1} {b}")["exit_code"] == 0
    if IS_MAC and shutil.which("cliclick"):
        verb = "dc" if double else ("rc" if btn == "right" else "c")
        pos = f"{int(x)},{int(y)}" if x is not None and y is not None else "."
        return run_command(f"cliclick {verb}:{pos}")["exit_code"] == 0
    return False


def mouse_drag(x1: int, y1: int, x2: int, y2: int) -> bool:
    if IS_WINDOWS:
        try:
            import ctypes
            u32 = ctypes.windll.user32
            u32.SetCursorPos(int(x1), int(y1))
            time.sleep(0.05)
            u32.mouse_event(0x0002, 0, 0, 0, 0)
            steps = 15
            for i in range(1, steps + 1):
                u32.SetCursorPos(int(x1 + (x2 - x1) * i / steps), int(y1 + (y2 - y1) * i / steps))
                time.sleep(0.015)
            u32.mouse_event(0x0004, 0, 0, 0, 0)
            return True
        except Exception as e:
            print(f"[GUI] mouse_drag error: {e}")
            return False
    if IS_LINUX and shutil.which("xdotool"):
        return run_command(f"xdotool mousemove {x1} {y1} mousedown 1 mousemove {x2} {y2} mouseup 1")["exit_code"] == 0
    return False


def mouse_scroll(dy: int = -3, dx: int = 0, x: int = None, y: int = None) -> bool:
    """Scroll by notches: dy<0 scrolls down, dy>0 up; dx>0 right."""
    if x is not None and y is not None:
        mouse_move(x, y)
    if IS_WINDOWS:
        try:
            import ctypes
            if dy:
                ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(dy) * 120, 0)
            if dx:
                ctypes.windll.user32.mouse_event(0x01000, 0, 0, int(dx) * 120, 0)
            return True
        except Exception:
            return False
    if IS_LINUX and shutil.which("xdotool"):
        b = 4 if dy > 0 else 5
        return run_command(f"xdotool click --repeat {abs(int(dy)) or 1} {b}")["exit_code"] == 0
    return False


# Virtual-key codes
_VK = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "backspace": 0x08, "bs": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "printscreen": 0x2C, "prtsc": 0x2C, "capslock": 0x14, "menu": 0x5D, "apps": 0x5D,
    "volumemute": 0xAD, "mute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "nexttrack": 0xB0, "next": 0xB0, "prevtrack": 0xB1, "previous": 0xB1, "prev": 0xB1,
    "stop": 0xB2, "playpause": 0xB3, "play": 0xB3, "pause": 0xB3,
    "plus": 0xBB, "=": 0xBB, "minus": 0xBD, "-": 0xBD, ",": 0xBC, ".": 0xBE, "/": 0xBF,
    ";": 0xBA, "'": 0xDE, "[": 0xDB, "]": 0xDD, "\\": 0xDC, "`": 0xC0,
}
_VK_MODIFIERS = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
    "win": 0x5B, "windows": 0x5B, "super": 0x5B, "meta": 0x5B, "cmd": 0x11, "command": 0x11,
}
_EXTENDED_KEYS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5D,
                  0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}


def key_to_vk(key: str) -> Optional[int]:
    k = key.lower().strip()
    if k in _VK:
        return _VK[k]
    if re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", k):
        return 0x70 + int(k[1:]) - 1
    if len(k) == 1 and (k.isalpha() or k.isdigit()):
        return ord(k.upper())
    return None


def parse_hotkey(hotkey_str: str) -> Optional[tuple]:
    """'ctrl+shift+o' -> ([VK_CONTROL, VK_SHIFT], VK_O). Returns None if not understood."""
    hk = hotkey_str.lower().replace(" ", "")
    if not hk:
        return None
    parts = [p for p in re.split(r"\+(?!$)", hk) if p]
    mods, main = [], None
    for p in parts:
        if p in _VK_MODIFIERS and main is None:
            vk = _VK_MODIFIERS[p]
            if vk not in mods:
                mods.append(vk)
        else:
            if main is not None:
                return None
            main = key_to_vk(p)
            if main is None:
                return None
    if main is None:
        if len(mods) == 1:  # a lone modifier, e.g. "win"
            return ([], mods[0])
        return None
    return (mods, main)


def _key_event(vk: int, up: bool = False):
    import ctypes
    flags = 0x0001 if vk in _EXTENDED_KEYS else 0
    if up:
        flags |= 0x0002
    ctypes.windll.user32.keybd_event(vk, 0, flags, 0)


_MAC_KEYCODES = {"enter": 36, "return": 36, "tab": 48, "esc": 53, "escape": 53, "space": 49,
                 "backspace": 51, "delete": 117, "up": 126, "down": 125, "left": 123, "right": 124,
                 "home": 115, "end": 119, "pageup": 116, "pagedown": 121}


def press_hotkey(hotkey_str: str) -> bool:
    """Presses any combination like ctrl+w, ctrl+shift+o, alt+f4, win+d, win+m, f5."""
    if IS_WINDOWS:
        parsed = parse_hotkey(hotkey_str)
        if not parsed:
            print(f"[GUI] Unknown hotkey: {hotkey_str}")
            return False
        mods, main = parsed
        try:
            for m in mods:
                _key_event(m)
            _key_event(main)
            time.sleep(0.03)
            _key_event(main, up=True)
            for m in reversed(mods):
                _key_event(m, up=True)
            return True
        except Exception as e:
            print(f"[GUI] press_hotkey error: {e}")
            return False
    if IS_MAC:
        parts = hotkey_str.lower().replace(" ", "").split("+")
        mod_names = {"ctrl": "command down", "cmd": "command down", "command": "command down",
                     "alt": "option down", "option": "option down", "shift": "shift down",
                     "control": "control down"}
        mods = [mod_names[p] for p in parts[:-1] if p in mod_names]
        key = parts[-1]
        using = f" using {{{', '.join(mods)}}}" if mods else ""
        if key in _MAC_KEYCODES:
            action = f"key code {_MAC_KEYCODES[key]}{using}"
        else:
            action = f'keystroke "{key}"{using}'
        return run_command(f"osascript -e 'tell application \"System Events\" to {action}'")["exit_code"] == 0
    if IS_LINUX and shutil.which("xdotool"):
        combo = hotkey_str.lower().replace(" ", "").replace("win", "super")
        return run_command(f"xdotool key {shlex.quote(combo)}")["exit_code"] == 0
    return False


def press_key(key_name: str) -> bool:
    """Presses a single key (enter, tab, esc, space, backspace, arrows, f1-f24, letters...)."""
    return press_hotkey(key_name.strip())


def _send_unicode_text(text: str) -> bool:
    """Types text with SendInput + KEYEVENTF_UNICODE (works for any language/emoji)."""
    import ctypes
    from ctypes import wintypes

    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    send_input = ctypes.windll.user32.SendInput
    send_input.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    KEYEVENTF_UNICODE, KEYEVENTF_KEYUP = 0x0004, 0x0002
    target = ctypes.windll.user32.GetForegroundWindow()

    for i, ch in enumerate(text):
        if i % 8 == 0 and ctypes.windll.user32.GetForegroundWindow() != target:
            print(f"[GUI] Focus changed after {i} characters - stopped typing")
            return False
        if ch == "\n":
            press_key("enter")
            continue
        data = ch.encode("utf-16-le")
        units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
        for unit in units:
            arr = (INPUT * 2)()
            for idx, flags in enumerate((KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)):
                arr[idx].type = 1  # INPUT_KEYBOARD
                arr[idx].u.ki = KEYBDINPUT(0, unit, flags, 0, 0)
            send_input(2, arr, ctypes.sizeof(INPUT))
            time.sleep(0.003)
        time.sleep(0.008)
    return True


def wait_foreground_ready(timeout: float = 4.0) -> bool:
    """Waits until the foreground window has finished starting up and stops changing.

    Typing into a window that is still loading (e.g. right after "open notepad") drops
    or garbles keys, so callers wait for: the process to be idle for input, and the same
    foreground window + title for ~0.4 s.
    """
    if not IS_WINDOWS:
        time.sleep(0.3)
        return True
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    deadline = time.time() + timeout

    def snapshot():
        hwnd = u32.GetForegroundWindow()
        n = u32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        return hwnd, buf.value

    hwnd, _ = snapshot()
    if hwnd:
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = k32.OpenProcess(0x0400 | 0x1000, False, pid.value)  # QUERY_INFORMATION | QUERY_LIMITED
        if handle:
            try:
                u32.WaitForInputIdle(handle, int(max(0.1, deadline - time.time()) * 1000))
            finally:
                k32.CloseHandle(handle)
    stable_since, last = time.time(), snapshot()
    while time.time() < deadline:
        time.sleep(0.1)
        cur = snapshot()
        if cur != last:
            last, stable_since = cur, time.time()
        elif time.time() - stable_since >= 0.4 and cur[0]:
            return True
    return False


def _foreground_hwnd():
    import ctypes
    return ctypes.windll.user32.GetForegroundWindow()


def _visible_window_handles() -> set:
    return {h for h, _ in list_windows()}


def wait_for_new_window(before_windows: set, before_fg, timeout: float = 8.0) -> bool:
    """After launching something, waits until a new window appears or the foreground changes,
    then until it is ready for input. Returns False if nothing happened within `timeout`."""
    if not IS_WINDOWS:
        time.sleep(1.0)
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        fg = _foreground_hwnd()
        if (fg and fg != before_fg) or (_visible_window_handles() - before_windows):
            wait_foreground_ready(timeout=max(0.5, deadline - time.time()))
            return True
        time.sleep(0.15)
    return False


def type_text(text: str) -> bool:
    """Types text into the focused window (waits for it to be ready first).
    Stops if another window takes focus while typing, so text never lands in the wrong window.
    Long text is pasted via the clipboard (the previous clipboard is restored)."""
    if not text:
        return True
    if IS_WINDOWS:
        try:
            wait_foreground_ready()
            if len(text) > 200:
                old = get_clipboard()
                if set_clipboard(text):
                    time.sleep(0.1)
                    ok = press_hotkey("ctrl+v")
                    time.sleep(0.3)
                    if old is not None:
                        set_clipboard(old)
                    return ok
            return _send_unicode_text(text)
        except Exception as e:
            print(f"[GUI] type_text error: {e}")
            return False
    if IS_MAC:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        script = 'tell application "System Events" to keystroke "' + escaped + '"'
        return run_command("osascript -e " + shlex.quote(script))["exit_code"] == 0
    if IS_LINUX and shutil.which("xdotool"):
        return run_command(f"xdotool type --delay 5 -- {shlex.quote(text)}")["exit_code"] == 0
    return False


# ----------------------------------------------------------------------
# Windows: window management
# ----------------------------------------------------------------------
def list_windows() -> list:
    """Returns [(hwnd, title)] of visible top-level windows with a title."""
    result = []
    if IS_WINDOWS:
        try:
            import ctypes
            u32 = ctypes.windll.user32

            def enum_proc(hwnd, lparam):
                if u32.IsWindowVisible(hwnd):
                    length = u32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        u32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value.strip()
                        if title and title not in ("Program Manager",):
                            result.append((hwnd, title))
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            u32.EnumWindows(WNDENUMPROC(enum_proc), 0)
        except Exception as e:
            print(f"[GUI] list_windows error: {e}")
    elif IS_LINUX and shutil.which("wmctrl"):
        for line in run_command("wmctrl -l")["stdout"].splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4:
                result.append((parts[0], parts[3]))
    elif IS_MAC:
        out = run_command("osascript -e 'tell application \"System Events\" to get name of every process whose visible is true'")["stdout"]
        result = [(None, n.strip()) for n in out.split(",") if n.strip()]
    return result


def _find_window(title_query: str):
    q = title_query.lower().strip()
    if not q:
        return None
    for hwnd, title in list_windows():
        if q in title.lower():
            return hwnd
    return None


def force_foreground(hwnd, maximize: bool = False) -> bool:
    """Brings a window to the front, bypassing the Windows foreground lock."""
    import ctypes
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    fore = u32.GetForegroundWindow()
    tid_fore = u32.GetWindowThreadProcessId(fore, None)
    tid_cur = k32.GetCurrentThreadId()

    u32.AllowSetForegroundWindow(0x0000FFFF)
    attached = bool(u32.AttachThreadInput(tid_cur, tid_fore, True)) if tid_fore and tid_fore != tid_cur else False
    try:
        if maximize:
            u32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        elif u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        u32.BringWindowToTop(hwnd)
        u32.SetForegroundWindow(hwnd)
        if u32.GetForegroundWindow() != hwnd:
            # Foreground lock: a synthetic key press lets us take focus. F24 is used instead of
            # Alt because an Alt tap turns on "access key" mode in many apps (Windows 11 Notepad,
            # Office...), which then swallows the first characters we type.
            u32.keybd_event(0x87, 0, 0, 0)
            u32.keybd_event(0x87, 0, 2, 0)
            u32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            u32.AttachThreadInput(tid_cur, tid_fore, False)
    return u32.GetForegroundWindow() == hwnd


def focus_window(title_query: str) -> bool:
    """Finds a window by title (case-insensitive substring) and brings it to the front."""
    if IS_WINDOWS:
        try:
            hwnd = _find_window(title_query)
            if hwnd:
                force_foreground(hwnd)
                wait_foreground_ready(timeout=2.0)
                return True
        except Exception as e:
            print(f"[GUI] focus_window error: {e}")
        return False
    if IS_MAC:
        q = title_query.replace('"', "")
        script = f'tell application "System Events" to set frontmost of first process whose name contains "{q}" to true'
        return run_command(f"osascript -e {shlex.quote(script)}")["exit_code"] == 0
    if IS_LINUX and shutil.which("wmctrl"):
        return run_command(f"wmctrl -a {shlex.quote(title_query)}")["exit_code"] == 0
    return False


def focus_and_maximize_window(query: str = "edge") -> bool:
    """Finds window matching query, restores & maximizes it, and brings to foreground."""
    if IS_WINDOWS:
        try:
            hwnd = _find_window(query)
            if hwnd:
                force_foreground(hwnd, maximize=True)
                time.sleep(0.5)
                return True
        except Exception as e:
            print(f"[GUI] focus_and_maximize error: {e}")
        return False
    return focus_window(query)


# ----------------------------------------------------------------------
# Clipboard
# ----------------------------------------------------------------------
def set_clipboard(text: str) -> bool:
    if IS_WINDOWS:
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            u32 = ctypes.windll.user32
            k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            k32.GlobalAlloc.restype = ctypes.c_void_p
            k32.GlobalLock.argtypes = [ctypes.c_void_p]
            k32.GlobalLock.restype = ctypes.c_void_p
            k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

            for _ in range(5):
                if u32.OpenClipboard(0):
                    break
                time.sleep(0.05)
            else:
                return False
            try:
                u32.EmptyClipboard()
                data = (text + "\0").encode("utf-16le")
                h = k32.GlobalAlloc(0x0042, len(data))
                if h:
                    p = k32.GlobalLock(h)
                    ctypes.memmove(p, data, len(data))
                    k32.GlobalUnlock(h)
                    u32.SetClipboardData(13, h)  # CF_UNICODETEXT
            finally:
                u32.CloseClipboard()
            return True
        except Exception as e:
            print(f"[Clipboard] Error: {e}")
            return False
    if IS_MAC:
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(input=text.encode("utf-8"))
        return p.returncode == 0
    if IS_LINUX:
        for tool in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"], ["wl-copy"]):
            if shutil.which(tool[0]):
                p = subprocess.Popen(tool, stdin=subprocess.PIPE)
                p.communicate(input=text.encode("utf-8"))
                return p.returncode == 0
    return False


def get_clipboard() -> Optional[str]:
    if IS_WINDOWS:
        res = run_command("Get-Clipboard -Raw", timeout=10)
        return res["stdout"] if res["exit_code"] == 0 else None
    if IS_MAC:
        return run_command("pbpaste")["stdout"]
    if IS_LINUX:
        for cmd in ("xclip -selection clipboard -o", "xsel --clipboard --output", "wl-paste"):
            if shutil.which(cmd.split()[0]):
                return run_command(cmd)["stdout"]
    return None


def media_key(action: str) -> bool:
    """volume up/down/mute, media play/next/prev."""
    mapping = {"up": "volumeup", "down": "volumedown", "mute": "mute", "unmute": "mute",
               "play": "playpause", "pause": "playpause", "playpause": "playpause",
               "next": "nexttrack", "prev": "prevtrack", "previous": "prevtrack", "stop": "stop"}
    key = mapping.get(action.lower().strip())
    if not key:
        return False
    if IS_WINDOWS:
        return press_key(key)
    if IS_MAC and key in ("volumeup", "volumedown", "mute"):
        script = {"volumeup": "set volume output volume ((output volume of (get volume settings)) + 10)",
                  "volumedown": "set volume output volume ((output volume of (get volume settings)) - 10)",
                  "mute": "set volume output muted not (output muted of (get volume settings))"}[key]
        return run_command(f"osascript -e {shlex.quote(script)}")["exit_code"] == 0
    if IS_LINUX and shutil.which("xdotool"):
        xkey = {"volumeup": "XF86AudioRaiseVolume", "volumedown": "XF86AudioLowerVolume", "mute": "XF86AudioMute",
                "playpause": "XF86AudioPlay", "nexttrack": "XF86AudioNext", "prevtrack": "XF86AudioPrev",
                "stop": "XF86AudioStop"}[key]
        return run_command(f"xdotool key {xkey}")["exit_code"] == 0
    return False


# ----------------------------------------------------------------------
# Remote-desktop helpers: cursor, annotated screenshots, file-picker upload
# ----------------------------------------------------------------------
def get_cursor_pos() -> Optional[tuple]:
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            p = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
            return p.x, p.y
        except Exception:
            return None
    if IS_LINUX and shutil.which("xdotool"):
        m = re.search(r"x:(\d+) y:(\d+)", run_command("xdotool getmouselocation")["stdout"])
        return (int(m.group(1)), int(m.group(2))) if m else None
    return None


def screenshot_annotated(output_path: Path, grid: bool = False, grid_step: int = 100) -> bool:
    """Screenshot with the mouse cursor marked (red crosshair) and, optionally, a labelled
    coordinate grid in real screen pixels - so you can pick x/y for /click from your phone."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import ImageDraw, ImageGrab
        attach_to_input_desktop()
        ensure_dpi_aware()
        left, top, _, _ = get_virtual_screen()
        try:
            img = ImageGrab.grab(all_screens=True)
        except TypeError:
            img, left, top = ImageGrab.grab(), 0, 0
        img = img.convert("RGB")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        if grid:
            step = max(25, int(grid_step))
            first_x = ((left + step - 1) // step) * step
            first_y = ((top + step - 1) // step) * step
            # x labels along the top and middle rows, y labels along the left and middle columns
            for sx in range(first_x, left + w, step):
                x = sx - left
                major = sx % (step * 5) == 0
                draw.line([(x, 0), (x, h)], fill=(255, 0, 255) if major else (0, 200, 255), width=1)
                for ly in (2, h // 2):
                    draw.rectangle([x + 2, ly, x + 42, ly + 13], fill=(0, 0, 0))
                    draw.text((x + 4, ly + 1), f"x{sx}", fill=(255, 255, 0))
            for sy in range(first_y, top + h, step):
                y = sy - top
                major = sy % (step * 5) == 0
                draw.line([(0, y), (w, y)], fill=(255, 0, 255) if major else (0, 200, 255), width=1)
                for lx in (2, w // 2 + 46):
                    draw.rectangle([lx, y + 2, lx + 42, y + 15], fill=(0, 0, 0))
                    draw.text((lx + 2, y + 3), f"y{sy}", fill=(0, 255, 0))
        pos = get_cursor_pos()
        if pos:
            cx, cy = pos[0] - left, pos[1] - top
            r = 18
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 0, 0), width=3)
            draw.line([(cx - r - 8, cy), (cx + r + 8, cy)], fill=(255, 0, 0), width=2)
            draw.line([(cx, cy - r - 8), (cx, cy + r + 8)], fill=(255, 0, 0), width=2)
            draw.rectangle([cx + r + 4, cy - 9, cx + r + 100, cy + 9], fill=(255, 0, 0))
            draw.text((cx + r + 8, cy - 7), f"{pos[0]},{pos[1]}", fill=(255, 255, 255))
        img.save(str(output_path), "JPEG", quality=85)
        return True
    except Exception as e:
        print(f"[GUI] screenshot_annotated error: {e}")
        return take_screenshot(output_path)


_FILE_DIALOG_TITLES = ("open", "file upload", "choose file", "select file", "upload", "browse",
                       "kholo", "choose files", "select files", "insert", "attach")


def _is_file_dialog(hwnd, title: str) -> bool:
    import ctypes
    buf = ctypes.create_unicode_buffer(64)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 64)
    t = title.lower()
    return buf.value == "#32770" and any(k in t for k in _FILE_DIALOG_TITLES)


def find_file_dialog():
    """Returns (hwnd, title) of an open Windows file picker (Open / File Upload), or None."""
    if not IS_WINDOWS:
        return None
    import ctypes
    fg = ctypes.windll.user32.GetForegroundWindow()
    windows = list_windows()
    for hwnd, title in windows:  # prefer the foreground dialog
        if hwnd == fg and _is_file_dialog(hwnd, title):
            return hwnd, title
    for hwnd, title in windows:
        if _is_file_dialog(hwnd, title):
            return hwnd, title
    return None


def upload_file_dialog(path: str, wait_sec: float = 8.0) -> dict:
    """Fills an open browser/app file picker with `path` and confirms it.

    Use after clicking a website's "Upload" / "Choose file" button. Works for the standard
    Windows Open dialog used by Edge, Chrome, Firefox and most apps.
    """
    p = Path(os.path.expandvars(os.path.expanduser(path.strip().strip('"'))))
    if not p.is_file():
        found = find_file(path)
        if not found:
            return _err(f"File '{path}' not found.")
        p = found
    if not IS_WINDOWS:
        return _err("Filling file pickers is only supported on Windows.")
    deadline = time.time() + wait_sec
    dialog = find_file_dialog()
    while not dialog and time.time() < deadline:
        time.sleep(0.25)
        dialog = find_file_dialog()
    if not dialog:
        return _err("No file picker is open. Click the website's Upload / Choose file button first.")
    hwnd, title = dialog
    force_foreground(hwnd)
    wait_foreground_ready(timeout=2.0)
    old_clip = get_clipboard()
    with UserInputLock("Upload file"):
        press_hotkey("alt+n")  # focus the "File name" box
        time.sleep(0.25)
        set_clipboard(f'"{p}"')
        time.sleep(0.1)
        press_hotkey("ctrl+a")
        press_hotkey("ctrl+v")
        time.sleep(0.3)
        press_key("enter")
    if old_clip is not None:
        time.sleep(0.3)
        set_clipboard(old_clip)
    closed_by = time.time() + 6
    while time.time() < closed_by:
        if not any(h == hwnd for h, _ in list_windows()):
            return _ok(f"Selected {p.name} in the '{title}' dialog.")
        time.sleep(0.25)
    return _err(f"Typed the path into '{title}' but the dialog is still open (the site may not accept this file type).")


# ----------------------------------------------------------------------
# ChatGPT workflow
# ----------------------------------------------------------------------
def automate_chatgpt(prompt: str, new_chat: bool = True) -> dict:
    """Opens ChatGPT in Microsoft Edge, optionally starts a new chat, pastes the prompt and submits it."""
    if not IS_WINDOWS:
        res = launch_app("chatgpt")
        return {"success": res["exit_code"] == 0, "screenshot": None, "prompt": prompt,
                "note": "Prompt automation is Windows-only; ChatGPT was opened in the browser."}

    # 1. Re-use an open ChatGPT window, otherwise launch Edge directly on chatgpt.com
    if not focus_and_maximize_window("chatgpt"):
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        edge_bin = next((p for p in edge_paths if os.path.exists(p)), "msedge.exe")
        subprocess.Popen(f'cmd.exe /c start "" "{edge_bin}" "https://chatgpt.com"', shell=True)
        time.sleep(4.0)
        if not focus_and_maximize_window("chatgpt"):
            focus_and_maximize_window("edge")
    time.sleep(0.5)

    # 2. New chat (ChatGPT shortcut Ctrl+Shift+O)
    if new_chat:
        press_hotkey("ctrl+shift+o")
        time.sleep(1.5)

    # 3. Focus the prompt box: bottom area (existing chat) then middle area (new chat)
    width, height = get_primary_screen_size()
    target_x = int(width * 0.5)
    with UserInputLock("ChatGPT Automate"):
        mouse_click(target_x, int(height * 0.88))
        time.sleep(0.2)
        mouse_click(target_x, int(height * 0.44))
        time.sleep(0.2)

        # 4. Paste prompt via clipboard and submit
        set_clipboard(prompt)
        time.sleep(0.2)
        press_hotkey("ctrl+v")
        time.sleep(0.5)
        press_key("enter")

    time.sleep(5.0)

    # 5. Capture result screenshot
    out_file = config.SCREENSHOTS_DIR / f"shot_{int(time.time())}.jpg"
    take_screenshot(out_file)

    return {
        "success": True,
        "screenshot": str(out_file) if out_file.exists() else None,
        "prompt": prompt,
    }
