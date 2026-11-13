"""Hermes Agent: Autonomous desktop agent loop.
Combines LLM reasoning with OS execution tools to control your PC via Telegram.
"""
import json
import re
import time
from pathlib import Path

from . import os_bridge
from . import llm_router
from . import memory_logger
import config

SYSTEM_PROMPT = """You are Hermes Agent, a powerful desktop AI assistant running locally on the user's computer.
You have direct execution capability to control the PC using specific tool actions.

When the user asks you to do something, you can choose to execute tools by replying in JSON format:
```json
{
  "actions": [
    {
      "action": "<tool_name>",
      "parameters": { ... }
    }
  ],
  "message": "Optional friendly reply to user"
}
```
Or for a single action:
```json
{
  "action": "<tool_name>",
  "parameters": { ... }
}
```

Available Tools:
1. `take_screenshot`: Captures the current desktop screen. No parameters required.
2. `get_system_stats`: Returns CPU, RAM, Disk, and OS metrics. No parameters required.
3. `execute_command`: Runs any command in PowerShell (Windows) or Bash (Mac). Parameters: `{"command": "string"}`.
4. `launch_app`: Opens an application or website. Parameters: `{"app_name": "string"}` (e.g. "edge", "chrome", "notepad", "calc", "chatgpt", "youtube studio").
5. `focus_window`: Brings an existing open window to the front. Parameters: `{"window_title": "string"}` (e.g. "chatgpt", "edge", "chrome").
6. `close_app`: Closes an application or website tab. Parameters: `{"target": "string"}` (e.g. "edge", "notepad", "youtube studio").
7. `list_processes`: Lists top running processes by CPU. Parameters: `{"limit": 10}`.
8. `lock_pc`: Locks the workstation screen. No parameters required.
9. `mouse_click`: Clicks the mouse at screen coordinates (x, y) or current position. Parameters: `{"x": int, "y": int, "button": "left"|"right", "double": bool}`.
10. `mouse_move`: Moves mouse cursor to (x, y). Parameters: `{"x": int, "y": int}`.
11. `type_text`: Types plain text into the active focused window. Parameters: `{"text": "string"}`.
12. `press_key`: Presses a special key. Parameters: `{"key": "enter"|"tab"|"esc"|"space"|"backspace"}`.
13. `press_hotkey`: Presses a hotkey combination. Parameters: `{"hotkey": "ctrl+c"|"ctrl+v"|"ctrl+w"|"alt+tab"|"win+d"}`.
14. `automate_chatgpt`: Direct tool to open ChatGPT in Microsoft Edge, start a new chat, enter prompt, submit it, and capture screenshot. Parameters: `{"prompt": "string", "new_chat": bool}`.

CRITICAL RULES FOR MULTI-STEP AUTOMATION:
- For requests involving ChatGPT (e.g. "open chatgpt and generate thumbnails", "generate 3 thumbnails for luffy in chatgpt"):
  You can either return `{"action": "automate_chatgpt", "parameters": {"prompt": "Detailed thumbnail prompt...", "new_chat": true}}` OR use the sequence: `launch_app` -> `type_text` -> `press_key: enter` -> `take_screenshot`.
- When the user asks to DO something in an app: NEVER just launch the app and stop! Always include typing, submitting, and screenshotting in one response.

If the user asks a normal question that requires no tool execution, just reply with helpful text normally.
Be concise, helpful, and speak in Hinglish/English as the user prefers.
"""


