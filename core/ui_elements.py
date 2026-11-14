"""Lists the clickable / typable elements of the active window via Windows UI Automation.

This is the technique used by Microsoft UFO and Windows-MCP: instead of guessing pixel
coordinates from a screenshot, the AI picks an element by number ("click [12] Upload")
and we click the exact centre that Windows reports.

No extra Python packages: a small long-running PowerShell helper (built into Windows)
does the UI Automation queries and answers in JSON over stdin/stdout.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import config

IS_WINDOWS = sys.platform == "win32"

_HELPER_PS1 = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class TgDpi { [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v); }
"@
[void][TgDpi]::SetProcessDpiAwarenessContext([IntPtr](-4))   # per-monitor v2: physical pixels
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$CT = [System.Windows.Automation.ControlType]
$types = @($CT::Button, $CT::SplitButton, $CT::MenuItem, $CT::Edit, $CT::Document, $CT::TabItem, $CT::Hyperlink,
           $CT::ListItem, $CT::ComboBox, $CT::CheckBox, $CT::RadioButton, $CT::TreeItem, $CT::DataItem, $CT::Slider)
$typeConds = [System.Windows.Automation.Condition[]]@($types | ForEach-Object { New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $_) })
$orCond = New-Object System.Windows.Automation.OrCondition(,$typeConds)
$onScreen = New-Object System.Windows.Automation.PropertyCondition($AE::IsOffscreenProperty, $false)
$cond = New-Object System.Windows.Automation.AndCondition($orCond, $onScreen)
$cr = New-Object System.Windows.Automation.CacheRequest
foreach ($p in @($AE::NameProperty, $AE::ControlTypeProperty, $AE::BoundingRectangleProperty, $AE::IsEnabledProperty)) { $cr.Add($p) }
$cr.TreeScope = [System.Windows.Automation.TreeScope]::Element
$cr.AutomationElementMode = [System.Windows.Automation.AutomationElementMode]::None
[Console]::Out.WriteLine('READY')
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $req = $line | ConvertFrom-Json
        $root = $AE::FromHandle([IntPtr][long]$req.hwnd)
        $act = $cr.Activate()
        try { $found = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond) } finally { $act.Dispose() }
        $items = New-Object System.Collections.ArrayList
        foreach ($e in $found) {
            $c = $e.Cached
            $r = $c.BoundingRectangle
            if ($r.IsEmpty -or $r.Width -lt 3 -or $r.Height -lt 3) { continue }
            $t = $c.ControlType.ProgrammaticName.Substring(12)
            $n = [string]$c.Name
            if (-not $n -and @('Edit', 'Document', 'ComboBox') -notcontains $t) { continue }
            if ($n.Length -gt 70) { $n = $n.Substring(0, 70) }
            [void]$items.Add(@{ n = $n; t = $t; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height; e = [bool]$c.IsEnabled })
            if ($items.Count -ge [int]$req.max) { break }
        }
        $out = @{ ok = $true; items = $items; ms = $sw.ElapsedMilliseconds }
    } catch {
        $out = @{ ok = $false; error = $_.Exception.Message; ms = $sw.ElapsedMilliseconds }
    }
    [Console]::Out.WriteLine(($out | ConvertTo-Json -Compress -Depth 4))
}
"""


@dataclass
class UIElement:
    id: int
    name: str
    type: str
    x: int
    y: int
    w: int
    h: int
    enabled: bool = True

    @property
    def center(self) -> tuple:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def label(self) -> str:
        name = self.name or "(no name)"
        return f"[{self.id}] {self.type} \"{name}\"" + ("" if self.enabled else " (disabled)")


class _Helper:
    def __init__(self):
        self.proc = None
        self.lines: "queue.Queue[str]" = queue.Queue()
        self.lock = threading.Lock()
        self.broken_until = 0.0

    def _reader(self, stream):
        for line in iter(stream.readline, ""):
            self.lines.put(line.strip())
        self.lines.put("__EOF__")

    def _start(self) -> bool:
        script = Path(config.TEMP_DIR) / "uia_helper.ps1"
        script.write_text(_HELPER_PS1, encoding="utf-8-sig")
        flags = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags,
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, args=(self.proc.stdout,), daemon=True).start()
        try:
            first = self.lines.get(timeout=20)
        except queue.Empty:
            first = ""
        if first != "READY":
            self._kill()
            return False
        return True

    def _kill(self):
        try:
            if self.proc:
                self.proc.kill()
        except Exception:
            pass
        self.proc = None

    def query(self, hwnd: int, max_items: int, timeout: float) -> Optional[dict]:
        with self.lock:
            if time.time() < self.broken_until:
                return None
            if self.proc is None or self.proc.poll() is not None:
                if not self._start():
                    self.broken_until = time.time() + 60
                    return None
            try:
                self.proc.stdin.write(json.dumps({"hwnd": int(hwnd), "max": max_items}) + "\n")
                self.proc.stdin.flush()
                line = self.lines.get(timeout=timeout)
            except (queue.Empty, OSError, ValueError):
                self._kill()  # stuck on a huge/hung window: restart next time
                return None
            if line == "__EOF__":
                self._kill()
                return None
            try:
                return json.loads(line)
            except Exception:
                return None


_HELPER = _Helper()

