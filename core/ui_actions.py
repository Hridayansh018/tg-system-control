"""Acting on UI controls the way that was PROVEN to work (see the prototype results in README -> v2.8).

Native Windows apps (Win32 / WinForms / WPF / UWP):
    click   -> Invoke / Toggle / SelectionItem pattern: no mouse movement, ~1-25 ms, exact control.
    type    -> ValuePattern.SetValue on plain text boxes, read back to confirm; else click + paste.
Browser and Electron windows (Edge, Chrome, Firefox, Antigravity ...): ALWAYS real mouse clicks and Ctrl+V.
    Tested: an invoked click does NOT open a file picker (browsers need a real user action), a rich text
    box (ChatGPT style) shows set text but never gets the 'input' event, and Antigravity ignores SetValue.

Everything falls back to the mouse when the `uiautomation` package is missing, the control can't be found
under the element's position, or a pattern isn't offered. After typing, the field is read back when possible
so a failed paste is reported instead of silently believed.
"""
import ctypes
import re
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

from . import os_bridge

try:
    import uiautomation as _auto
except Exception:  # not installed / not Windows
    _auto = None

BROWSER_LIKE_CLASSES = {"chrome_widgetwin_0", "chrome_widgetwin_1", "mozillawindowclass", "mozillauiwindowclass"}
_TLS = threading.local()


def available() -> bool:
    return _auto is not None and os_bridge.IS_WINDOWS


def _init_thread():
    """uiautomation needs COM initialised once in every thread that uses it."""
    if getattr(_TLS, "ready", False):
        return
    try:
        _auto.InitializeUIAutomationInCurrentThread()
    except Exception:
        pass
    _TLS.ready = True


def _root_window_class(x: int, y: int) -> str:
    """Window class of the top-level window under a screen point ('' if unknown)."""
    try:
        u32 = ctypes.windll.user32
        u32.WindowFromPoint.argtypes = [wintypes.POINT]
        u32.WindowFromPoint.restype = wintypes.HWND
        u32.GetAncestor.restype = wintypes.HWND
        h = u32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        root = u32.GetAncestor(h, 2) or h  # GA_ROOT
        buf = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(root, buf, 256)
        return buf.value.lower()
    except Exception:
        return ""


def is_browser_like(el) -> bool:
    cx, cy = el.center
    return _root_window_class(cx, cy) in BROWSER_LIKE_CLASSES


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def find_control(el):
    """The live UI Automation control at the element's position whose name matches (None if not sure)."""
    if not available():
        return None
    _init_thread()
    try:
        cx, cy = el.center
        ctrl = _auto.ControlFromPoint(cx, cy)
        if ctrl is None:
            return None
        want = _norm(el.name)
        chain, cur = [ctrl], ctrl
        for _ in range(4):
            cur = cur.GetParentControl()
            if cur is None:
                break
            chain.append(cur)
        if not want:
            return ctrl if ctrl.ControlTypeName.replace("Control", "") == el.type else None
        for c in chain:
            n = _norm(c.Name)
            if n and (n == want or n.startswith(want) or want.startswith(n)):
                return c
    except Exception:
        pass
    return None


def _pattern(ctrl, name: str):
    try:
        return ctrl.GetPattern(getattr(_auto.PatternId, name))
    except Exception:
        return None


# ----------------------------------------------------------------------
# Click
# ----------------------------------------------------------------------
def activate(el, mouse_click: Callable[[int, int, str, bool], bool], button: str = "left", double: bool = False) -> dict:
    """Click an element. Returns {"method": "uia-invoke"|"uia-toggle"|"uia-select"|"mouse", "ok": bool}."""
    cx, cy = el.center

    def by_mouse(note: str = "") -> dict:
        ok = mouse_click(cx, cy, button, double)
        return {"method": "mouse", "ok": bool(ok), "note": note}

    if button != "left" or double or not available() or not el.enabled:
        return by_mouse()
    if is_browser_like(el):
        return by_mouse("browser/Electron window: real click (needed for user activation)")
    ctrl = find_control(el)
    if ctrl is None:
        return by_mouse("control not found under the element")
    try:
        tp = _pattern(ctrl, "TogglePattern")
        if tp:
            tp.Toggle(waitTime=0)
            return {"method": "uia-toggle", "ok": True}
        ip = _pattern(ctrl, "InvokePattern")
        if ip:
            ip.Invoke(waitTime=0)
            return {"method": "uia-invoke", "ok": True}
        sp = _pattern(ctrl, "SelectionItemPattern")
        if sp:
            sp.Select(waitTime=0)
            return {"method": "uia-select", "ok": True}
    except Exception:
        pass
    return by_mouse("no usable pattern")


# ----------------------------------------------------------------------
# Text
# ----------------------------------------------------------------------
def read_value(el) -> Optional[str]:
    """Current text of a field (None when it can't be read)."""
    ctrl = find_control(el)
    if ctrl is None:
        return None
    try:
        vp = _pattern(ctrl, "ValuePattern")
        if vp:
            return vp.Value or ""
        tp = _pattern(ctrl, "TextPattern")
        if tp:
            return tp.DocumentRange.GetText(20000) or ""
    except Exception:
        pass
    return None


def text_matches(actual: Optional[str], expected: str) -> Optional[bool]:
    """True / False / None (= couldn't tell) for 'did the field get this text?'."""
    if actual is None:
        return None
    a, e = _norm(actual), _norm(expected)
    if not a:
        return False if e else True
    probe = e[:80]
    return probe in a and (len(a) >= min(len(e), 40))


def set_text(el, text: str, paste: Callable[[], bool]) -> dict:
    """Put text into a field. paste() does the mouse path (click the field + Ctrl+V).
    Returns {"method": "uia-value"|"paste", "ok": bool, "verified": True|False|None}."""
    if (available() and el.type == "Edit" and el.enabled and not is_browser_like(el)):
        ctrl = find_control(el)
        vp = _pattern(ctrl, "ValuePattern") if ctrl is not None else None
        try:
            if vp and not vp.IsReadOnly:
                vp.SetValue(text, waitTime=0)
                time.sleep(0.05)
                if (vp.Value or "") == text:
                    return {"method": "uia-value", "ok": True, "verified": True}
        except Exception:
            pass
    ok = paste()
    verified = None
    if ok and available():
        time.sleep(0.25)
        verified = text_matches(read_value(el), text)
    return {"method": "paste", "ok": bool(ok), "verified": verified}
