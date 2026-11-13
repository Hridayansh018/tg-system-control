"""LLM Router: Gemini, OpenRouter (Hermes 3 / Claude / any model), Groq, or offline.

The bot never lets a model execute things directly. Models are only used to
translate free text into commands from a fixed menu (see core/translator.py)
and, in agent mode, to pick the next UI action (see core/computer_agent.py).
"""
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config

GEMINI_TEXT_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
]


def active_provider() -> str:
    """Returns the configured provider, or 'offline' when its API key is missing."""
    provider = config.LLM_PROVIDER
    keys = {
        "gemini": config.GEMINI_API_KEY,
        "openrouter": config.OPENROUTER_API_KEY,
        "groq": config.GROQ_API_KEY,
    }
    if provider in keys and keys[provider]:
        return provider
    return "offline"


def _gemini_models(override: str, defaults: list) -> list:
    models = [m.strip() for m in (override or "").split(",") if m.strip()]
    return models + [m for m in defaults if m not in models]


def call_gemini(prompt: str, system_prompt: str, *, json_schema: dict = None, image_parts: list = None,
                models: list = None, timeout: int = 30) -> dict:
    """Calls Gemini with model fallback. Returns {"reply": text} or {"error": msg}.

    json_schema: Gemini responseSchema (OpenAPI subset) -> reply is a JSON string.
    image_parts: list of {"mime_type": ..., "data": base64} added before the text.
    """
    key = config.GEMINI_API_KEY
    if not key:
        return {"error": "GEMINI_API_KEY is not set in .env"}

    parts = [{"inline_data": p} for p in (image_parts or [])]
    parts.append({"text": prompt})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
    }
    if json_schema:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseSchema": json_schema,
            "temperature": 0.1,
        }

    last_error = "Unknown error"
    for model_name in models or _gemini_models(config.GEMINI_MODEL, GEMINI_TEXT_MODELS):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        try:
            res = requests.post(url, params={"key": key}, json=payload, timeout=timeout)
            data = res.json()
            if "error" in data:
                last_error = data["error"].get("message", f"Gemini {model_name} error")
                continue
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                texts = [p["text"] for p in candidates[0]["content"].get("parts", []) if "text" in p]
                if texts:
                    return {"reply": "".join(texts), "model": model_name}
            last_error = f"Gemini {model_name} returned no text"
        except Exception as e:
            last_error = f"Gemini connection error on {model_name}: {e}"
    return {"error": last_error}


def _call_openai_compatible(url: str, key: str, model: str, prompt: str, system_prompt: str,
                            json_mode: bool, extra_headers: dict = None, timeout: int = 30) -> dict:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
        payload["temperature"] = 0.1
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=timeout)
        data = res.json()
        if "error" in data:
            err = data["error"]
            return {"error": err.get("message", str(err)) if isinstance(err, dict) else str(err)}
        return {"reply": data["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"error": f"Connection error: {e}"}


def call_openrouter(prompt: str, system_prompt: str, json_mode: bool = False) -> dict:
    if not config.OPENROUTER_API_KEY:
        return {"error": "OPENROUTER_API_KEY is not set in .env"}
    return _call_openai_compatible(
        "https://openrouter.ai/api/v1/chat/completions", config.OPENROUTER_API_KEY, config.OPENROUTER_MODEL,
        prompt, system_prompt, json_mode,
        extra_headers={"HTTP-Referer": "https://github.com/tg-system-control", "X-Title": "TG System Control"},
    )


def call_groq(prompt: str, system_prompt: str, json_mode: bool = False) -> dict:
    if not config.GROQ_API_KEY:
        return {"error": "GROQ_API_KEY is not set in .env"}
    return _call_openai_compatible(
        "https://api.groq.com/openai/v1/chat/completions", config.GROQ_API_KEY, "llama-3.3-70b-versatile",
        prompt, system_prompt, json_mode,
    )


def route_prompt(prompt: str, system_prompt: str) -> dict:
    """Plain-text completion via the configured provider ({"offline": True} if none)."""
    provider = active_provider()
    if provider == "gemini":
        return call_gemini(prompt, system_prompt)
    if provider == "openrouter":
        return call_openrouter(prompt, system_prompt)
    if provider == "groq":
        return call_groq(prompt, system_prompt)
    return {"offline": True}


def extract_json(text: str):
    """Parses JSON from a model reply (tolerates ```json fences and surrounding prose)."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start >= 0:
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except Exception:
                continue
    raise ValueError("No JSON object found in model reply")


def route_json(prompt: str, system_prompt: str, schema: dict) -> dict:
    """JSON completion. Returns {"data": obj} | {"error": msg} | {"offline": True}."""
    provider = active_provider()
    if provider == "offline":
        return {"offline": True}
    if provider == "gemini":
        res = call_gemini(prompt, system_prompt, json_schema=schema)
    else:
        sys_with_schema = system_prompt + "\n\nReply ONLY with a JSON object matching this schema:\n" + json.dumps(schema)
        res = (call_openrouter if provider == "openrouter" else call_groq)(prompt, sys_with_schema, json_mode=True)
    if "error" in res:
        return res
    try:
        return {"data": extract_json(res["reply"])}
    except Exception as e:
        return {"error": f"Model reply was not valid JSON: {e}"}
