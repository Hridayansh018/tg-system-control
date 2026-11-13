# 🤖 TG-System-Control (Hermes Desktop Agent)

A cross-platform (Windows & macOS & Linux) workstation remote controller and system verification agent powered by Telegram and modern LLMs (Google Gemini 2.0, Anthropic Claude, Nous Hermes 3, or Groq).

Remotely monitor your machine, run terminal commands, capture live desktop screenshots, launch apps, inspect resource bottlenecks, and manage interactive pipeline approval cards — all directly from your smartphone via Telegram.

---

## 💡 Quick Setup Prompt for AI Agents (Antigravity, Claude, Cursor)

Copy and paste this prompt to your AI coding agent to set up this repository effortlessly on any computer:

```text
Please read the SETUP.md file, set up this project on my computer with Bot Token: <YOUR_BOT_TOKEN> and Chat ID: <YOUR_CHAT_ID>, and configure the AI engine to be powered by <"specify model: e.g., gemini / claude / openrouter / offline">.
```

The agent will read [SETUP.md](file:///D:/git-data/tg-system-control/SETUP.md), detect your OS, install dependencies, configure environment variables, run pre-flight warm-up tests, and certify readiness.

---

## 📱 How to Get Your Telegram Bot Token & Chat ID

Before running the agent, you need a Telegram Bot and your personal Chat ID:

### Step 1: Create a Bot via @BotFather
1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)** (the official verified bot).
2. Press **Start** (or send `/start`), then send `/newbot`.
3. Enter a friendly name for your bot (e.g. `My Desktop Controller`).
4. Enter a unique username ending in `bot` (e.g. `my_studio_pc_bot`).
5. BotFather will provide your **HTTP API Token** (e.g. `9236178910:AAEw5v7lZwlvJ8AkaJ9vOlbknnyOb8qQmqY`). Save this token!

