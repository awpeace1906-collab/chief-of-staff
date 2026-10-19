"""AI provider settings and per-task routing.

Each task the assistant does goes through a named route. A route points at a
provider (Claude API, or a local model behind an OpenAI-compatible endpoint
such as Ollama or llama.cpp) and a model. Users change routes in
Settings → Advanced → AI. v0.1 only stores and resolves routes; calls arrive in v0.3.
"""

import sqlite3

from .store import get_setting

ROUTES = {
    "triage": "Sort mail and digests, spot commitments, classify items (high volume, simple)",
    "plan": "Build the brief, coverage check and proposals (reasoning across calendars)",
    "draft": "Write emails and messages for approval",
    "chat": "Answer texts, voice notes and calls",
}

PROVIDER_TYPES = {"anthropic", "openai-compatible"}

DEFAULT_AI = {
    "providers": {
        "anthropic": {"type": "anthropic", "enabled": True, "apiKeyEnv": "ANTHROPIC_API_KEY"},
        "local": {"type": "openai-compatible", "enabled": False, "baseUrl": "http://localhost:11434/v1"},
    },
    "routes": {
        "triage": {"provider": "anthropic", "model": "claude-haiku-5-5"},
        "plan": {"provider": "anthropic", "model": "claude-opus-5-5"},
        "draft": {"provider": "anthropic", "model": "claude-opus-5-5"},
        "chat": {"provider": "anthropic", "model": "claude-opus-5-5"},
    },
}


def ai_settings(conn: sqlite3.Connection) -> dict:
    return get_setting(conn, "ai", DEFAULT_AI)


def validate(ai: dict) -> None:
    if not isinstance(ai, dict):
        raise ValueError("ai settings must be an object")
    providers = ai.get("providers", {})
    for name, p in providers.items():
        if p.get("type") not in PROVIDER_TYPES:
            raise ValueError(f"provider '{name}' has unknown type '{p.get('type')}'")
        if p["type"] == "openai-compatible" and not p.get("baseUrl"):
            raise ValueError(f"provider '{name}' needs a baseUrl")
    for route, r in ai.get("routes", {}).items():
        if route not in ROUTES:
            raise ValueError(f"unknown route '{route}'")
        if r.get("provider") not in providers:
            raise ValueError(f"route '{route}' uses unknown provider '{r.get('provider')}'")
        if not r.get("model"):
            raise ValueError(f"route '{route}' needs a model")


def resolve(conn: sqlite3.Connection, route: str) -> dict:
    """Provider config and model for a route; raises if the route can't run."""
    ai = ai_settings(conn)
    r = ai["routes"].get(route) or DEFAULT_AI["routes"][route]
    provider = ai["providers"][r["provider"]]
    if not provider.get("enabled"):
        raise RuntimeError(f"route '{route}' points at disabled provider '{r['provider']}'")
    return {"route": route, "provider": r["provider"], "model": r["model"], **provider}
