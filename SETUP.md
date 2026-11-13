# 🛠️ TG-System-Control: Comprehensive Setup & Installation Guide

This document provides step-by-step instructions for humans and AI agents (Antigravity, Claude Code, Cursor, Windsurf) to setup, configure, verify, and run **TG-System-Control** on any machine (Windows, macOS, Linux).

---

## 📌 For AI Agents (Quick Automation Instruction)

If you are an AI agent asked to set up this project:
```text
Please read the SETUP.md file, set up this project on my computer with Bot Token: <YOUR_BOT_TOKEN> and Chat ID: <YOUR_CHAT_ID>, and configure the AI engine to be powered by <"specify model: e.g., gemini / claude / openrouter / offline">.
```
1. Parse `Bot Token` and `Chat ID` from the prompt and inject them into `.env`.
2. Verify Python version is `>= 3.10`.
3. Create a virtual environment (`python -m venv .venv`) and install minimal dependencies (`pip install requests Pillow`).
4. Ensure `.env` is created from `.env.example` with valid credentials.
5. **Install Official Hermes Desktop App (Mandatory for Every Setup):**
   - Run `install_hermes_app.bat` (or clone `https://github.com/nousresearch/hermes-agent`, run `setup-hermes.ps1 -RuntimeOnly`, build via `hermes desktop --build-only`).
   - Ensure `Hermes Agent.lnk` desktop shortcut is created pointing to `Hermes.exe` with the official icon (`apps\desktop\assets\icon.ico`).
6. Run `python setup_check.py` to verify all components pass.
7. Follow the platform-specific autostart or launcher steps.

---

## 📱 How to Generate Your Telegram Bot & Find Your Chat ID

### Step 1: Create Your Bot via @BotFather
1. In Telegram, search for **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`.
3. Give it a friendly display name (e.g. `My Desktop Controller`).
4. Give it a unique username ending with `bot` (e.g. `my_studio_pc_bot`).
5. Copy the HTTP API token provided by BotFather (format: `1234567890:ABCdef...`).

### Step 2: Get Your Personal Chat ID
1. In Telegram, search for **[@userinfobot](https://t.me/userinfobot)**.
2. Send `/start`.
3. Note your numerical **`Id`** (e.g. `7166744280`).
4. Paste both into `.env` (or pass them in the setup prompt above).

---

## ⚡ Zero-Latency Pre-Flight Warm-Up Architecture

When `start_agent.bat` or Windows boots up:
1. **Subsystem Warm-Up (`core/system_lifecycle.py`):**
   - Pre-imports Python libraries (`requests`, `Pillow`, `ctypes`).
   - Indexes all 140+ installed applications into `apps_cache.json`.
   - Primes the GDI/display screenshot context and DPI awareness.
   - Tests and arms the Win32 `UserInputLock` bridge.
   - Measures Telegram API network latency.
2. **Delayed Telegram Ping:**
   - The bot starts listening first.
   - **ONLY WHEN** all subsystems are 100% verified and the polling loop is active does the bot dispatch `🟢 SYSTEM ONLINE ⚡` to Telegram.
   - This eliminates startup command latency.

---

## 💻 1. System Requirements & Dependency Breakdown

### Core Requirements
- **Python:** Version `3.10` or higher.
- **Git:** For cloning and updating the repository.
- **Network:** Active internet connection to reach Telegram Bot API (`api.telegram.org`) and LLM endpoints.

### Python Packages (Minimal & Lightweight)
| Package | Why It Is Needed | Minimal Version |
|---|---|---|
| `requests` | High-level HTTP client for long-polling Telegram API and sending REST calls to LLM providers. | `>= 2.28.0` |
| `Pillow` (PIL) | Native cross-platform desktop screenshot grabbing and image compression before dispatching over Telegram. | `>= 9.0.0` |
| `psutil` *(Optional)* | Used for high-precision CPU/RAM process listing if installed. If omitted, the native OS bridge automatically falls back to PowerShell/CIM on Windows, `sysctl`/`ps` on macOS, and `/proc` on Linux. | `>= 5.9.0` |

---

## 🚀 2. Step-by-Step Installation

### Step A: Clone Repository & Create Virtual Environment

#### On Windows (PowerShell):
```powershell
git clone https://github.com/your-username/tg-system-control.git
cd tg-system-control

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

