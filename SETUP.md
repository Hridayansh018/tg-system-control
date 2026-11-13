# 🛠️ TG-System-Control: Comprehensive Setup & Installation Guide

This document provides step-by-step instructions for humans and AI agents (Antigravity, Claude Code, Cursor, Windsurf) to setup, configure, verify, and run **TG-System-Control** on any machine (Windows, macOS, Linux).

---

## 📌 For AI Agents (Quick Automation Instruction)

If you are an AI agent asked to set up this project:
```text
Please read the SETUP.md file, set up this project on my computer, and configure the AI engine to be powered by <"specify model: e.g., gemini / claude / openrouter / offline">.
```
2. Verify Python version is `>= 3.10`.
3. Create a virtual environment (`python -m venv .venv`).
4. Install minimal dependencies (`pip install requests Pillow`).
5. Ensure `.env` is created from `.env.example` with valid credentials.
6. Run `python setup_check.py` to verify all components pass.
7. Follow the platform-specific autostart or launcher steps.

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

## 🔍 4. Automated Environment Verification

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

## 🧠 5. Project Memory Logging (`memory.md`)

During setup, an append-only constructive memory file (`memory.md`) is automatically created at the repository root.

### Rules of `memory.md`:
1. **Append-Only (Constructive Writes Only):** Every action, command execution, agent reasoning thought, completed task, and system lifecycle event (startup, shutdown, network interruption) is appended chronologically.
2. **Never Deleted or Truncated:** The file is permanent and protected. No purge or deletion operations are permitted.
3. **Strictly Git-Ignored:** Added to `.gitignore` so your personal command history and desktop logs are never committed to GitHub.

---

## 🏃 6. How to Run the Bot

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

### Windows Auto-Start on System Boot
To have the bot start automatically every time your PC turns on:
1. Double-click `install_autostart.bat`.
2. It places a shortcut in `shell:startup`.
3. From your next boot, the bot will start silently and send `🟢 System ONLINE` to your Telegram!
*(To remove: run `uninstall_autostart.bat`)*

---

## 🛑 How to Stop
- **Console Mode:** Press `Ctrl + C` in the terminal.
- **Background Mode (Windows):** Double-click `stop_agent.bat`.
- **Background Mode (macOS/Linux):**
  ```bash
  pkill -f "python.*main.py"
  ```
Whenever stopped, the bot automatically sends `🔴 System OFFLINE` to Telegram.
