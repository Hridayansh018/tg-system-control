"""Telegram API client for sending messages, photos, and interactive buttons."""
import json
from pathlib import Path
import requests
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config


def get_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def send_message(chat_id: str, text: str, parse_mode: str = "Markdown", reply_markup: dict = None) -> dict:
    url = get_api_url("sendMessage")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        res = requests.post(url, json=payload, timeout=15)
        data = res.json()
        if not data.get("ok") and "can't parse entities" in data.get("description", "").lower():
            # Retry without parse_mode
            payload.pop("parse_mode", None)
            res = requests.post(url, json=payload, timeout=15)
            data = res.json()
        return data
    except Exception as e:
        print(f"[Telegram Client] sendMessage error: {e}")
        return {"ok": False, "error": str(e)}


def send_photo(chat_id: str, photo_path: str, caption: str = "", parse_mode: str = "Markdown") -> dict:
    url = get_api_url("sendPhoto")
    path_obj = Path(photo_path)
    if not path_obj.exists():
        print(f"[Telegram Client] Photo path not found: {photo_path}")
        return {"ok": False, "error": "File not found"}

    data = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": parse_mode,
    }
    try:
        with open(path_obj, "rb") as f:
            res = requests.post(url, data=data, files={"photo": f}, timeout=60)
            return res.json()
    except Exception as e:
        print(f"[Telegram Client] sendPhoto error: {e}")
        return {"ok": False, "error": str(e)}


def send_approval_card(chat_id: str, title: str, description: str, callback_key: str) -> dict:
    text = (
        f"🚨 *APPROVAL REQUIRED*\n\n"
        f"📌 *Task:* {title}\n"
        f"📝 *Details:* {description}\n\n"
        f"Please tap below to approve or cancel:"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"appr:{callback_key}"},
                {"text": "❌ Cancel", "callback_data": f"canc:{callback_key}"},
            ]
        ]
    }
    return send_message(chat_id, text, reply_markup=reply_markup)