# ----------------------------------------------------------------------
# Preferred backend: UI Automation 3 (COM) through the `uiautomation` package.
# Measured against the PowerShell helper above: it sees classic Win32 / WinForms / WPF controls with
# their real types (the helper sees them as untyped "panes", i.e. finds nothing), lists Antigravity
# identically, finds more in Edge, and takes about the same time (tens of ms), with no subprocess.
# ----------------------------------------------------------------------
_UIA3_TYPES = {50000: "Button", 50031: "SplitButton", 50011: "MenuItem", 50004: "Edit", 50030: "Document",
               50019: "TabItem", 50005: "Hyperlink", 50007: "ListItem", 50003: "ComboBox", 50002: "CheckBox",
               50013: "RadioButton", 50024: "TreeItem", 50029: "DataItem", 50015: "Slider"}
_UIA3_STATE = {"mod": None, "disabled_until": 0.0, "cond": None}
_TLS = threading.local()


def _uia3_module():
    if _UIA3_STATE["mod"] is None:
        try:
            import uiautomation as _a
            import uiautomation.uiautomation as _m
            _UIA3_STATE["mod"] = (_a, _m)
        except Exception:
            _UIA3_STATE["mod"] = False
    return _UIA3_STATE["mod"] or None


def _query_uia3(hwnd: int, max_items: int) -> Optional[dict]:
    """Same result shape as the PowerShell helper ({"ok": True, "items": [...]}); None = unavailable/failed."""
    if not IS_WINDOWS or time.time() < _UIA3_STATE["disabled_until"] or os.environ.get("UIA_BACKEND", "").lower() == "powershell":
        return None
    mods = _uia3_module()
    if not mods:
        return None
    _a, _m = mods
    try:
        if not getattr(_TLS, "ready", False):  # COM must be initialised once per thread
            _a.InitializeUIAutomationInCurrentThread()
            _TLS.ready = True
        ui = _m._AutomationClient.instance().IUIAutomation
        if _UIA3_STATE["cond"] is None:
            pid = _a.PropertyId
            typed = None
            for t in _UIA3_TYPES:
                c = ui.CreatePropertyCondition(pid.ControlTypeProperty, t)
                typed = c if typed is None else ui.CreateOrCondition(typed, c)
            _UIA3_STATE["cond"] = ui.CreateAndCondition(typed, ui.CreatePropertyCondition(pid.IsOffscreenProperty, False))
        pid = _a.PropertyId
        cache = ui.CreateCacheRequest()
        for p in (pid.NameProperty, pid.ControlTypeProperty, pid.BoundingRectangleProperty, pid.IsEnabledProperty):
            cache.AddProperty(p)
        root = ui.ElementFromHandle(int(hwnd))
        arr = root.FindAllBuildCache(4, _UIA3_STATE["cond"], cache)  # 4 = TreeScope_Descendants
        items = []
        for i in range(arr.Length):
            e = arr.GetElement(i)
            r = e.CachedBoundingRectangle
            w, h = r.right - r.left, r.bottom - r.top
            name = (e.CachedName or "")
            t = _UIA3_TYPES.get(e.CachedControlType, "")
            if w < 3 or h < 3 or not t or (not name and t not in ("Edit", "Document", "ComboBox")):
                continue
            items.append({"n": name[:70], "t": t, "x": int(r.left), "y": int(r.top), "w": int(w), "h": int(h),
                          "e": bool(e.CachedIsEnabled)})
            if len(items) >= max_items:
                break
        return {"ok": True, "items": items}
    except Exception as e:
        # Window closed mid-query, COM hiccup... try the PowerShell helper this time; give UIA3 a short rest if it keeps failing
        _UIA3_STATE["fails"] = _UIA3_STATE.get("fails", 0) + 1
        if _UIA3_STATE["fails"] >= 5:
            _UIA3_STATE["disabled_until"] = time.time() + 120
            _UIA3_STATE["fails"] = 0
            print(f"[UI] UIA3 listing failing repeatedly ({e}); using the PowerShell helper for 2 min")
        return None


def warm_up() -> bool:
    """Starts the helpers in advance (the PowerShell one takes ~1-2 s to start; it is only a fallback now)."""
    if not IS_WINDOWS:
        return False
    import ctypes
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if _query_uia3(hwnd, 1) is not None:
        return True
    return _HELPER.query(hwnd, 1, 20) is not None


def list_elements(hwnd: int = None, max_items: int = 150, timeout: float = 6.0,
                  screen_bounds: tuple = None) -> List[UIElement]:
    """Returns visible named buttons, fields, links, tabs, menu items... of a window
    (default: the foreground window), numbered from 1, in real screen pixels."""
    if not IS_WINDOWS:
        return []
    import ctypes
    hwnd = hwnd or ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return []
    res = _query_uia3(hwnd, max_items)
    if res is None:  # UIA3 unavailable / failed: PowerShell helper (blind to classic Win32 controls, fine for the rest)
        res = _HELPER.query(hwnd, max_items, timeout)
    if not res or not res.get("ok"):
        return []
    left, top, width, height = screen_bounds or (-100000, -100000, 200000, 200000)
    seen, out = set(), []
    for it in res.get("items") or []:
        x, y, w, h = int(it.get("x", 0)), int(it.get("y", 0)), int(it.get("w", 0)), int(it.get("h", 0))
        cx, cy = x + w // 2, y + h // 2
        if not (left <= cx < left + width and top <= cy < top + height):
            continue  # minimized / off-screen
        key = (it.get("n"), it.get("t"), x, y, w, h)
        if key in seen:
            continue
        seen.add(key)
        out.append(UIElement(len(out) + 1, str(it.get("n") or ""), str(it.get("t") or ""), x, y, w, h, bool(it.get("e", True))))
    return out


def format_for_model(elements: List[UIElement], limit: int = 150) -> str:
    return "\n".join(e.label() for e in elements[:limit])
