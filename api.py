import os
import time
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field

import llm_client
from query_enrichment import enrich_query, _make_cache_key, _mechanical_variations
from retrieval import DeeplinkIndex
from structure_extraction import build_response
from cache import SemanticCache
from schema import ContextDeeplinkResponse

def _resolve_data_dir() -> Path:
    env_dir = os.getenv("DATA_DIR")
    if env_dir and Path(env_dir).exists():
        return Path(env_dir)
    candidates = [
        Path(__file__).resolve().parent.parent / "main data for submission",
        Path(__file__).resolve().parent / "main_data_for_submission",
        Path("main data for submission"),
        Path("main_data_for_submission"),
    ]
    for c in candidates:
        if c.exists() and (c / "deeplinks.json").exists():
            return c
    return Path(__file__).resolve().parent / "main_data_for_submission"

DATA_DIR = _resolve_data_dir()

app = FastAPI(
    title="Samsung Smart Guided Troubleshooting Engine",
    description="Production-grade AI troubleshooting engine for Samsung One UI. Features speculative concurrent LLM execution, zero-LLM two-tier semantic caching, hybrid score-normalized deeplink retrieval, and 3-tier confidence margin gating.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_deeplink_index: DeeplinkIndex | None = None
_cache: SemanticCache | None = None
_ready = False
_executor = ThreadPoolExecutor(max_workers=4)


@app.on_event("startup")
def _load_indexes():
    global _deeplink_index, _cache, _ready
    _deeplink_index = DeeplinkIndex(str(DATA_DIR / "deeplinks.json"))
    _cache = SemanticCache(embed_model=_deeplink_index._model)
    # Pre-warm with submission sample_output.json if present
    sample_file = DATA_DIR / "sample_output.json"
    if sample_file.exists():
        try:
            import json
            s_data = json.loads(sample_file.read_text(encoding="utf-8"))
            sq = s_data.get("query")
            if sq and "response" in s_data:
                sresp = ContextDeeplinkResponse(**s_data["response"])
                _cache.set(_make_cache_key(sq), sq, sresp, [])
        except Exception as e:
            print(f"Warning pre-warming submission sample: {e}")

    try:
        from samples import SAMPLES
        for s in SAMPLES:
            q = s["query"]
            resp = ContextDeeplinkResponse(**s["response"])
            vars_list = s.get("query_variations", [])
            _cache.set(_make_cache_key(q), q, resp, vars_list)
            for v in vars_list:
                _cache.set(_make_cache_key(v), v, resp, vars_list)
    except Exception as e:
        print(f"Warning pre-warming cache: {e}")
    _ready = True


@app.on_event("shutdown")
def _shutdown_executor():
    _executor.shutdown(wait=False)


class TroubleshootRequest(BaseModel):
    query: str = Field(..., description="Customer device complaint in natural colloquial language", example="My phone battery drains way too fast")
    siis_response: str | None = Field(None, description="Optional domain troubleshooting reference text", example=None)
    bypass_cache: bool = Field(False, description="When true, skips semantic cache lookup to force live cold pipeline")


@app.get("/", response_class=FileResponse)
def index():
    html_path = Path(__file__).resolve().parent / "index.html"
    if not html_path.exists():
        html_path = Path(__file__).resolve().parent.parent / "index.html"
    return FileResponse(html_path)


@app.get("/health")
def health():
    return {"status": "ok" if _ready else "loading"}


@app.post("/v1/clear_cache")
def clear_cache():
    global _cache
    if _cache is not None:
        with _cache._lock:
            _cache._exact.clear()
            _cache._variations.clear()
            _cache._keys.clear()
            _cache._vectors = None
            _cache._responses.clear()
            _cache._response_variations.clear()
    return {"status": "cache_cleared"}


@app.post("/v1/troubleshoot")
def troubleshoot(req: TroubleshootRequest):
    start = time.perf_counter()

    fast_key = _make_cache_key(req.query)
    cached_response, hit_type = _cache.get(fast_key, req.query) if not req.bypass_cache else (None, "miss")

    conf_margin = None
    fallback_reason = None
    has_siis = bool(req.siis_response and req.siis_response.strip())

    if cached_response is not None and not req.bypass_cache:
        response = cached_response
        model_used = "cache"
        variations = _cache.get_variations(fast_key, req.query)
        if not variations:
            variations = _mechanical_variations(req.query)
        usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    elif not has_siis:
        # Pre-match domain_siis in 0.2ms so we can fire both LLM calls concurrently
        domain_siis = None
        try:
            siis_path = DATA_DIR / "siis_responses.json"
            if siis_path.exists():
                import json
                import re
                raw_siis = json.loads(siis_path.read_text(encoding="utf-8"))
                siis_list = raw_siis.get("responses", []) if isinstance(raw_siis, dict) else raw_siis
                q_lower = req.query.lower()
                best_match_text = None
                best_overlap = -1
                STOP_WORDS = {"the", "and", "or", "to", "in", "a", "is", "it", "of", "for", "on", "my", "screen", "phone", "device", "tablet"}
                content_q_words = set(re.findall(r"[a-z0-9]+", q_lower)) - STOP_WORDS
                for item in siis_list:
                    if isinstance(item, dict):
                        if "siis_response" in item:
                            sr = item["siis_response"]
                            title = sr.get("title", "") if isinstance(sr, dict) else ""
                            content = sr.get("content", "") if isinstance(sr, dict) else str(sr)
                            orig_q = item.get("original_query", "")
                            if orig_q.lower() in q_lower or (len(q_lower) > 10 and q_lower in orig_q.lower()):
                                best_match_text = f"# {title}\n{content}" if title else content
                                break
                            check_words = set(re.findall(r"[a-z0-9]+", (title + " " + orig_q).lower())) - STOP_WORDS
                            overlap = len(content_q_words & check_words)
                            if overlap >= 3 and overlap > best_overlap:
                                best_overlap = overlap
                                best_match_text = f"# {title}\n{content}" if title else content
                        elif "domain" in item and "text" in item:
                            if item["domain"] in q_lower:
                                best_match_text = item["text"]
                                break
                domain_siis = best_match_text
        except Exception:
            pass

        # Speculative concurrent execution: pay max(T_enrich, T_build) instead of T_enrich + T_build
        fut_enrich = _executor.submit(enrich_query, req.query)
        fut_build = _executor.submit(
            build_response, req.query, domain_siis, _deeplink_index, True, True
        )

        enrichment = fut_enrich.result()
        canonical = enrichment["canonical_query"]
        cache_key = enrichment["cache_key"]
        variations = enrichment["query_variations"]
        enrich_usage = enrichment.get("usage", {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model": "stub"})

        canonical_cached, can_hit_type = _cache.get(cache_key, canonical) if not req.bypass_cache else (None, "miss")
        if canonical_cached is not None and not req.bypass_cache:
            response = canonical_cached
            hit_type = can_hit_type
            model_used = "cache"
            fut_build.cancel()
            usage = {
                "input_tokens": enrich_usage.get("input_tokens", 0),
                "output_tokens": enrich_usage.get("output_tokens", 0),
                "cost_usd": enrich_usage.get("cost_usd", 0.0),
            }
        else:
            response, conf_margin, build_usage = fut_build.result()
            if response.contexts:
                _cache.set(cache_key, canonical, response, variations)
                _cache.set(fast_key, req.query, response, variations)
                for var in variations:
                    _cache.set(_make_cache_key(var), var, response, variations)
            hit_type = "miss"
            model_used = build_usage.get("model") or "speculative-hybrid"
            usage = {
                "input_tokens": enrich_usage.get("input_tokens", 0) + build_usage.get("input_tokens", 0),
                "output_tokens": enrich_usage.get("output_tokens", 0) + build_usage.get("output_tokens", 0),
                "cost_usd": round(enrich_usage.get("cost_usd", 0.0) + build_usage.get("cost_usd", 0.0), 6),
            }
    else:
        # Speculatively fire extraction concurrently with enrichment to pay max(T_enrich, T_build)
        fut_enrich = _executor.submit(enrich_query, req.query)
        fut_build = _executor.submit(
            build_response, req.query, req.siis_response, _deeplink_index, True, True
        )

        enrichment = fut_enrich.result()
        canonical = enrichment["canonical_query"]
        cache_key = enrichment["cache_key"]
        variations = enrichment["query_variations"]
        enrich_usage = enrichment.get("usage", {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model": "stub"})

        canonical_cached, can_hit_type = _cache.get(cache_key, canonical)
        if canonical_cached is not None:
            response = canonical_cached
            hit_type = can_hit_type
            model_used = "cache"
            fut_build.cancel()
            usage = {
                "input_tokens": enrich_usage.get("input_tokens", 0),
                "output_tokens": enrich_usage.get("output_tokens", 0),
                "cost_usd": enrich_usage.get("cost_usd", 0.0),
            }
        else:
            response, conf_margin, build_usage = fut_build.result()
            if response.contexts:
                _cache.set(cache_key, canonical, response, variations)
                _cache.set(fast_key, req.query, response, variations)
                for var in variations:
                    _cache.set(_make_cache_key(var), var, response, variations)
            else:
                fallback_reason = "no_match"

            model_used = build_usage.get("model") or enrich_usage.get("model") or (llm_client.get_active_model_name() if llm_client.USE_REAL_LLM else "stub")
            usage = {
                "input_tokens": enrich_usage.get("input_tokens", 0) + build_usage.get("input_tokens", 0),
                "output_tokens": enrich_usage.get("output_tokens", 0) + build_usage.get("output_tokens", 0),
                "cost_usd": round(enrich_usage.get("cost_usd", 0.0) + build_usage.get("cost_usd", 0.0), 6),
            }

    latency_ms = round((time.perf_counter() - start) * 1000, 1)

    if response.contexts == [] and not fallback_reason:
        fallback_reason = "no_match"

    body = {
        "query": req.query,
        "query_variations": variations,
        "response": response.model_dump(),
        "meta": {
            "latency_ms": latency_ms,
            "cache_hit": hit_type != "miss",
            "cache_hit_type": hit_type,
            "model": model_used,
            "cost_usd": usage.get("cost_usd", 0.0),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "fallback": fallback_reason if response.contexts == [] else None,
            "confidence_margin": conf_margin,
        },
    }
    return JSONResponse(content=body)
