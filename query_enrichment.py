import json
import re
from typing import List

from llm_client import llm_complete

_FILLERS = {
    "like", "kinda", "sorta", "basically", "literally", "so", "just", "really",
}

_SYSTEM = """You normalize vague customer device complaints into a single
canonical technical query (5-10 words, no filler words) and generate 8-10
distinct paraphrases of that same complaint spanning formal, casual,
keyword-only, frustrated, and typo-inclusive registers. Respond with ONLY a JSON object:
{"canonical": "...", "variations": ["...", ...]}. No prose, no markdown fences."""


def _strip_fillers(text: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9']+", text) if w.lower() not in _FILLERS]
    return " ".join(words)


def _clean_json_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def enrich_query(raw_complaint: str) -> dict:
    """Normalizes a raw complaint and extracts 8-10 query variations across registers."""
    prompt = f'query: "{raw_complaint}"\n\nNormalize and generate 8-10 paraphrases across formal, casual, keyword, frustrated, and typo registers.'
    raw, usage = llm_complete(_SYSTEM, prompt, return_usage=True)

    canonical = _strip_fillers(raw_complaint)
    variations: List[str] = []
    try:
        parsed = json.loads(_clean_json_markdown(raw))
        if parsed.get("canonical"):
            canonical = parsed["canonical"]
        if isinstance(parsed.get("variations"), list):
            variations = [str(v).strip() for v in parsed["variations"] if str(v).strip()]
    except (json.JSONDecodeError, AttributeError):
        pass

    # Ensure 8-10 distinct variations across registers
    seen = set()
    deduped = []
    for v in variations:
        v_clean = re.sub(r"\s+", " ", v).strip()
        if v_clean.lower() not in seen and v_clean.lower() != canonical.lower():
            seen.add(v_clean.lower())
            deduped.append(v_clean)

    if len(deduped) < 8:
        for mv in _mechanical_variations(canonical, raw_complaint):
            if mv.lower() not in seen:
                seen.add(mv.lower())
                deduped.append(mv)
            if len(deduped) >= 10:
                break

    final_variations = deduped[:10]

    return {
        "canonical_query": canonical,
        "cache_key": _make_cache_key(canonical),
        "query_variations": final_variations,
        "usage": usage,
    }


def _mechanical_variations(canonical: str, raw_complaint: str = "") -> List[str]:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", canonical) if len(w) > 0]
    base_lower = canonical.lower()
    kw = " ".join(words[:4]).lower() if words else base_lower
    src = raw_complaint.strip() if raw_complaint else canonical

    # Typo simulation: swap adjacent letters in first long word
    typo_str = base_lower
    for w in words:
        if len(w) > 4:
            swapped = w[0] + w[2] + w[1] + w[3:]
            typo_str = base_lower.replace(w.lower(), swapped.lower(), 1)
            break

    return [
        f"Device configuration assistance for {base_lower}",            # formal
        f"My phone is having an issue where {base_lower}",             # casual
        kw,                                                            # keyword-only
        f"Why does my phone keep doing this: {base_lower}!",           # frustrated
        typo_str,                                                      # typo-inclusive
        f"How to fix {base_lower} on Samsung Galaxy?",                 # interrogative
        f"Troubleshooting steps for {base_lower}",                     # technical
        f"Samsung One UI {base_lower} settings",                       # device-specific
        f"Need help resolving {base_lower}",                           # colloquial
        src if src.lower() != base_lower else f"Cannot fix {base_lower}", # alternate
    ]


def _make_cache_key(canonical: str) -> str:
    words = sorted(set(w.lower() for w in re.findall(r"[a-z0-9]+", canonical.lower())))
    return "|".join(words)
