"""Telegram Bot API client: messages, photos, documents, inline buttons, file downloads."""
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config

MAX_TEXT = 4000  # Telegram limit is 4096 characters per message


def get_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def _post(method: str, timeout: int = 15, **kwargs) -> dict:
    try:
        return requests.post(get_api_url(method), timeout=timeout, **kwargs).json()
    except Exception as e:
        print(f"[Telegram Client] {method} error: {e}")
        return {"ok": False, "error": str(e)}


def _is_parse_error(data: dict) -> bool:
    return not data.get("ok") and "can't parse entities" in str(data.get("description", "")).lower()


def send_message(chat_id: str, text: str, parse_mode: str = "Markdown", reply_markup: dict = None) -> dict:
    """Sends text (split into several messages if longer than Telegram's limit)."""
    text = text or "(empty)"
    chunks = [text[i:i + MAX_TEXT] for i in range(0, len(text), MAX_TEXT)]
    data = {}
    for idx, chunk in enumerate(chunks):
        payload = {"chat_id": chat_id, "text": chunk}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup and idx == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        data = _post("sendMessage", json=payload)
        if _is_parse_error(data):
            payload.pop("parse_mode", None)
            data = _post("sendMessage", json=payload)
    return data


def edit_message(chat_id: str, message_id: int, text: str, parse_mode: str = "Markdown", reply_markup: dict = None) -> dict:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": (text or "(empty)")[:MAX_TEXT]}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    data = _post("editMessageText", json=payload)
    if _is_parse_error(data):
        payload.pop("parse_mode", None)
        data = _post("editMessageText", json=payload)
    return data


def _send_file(method: str, field: str, chat_id: str, path: str, caption: str, parse_mode: str) -> dict:
    path_obj = Path(path)
    if not path_obj.exists():
        print(f"[Telegram Client] File not found: {path}")
        return {"ok": False, "error": "File not found"}
    data = {"chat_id": chat_id, "caption": (caption or "")[:1000]}
    if parse_mode:
        data["parse_mode"] = parse_mode
    try:
        with open(path_obj, "rb") as f:
            res = requests.post(get_api_url(method), data=data, files={field: (path_obj.name, f)}, timeout=120).json()
        if _is_parse_error(res):
            data.pop("parse_mode", None)
            with open(path_obj, "rb") as f:
                res = requests.post(get_api_url(method), data=data, files={field: (path_obj.name, f)}, timeout=120).json()
        return res
    except Exception as e:
        print(f"[Telegram Client] {method} error: {e}")
        return {"ok": False, "error": str(e)}


def send_photo(chat_id: str, photo_path: str, caption: str = "", parse_mode: str = "Markdown") -> dict:
    res = _send_file("sendPhoto", "photo", chat_id, photo_path, caption, parse_mode)
    if not res.get("ok") and Path(photo_path).exists():  # e.g. too large / odd dimensions -> send as file
        res = send_document(chat_id, photo_path, caption, parse_mode)
    return res


def send_document(chat_id: str, file_path: str, caption: str = "", parse_mode: str = "Markdown") -> dict:
    return _send_file("sendDocument", "document", chat_id, file_path, caption, parse_mode)


def answer_callback(callback_query_id: str, text: str = "") -> dict:
    return _post("answerCallbackQuery", timeout=5, json={"callback_query_id": callback_query_id, "text": text[:190]})


def send_chat_action(chat_id: str, action: str = "typing") -> dict:
    return _post("sendChatAction", timeout=5, json={"chat_id": chat_id, "action": action})


def download_file(file_id: str, dest: Path) -> Path:
    """Downloads a Telegram file (max 20 MB for bots) to `dest` and returns the path."""
    info = _post("getFile", json={"file_id": file_id})
    if not info.get("ok"):
        raise RuntimeError(info.get("description") or info.get("error") or "getFile failed")
    file_path = info["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{file_path}"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
    return dest


def send_approval_card(chat_id: str, title: str, description: str, callback_key: str) -> dict:
    text = (
        f"🚨 *APPROVAL REQUIRED*\n\n"
        f"📌 *Task:* {title}\n"
        f"📝 *Details:* {description}\n\n"
        f"Tap to approve or cancel:"
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"appr:{callback_key}"},
            {"text": "❌ Cancel", "callback_data": f"canc:{callback_key}"},
        ]]
    }
    return send_message(chat_id, text, reply_markup=reply_markup)
