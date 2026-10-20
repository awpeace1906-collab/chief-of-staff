"""Model calls: one entry point for every route, with usage logging.

Every call returns JSON that matches the caller's schema (structured outputs).
The stable instructions go in a cached system block; per-run data goes in the
user message, so repeated runs reuse the cache.
"""

import json
import os
import sqlite3

import anthropic
import httpx

from . import ai
from .db import now

# USD per million tokens (Anthropic list prices, Oct 2026): input, output, cache read.
# Cache writes bill at 1.25x input. Used only for the usage estimate.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
}

# Models that take the server-side refusal fallback ("default" routing).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"}


class ModelError(RuntimeError):
    pass


def complete(conn: sqlite3.Connection, route: str, system: str, user: str, schema: dict,
             max_tokens: int = 16000, client: anthropic.Anthropic | None = None, http: httpx.Client | None = None) -> dict:
    """Run one structured-output request on `route` and return the parsed JSON."""
    cfg = ai.resolve(conn, route)
    if cfg["type"] == "openai-compatible":
        return _complete_local(conn, route, cfg, system, user, schema, max_tokens, http)
    client = client or anthropic.Anthropic()

    params = dict(
        model=cfg["model"],
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": cfg["effort"], "format": {"type": "json_schema", "schema": schema}},
    )
    try:
        if cfg["model"] in FALLBACK_MODELS:
            response = client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
            )
        else:
            response = client.messages.create(**params)
    except anthropic.AuthenticationError:
        raise ModelError("the Anthropic API key is missing or invalid (set ANTHROPIC_API_KEY)")
    except anthropic.RateLimitError:
        raise ModelError("Anthropic rate limit hit; try again in a minute")
    except anthropic.APIStatusError as e:
        raise ModelError(f"Anthropic API error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise ModelError("could not reach the Anthropic API")

    _log_usage(conn, route, cfg, response)

    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None) if response.stop_details else None
        raise ModelError(f"the model declined this request (category: {category})")
    if response.stop_reason == "max_tokens":
        raise ModelError(f"route '{route}' ran out of output tokens ({max_tokens}); raise max_tokens")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ModelError("the model returned no text")
    return json.loads(text)