### Step 2: Get Your Personal Chat ID (Zero-Trust Security)
1. In Telegram, search for **[@userinfobot](https://t.me/userinfobot)** or **[@raw_data_bot](https://t.me/raw_data_bot)**.
2. Send `/start`.
3. It will immediately reply with your numerical **`Id`** (e.g. `7166744280`).
4. This ensures only YOU can control your workstation. Any other Telegram user who attempts to message your bot receives `⛔ Access Denied`.

### Step 3: Use the Credentials in the Setup Prompt
Replace `<YOUR_BOT_TOKEN>` and `<YOUR_CHAT_ID>` in the prompt above and send it to your AI agent!

---

## ⚡ Zero-Latency Pre-Flight Warm-Up

To eliminate command lag and latency:
- When starting TG-System-Control (manually or via Windows boot), **all required packages, display contexts, input bridges, and universal application catalogs are pre-loaded and warmed up in memory first**.
- **Telegram is pinged with `🟢 SYSTEM ONLINE ⚡` ONLY AFTER every single script, package, and engine is 100% verified and primed.**
- The initial ping includes a benchmark report showing warm-up time (e.g. `⚡ Zero-Latency Warm-Up: ~840 ms`), indexed applications count, and Telegram API latency.

---

## 🖥️ Universal Desktop App Control (Open & Close ANY App)

You can launch and close **ANY** application or website installed on your desktop:

| Action | Example Telegram Commands | What Happens on Your PC |
|---|---|---|
| **Open App** | `open spotify`, `open edge`, `open discord`, `open notepad`, `open calculator`, `open hermes` | Resolves from universal Windows app catalog (140+ Win32, Store, and PWA apps) and displays GUI window. |
| **Open Website / PWA** | `open youtube`, `open edge gmail app`, `open youtube studio` | Launches dedicated web interface or standalone Edge PWA window. |
| **Close App** | `close spotify`, `close edge`, `close notepad`, `close calc` | Gracefully closes the matching running process and terminates any hung instances. |
| **Close Tab / Site** | `close youtube studio`, `close tab`, `close gmail` | Safely sends `Ctrl+W` to close the active web tab. |
| **Fallback Window Close** | `close window`, `hatao`, `band karo` | Sends `Alt+F4` to close the active frontmost window. |

---

## 🌟 What is this Bot & How Capable is It?

TG-System-Control acts as a **secure personal bridge between your phone and your physical workstation**. Unlike cloud bots that live on remote servers, this agent runs locally on your PC. It understands both direct commands and natural conversational language, executing tasks on your desktop and reporting results with zero latency.

### 🎯 Core Capabilities:
1. **Live Desktop Visibility (Vision):** Captures high-res desktop screenshots and sends them directly to Telegram so you can check progress, active windows, or error dialogues when away from your desk.
2. **Terminal & Shell Execution:** Run any PowerShell (Windows) or Bash (macOS/Linux) script remotely and receive formatted stdout/stderr logs.
3. **Hardware Health Monitoring:** Instant breakdown of OS version, CPU core count, active RAM utilization %, and free storage on primary drives.
4. **App Launcher:** Remotely launch browsers (`open edge`, `open chrome`), tools, editors, or background batch scripts.
5. **Smart Online/Offline Lifecycles:**
   - When the desktop turns on / boots up: Automatically sends `🟢 System ONLINE` to Telegram and updates the bot's bio.
   - When the desktop is shutting down, logged off, or stopped: Automatically dispatches `🔴 System OFFLINE` with the exact reason.
6. **Zero-Trust Security Filter:** Rejects messages from any unauthorized Telegram user with `⛔ Access Denied`.
7. **Multi-Model Intelligence:** Switch brains between Google Gemini 2.0, Anthropic Claude 3.5 Sonnet, Nous Hermes 3, or Groq with a single line in `.env`. Works in 100% offline rule mode if no API key is provided.

---

## 📁 Repository Structure

```text
tg-system-control/
├── .env.example              # Environment variables template
├── .env                      # Local credentials (git-ignored for security)
├── .gitignore                # Protects secrets and temporary files
├── requirements.txt          # Minimal Python dependencies (requests, Pillow)
├── README.md                 # Project overview and AI prompt
├── SETUP.md                  # Comprehensive setup manual for all platforms
├── setup_check.py            # Automated OS & dependency verification script
├── config.py                 # Configuration parser
│
├── core/
│   ├── os_bridge.py          # Cross-platform execution (Windows/macOS/Linux)
│   ├── llm_router.py         # Multi-brain router (Gemini, Claude, Hermes, Groq)
│   ├── hermes_agent.py       # Autonomous agent reasoning and tool loop
│   └── system_lifecycle.py   # Windows shutdown hooks & online/offline alerts
│
├── bot/
│   ├── telegram_client.py    # Telegram Bot API client (messages, photos, cards)
│   └── listener.py           # Polling listener & request handler
│
├── start_agent.bat           # 1-Click interactive console launcher (Windows)
├── start_agent_silent.vbs    # Silent background launcher (Windows, 0 black windows)
├── stop_agent.bat            # 1-Click process killer (Windows)
├── install_autostart.bat     # Installs auto-launch shortcut to Windows Startup
├── uninstall_autostart.bat   # Removes auto-launch shortcut (Windows)
├── install_autostart_mac.sh  # Auto-start installer for macOS (launchd User Agent)
├── install_autostart_linux.sh# Auto-start installer for Linux (systemd User Service)
└── install_hermes_app.bat    # 1-Click installer for official Nous Research Hermes Desktop App
```

---

## ⚡ Telegram Commands & Capabilities

| Command / Natural Query | What the Bot Does on Your PC |
|---|---|
| `status` or `/status` | Returns OS specs, CPU cores, RAM % used, and Disk GB free. |
| `screenshot` or `/shot` | Grabs the current desktop monitor and sends a clean JPEG photo. |
| `open edge` / `open chrome` | Launches Microsoft Edge, Google Chrome, or any named program. |
| `/exec <command>` | Runs PowerShell / Bash command and replies with terminal output. |
| `processes` or `/proc` | Lists the top running processes sorted by CPU consumption. |
| `lock pc` or `/lock` | Locks the workstation screen immediately. |
| *Natural Language* | *"Check karo PC me kitna space bacha hai"*, *"Edge kholo"*, *"Downloads me kitni zip files hain"* (when LLM is configured). |

---

## 🛠️ Verification & Testing

Verify that your system meets all requirements and that your bot is communicating with Telegram:

```bash
python setup_check.py
```

Expected output:
```text
=================================================================
  TG-SYSTEM-CONTROL · ENVIRONMENT VERIFICATION
=================================================================
[✅ PASS] Operating System                 Windows (11, AMD64)
[✅ PASS] Python Version                   3.13.x (Requires 3.10+)
[✅ PASS] Package: requests                Installed & functional
[✅ PASS] Package: PIL                     Installed & functional
[✅ PASS] Telegram Bot Token               92361789...
[✅ PASS] Authorized Chat ID               7166744280
[✅ PASS] System Metrics Reader            CPU Cores: 18, Disk Free: 68.0 GB
[✅ PASS] Shell Execution Bridge           Shell exit code: 0
[✅ PASS] Desktop Screen Grabber           Saved to test_shot.jpg
[✅ PASS] Telegram Bot API                 Connected to @hridduh_studio_bot
=================================================================
🎉 ALL CORE CHECKS PASSED! Your device is ready to run TG-System-Control.
```

---

## 📄 License
MIT License. Free for personal, commercial, and studio automation workflows.