#### On macOS & Linux (Terminal):
```bash
git clone https://github.com/your-username/tg-system-control.git
cd tg-system-control

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

---

## ⚙️ 3. Configuration Setup (`.env`)

Copy the example file to `.env`:
```bash
cp .env.example .env
```

Open `.env` in any text editor and configure:

### 1. Telegram Credentials (Required)
- **`TELEGRAM_BOT_TOKEN`**: Create a bot on Telegram via `@BotFather`, send `/newbot`, and paste the token string here.
- **`TELEGRAM_CHAT_ID`**: Your personal Telegram user ID (prevents unauthorized users from controlling your computer). Run `python tools/telegram_bot.py get-chat-id` or message `@userinfobot` to find your ID.

### 2. Choosing Your AI Brain Model
Configure `LLM_PROVIDER` according to your preference:

#### Option 1: Google Gemini 2.0 Flash (Recommended — Free & Fast)
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIzaSyYourGoogleAIStudioKeyHere
```
*(Get your free key at [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) — 1,500 free requests/day)*

#### Option 2: Anthropic Claude (via OpenRouter)
```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-YourKeyHere
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
```

#### Option 3: Nous Hermes 3 (Local or OpenRouter)
```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-YourKeyHere
OPENROUTER_MODEL=nousresearch/hermes-3-llama-3.1-70b
```

#### Option 4: Groq (Ultra-Fast 300+ tok/s)
```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_YourGroqKeyHere
```

#### Option 5: Offline Mode (Zero Keys Needed)
```env
LLM_PROVIDER=offline
```
*(Directly processes system commands: `status`, `screenshot`, `open edge`, `/exec <cmd>`, `processes`, `lock pc`)*

---

## 🦅 4. Installing the Official Hermes Agent Desktop App (Required for Every Setup)

Every time this workstation setup is prepared on a computer, the official **Nous Research Hermes Agent Desktop Application** must be installed and linked alongside the Telegram controller:

### Quick 1-Click Installation (Windows)
Double-click `install_hermes_app.bat` in the repository root. It will:
1. Clone the official repository from `https://github.com/nousresearch/hermes-agent`.
2. Bootstrap the isolated Hermes runtime and PM toolchain (`setup-hermes.ps1 -RuntimeOnly`).
3. Compile and package the standalone Electron desktop application (`hermes desktop --build-only`).
4. Generate the `Hermes Agent.lnk` Desktop & Start Menu shortcuts pointing to `Hermes.exe` with the official icon (`apps\desktop\assets\icon.ico`).

### Manual Setup Commands:
```powershell
# 1. Clone official repository
git clone --depth 1 https://github.com/nousresearch/hermes-agent.git D:\git-data\hermes-agent
cd D:\git-data\hermes-agent

# 2. Run PM toolchain bootstrap
powershell -ExecutionPolicy Bypass -File .\setup-hermes.ps1 -RuntimeOnly

# 3. Build standalone Electron desktop application
powershell -ExecutionPolicy Bypass -Command ". .\activate.ps1; hermes desktop --build-only"

# 4. Standalone binary created:
# D:\git-data\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe
```

---

## 🔍 5. Automated Environment Verification

Before running the bot, always execute the built-in verifier:
```bash
python setup_check.py
```

### What `setup_check.py` Automatically Does:
1. Detects OS: Windows, macOS, or Linux.
2. Checks Python version `>= 3.10`.
3. Validates required packages (`requests`, `Pillow`).
4. Verifies `.env` has valid credentials.
5. Tests hardware OS metrics reader (CPU, RAM, Disk).
6. Tests desktop screenshot engine.
7. Pings Telegram Bot API to confirm token authenticity.

