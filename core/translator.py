"""Gemini (or other provider) as a TRANSLATOR only.

Free text / Hinglish is converted into commands from a fixed menu. The model never
executes anything itself: the returned commands are validated here and then run by the
same local handlers that serve typed commands.
"""
from . import llm_router

# command name -> (needs_arg, description shown to the model)
COMMAND_MENU = {
    "open": (True, "Open an installed app or website. arg = app/site name, e.g. 'spotify', 'edge', 'youtube studio', 'gmail app'."),
    "close": (True, "Close an app, a website tab, or the active window. arg = app/site name, 'tab', or 'window'."),
    "status": (False, "Show CPU / RAM / disk / OS status."),
    "screenshot": (False, "Capture the screen and send it."),
    "processes": (False, "List top running processes."),
    "lock": (False, "Lock the PC screen."),
    "type": (True, "Type text into the focused window. arg = exact text to type."),
    "type_enter": (True, "Type text and press Enter (submit). arg = exact text."),
    "press": (True, "Press one key. arg = enter, tab, esc, space, backspace, up, down, f5, ..."),
    "hotkey": (True, "Press a key combination. arg = e.g. 'ctrl+w', 'alt+tab', 'win+d', 'ctrl+shift+t'."),
    "focus": (True, "Bring an open window to the front. arg = part of its title, e.g. 'chatgpt', 'notepad'."),
    "chatgpt": (True, "Open ChatGPT in Edge, start a new chat and submit a prompt. arg = the full prompt in English."),
    "send_latest_download": (False, "Send the newest file from the Downloads folder to the user's phone."),
    "send_file": (True, "Send a file from the PC to the user's phone. arg = file name or path."),
    "studio": (True, "Control the separate Video Studio bot (the video pipeline's own Telegram bot). "
                     "arg = start, stop, restart, status or logs."),
    "remember": (True, "Save a note to the bot's long-term memory. arg = the fact to remember, in English."),
    "thumbnails": (False, "Generate YouTube thumbnails with ChatGPT in Edge, download them and send them. "
                          "arg = video name (e.g. 'luffy marineford p2') or a thumbnail idea; empty = the video in "
                          "READY_TO_UPLOAD."),
    "ytupload": (False, "Upload + schedule the video to YouTube Studio from READY_TO_UPLOAD metadata. "
                        "arg = '' to upload, 'check' to only verify the metadata, or a folder path."),
    "studio_session": (False, "Start Antigravity and a NEW session for the video pipeline (video generation, "
                              "status, scripts...), connected to the Video Studio bot. arg = the task in English, "
                              "e.g. 'start a new One Piece what-if video, 40 min' (empty = check status)."),
}

# Extra commands only offered when agent mode / extra controls are available.
EXTRA_MENU = {
    "volume": (True, "Change volume. arg = up, down or mute."),
    "media": (True, "Media control. arg = play, pause, next or prev."),
    "windows": (False, "List open windows."),
    "clipboard_get": (False, "Send the PC clipboard text to the user."),
    "clipboard_set": (True, "Copy text to the PC clipboard. arg = the text."),
    "scroll": (True, "Scroll the active window. arg = up or down."),
}

MAX_COMMANDS = 6


def _menu(include_extra: bool) -> dict:
    menu = dict(COMMAND_MENU)
    if include_extra:
        menu.update(EXTRA_MENU)
    return menu


def _schema(menu: dict) -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "kind": {"type": "STRING", "enum": ["commands", "agent_task", "chat"]},
            "english": {"type": "STRING"},
            "commands": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "command": {"type": "STRING", "enum": list(menu)},
                        "arg": {"type": "STRING"},
                    },
                    "required": ["command"],
                },
            },
            "agent_task": {"type": "STRING"},
            "reply": {"type": "STRING"},
        },
        "required": ["kind"],
    }


