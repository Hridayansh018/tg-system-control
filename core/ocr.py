"""Find text on screen with the OCR engine built into Windows 10/11 (Windows.Media.Ocr) - nothing to install.

Used as a fallback by the agent action `click_text` when a button or label has no accessible name in the
ELEMENTS list. Runs offline through PowerShell (about 1-2 s per image).
"""
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import config

IS_WINDOWS = sys.platform == "win32"

_PS = r"""
param([string]$Path)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
[void][Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); [void]$t.Wait(-1); $t.Result }
try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) { '{"error":"no OCR language installed"}'; exit 0 }
    $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $words = New-Object System.Collections.ArrayList
    $li = 0
    foreach ($line in $res.Lines) {
        foreach ($w in $line.Words) {
            $r = $w.BoundingRect
            [void]$words.Add(@{ t = $w.Text; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height; l = $li })
        }
        $li++
    }
    @{ words = $words } | ConvertTo-Json -Compress -Depth 4
} catch { @{ error = $_.Exception.Message } | ConvertTo-Json -Compress }
"""


def available() -> bool:
    return IS_WINDOWS


def read_words(image_path: str, timeout: float = 40.0) -> Optional[List[dict]]:
    """[{t: word, x, y, w, h, l: line index}] in image pixels; None if OCR is unavailable / failed."""
    if not IS_WINDOWS:
        return None
    script = Path(config.TEMP_DIR) / "ocr_helper.ps1"
    try:
        script.write_text(_PS, encoding="utf-8-sig")
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-Path", str(Path(image_path).resolve())],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=0x08000000)
        data = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    if data.get("error"):
        return None
    words = data.get("words") or []
    return words if isinstance(words, list) else [words]  # PowerShell collapses a 1-item list


def _norm(s: str) -> str:
    return re.sub(r"[^\w]+", "", s.lower())


def find_text(words: List[dict], query: str) -> List[dict]:
    """Matches of `query` (one or several words) among OCR words on the same line.
    Returns [{"x","y","w","h","text"}] (bounding box of the matched words), best (exact) matches first."""
    q_words = [_norm(w) for w in query.split() if _norm(w)]
    if not q_words or not words:
        return []
    matches = []
    n = len(q_words)
    for i in range(len(words) - n + 1):
        seq = words[i:i + n]
        if len({w["l"] for w in seq}) != 1:
            continue
        got = [_norm(w["t"]) for w in seq]
        exact = got == q_words
        loose = all(g == q or (len(q) >= 4 and (q in g or g in q) and len(g) >= 3) for g, q in zip(got, q_words))
        if not (exact or loose):
            continue
        x0 = min(w["x"] for w in seq); y0 = min(w["y"] for w in seq)
        x1 = max(w["x"] + w["w"] for w in seq); y1 = max(w["y"] + w["h"] for w in seq)
        matches.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "text": " ".join(w["t"] for w in seq), "_exact": exact})
    matches.sort(key=lambda m: (not m["_exact"], m["y"], m["x"]))
    for m in matches:
        m.pop("_exact", None)
    return matches