def _complete_local(conn, route: str, cfg: dict, system: str, user: str, schema: dict, max_tokens: int,
                    http: httpx.Client | None) -> dict:
    """A local model behind an OpenAI-compatible endpoint (Ollama, llama.cpp server, vLLM, LM Studio)."""
    http = http or httpx.Client(timeout=300)
    headers = {}
    if cfg.get("apiKeyEnv") and os.environ.get(cfg["apiKeyEnv"]):
        headers["Authorization"] = f"Bearer {os.environ[cfg['apiKeyEnv']]}"
    try:
        r = http.post(cfg["baseUrl"].rstrip("/") + "/chat/completions", headers=headers, json={
            "model": cfg["model"],
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
        })
    except httpx.HTTPError as e:
        raise ModelError(f"could not reach the local model at {cfg['baseUrl']} ({e.__class__.__name__})")
    if not r.is_success:
        raise ModelError(f"local model returned {r.status_code}: {r.text[:200]}")
    data = r.json()
    usage = data.get("usage") or {}
    choice = (data.get("choices") or [{}])[0]
    conn.execute(
        """INSERT INTO ai_usage (at, route, provider, model, input, output, stop_reason) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (now(), route, cfg["provider"], data.get("model") or cfg["model"], usage.get("prompt_tokens", 0),
         usage.get("completion_tokens", 0), choice.get("finish_reason")),
    )
    conn.commit()
    if choice.get("finish_reason") == "length":
        raise ModelError(f"route '{route}' ran out of output tokens ({max_tokens}); raise max_tokens")
    try:
        return json.loads((choice.get("message") or {}).get("content") or "")
    except json.JSONDecodeError:
        raise ModelError("the local model didn't return valid JSON; try a larger model for this route")


def _log_usage(conn: sqlite3.Connection, route: str, cfg: dict, response) -> None:
    u = response.usage
    conn.execute(
        """INSERT INTO ai_usage (at, route, provider, model, input, output, cache_read, cache_write, stop_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (now(), route, cfg["provider"], response.model or cfg["model"], u.input_tokens, u.output_tokens,
         u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0, response.stop_reason),
    )
    conn.commit()


def usage_summary(conn: sqlite3.Connection, days: int = 30) -> dict:
    """Token totals and estimated cost per route and model over the last `days`."""
    rows = conn.execute(
        """SELECT route, model, COUNT(*) AS calls, SUM(input) AS input, SUM(output) AS output,
                  SUM(cache_read) AS cache_read, SUM(cache_write) AS cache_write
           FROM ai_usage WHERE at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)
           GROUP BY route, model ORDER BY route""",
        (f"-{int(days)} days",),
    ).fetchall()
    out, total = [], 0.0
    for r in rows:
        price = PRICES.get(r["model"])
        cost = None
        if price:
            p_in, p_out, p_read = price
            cost = (r["input"] * p_in + r["output"] * p_out + r["cache_read"] * p_read
                    + r["cache_write"] * p_in * 1.25) / 1_000_000
            total += cost
        out.append(dict(r) | {"estimatedUsd": round(cost, 4) if cost is not None else None})
    return {"days": days, "routes": out, "estimatedUsd": round(total, 4)}


def run_tools(conn: sqlite3.Connection, route: str, system: str, user: str, tools: list[dict],
              handlers: dict, finish: set[str], max_steps: int = 12, max_tokens: int = 4000,
              client: anthropic.Anthropic | None = None) -> dict:
    """A tool-use loop on `route`. `handlers` maps tool name → function(input) returning JSON-able data
    (raise to report an error to the model). Stops when the model calls a tool in `finish`; returns
    {"tool": name, "input": {...}, "steps": n}. A model that just stops talking returns {"tool": None, "text": ...}."""
    cfg = ai.resolve(conn, route)
    if cfg["type"] != "anthropic":
        raise ModelError(f"route '{route}' uses a {cfg['type']} provider; tool use needs the Claude API")
    client = client or anthropic.Anthropic()
    messages = [{"role": "user", "content": user}]
    for step in range(1, max_steps + 1):
        params = dict(
            model=cfg["model"], max_tokens=max_tokens, tools=tools, messages=messages,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": cfg["effort"]},
        )
        try:
            if cfg["model"] in FALLBACK_MODELS:
                response = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
            else:
                response = client.messages.create(**params)
        except anthropic.AuthenticationError:
            raise ModelError("the Anthropic API key is missing or invalid (set ANTHROPIC_API_KEY)")
        except anthropic.RateLimitError:
            raise ModelError("Anthropic rate limit hit; try again in a minute")
        except anthropic.APIStatusError as e:
            raise ModelError(f"Anthropic API error {e.status_code}: {e.message}")
        except anthropic.APIConnectionError:
            raise ModelError("could not reach the Anthropic API")
        _log_usage(conn, route, cfg, response)
        if response.stop_reason == "refusal":
            raise ModelError("the model declined this request")
        calls = [b for b in response.content if b.type == "tool_use"]
        if not calls:
            text = "\n".join(b.text for b in response.content if b.type == "text").strip()
            return {"tool": None, "text": text, "steps": step}
        messages.append({"role": "assistant", "content": [_block(b) for b in response.content]})
        results = []
        for call in calls:
            if call.name in finish:
                return {"tool": call.name, "input": call.input, "steps": step}
            try:
                fn = handlers[call.name]
                out, is_error = json.dumps(fn(call.input or {}), ensure_ascii=False, default=str), False
            except Exception as e:  # tell the model; it can correct itself or give up
                out, is_error = f"{e.__class__.__name__}: {e}", True
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": out[:20000], "is_error": is_error})
        messages.append({"role": "user", "content": results})
    raise ModelError(f"route '{route}' didn't finish within {max_steps} steps")


def _block(b) -> dict:
    """A response content block as a request block (thinking blocks round-trip unchanged)."""
    if hasattr(b, "model_dump"):
        return b.model_dump(exclude_none=True)
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if b.type == "text":
        return {"type": "text", "text": b.text}
    return {k: v for k, v in vars(b).items()}
