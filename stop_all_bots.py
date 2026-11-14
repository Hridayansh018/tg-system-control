"""Stops the Video Studio bot cleanly (it posts its own 🔴 OFFLINE notice). Called by stop_all_bots.bat,
which then stops TG-System-Control itself with stop_agent.bat (also clean)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core import studio_control  # noqa: E402

print("Video Studio bot:", studio_control.stop()["msg"])
