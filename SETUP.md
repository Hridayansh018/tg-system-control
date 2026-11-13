# 🛠️ TG-System-Control: Setup & Installation Guide

Step-by-step instructions for humans and AI coding agents (Antigravity, Claude Code, Cursor, Windsurf) to install, configure, verify, run, update and uninstall **TG-System-Control** on Windows, macOS or Linux.

---

## 📌 For AI agents (quick automation instruction)

If you are an AI agent asked to set up this project:
```text
Please read the SETUP.md file, set up this project on my computer with Bot Token: <YOUR_BOT_TOKEN> and Chat ID: <YOUR_CHAT_ID>, and configure the AI engine to be powered by <"specify model: e.g., gemini / claude / openrouter / offline">.
```
1. Verify Python is `>= 3.10`.
2. Create a virtual environment in the project folder (`python -m venv .venv`) and run `pip install -r requirements.txt` inside it. The launchers use `.venv` automatically.
3. Copy `.env.example` to `.env` and set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from the prompt. Never commit `.env` and never write the token into any other file.
4. Configure the AI engine:
   - `gemini` → `LLM_PROVIDER=gemini` + `GEMINI_API_KEY`
   - `claude` → `LLM_PROVIDER=openrouter` + `OPENROUTER_API_KEY` + `OPENROUTER_MODEL=anthropic/claude-3.5-sonnet` (or a newer Claude model on OpenRouter)
   - `openrouter` → `LLM_PROVIDER=openrouter` + key (+ optional model)
   - `offline` → `LLM_PROVIDER=offline`
   Ask the user for the API key; don't invent one.
5. Optional (Windows): install the Nous Research Hermes desktop app with `install_hermes_app.bat` (see section 4).
6. Run `python setup_check.py`; every line must be `✅ PASS`.
7. Start the bot (section 7) and, if the user wants, enable autostart (section 8).

---

## 📱 Create your Telegram bot & find your chat ID

