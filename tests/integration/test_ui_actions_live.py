"""core/ui_actions end to end: list elements with our helper -> activate / set_text. Own test windows only."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

import sys, time, ctypes, subprocess, os
from ctypes import wintypes
sys.stdout.reconfigure(encoding="utf-8")
from core import ui_actions as ua, ui_elements as ue, os_bridge as ob

S = str(FIXTURES)
u32 = ctypes.windll.user32
PS = ["powershell.exe", "-STA", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(FIXTURES / "uia_form.ps1"), "-Title"]
procs = []
fails = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""), flush=True)
    if not cond: fails.append(name)


def cursor():
    p = wintypes.POINT(); u32.GetCursorPos(ctypes.byref(p)); return (p.x, p.y)


def window(prefix, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        for h, t in ob.list_windows():
            if t.startswith(prefix): return h, t
        time.sleep(0.5)
    return None, ""


def title_of(prefix): return next((t for _, t in ob.list_windows() if t.startswith(prefix)), "")


def el_by(els, type_, name):
    return next((e for e in els if e.type == type_ and e.name == name), None)


try:
    check("library available", ua.available())
    # ================= native window =================
    procs.append(subprocess.Popen(PS + ["UIA TEST FORM"])); time.sleep(5)
    h, t = window("UIA TEST FORM")
    check("native test window found", bool(h))
    els = ue.list_elements(hwnd=h, screen_bounds=ob.get_virtual_screen())
    names = [(e.type, e.name) for e in els]
    check("elements listed by our helper", ("Button", "Go") in names and ("Edit", "Name box") in names, str(names)[:150])
    mouse_calls = []
    stub_mouse = lambda x, y, b, d: mouse_calls.append((x, y)) or True
    cur0 = cursor()

    r = ua.activate(el_by(els, "Button", "Go"), stub_mouse)
    time.sleep(0.4)
    check("native button -> Invoke (no mouse)", r["method"] == "uia-invoke" and "clicks=1" in title_of("UIA TEST FORM") and not mouse_calls, f"{r} | {title_of('UIA TEST FORM')[17:70]}")
    r = ua.activate(el_by(els, "CheckBox", "Agree"), stub_mouse)
    time.sleep(0.4)
    check("native checkbox -> Toggle", r["method"] == "uia-toggle" and "agree=True" in title_of("UIA TEST FORM"), str(r))
    box = el_by(els, "Edit", "Name box")
    r = ua.set_text(box, "typed via UIA", paste=lambda: False)
    time.sleep(0.4)
    check("native text box -> SetValue verified", r == {"method": "uia-value", "ok": True, "verified": True} and "text=typed via UIA" in title_of("UIA TEST FORM"), str(r))
    check("read_value reads the field back", ua.read_value(box) == "typed via UIA", repr(ua.read_value(box)))
    lock = el_by(els, "Edit", "Locked box")
    pasted = []
    r = ua.set_text(lock, "nope", paste=lambda: pasted.append(1) or True)
    check("read-only field is NOT overwritten (falls back, then can't confirm)", r["method"] == "paste" and ua.read_value(lock) == "read only", str(r))
    check("disabled/unknown handling: right-click always uses the mouse", ua.activate(el_by(els, "Button", "Go"), stub_mouse, button="right")["method"] == "mouse")
    check("native actions never moved the mouse", cursor() == cur0 and len(mouse_calls) == 1, f"{cur0}->{cursor()} calls={mouse_calls}")
    check("browser detection: native window is NOT browser-like", not ua.is_browser_like(el_by(els, "Button", "Go")))

    # ================= Edge web page: real mouse + paste =================
    subprocess.Popen(["cmd.exe", "/c", "start", "", "msedge", "--new-window", "file:///" + S.replace("\\", "/") + "/uia_web.html"])
    hw, tw = window("UIA WEB TEST")
    check("Edge test page opened", bool(hw))
    time.sleep(3)
    w_els = ue.list_elements(hwnd=hw, screen_bounds=ob.get_virtual_screen())
    go = el_by(w_els, "Button", "Go web")
    check("web button listed", go is not None, str([(e.type, e.name) for e in w_els])[:150])
    check("Edge window is browser-like", ua.is_browser_like(go))
    real_mouse = lambda x, y, b, d: ob.mouse_click(x, y, button=b, double=d)
    ob.force_foreground(hw); time.sleep(0.5)
    r = ua.activate(go, real_mouse)
    time.sleep(0.8)
    check("web button -> real mouse click", r["method"] == "mouse" and "clicks=1" in title_of("UIA WEB TEST"), f"{r['method']} | {title_of('UIA WEB TEST')[15:60]}")
    field = el_by(w_els, "Edit", "Name field")
    ob.force_foreground(hw)
    r = ua.set_text(field, "pasted into web", paste=lambda: (ob.mouse_click(*field.center), time.sleep(0.2), ob.type_text("pasted into web"))[-1])
    time.sleep(0.8)
    t = title_of("UIA WEB TEST")
    check("web field -> paste, page saw it with input event", r["method"] == "paste" and "name=pasted into web" in t and "input_ev=" in t and "input_ev=0" not in t, f"{r} | {t[15:100]}")
    check("typed text verified by reading the field back", r["verified"] is True, str(r))
    wrong = ua.text_matches(ua.read_value(field), "something completely different")
    check("verification catches wrong text", wrong is False, str(wrong))
    # close the page
    ob.press_hotkey("ctrl+w"); time.sleep(1)

    # ================= file picker needs a REAL click =================
    subprocess.Popen(["cmd.exe", "/c", "start", "", "msedge", "--new-window", "file:///" + S.replace("\\", "/") + "/uia_file.html"])
    hf, _ = window("UIA FILE TEST")
    time.sleep(3)
    f_els = ue.list_elements(hwnd=hf, screen_bounds=ob.get_virtual_screen())
    pick = el_by(f_els, "Button", "Pick file")
    ob.force_foreground(hf); time.sleep(0.5)
    r = ua.activate(pick, real_mouse)
    time.sleep(2.5)
    dlg = ob.find_file_dialog()
    check("file picker opens with the real click (browser path)", r["method"] == "mouse" and dlg is not None, f"{r['method']} dialog={dlg}")
    if dlg:
        ob.force_foreground(dlg[0]); time.sleep(0.3); ob.press_key("esc"); time.sleep(0.8)
    ob.force_foreground(hf); ob.press_hotkey("ctrl+w"); time.sleep(0.8)
finally:
    print("FAILED:", fails if fails else "none", flush=True)
    for p in procs:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/F", "/T"], capture_output=True)
    sys.stdout.flush(); os._exit(1 if fails else 0)
