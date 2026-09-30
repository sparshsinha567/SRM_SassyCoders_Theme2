"""
Cache Precision Evaluation Harness: Adversarial Near-Miss Discrimination Test

Tests whether the two-tier cache correctly rejects false hits when presented
with genuinely distinct customer complaints that share high lexical or
topical overlap (domain near-misses).

A false cache hit is worse than a cache miss: it returns incorrect troubleshooting
steps to a user experiencing an entirely different device issue.

Run against a live service:
    python cache_precision_test.py --base-url http://localhost:8000

Or standalone (uses FastAPI TestClient if no server is running):
    python cache_precision_test.py
"""
import argparse
import sys
from pathlib import Path
import requests

# 4 Adversarial Near-Miss Evaluation Pairs:
# Each pair pairs an Anchor query with a genuine, distinct failure mode in the same domain.
PRECISION_PAIRS = [
    {
        "domain": "Battery & Power",
        "anchor_query": "phone battery drains overnight even when idle",
        "near_miss_query": "phone gets extremely hot while charging on cable",
        "anchor_expected_action": "0002",  # Battery usage
        "distinction_note": "Idle standby drain vs. thermal charging safety failure",
    },
    {
        "domain": "Camera & Optics",
        "anchor_query": "camera app keeps crashing when I open it",
        "near_miss_query": "camera pictures look blurry and out of focus",
        "anchor_expected_action": "0006",  # App cache / storage reset
        "distinction_note": "App process crash vs. optical autofocus failure",
    },
    {
        "domain": "Display & Navigation",
        "anchor_query": "swipe navigation is inverted after installing an app",
        "near_miss_query": "screen brightness is too dim under direct sunlight",
        "anchor_expected_action": "0001",  # Navigation bar
        "distinction_note": "Gesture coordinate mapping vs. display luminance",
    },
    {
        "domain": "System & Firmware",
        "anchor_query": "phone got slow after the update",
        "near_miss_query": "how do I download the latest software update",
        "anchor_expected_action": "0007",  # Device care optimization
        "distinction_note": "Post-update performance cleanup vs. downloading firmware",
    },
]


def _call_api(base_url: str, query: str, client=None) -> dict:
    if client:
        resp = client.post("/v1/troubleshoot", json={"query": query})
        return resp.json()
    resp = requests.post(f"{base_url}/v1/troubleshoot", json={"query": query}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def run_precision_test(base_url: str = "http://localhost:8000") -> dict:
    client = None
    try:
        requests.get(f"{base_url}/health", timeout=2)
        print(f"Testing against live service at {base_url} ...\n")
    except Exception:
        print(f"No running server detected at {base_url}. Falling back to internal TestClient ...\n")
        from fastapi.testclient import TestClient
        from api import app, _load_indexes
        _load_indexes()
        client = TestClient(app)

    results = []
    false_positive_count = 0

    print("=" * 82)
    print("Cache Precision Test: Adversarial Near-Miss Discrimination (N = 4 Pairs)")
    print("=" * 82)

    for i, pair in enumerate(PRECISION_PAIRS, 1):
        domain = pair["domain"]
        anchor = pair["anchor_query"]
        near_miss = pair["near_miss_query"]
        note = pair["distinction_note"]

        # 1. Warm cache with anchor query
        anchor_resp = _call_api(base_url, anchor, client)

        # 2. Query near-miss to test if cache falsely triggers
        near_resp = _call_api(base_url, near_miss, client)

        meta = near_resp.get("meta", {})
        hit = meta.get("cache_hit", False)
        hit_type = meta.get("cache_hit_type", "miss")

        # Extract resolved deeplink for near-miss
        contexts = near_resp.get("response", {}).get("contexts", [])
        resolved_link = None
        if contexts and contexts[0].get("actions"):
            step_groups = contexts[0]["actions"][0].get("stepGroups", [])
            if step_groups and step_groups[0].get("actionableDeeplink"):
                resolved_link = step_groups[0]["actionableDeeplink"].get("deeplink")

        is_false_positive = hit is True
        if is_false_positive:
            false_positive_count += 1
            status = "FAIL (FALSE POSITIVE CACHE HIT)"
        else:
            status = "PASS (CORRECTLY DIFFERENTIATED)"

        results.append({
            "pair": i,
            "domain": domain,
            "anchor": anchor,
            "near_miss": near_miss,
            "hit": hit,
            "hit_type": hit_type,
            "resolved_link": resolved_link,
            "passed": not is_false_positive,
        })

        print(f"Pair {i} [{domain}]:")
        print(f"  Anchor:    \"{anchor}\"")
        print(f"  Near-Miss: \"{near_miss}\" ({note})")
        print(f"  Result:    Cache Hit: {hit} ({hit_type}) -> Status: {status}")
        if resolved_link:
            print(f"  Resolved:  {resolved_link[-4:]}")
        print("-" * 82)

    total = len(PRECISION_PAIRS)
    precision_pct = round(100.0 * (total - false_positive_count) / total, 1)

    print("=" * 82)
    print(f"Summary: {total - false_positive_count}/{total} Pairs Correctly Kept Distinct | Precision: {precision_pct}%")
    print(f"False Positive Hits: {false_positive_count} / {total}")
    print("=" * 82)

    return {
        "total_pairs": total,
        "correctly_separated": total - false_positive_count,
        "false_positives": false_positive_count,
        "cache_precision_pct": precision_pct,
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test cache precision against near-miss queries")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL of running service")
    args = parser.parse_args()

    run_precision_test(args.base_url)
