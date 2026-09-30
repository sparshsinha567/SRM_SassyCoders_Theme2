import os
import json
import re
import time
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def is_real_llm() -> bool:
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )


USE_REAL_LLM = is_real_llm()

_PRICING_PER_1M = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "gemini-flash-lite-latest": {"input": 0.075, "output": 0.30},
    "gemini-flash-latest": {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}
_DEFAULT_PRICING = {"input": 3.00, "output": 15.00}

import threading

_usage_log: list[dict] = []
_usage_lock = threading.Lock()


def reset_usage() -> None:
    with _usage_lock:
        _usage_log.clear()


def usage_summary() -> dict:
    with _usage_lock:
        input_tokens = sum(u.get("input_tokens", 0) for u in _usage_log)
        output_tokens = sum(u.get("output_tokens", 0) for u in _usage_log)
        cost = sum(u.get("cost_usd", 0.0) for u in _usage_log)
        return {
            "calls": len(_usage_log),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        }


def _record_usage(input_tokens: int, output_tokens: int, cost_usd: float, model: str) -> None:
    with _usage_lock:
        _usage_log.append({
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "model": model,
        })


def get_active_model_name() -> str:
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    return "stub"


def llm_complete(system: str, prompt: str, model: Optional[str] = None, return_usage: bool = False):
    """Dispatches completion request to configured LLM provider or deterministic stub."""
    if os.environ.get("FORCE_STUB") == "1":
        usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model": "stub"}
        text = _stub_complete(system, prompt)
        _record_usage(0, 0, 0.0, "stub")
        return (text, usage) if return_usage else text

    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        try:
            m = model or os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
            text, usage = _call_gemini(system, prompt, m)
            return (text, usage) if return_usage else text
        except Exception as e:
            print(f"[llm_client] Remote Gemini call failed ({e}); falling back to deterministic stub.")

    if os.environ.get("OPENAI_API_KEY"):
        try:
            m = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            text, usage = _call_openai(system, prompt, m)
            return (text, usage) if return_usage else text
        except Exception as e:
            print(f"[llm_client] Remote OpenAI call failed ({e}); falling back to deterministic stub.")

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            m = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            text, usage = _call_anthropic(system, prompt, m)
            return (text, usage) if return_usage else text
        except Exception as e:
            print(f"[llm_client] Remote Anthropic call failed ({e}); falling back to deterministic stub.")

    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model": "stub"}
    text = _stub_complete(system, prompt)
    _record_usage(0, 0, 0.0, "stub")
    return (text, usage) if return_usage else text


def _call_gemini(system: str, prompt: str, model: str) -> tuple[str, dict]:
    import requests

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1024},
    }

    resp = None
    for attempt in range(4):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            resp.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 3 and resp is not None:
                resp.raise_for_status()
            time.sleep(1.5)

    if resp is None or resp.status_code != 200:
        return "", {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model": model}
    data = resp.json()

    usage_data = data.get("usageMetadata", {})
    in_tok = usage_data.get("promptTokenCount", 0)
    out_tok = usage_data.get("candidatesTokenCount", 0)
    rates = _PRICING_PER_1M.get(model, {"input": 0.075, "output": 0.30})
    cost = (in_tok / 1_000_000) * rates["input"] + (out_tok / 1_000_000) * rates["output"]
    usage = {"input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": round(cost, 6), "model": model}
    _record_usage(in_tok, out_tok, cost, model)

    candidates = data.get("candidates", [])
    if candidates and "content" in candidates[0]:
        parts = candidates[0]["content"].get("parts", [])
        return "".join(p.get("text", "") for p in parts), usage
    return "", usage


def _call_openai(system: str, prompt: str, model: str) -> tuple[str, dict]:
    import requests

    key = os.environ.get("OPENAI_API_KEY")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    usage_data = data.get("usage", {})
    in_tok = usage_data.get("prompt_tokens", 0)
    out_tok = usage_data.get("completion_tokens", 0)
    rates = _PRICING_PER_1M.get(model, {"input": 0.15, "output": 0.60})
    cost = (in_tok / 1_000_000) * rates["input"] + (out_tok / 1_000_000) * rates["output"]
    usage = {"input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": round(cost, 6), "model": model}
    _record_usage(in_tok, out_tok, cost, model)
    return data["choices"][0]["message"]["content"], usage


def _call_anthropic(system: str, prompt: str, model: str) -> tuple[str, dict]:
    import requests

    key = os.environ.get("ANTHROPIC_API_KEY")
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 1024,
        "temperature": 0.0,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    rates = _PRICING_PER_1M.get(model, _DEFAULT_PRICING)
    usage_data = data.get("usage", {})
    input_tokens = usage_data.get("input_tokens", 0)
    output_tokens = usage_data.get("output_tokens", 0)
    cost = (input_tokens / 1_000_000) * rates["input"] + (output_tokens / 1_000_000) * rates["output"]
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": round(cost, 6), "model": model}
    _record_usage(input_tokens, output_tokens, cost, model)
    content = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    return content, usage


def _stub_complete(system: str, prompt: str) -> str:
    m = re.search(r'"?query"?\s*[:=]\s*"([^"]+)"', prompt)
    query = m.group(1) if m else "device issue"
    base_lower = query.strip().lower()

    if "paraphrases" in prompt.lower() or "normalize" in prompt.lower():
        canonical = query.strip()
        words = re.findall(r"[A-Za-z0-9]+", base_lower)
        kw = " ".join(words[:3]) if words else base_lower
        variations = [
            f"Device configuration assistance for {base_lower}",      # formal
            f"My phone is having an issue where {base_lower}",       # casual
            kw,                                                      # keyword-only
            f"Why does my phone keep doing this: {base_lower}!",     # frustrated
            f"phne {base_lower}",                                    # typo-inclusive
            f"How to fix {base_lower} on Samsung Galaxy?",           # interrogative
            f"Troubleshooting steps for {base_lower}",               # technical
            f"Samsung One UI {base_lower} settings",                 # device-specific
        ]
        return json.dumps({"canonical": canonical, "variations": variations})

    topic = _short_title(query).title()
    goal = {
        "goal": f"Follow these steps to perform this {topic} Troubleshooting",
        "title": _short_title(query),
        "score": 0.55,
        "actions": [
            {
                "actionName": "Review Relevant Settings",
                "description": "It will let you check related options",
                "category": "auto",
                "stepGroups": [
                    {
                        "steps": [
                            "Navigate to and open Settings.",
                            f"Locate the option related to: {query}.",
                        ]
                    }
                ],
            }
        ],
    }
    return json.dumps(goal)


def _short_title(query: str) -> str:
    words = re.findall(r"[A-Za-z]+", query)[:3]
    if len(words) < 2:
        words = words + ["settings"] if words else ["device", "issue"]
    return words[0].capitalize() + " " + " ".join(w.lower() for w in words[1:])