class HermesAgent:
    def __init__(self):
        self.screenshot_counter = 0

    def process_message(self, user_text: str) -> dict:
        """Processes an incoming user message and executes any required desktop actions.
        Returns a dict: {"text": str, "photo": str or None}
        """
        user_lower = user_text.strip().lower()

        # -------------------------------------------------------------
        # Fast Path / Direct Commands & Offline Fallback Handling
        # -------------------------------------------------------------
        # 1. Screenshot
        if any(k in user_lower for k in ["screenshot", "screen shot", "/shot", "ss bhejo", "screen capture", "desktop dikhao"]):
            out_file = config.SCREENSHOTS_DIR / f"shot_{int(time.time())}.jpg"
            ok = os_bridge.take_screenshot(out_file)
            memory_logger.log_entry(
                "DESKTOP_ACTION",
                "Captured Desktop Screenshot",
                details={"file": out_file.name, "success": ok},
                thinking=f"User asked '{user_text}'. Triggering screen capture and sending photo."
            )
            if ok and out_file.exists():
                return {
                    "text": "📸 *Desktop Screenshot Captured!*",
                    "photo": str(out_file)
                }
            else:
                return {"text": "⚠️ Screenshot capture failed (Screen might be locked or running without desktop session).", "photo": None}

        # 2. System Status / Metrics
        if any(k in user_lower for k in ["status", "/status", "pc status", "ram", "cpu", "disk", "specs", "system stats"]):
            stats = os_bridge.get_system_stats()
            memory_logger.log_entry(
                "HARDWARE_METRICS",
                "Collected Hardware Specs & Resource Utilization",
                details=stats,
                thinking=f"User asked for system status. Polled CPU ({stats.get('cpu_cores')} cores), RAM ({stats.get('ram_used_pct')}%), and storage."
            )
            reply = (
                f"💻 *SYSTEM HARDWARE & RESOURCE STATUS*\n\n"
                f"🖥️ *OS:* `{stats.get('os')}` ({stats.get('architecture')})\n"
                f"🧠 *CPU Cores:* `{stats.get('cpu_cores')}`\n"
            )
            if "ram_total_gb" in stats:
                reply += f"⚡ *RAM:* `{stats.get('ram_used_gb', 0)} GB` / `{stats.get('ram_total_gb')} GB` ({stats.get('ram_used_pct')} % used)\n"
            if "disk_total_gb" in stats:
                reply += f"💾 *Disk (C:):* `{stats.get('disk_free_gb')} GB Free` / `{stats.get('disk_total_gb')} GB` ({stats.get('disk_used_pct')} % used)\n"

            reply += f"\n🕒 *Server Time:* `{time.strftime('%Y-%m-%d %H:%M:%S')}`"
            return {"text": reply, "photo": None}

        # 3. Top Processes
        if any(k in user_lower for k in ["process", "processes", "taskmgr", "task manager", "/proc"]):
            proc_out = os_bridge.list_top_processes(limit=8)
            memory_logger.log_entry(
                "PROCESS_INSPECTION",
                "Queried Top Running Processes",
                details={"limit": 8},
                thinking="Inspected CPU/Memory consuming processes."
            )
            return {"text": f"📋 *TOP RUNNING PROCESSES:*\n```text\n{proc_out[:3500]}\n```", "photo": None}

        # 4. Lock PC
        if any(k in user_lower for k in ["lock pc", "lock screen", "/lock"]):
            os_bridge.lock_workstation()
            memory_logger.log_entry(
                "SECURITY_ACTION",
                "Locked Workstation",
                thinking="User instructed remote screen lock via Telegram."
            )
            return {"text": "🔒 *Workstation Locked successfully!*", "photo": None}

        # 5. Direct Shell Execution (/exec or /run)
        if any(user_lower.startswith(p) for p in ["/exec ", "/run ", "run: ", "cmd: "]):
            cmd = re.sub(r"^(/exec |/run |run: |cmd: )", "", user_text, flags=re.IGNORECASE).strip()
            res = os_bridge.run_command(cmd)
            out_str = (res["stdout"] or res["stderr"] or "Command executed with no output.")[:3500]
            status_icon = "✅" if res["exit_code"] == 0 else "⚠️"
            memory_logger.log_entry(
                "SHELL_COMMAND",
                f"Executed: {cmd}",
                details={"exit_code": res["exit_code"], "output_preview": out_str[:250]},
                thinking=f"Executing remote shell command from Telegram: {cmd}"
            )
            return {
                "text": f"{status_icon} *Command Output (Exit code {res['exit_code']}):*\n```text\n{out_str}\n```",
                "photo": None
            }

        # 6. Launch App (/open or open or kholo or start)
        # CRITICAL: Only trigger simple app launch if it is NOT a complex instruction with actions!
        action_indicators = [
            "generate", "thumbnail", "prompt", "video", "write", "search", "type", "click",
            "create", "banao", "dalo", "likho", "chat", "new chat", "then", "and", "karke",
            "send", "dikhao", "review", "wha", "wahan", "pe", "par", "me", "mein", "aur",
            "image", "photo", "pic", "make", "find", "luffy", "marinford"
        ]
        is_complex = any(w in user_lower for w in action_indicators)

        if not is_complex and (
            any(user_lower.startswith(p) for p in ["/open ", "/launch ", "open ", "launch ", "start "])
            or any(user_lower.endswith(k) for k in [" open karo", " kholo", " chalao"])
        ):
            # Extract app name
            app = re.sub(r"^(/open\s+|/launch\s+|open\s+|launch\s+|start\s+)", "", user_text, flags=re.IGNORECASE).strip()
            app = re.sub(r"\s+(open karo|kholo|chalao)$", "", app, flags=re.IGNORECASE).strip()
            if len(app.split()) <= 3:
                res = os_bridge.launch_app(app)
                memory_logger.log_entry(
                    "APP_LAUNCH",
                    f"Launched application: {app}",
                    details={"app": app, "exit_code": res["exit_code"]},
                    thinking=f"Launching application '{app}' on workstation."
                )
                if res["exit_code"] == 0:
                    return {"text": f"🚀 Launched *{app}* on PC!", "photo": None}
                else:
                    return {"text": f"⚠️ Could not launch *{app}*: {res['stderr']}", "photo": None}

        # 6b. Close App / Window / Tab (/close or close or band karo or kill)
        if any(user_lower.startswith(p) for p in ["/close ", "/kill ", "close ", "kill "]) or any(k in user_lower for k in [" band karo", " hatao", " close karo"]):
            target = re.sub(r"^(/close\s+|/kill\s+|close\s+|kill\s+)", "", user_text, flags=re.IGNORECASE).strip()
            target = re.sub(r"\s+(band karo|hatao|close karo)$", "", target, flags=re.IGNORECASE).strip()
            res = os_bridge.close_app(target)
            memory_logger.log_entry(
                "APP_CLOSE",
                f"Closed: {target}",
                details={"target": target, "result": res},
                thinking=f"Closing window/tab/application '{target}' on workstation."
            )
            return {"text": f"🛑 {res['stdout'] or 'Closed.'}", "photo": None}

        # 7. GUI: Mouse Click (/click X Y or click X Y)
        if re.match(r"^(/click|click)\s+\d+\s+\d+", user_lower):
            m = re.findall(r"\d+", user_text)
            if len(m) >= 2:
                x, y = int(m[0]), int(m[1])
                with os_bridge.UserInputLock("Mouse Click"):
                    ok = os_bridge.mouse_click(x, y)
                memory_logger.log_entry("GUI_MOUSE_CLICK", f"Clicked at ({x}, {y})", details={"x": x, "y": y, "success": ok})
                return {"text": f"🖱️ Clicked at *({x}, {y})* (User input safely locked & restored)", "photo": None}

        # 8. GUI: Type Text (/type text or type: text)
        if any(user_lower.startswith(p) for p in ["/type ", "type: ", "write: ", "type "]):
            txt = re.sub(r"^(/type\s+|type:\s*|write:\s*|type\s+)", "", user_text, flags=re.IGNORECASE)
            with os_bridge.UserInputLock("Keyboard Type"):
                ok = os_bridge.type_text(txt)
            memory_logger.log_entry("GUI_KEYBOARD_TYPE", f"Typed text ({len(txt)} chars)", details={"preview": txt[:100], "success": ok})
            return {"text": f"⌨️ Typed: `{txt[:100]}` (User input safely locked & restored)", "photo": None}

        # 8b. GUI: Type & Press Enter (Compound action for forms/search/chatgpt prompt box)
        if any(user_lower.startswith(p) for p in ["/prompt ", "prompt: ", "type and enter: ", "enter prompt: "]):
            txt = re.sub(r"^(/prompt\s+|prompt:\s*|type and enter:\s*|enter prompt:\s*)", "", user_text, flags=re.IGNORECASE).strip()
            with os_bridge.UserInputLock("Type & Enter Prompt"):
                ok = os_bridge.type_text(txt)
                time.sleep(0.3)
                os_bridge.press_key("enter")
            memory_logger.log_entry("GUI_TYPE_AND_ENTER", f"Typed and submitted prompt ({len(txt)} chars)", details={"preview": txt[:100], "success": ok})
            return {"text": f"⌨️ *Prompt Typed & Submitted (Enter pressed):*\n`{txt[:250]}`\n\n📸 *Tip:* Send `/shot` after a few seconds to see the result!", "photo": None}

        # 9. GUI: Press Key (/key enter or key: esc or press enter)
        if user_lower in ["enter", "hit enter", "press enter"] or any(user_lower.startswith(p) for p in ["/key ", "key: ", "press ", "hit "]):
            k = re.sub(r"^(/key\s+|key:\s*|press\s+|hit\s+)", "", user_text, flags=re.IGNORECASE).strip()
            if not k:
                k = "enter"
            with os_bridge.UserInputLock(f"Key Press {k}"):
                ok = os_bridge.press_key(k)
            memory_logger.log_entry("GUI_KEY_PRESS", f"Pressed key: {k}", details={"key": k, "success": ok})
            return {"text": f"🔘 Pressed key *{k.upper()}*", "photo": None}

        # 10. GUI: Hotkey (/hotkey ctrl+v or hotkey: alt+tab)
        if any(user_lower.startswith(p) for p in ["/hotkey ", "hotkey: "]):
            hk = re.sub(r"^(/hotkey\s+|hotkey:\s*)", "", user_text, flags=re.IGNORECASE).strip()
            with os_bridge.UserInputLock(f"Hotkey {hk}"):
                ok = os_bridge.press_hotkey(hk)
            memory_logger.log_entry("GUI_HOTKEY", f"Pressed hotkey: {hk}", details={"hotkey": hk, "success": ok})
            return {"text": f"⚡ Pressed hotkey *{hk.upper()}*", "photo": None}

        # -------------------------------------------------------------
        # LLM Router Path (Gemini / Hermes 3 / Groq)
        # -------------------------------------------------------------
        llm_res = llm_router.route_prompt(user_text, SYSTEM_PROMPT)

        if "error" in llm_res:
            return {
                "text": f"⚠️ *LLM Error:* {llm_res['error']}\n\n💡 *Offline Commands Available:*\n• `/status` - Check CPU/RAM/Disk\n• `/shot` - Capture desktop screenshot\n• `/open <app>` - Launch browser/app\n• `/exec <cmd>` - Run PowerShell command\n• `/proc` - Top processes\n• `/lock` - Lock PC",
                "photo": None
            }

        if llm_res.get("offline"):
            # Offline help
            return {
                "text": (
                    f"🤖 *Hermes PC Controller (Offline Mode)*\n\n"
                    f"Main abhi bina cloud API key ke direct system mode mein chal raha hoon.\n\n"
                    f"📌 *Commands Available:*\n"
                    f"• `status` ya `/status` - PC ki RAM, CPU aur Disk dekhein\n"
                    f"• `screenshot` ya `/shot` - Live desktop screenshot lein\n"
                    f"• `open edge` ya `/open chrome` - Koi bhi application kholein\n"
                    f"• `/exec <command>` - Koi bhi PowerShell command run karein\n"
                    f"• `processes` ya `/proc` - Running tasks dekhein\n"
                    f"• `lock pc` ya `/lock` - PC screen lock karein\n\n"
                    f"💡 *Tip:* `.env` mein `GEMINI_API_KEY` daal doge toh main natural language mein baatein karke decisions bhi le sakunga!"
                ),
                "photo": None
            }

        reply_raw = llm_res.get("reply", "")

        # Check if LLM emitted JSON tool action(s)
        json_match = re.search(r"```json\s*(\{.*?\}|\[.*?\])\s*```", reply_raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if isinstance(data, list):
                    actions_list = data
                    reply_msg = ""
                elif isinstance(data, dict):
                    actions_list = data.get("actions") or [data]
                    reply_msg = data.get("message", "")
                else:
                    actions_list = []
                    reply_msg = ""

                photo_to_send = None
                executed_logs = []

                for item in actions_list:
                    act = item.get("action")
                    params = item.get("parameters", {})

                    if act == "automate_chatgpt":
                        prm = params.get("prompt", "")
                        nc = params.get("new_chat", True)
                        res = os_bridge.automate_chatgpt(prm, new_chat=nc)
                        if res.get("screenshot"):
                            photo_to_send = res["screenshot"]
                        executed_logs.append(f"Automated ChatGPT with prompt: `{prm[:50]}...`")

                    elif act == "launch_app":
                        app = params.get("app_name", "")
                        os_bridge.launch_app(app)
                        executed_logs.append(f"Launched {app}")
                        # If more actions follow (like typing), allow page/browser time to load and gain focus
                        time.sleep(3.0 if any(b in app.lower() for b in ["edge", "chrome", "chatgpt", "browser", "http"]) else 1.5)

                    elif act == "focus_window":
                        win_title = params.get("window_title", "")
                        ok = os_bridge.focus_window(win_title)
                        executed_logs.append(f"Focused window '{win_title}'")
                        time.sleep(0.5)

                    elif act == "close_app":
                        target = params.get("target", "")
                        os_bridge.close_app(target)
                        executed_logs.append(f"Closed {target}")

                    elif act == "type_text":
                        txt = params.get("text", "")
                        with os_bridge.UserInputLock("LLM Keyboard Type"):
                            os_bridge.type_text(txt)
                        executed_logs.append(f"Typed: `{txt[:40]}`")
                        time.sleep(0.3)

                    elif act == "press_key":
                        k = params.get("key", "enter")
                        with os_bridge.UserInputLock(f"LLM Key Press {k}"):
                            os_bridge.press_key(k)
                        executed_logs.append(f"Pressed {k.upper()}")
                        time.sleep(0.3)

                    elif act == "press_hotkey":
                        hk = params.get("hotkey", "")
                        with os_bridge.UserInputLock(f"LLM Hotkey {hk}"):
                            os_bridge.press_hotkey(hk)
                        executed_logs.append(f"Pressed hotkey {hk.upper()}")

                    elif act == "mouse_click":
                        x = params.get("x")
                        y = params.get("y")
                        btn = params.get("button", "left")
                        dbl = params.get("double", False)
                        with os_bridge.UserInputLock("LLM Mouse Click"):
                            os_bridge.mouse_click(x, y, btn, dbl)
                        executed_logs.append(f"Clicked ({x}, {y})")

                    elif act == "take_screenshot":
                        out_file = config.SCREENSHOTS_DIR / f"shot_{int(time.time())}.jpg"
                        ok = os_bridge.take_screenshot(out_file)
                        if ok and out_file.exists():
                            photo_to_send = str(out_file)
                        executed_logs.append("Captured screenshot")

                    elif act == "get_system_stats":
                        stats = os_bridge.get_system_stats()
                        executed_logs.append(f"CPU: {stats.get('cpu_cores')} cores | RAM: {stats.get('ram_used_pct')}%")

                    elif act == "execute_command":
                        cmd = params.get("command", "")
                        res = os_bridge.run_command(cmd)
                        executed_logs.append(f"Executed: `{cmd[:40]}` (Exit {res['exit_code']})")

                    elif act == "lock_pc":
                        os_bridge.lock_workstation()
                        executed_logs.append("Locked workstation")

                summary = reply_msg or ("⚡ *Actions Completed:*\n• " + "\n• ".join(executed_logs))
                return {"text": summary, "photo": photo_to_send}

            except Exception as e:
                print(f"[HermesAgent] Tool execution error: {e}")

        # Return standard conversational reply
        return {"text": reply_raw, "photo": None}