If all items print `[✅ PASS]`, your system is fully certified to run!

---

## 🧠 6. Project Memory Logging (`memory.md`)

During setup, an append-only constructive memory file (`memory.md`) is automatically created at the repository root.

### Rules of `memory.md`:
1. **Append-Only (Constructive Writes Only):** Every action, command execution, agent reasoning thought, completed task, and system lifecycle event (startup, shutdown, network interruption) is appended chronologically.
2. **Never Deleted or Truncated:** The file is permanent and protected. No purge or deletion operations are permitted.
3. **Strictly Git-Ignored:** Added to `.gitignore` so your personal command history and desktop logs are never committed to GitHub.

---

## 🏃 7. How to Run the Bot

### Interactive Mode (Console Window)
- **Windows:** Double-click `start_agent.bat` or run:
  ```powershell
  python main.py
  ```
- **macOS / Linux:**
  ```bash
  python3 main.py
  ```

### Silent Background Mode (No Black Window)
- **Windows:** Double-click `start_agent_silent.vbs`
  *(Runs silently in background with ~30 MB RAM)*
- **macOS / Linux:**
  ```bash
  nohup python3 main.py > /dev/null 2>&1 &
  ```

---

## 🔄 8. Automatic Startup on Boot (Hands-Free Device Setup)

To ensure the Telegram bot starts automatically on every system boot without requiring you to open a terminal or touch your computer:

### A. Windows (Auto-Start via Startup Folder)
1. **1-Click Installer:** Double-click `install_autostart.bat`.
2. **What It Does:** It creates a silent shortcut `TGSystemControl.lnk` inside your Windows Startup directory (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`).
3. **Execution:** On every Windows login/reboot, Windows automatically executes `start_agent_silent.vbs`, warms up all required packages, and sends `🟢 SYSTEM ONLINE ⚡` to Telegram.
4. **Verify:** Press `Win + R`, type `shell:startup`, and verify `TGSystemControl.lnk` is present.
5. **Uninstall:** Run `uninstall_autostart.bat` to remove auto-start.

### B. macOS (Auto-Start via launchd User Agent)
1. **1-Click Installer:** Run:
   ```bash
   bash install_autostart_mac.sh
   ```
2. **What It Does:** Generates a `launchd` plist at `~/Library/LaunchAgents/com.hermes.tgsystemcontrol.plist` with `RunAtLoad` and `KeepAlive` set to `true`.
3. **Execution:** macOS automatically launches the daemon on user login and restarts it if closed.
4. **Verify:**
   ```bash
   launchctl list | grep tgsystemcontrol
   ```
5. **Uninstall:**
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.hermes.tgsystemcontrol.plist
   rm ~/Library/LaunchAgents/com.hermes.tgsystemcontrol.plist
   ```

### C. Linux (Auto-Start via systemd User Service)
1. **1-Click Installer:** Run:
   ```bash
   bash install_autostart_linux.sh
   ```
2. **What It Does:** Creates a `systemd` user service unit at `~/.config/systemd/user/tg-system-control.service` and enables user lingering via `loginctl enable-linger $USER` (allowing the bot to run even when logged out).
3. **Execution:** Starts immediately and automatically re-launches on system boot with auto-restart on network interruptions.
4. **Verify:**
   ```bash
   systemctl --user status tg-system-control
   ```
5. **Uninstall:**
   ```bash
   systemctl --user disable --now tg-system-control
   rm ~/.config/systemd/user/tg-system-control.service
   ```

---

## 🛑 9. How to Stop the Bot
- **Console Mode:** Press `Ctrl + C` in the terminal.
- **Background Mode (Windows):** Double-click `stop_agent.bat`.
- **Background Mode (macOS/Linux):**
  ```bash
  pkill -f "python.*main.py"
  ```
Whenever stopped, the bot automatically intercepts the exit signal and dispatches `🔴 System OFFLINE` to Telegram.
