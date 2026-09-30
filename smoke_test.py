"""
Runs the full pipeline end-to-end against the sample data, with no server
and no API key required (falls back to the deterministic stub LLM). Use
this first to confirm the wiring works before pointing it at a real model.

Run: python smoke_test.py
"""
import json
import time
from pathlib import Path

import os
from query_enrichment import enrich_query, _make_cache_key
from retrieval import DeeplinkIndex
from structure_extraction import build_response
from cache import SemanticCache

def _resolve_data_dir() -> Path:
    env_dir = os.getenv("DATA_DIR")
    if env_dir and Path(env_dir).exists():
        return Path(env_dir)
    candidates = [
        Path(__file__).resolve().parent.parent / "main data for submission",
        Path(__file__).resolve().parent / "main_data_for_submission",
    ]
    for c in candidates:
        if c.exists() and (c / "deeplinks.json").exists():
            return c
    return Path(__file__).resolve().parent / "main_data_for_submission"

DATA_DIR = _resolve_data_dir()


def run_query(query: str, index: DeeplinkIndex, cache: SemanticCache, siis_response: str | None = None):
    start = time.perf_counter()
    fast_key = _make_cache_key(query)
    cached, hit_type = cache.get(fast_key, query)

    if cached is not None:
        response = cached
        canonical = query
    else:
        enrichment = enrich_query(query)
        canonical = enrichment["canonical_query"]
        cached, hit_type = cache.get(enrichment["cache_key"], canonical)
        if cached is not None:
            response = cached
        else:
            response = build_response(query, siis_response, index)
            cache.set(enrichment["cache_key"], canonical, response)
            cache.set(fast_key, query, response)
            for var in enrichment["query_variations"]:
                cache.set(_make_cache_key(var), var, response)

    latency_ms = round((time.perf_counter() - start) * 1000, 1)

    print(f"\n--- Query: {query!r} ---")
    print(f"canonical: {canonical}")
    print(f"cache hit: {hit_type}   latency: {latency_ms}ms")
    print(json.dumps(response.model_dump(), indent=2)[:1200])


if __name__ == "__main__":
    print(f"Using DATA_DIR: {DATA_DIR}")
    print("Loading deeplink index...")
    index = DeeplinkIndex(str(DATA_DIR / "deeplinks.json"))
    cache = SemanticCache(embed_model=index._model)

    queries_path = DATA_DIR / "queries.json"
    if queries_path.exists():
        queries = json.loads(queries_path.read_text(encoding="utf-8"))
    else:
        queries = [{"query": "My phone screen is blank"}]

    siis_path = DATA_DIR / "siis_responses.json"
    siis_dict = {}
    if siis_path.exists():
        raw_siis = json.loads(siis_path.read_text(encoding="utf-8"))
        if isinstance(raw_siis, dict) and "responses" in raw_siis:
            for item in raw_siis["responses"]:
                sr = item.get("siis_response", {})
                content = sr.get("content", "") if isinstance(sr, dict) else str(sr)
                title = sr.get("title", "") if isinstance(sr, dict) else ""
                full_text = f"# {title}\n{content}" if title else content
                siis_dict[item.get("id")] = full_text
                siis_dict[item.get("original_query")] = full_text
        elif isinstance(raw_siis, list):
            for s in raw_siis:
                if "domain" in s:
                    siis_dict[s["domain"]] = s.get("text", "")

    for i, q in enumerate(queries[:5]):
        # Match by id or original_query or query string
        q_text = q["query"]
        siis_text = siis_dict.get(q.get("domain")) or siis_dict.get(q.get("raw_query")) or siis_dict.get(q_text)
        if not siis_text and siis_dict:
            # Fallback to closest match
            for k, val in siis_dict.items():
                if k and (k in q_text or q_text in k):
                    siis_text = val
                    break
        run_query(q_text, index, cache, siis_response=siis_text)

    # Re-run a colloquial paraphrase to test vector-based semantic cache generalization (bypasses exact-key tier)
    run_query("phone battery is running out extremely quickly", index, cache)

    print("\nCache stats:", cache.stats())
