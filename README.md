# 🤖 TG-System-Control (Hermes Agent)

A modular, cross-platform (Windows & macOS) desktop controller and verification agent powered by Telegram and LLMs (Google Gemini 2.0, Nous Hermes 3, Groq, or Offline Mode).

Remotely monitor and control your workstation, execute commands, capture screenshots, manage processes, and handle interactive approval cards directly from your phone via Telegram.

---

## 🌟 Key Features

- **📱 Remote Desktop Control via Telegram:** Send commands from your phone anywhere in the world.
- **🧠 Multi-Brain Architecture:**
  - **Google Gemini 2.0 Flash:** Fast, multimodal, and 100% free (1,500 requests/day).
  - **Nous Hermes 3 (OpenRouter):** Open-source agent model fine-tuned for tool use and function calling.
  - **Groq Llama 3.3 70B:** Blazing fast inference (300+ tok/s).
  - **Offline Fallback Mode:** Works instantly without any cloud API keys using direct system command matching.
- **📸 Live Screenshot Capture:** Request a desktop screenshot at any time to inspect your screen.
- **📊 Real-time Hardware Metrics:** Monitor CPU cores, RAM utilization, Disk space, and OS specs.
- **⚡ Application Launcher:** Remotely open applications (`open edge`, `open chrome`, `calc`, `notepad`).
- **🛡️ Secure Authorization:** Restricts control strictly to your authorized `TELEGRAM_CHAT_ID`.
- **🔕 Silent Background Mode:** Can run as a silent Windows background task (`.vbs` / Task Scheduler) with ~30 MB RAM usage.

---

## 📂 Project Structure

```text
tg-system-control/
├── .env.example              # Environment variables template
├── .env                      # Local credentials (git-ignored)
├── .gitignore                # Git ignore rules
├── requirements.txt          # Python dependencies
├── README.md                 # Documentation
├── config.py                 # Configuration loader
│
├── core/
│   ├── os_bridge.py          # Cross-platform Windows/Mac OS execution
│   ├── llm_router.py         # Gemini / Hermes / Groq / Offline router
│   └── hermes_agent.py       # Autonomous agent reasoning and tool loop
│
├── bot/
│   ├── telegram_client.py    # Telegram API client (messages, photos, buttons)
│   └── listener.py           # Polling listener & request handler
│
├── start_agent.bat           # 1-Click interactive launcher (Windows)
├── start_agent_silent.vbs    # Silent background launcher (Windows)
└── stop_agent.bat            # Process killer
```

---

## 🚀 Quick Setup Guide

### 1. Prerequisites
- Python 3.10+
- `requests` and `Pillow` libraries:
  ```bash
  pip install requests Pillow
  ```

### 2. Configure Credentials
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` with your credentials:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_CHAT_ID=your_telegram_chat_id
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_google_ai_studio_key
```

### 3. Run the Bot
- **Interactive Mode:**
  ```bash
  python main.py
  ```
- **Test Connectivity:**
  ```bash
  python main.py --test
  ```
- **Silent Background (Windows):**
  Double click `start_agent_silent.vbs`

---

## 📱 Telegram Commands & Usage

| Command / Prompt | Action |
|---|---|
| `status` or `/status` | Returns OS specs, CPU cores, RAM usage %, and free disk space |
| `screenshot` or `/shot` | Captures desktop screen and sends full JPEG photo to your chat |
| `open edge` or `/open chrome` | Launches the requested browser or application on the PC |
| `/exec <command>` | Runs any PowerShell or Bash command and returns the terminal output |
| `processes` or `/proc` | Lists the top 8 running processes by CPU |
| `lock pc` or `/lock` | Locks the workstation screen |
| *Natural Language* | Ask any question or request complex tasks when Gemini/Hermes API key is set |

---

## 🔒 Security
- All incoming updates from unauthorized chat IDs are rejected automatically with `⛔ Access Denied`.
- `.env` is strictly listed in `.gitignore` to prevent leaking tokens or keys to GitHub.
