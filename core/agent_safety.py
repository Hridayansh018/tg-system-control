"""Safety rules for the computer-use agent: what needs the user's approval and what is never allowed.

Approval cards are shown in Telegram before risky steps. Hard blocks (typing card numbers,
one-time codes or passwords) are never executed - the agent must ask the user instead.
"""
import re
from pathlib import Path
from typing import Optional

import config

# PowerShell cmdlet verbs that only read
_SAFE_PS_VERBS = {"get", "select", "where", "sort", "measure", "format", "test", "resolve", "split",
                  "join", "convertto", "group", "compare", "find"}
_SAFE_PS_CMDLETS = {"out-string", "write-output", "write-host"}
# Plain commands that only read (PowerShell aliases and POSIX tools)
_SAFE_PLAIN = {"dir", "ls", "cat", "type", "pwd", "whoami", "hostname", "echo", "findstr", "where", "tree",
               "head", "tail", "wc", "du", "df", "grep", "uname", "ps", "stat", "file", "date", "uptime",
               "gci", "gc", "gps", "sls", "measure", "select", "sort", "ft", "fl", "?", "%", "foreach"}
_DANGEROUS_SHELL = re.compile(
    r"(`|\$\(|>|::|\.\w+\s*\(|\binvoke-|\biex\b|\bstart-process\b|\s-exec\b|\s-delete\b|\s-command\b"
    r"|\s-encodedcommand\b|\bsudo\b|\brm\b|\bdel\b|\berase\b|\brmdir\b|\brd\b|\bmv\b|\bmove\b|\bcp\b|\bcopy\b"
    r"|\bren\b|\bkill\b|\bshutdown\b|\bformat\b(?!-)|\bcurl\b|\bwget\b|\bnet\b|\breg\b|\bsc\b|\bschtasks\b)",
    re.IGNORECASE,
)


def shell_is_read_only(command: str) -> bool:
    """True only for commands we are confident just read information."""
    cmd = (command or "").strip()
    if not cmd or _DANGEROUS_SHELL.search(cmd):
        return False
    # ForEach/Where script blocks can run anything: every cmdlet inside must be safe too.
    for verb_noun in re.findall(r"\b([A-Za-z]+)-([A-Za-z]+)\b", cmd):
        name = f"{verb_noun[0]}-{verb_noun[1]}".lower()
        if name in _SAFE_PS_CMDLETS:
            continue
        if verb_noun[0].lower() not in _SAFE_PS_VERBS:
            return False
    for segment in re.split(r"\|\||&&|[|;\n]", cmd):
        segment = segment.strip().lstrip("({").strip()
        if not segment:
            continue
        first = segment.split()[0].lower()
        if "-" in first:
            verb = first.split("-", 1)[0]
            if first not in _SAFE_PS_CMDLETS and verb not in _SAFE_PS_VERBS:
                return False
        elif first.startswith("$") or first.startswith("[") or first.startswith("'") or first.startswith('"'):
            continue  # variables / literals in an expression
        elif first not in _SAFE_PLAIN:
            return False
    return True


_SENSITIVE_PATH = re.compile(
    r"(\.env$|\.ssh|id_rsa|id_ed25519|\.pem$|\.key$|\.pfx$|password|passwd|credential|secret|token|wallet"
    r"|cookies|login data|\.kdbx$|keychain|memory\.md$)",
    re.IGNORECASE,
)


def user_folders() -> list:
    home = Path.home()
    return [home / "Downloads", home / "Desktop", home / "Documents", home / "Pictures", home / "Videos",
            home / "Music", home / "OneDrive" / "Desktop", home / "OneDrive" / "Documents",
            config.SCREENSHOTS_DIR, config.INBOX_DIR]


def path_needs_approval(path: str) -> Optional[str]:
    try:
        p = Path(path).expanduser().resolve()
    except Exception:
        return "Path could not be resolved"
    if _SENSITIVE_PATH.search(str(p)):
        return f"'{p.name}' may contain passwords or keys"
    for folder in user_folders():
        try:
            p.relative_to(folder.resolve())
            return None
        except Exception:
            continue
    return f"'{p}' is outside your personal folders"


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def blocked_text_reason(text: str, thought: str = "") -> Optional[str]:
    """Hard block: the agent must never type payment cards, OTPs or passwords."""
    t = text or ""
    digits = re.sub(r"[\s-]", "", t)
    if re.fullmatch(r"\d{13,19}", digits) and _luhn_ok(digits):
        return "looks like a payment card number"
    if re.fullmatch(r"\d{4,8}", t.strip()) and re.search(r"\b(otp|one[- ]time|verification code|2fa|pin)\b", thought, re.IGNORECASE):
        return "looks like a one-time code / PIN"
    if re.search(r"\b(password|passcode|passwd|pin code|cvv|cvc)\b", thought, re.IGNORECASE):
        return "the agent was about to type a password / security code"
    return None


_RISKY_WORDS = re.compile(
    r"\b(send|submit|post|publish|tweet|reply all|buy|pay|purchase|order|checkout|place order|transfer|"
    r"delete|remove|uninstall|install|format|erase|confirm|accept terms|sign up|subscribe|unsubscribe|"
    r"empty trash|empty recycle|wipe|reset|shut ?down|restart|log ?out|sign out)\b",
    re.IGNORECASE,
)


def approval_reason(action: dict) -> Optional[str]:
    """Returns why this step needs the user's approval, or None if it can run directly."""
    act = action["action"]
    if action.get("risky"):
        return action.get("risk_reason") or "The agent marked this step as risky"
    if act == "run_shell":
        if not shell_is_read_only(action.get("command", "")):
            return "Runs a shell command that can change your system"
        return None
    if act == "close_app":
        return "Closing an app can lose unsaved work"
    if act == "hotkey" and action.get("key", "").lower().replace(" ", "") in {"alt+f4", "ctrl+shift+delete", "ctrl+alt+delete"}:
        return "This shortcut can close windows or lose work"
    if act in ("send_file_to_user", "read_file", "list_dir", "upload_file"):
        return path_needs_approval(action.get("path", ""))
    if act in ("click", "double_click", "press_key", "type_text"):
        text = " ".join(str(action.get(k, "")) for k in ("thought", "text", "key"))
        if act == "press_key" and action.get("key", "").lower() not in ("enter", "return"):
            return None
        m = _RISKY_WORDS.search(text)
        if m:
            return f"Step looks like it will '{m.group(0)}' something"
    return None