### Step 1: Create the bot via @BotFather
1. In Telegram, open **[@BotFather](https://t.me/BotFather)** and send `/newbot`.
2. Give it a display name (e.g. `My Desktop Controller`) and a unique username ending in `bot` (e.g. `my_studio_pc_bot`).
3. Copy the HTTP API token (format `1234567890:ABCdef…`). **Keep it secret** — anyone with it can read what you send to the bot.
4. Open your new bot and press **Start** once.

### Step 2: Get your personal chat ID
1. Open **[@userinfobot](https://t.me/userinfobot)** and send `/start`.
2. Copy your numerical **Id**. Only this ID will be allowed to control the PC.

---

## ⚡ Startup sequence

When the bot starts (manually or on boot):
1. **Single-instance check** — only one copy per bot token may run on the machine (prevents duplicate replies).
2. **Lifecycle hooks** — Ctrl+C, stop requests, SIGTERM/SIGBREAK, console close and Windows shutdown/logoff all send one 🔴 OFFLINE message.
3. **Warm-up** — packages, app catalog (`temp/apps_cache.json`), screenshot engine, input-lock availability and Telegram latency are checked.
4. **🟢 SYSTEM ONLINE** is sent only after everything above is ready.

---

## 💻 1. Requirements

- **Python** 3.10 or newer, **Git**, internet access to `api.telegram.org` (and your AI provider if used).

| Package | Why | Version |
|---|---|---|
| `requests` | Telegram and AI HTTP calls | `>= 2.28.0` |
| `Pillow` | Screenshots and image handling | `>= 9.0.0` |
| `psutil` *(optional)* | More precise RAM numbers. Without it the bot uses CIM (Windows), `vm_stat` (macOS) or `/proc/meminfo` (Linux). | `>= 5.9.0` |

Optional tools on Linux: `xdotool` (typing/clicks/keys), `wmctrl` (focus windows), `xclip`/`xsel`/`wl-copy` (clipboard), `gnome-screenshot`/`scrot`/`grim` (screenshot fallback). On macOS, grant Terminal/Python **Accessibility** and **Screen Recording** permissions; `cliclick` enables mouse clicks.

---

## 🚀 2. Installation

### Windows (PowerShell)
```powershell
git clone https://github.com/your-username/tg-system-control.git
cd tg-system-control
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### macOS / Linux
```bash
git clone https://github.com/your-username/tg-system-control.git
cd tg-system-control
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## ⚙️ 3. Configuration (`.env`)

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Token from @BotFather |
| `TELEGRAM_CHAT_ID` | ✅ | — | Your numeric ID; the bot refuses to start without it |
| `LLM_PROVIDER` | | `offline` | `gemini`, `openrouter`, `groq`, `offline` |
| `GEMINI_API_KEY` | for gemini | — | [Google AI Studio](https://aistudio.google.com/app/apikey) key (free tier has daily limits) |
| `GEMINI_MODEL` | | built-in list | Comma-separated Gemini models to try first |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | for openrouter | — / `nousresearch/hermes-3-llama-3.1-70b` | Any OpenRouter model (Hermes, Claude, …) |
| `GROQ_API_KEY` | for groq | — | Uses `llama-3.3-70b-versatile` |
| `HERMES_APP_PATH` | | `D:\git-data\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe` | Used by `open hermes` |

**How the AI is used:** exact commands (`open edge`, `screenshot`, `/exec …`) never touch the AI. Other messages are sent to the provider, which may only translate them into commands from a fixed menu. If the provider's key is empty, the bot runs in offline mode.

Example (Gemini):
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_key
```

---

## 🦅 4. Optional: Nous Research Hermes desktop app (Windows)

`install_hermes_app.bat`:
1. Clones `https://github.com/nousresearch/hermes-agent` (default `D:\git-data\hermes-agent`, or next to this project if `D:\git-data` doesn't exist).
2. Runs `setup-hermes.ps1 -RuntimeOnly`.
3. Builds the desktop app (`hermes desktop --build-only`).
4. Creates a `Hermes Agent.lnk` desktop shortcut.

If you install it somewhere else, set `HERMES_APP_PATH` in `.env` so `open hermes` works.

---

## 🔍 5. Verify

```bash
python setup_check.py
```
It checks: OS, Python version, `requests`/`Pillow` (+ optional `psutil`), `.env` token and chat ID (**placeholders fail**), AI translator status, `memory.md` is git-ignored, metrics, shell, screenshot, and that the token works (`getMe`, no message is sent). Exit code is non-zero if anything required fails.

---

## 🧠 6. Activity log (`memory.md`)

Created automatically in the project folder:
1. **Append-only** — every command, translator result, lifecycle event (online, offline, warm-up), network drop/restore and rejected access attempt is appended with a timestamp.
2. **Never truncated** by the bot.
3. **Git-ignored** — it stays on your PC.

---

## 🏃 7. Run & stop

| | Windows | macOS / Linux |
|---|---|---|
| Console | `start_agent.bat` (runs `setup_check.py` first) | `python3 main.py` |
| Silent | `start_agent_silent.vbs` | `nohup python3 main.py >/dev/null 2>&1 &` |
| Stop | `stop_agent.bat` | `pkill -f "tg-system-control/main.py"` |

Python used by the Windows launchers: project `.venv` → `python` on PATH (if it has the packages) → legacy `D:\VideoStudio_Mac\.venv` → `python`.

`stop_agent.bat` asks the bot to stop itself (it sends 🔴 OFFLINE), waits up to 10 seconds, then force-stops anything still running from this folder (including bots started by v1 launchers).

**After changing code or `.env`, restart the bot** — changes are not picked up while it runs.

---

## 🔄 8. Automatic startup on boot

### A. Windows (Startup folder)
- Install: run `install_autostart.bat` → creates `TGSystemControl.lnk` in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`, which runs `start_agent_silent.vbs` at login.
- Verify: `Win + R` → `shell:startup`.
- Remove: `uninstall_autostart.bat`.

### B. macOS (launchd)
```bash
bash install_autostart_mac.sh
launchctl list | grep tgsystemcontrol            # verify
launchctl unload ~/Library/LaunchAgents/com.hermes.tgsystemcontrol.plist && rm ~/Library/LaunchAgents/com.hermes.tgsystemcontrol.plist   # remove
```

### C. Linux (systemd user service)
```bash
bash install_autostart_linux.sh
systemctl --user status tg-system-control        # verify
systemctl --user disable --now tg-system-control && rm ~/.config/systemd/user/tg-system-control.service   # remove
```
The unit sets `DISPLAY`/`XAUTHORITY` so screenshots and input reach your X11 session; edit it if your display isn't `:0`. Wayland sessions have limited support.

---

## ⬆️ 9. Updating & upgrading

```bash
git pull
pip install -r requirements.txt
python setup_check.py
```
Then restart the bot.

**From v1:** stop the old bot with the new `stop_agent.bat`; set `TELEGRAM_CHAT_ID` (now mandatory); if your token was ever committed or shared, revoke it in @BotFather (`/mybots` → bot → *API Token* → *Revoke*) and put the new one in `.env`.

---

## 🗑️ 10. Uninstall

1. Stop the bot and remove autostart (section 8).
2. Delete the project folder (this also deletes `memory.md`, `screenshots/`, `temp/`).
3. Optionally delete the bot in @BotFather (`/deletebot`).
