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

When the user asks you to do something, you can choose to execute a tool by replying in JSON format:
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
4. `launch_app`: Opens an application. Parameters: `{"app_name": "string"}` (e.g. "chrome", "edge", "notepad", "calc").
5. `list_processes`: Lists top running processes by CPU. Parameters: `{"limit": 10}`.
6. `lock_pc`: Locks the workstation screen. No parameters required.
7. `mouse_click`: Clicks the mouse at screen coordinates (x, y) or current position. Parameters: `{"x": int, "y": int, "button": "left"|"right", "double": bool}`.
8. `mouse_move`: Moves mouse cursor to (x, y). Parameters: `{"x": int, "y": int}`.
9. `type_text`: Types plain text into the active focused window. Parameters: `{"text": "string"}`.
10. `press_key`: Presses a special key. Parameters: `{"key": "enter"|"tab"|"esc"|"space"|"backspace"}`.
11. `press_hotkey`: Presses a hotkey combination. Parameters: `{"hotkey": "ctrl+c"|"ctrl+v"|"alt+tab"|"win+d"}`.

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
        if user_text.startswith(("/exec ", "/run ", "run: ", "cmd: ")):
            cmd = re.sub(r"^(/exec |/run |run: |cmd: )", "", user_text).strip()
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

        # 6. Launch App (/open or /launch)
        if user_text.startswith(("/open ", "/launch ", "open ", "launch ")):
            app = re.sub(r"^(/open |/launch |open |launch )", "", user_text).strip()
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

        # 7. GUI: Mouse Click (/click X Y or click X Y)
        if re.match(r"^(/click|click)\s+\d+\s+\d+", user_lower):
            m = re.findall(r"\d+", user_text)
            if len(m) >= 2:
                x, y = int(m[0]), int(m[1])
                ok = os_bridge.mouse_click(x, y)
                memory_logger.log_entry("GUI_MOUSE_CLICK", f"Clicked at ({x}, {y})", details={"x": x, "y": y, "success": ok})
                return {"text": f"🖱️ Clicked at *({x}, {y})*", "photo": None}

        # 8. GUI: Type Text (/type text or type: text)
        if user_text.startswith(("/type ", "type: ", "write: ")):
            txt = re.sub(r"^(/type |type: |write: )", "", user_text)
            ok = os_bridge.type_text(txt)
            memory_logger.log_entry("GUI_KEYBOARD_TYPE", f"Typed text ({len(txt)} chars)", details={"preview": txt[:100], "success": ok})
            return {"text": f"⌨️ Typed: `{txt[:100]}`", "photo": None}

        # 9. GUI: Press Key (/key enter or key: esc)
        if user_text.startswith(("/key ", "key: ")):
            k = re.sub(r"^(/key |key: )", "", user_text).strip()
            ok = os_bridge.press_key(k)
            memory_logger.log_entry("GUI_KEY_PRESS", f"Pressed key: {k}", details={"key": k, "success": ok})
            return {"text": f"🔘 Pressed key *{k.upper()}*", "photo": None}

        # 10. GUI: Hotkey (/hotkey ctrl+v or hotkey: alt+tab)
        if user_text.startswith(("/hotkey ", "hotkey: ")):
            hk = re.sub(r"^(/hotkey |hotkey: )", "", user_text).strip()
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

        # Check if LLM emitted a JSON tool call
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", reply_raw, re.DOTALL)
        if json_match:
            try:
                action_data = json.loads(json_match.group(1))
                act = action_data.get("action")
                params = action_data.get("parameters", {})

                if act == "take_screenshot":
                    out_file = config.SCREENSHOTS_DIR / f"shot_{int(time.time())}.jpg"
                    ok = os_bridge.take_screenshot(out_file)
                    return {"text": "📸 *Desktop Screenshot Captured!*", "photo": str(out_file) if ok else None}

                elif act == "get_system_stats":
                    stats = os_bridge.get_system_stats()
                    return {"text": f"📊 *System Stats:* CPU: {stats.get('cpu_cores')} cores | RAM: {stats.get('ram_used_pct')}% used | Disk: {stats.get('disk_free_gb')} GB free", "photo": None}

                elif act == "execute_command":
                    cmd = params.get("command", "")
                    res = os_bridge.run_command(cmd)
                    return {"text": f"Output:\n```\n{(res['stdout'] or res['stderr'])[:3500]}\n```", "photo": None}

                elif act == "launch_app":
                    app = params.get("app_name", "")
                    os_bridge.launch_app(app)
                    return {"text": f"🚀 Launched *{app}* on PC!", "photo": None}

                elif act == "lock_pc":
                    os_bridge.lock_workstation()
                    return {"text": "🔒 *Workstation Locked!*", "photo": None}

                elif act == "mouse_click":
                    x = params.get("x")
                    y = params.get("y")
                    btn = params.get("button", "left")
                    dbl = params.get("double", False)
                    os_bridge.mouse_click(x, y, btn, dbl)
                    return {"text": f"🖱️ Clicked at ({x}, {y})", "photo": None}

                elif act == "type_text":
                    txt = params.get("text", "")
                    os_bridge.type_text(txt)
                    return {"text": f"⌨️ Typed: `{txt}`", "photo": None}

                elif act == "press_key":
                    k = params.get("key", "enter")
                    os_bridge.press_key(k)
                    return {"text": f"🔘 Pressed key *{k.upper()}*", "photo": None}

                elif act == "press_hotkey":
                    hk = params.get("hotkey", "")
                    os_bridge.press_hotkey(hk)
                    return {"text": f"⚡ Pressed hotkey *{hk.upper()}*", "photo": None}

            except Exception:
                pass

        # Return standard conversational reply
        return {"text": reply_raw, "photo": None}
