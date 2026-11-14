"""Run the test suites:  python tests/run_all.py [--desktop] [name-filter]

  unit/         pure logic with fakes - safe anywhere, never touches your screen
  integration/  fake Telegram + (copied) Video Studio pipeline tools; skipped when the pipeline is missing
  desktop       (only with --desktop) opens real windows / uses OCR; do not touch the PC while they run
  live/         manual harnesses against real services (never run automatically)
Each script exits 0 on success; a script printing 'FAILED: <names>' (other than 'none') counts as a failure.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESKTOP = {"test_ocr.py", "test_ui_actions_live.py"}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    with_desktop = "--desktop" in sys.argv
    files = sorted((HERE / "unit").glob("test_*.py")) + sorted((HERE / "integration").glob("test_*.py"))
    results = []
    for f in files:
        if args and not any(a in f.name for a in args):
            continue
        if f.name in DESKTOP and not with_desktop:
            results.append((f.name, "SKIP", "desktop test (use --desktop)", 0))
            continue
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, "-u", str(f)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=900)
            out = (p.stdout or "") + (p.stderr or "")
            failed = re.findall(r"^FAILED:\s*(.+)$", out, re.M)
            bad = [x for x in failed if x.strip().lower() != "none"]
            if "SKIPPED:" in out and p.returncode == 0:
                status, note = "SKIP", out.split("SKIPPED:")[1].splitlines()[0].strip()
            elif p.returncode != 0 or bad:
                status, note = "FAIL", (bad[0] if bad else out.strip().splitlines()[-1][:120])
            else:
                status, note = "PASS", ""
        except subprocess.TimeoutExpired:
            status, note = "FAIL", "timeout"
        results.append((f.name, status, note, time.time() - t0))
    print()
    for name, status, note, secs in results:
        print(f"{status:5} {name:28} {secs:5.1f}s  {note}")
    n_fail = sum(1 for r in results if r[1] == "FAIL")
    print(f"\n{sum(r[1] == 'PASS' for r in results)} passed, {n_fail} failed, {sum(r[1] == 'SKIP' for r in results)} skipped")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
