"""LLM Router: Routes prompts to Gemini, OpenRouter (Hermes 3), Groq, or built-in offline handler."""
import json
import os
import requests
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config


def call_gemini(prompt: str, system_prompt: str, tools_schema: list = None) -> dict:
    """Calls Google AI Studio Gemini API."""
    key = config.GEMINI_API_KEY
    if not key:
        return {"error": "GEMINI_API_KEY is not set in .env"}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
    }
    try:
        res = requests.post(url, json=payload, timeout=25)
        data = res.json()
        if "error" in data:
            return {"error": data["error"].get("message", "Gemini API error")}
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return {"reply": text}
    except Exception as e:
        return {"error": f"Gemini connection error: {e}"}


def call_openrouter(prompt: str, system_prompt: str) -> dict:
    """Calls OpenRouter (Nous Hermes 3 / Llama 3.1)."""
    key = config.OPENROUTER_API_KEY
    if not key:
        return {"error": "OPENROUTER_API_KEY is not set in .env"}

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/tg-system-control",
        "X-Title": "TG System Control",
    }
    payload = {
        "model": config.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        data = res.json()
        if "error" in data:
            return {"error": data["error"].get("message", "OpenRouter error")}
        text = data["choices"][0]["message"]["content"]
        return {"reply": text}
    except Exception as e:
        return {"error": f"OpenRouter connection error: {e}"}


def call_groq(prompt: str, system_prompt: str) -> dict:
    """Calls Groq API."""
    key = config.GROQ_API_KEY
    if not key:
        return {"error": "GROQ_API_KEY is not set in .env"}

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        data = res.json()
        if "error" in data:
            return {"error": data["error"].get("message", "Groq error")}
        text = data["choices"][0]["message"]["content"]
        return {"reply": text}
    except Exception as e:
        return {"error": f"Groq connection error: {e}"}


def route_prompt(prompt: str, system_prompt: str) -> dict:
    """Routes prompt based on configured LLM_PROVIDER."""
    provider = config.LLM_PROVIDER
    if provider == "gemini":
        return call_gemini(prompt, system_prompt)
    elif provider == "openrouter":
        return call_openrouter(prompt, system_prompt)
    elif provider == "groq":
        return call_groq(prompt, system_prompt)
    else:
        return {"offline": True}