def _system_prompt(menu: dict, agent_available: bool) -> str:
    lines = [f"- {name}: {desc}" for name, (_, desc) in menu.items()]
    agent_rule = (
        '- kind="agent_task": the request needs several steps on screen that the menu cannot express '
        '(e.g. "chatgpt me 3 thumbnail banao aur download karke bhejo", "downloads me sabse badi file dhoondo aur bhejo"). '
        'Put a clear, complete English task in "agent_task".'
        if agent_available else
        '- kind="agent_task": multi-step on-screen tasks the menu cannot express; put the English task in "agent_task".'
    )
    return (
        "You translate messages sent from a phone (English, Hindi, or Hinglish) into commands for a PC remote-control bot.\n"
        "You NEVER execute anything; you only translate. Allowed commands:\n" + "\n".join(lines) + "\n\n"
        "Rules:\n"
        '- kind="commands": the message is an instruction that maps to 1-6 menu commands, in order. '
        'Example: "spotify kholo aur edge band karo" -> open spotify, close edge.\n'
        + agent_rule + "\n"
        '- kind="chat": greetings, questions, feedback, complaints, or anything that is not an instruction to act. '
        'Put a short helpful reply in the user\'s language in "reply". Do not invent commands for these.\n'
        '- Never output shell commands. If the user wants a shell command they must use /exec themselves.\n'
        '- Words like "band karo/hatao" mean close; "kholo/chalao/open karo" mean open; "bhejo" means send.\n'
        '- Always fill "english" with a short English version of what the user asked.'
    )


def translate(user_text: str, agent_available: bool = False, context: str = "") -> dict:
    """Returns one of:
    {"kind": "commands", "commands": [(name, arg)], "english": str}
    {"kind": "agent_task", "task": str, "english": str}
    {"kind": "chat", "reply": str, "english": str}
    {"kind": "offline"} | {"kind": "error", "error": str}
    """
    menu = _menu(include_extra=agent_available)
    prompt = user_text
    if context:
        prompt = (
            "MEMORY (use it to understand references like 'it', 'usko', 'wahi wala', and to answer questions "
            "about earlier messages; do NOT repeat old commands unless the new message asks for it):\n"
            f"{context[:4000]}\n\nNEW MESSAGE TO TRANSLATE:\n{user_text}"
        )
    res = llm_router.route_json(prompt, _system_prompt(menu, agent_available), _schema(menu))
    if res.get("offline"):
        return {"kind": "offline"}
    if "error" in res:
        return {"kind": "error", "error": res["error"]}
    return validate(res.get("data"), menu)


def validate(data, menu: dict = None) -> dict:
    """Validates the model's JSON. Unknown commands are dropped, never executed."""
    menu = menu or _menu(include_extra=True)
    if not isinstance(data, dict):
        return {"kind": "error", "error": "Translator returned an unexpected format"}
    kind = data.get("kind")
    english = str(data.get("english") or "").strip()

    if kind == "agent_task":
        task = str(data.get("agent_task") or english).strip()
        if task:
            return {"kind": "agent_task", "task": task[:1000], "english": english}
        return {"kind": "chat", "reply": "Samajh nahi aaya, thoda detail mein batao?", "english": english}

    if kind == "commands":
        commands, dropped = [], []
        for item in (data.get("commands") or [])[:MAX_COMMANDS]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("command") or "").strip()
            arg = str(item.get("arg") or "").strip()[:2000]
            if name not in menu:
                dropped.append(name)
                continue
            needs_arg = menu[name][0]
            if needs_arg and not arg and name != "close":
                dropped.append(name)
                continue
            commands.append((name, arg))
        if commands:
            return {"kind": "commands", "commands": commands, "english": english, "dropped": dropped}
        return {"kind": "chat", "reply": str(data.get("reply") or "Koi valid command nahi mila. /help dekho."), "english": english}

    reply = str(data.get("reply") or "").strip() or "👍"
    return {"kind": "chat", "reply": reply[:3000], "english": english}
