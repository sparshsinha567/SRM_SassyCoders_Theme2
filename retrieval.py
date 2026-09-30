import json
import re
from dataclasses import dataclass
from typing import List, Optional

from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
import numpy as np


def _stem(w: str) -> str:
    """Lightweight rule-based stemmer (offline, zero-dependency, CI-safe)."""
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("shes", "ches", "sses", "xes", "zes")) and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    if w.endswith("ing") and len(w) > 4:
        s = w[:-3]
        if s.endswith(("at", "bl", "iz")):
            return s + "e"
        if len(s) > 2 and s[-1] == s[-2] and s[-1] not in "lsz":
            return s[:-1]
        return s
    if w.endswith("ed") and len(w) > 3:
        s = w[:-2]
        if s.endswith(("at", "bl", "iz")):
            return s + "e"
        if len(s) > 2 and s[-1] == s[-2] and s[-1] not in "lsz":
            return s[:-1]
        if s.endswith("e"):
            return s
        return s
    return w


def _tokenize(text: str) -> List[str]:
    """Tokenizes and stems text for BM25 matching."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [_stem(t) for t in tokens if len(t) > 1]


RESERVED_PLACEHOLDER_URI = "voiceassist://dummy_positive"


@dataclass
class DeeplinkEntry:
    deeplink: str
    description: str
    message: str = ""
    qna_description: str = ""
    original_type: Optional[str] = None
    is_critical: bool = False
    validation: Optional[dict] = None
    id: Optional[str] = None
    control_type: Optional[int] = None


class DeeplinkIndex:
    """Hybrid BM25 and dense embedding index over the deeplink catalog with optional cross-encoder reranking."""

    EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
    RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, deeplinks_path: str):
        with open(deeplinks_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if isinstance(raw, dict) and "deeplinks" in raw:
            items = raw["deeplinks"]
        elif isinstance(raw, list):
            items = raw
        else:
            items = []

        self.entries: List[DeeplinkEntry] = [
            DeeplinkEntry(
                deeplink=item["deeplink"],
                description=item.get("description", ""),
                message=item.get("message", ""),
                qna_description=item.get("qna_description", ""),
                original_type=item.get("originalType"),
                is_critical=item.get("classes", {}).get("category") == "critical"
                if item.get("classes") else False,
                validation=item.get("validation"),
                id=item.get("id"),
                control_type=item.get("control_type"),
            )
            for item in items
            if isinstance(item, dict) and "deeplink" in item
        ]

        # Dynamic placeholder based on scheme
        is_voiceassist = any(e.deeplink.startswith("voiceassist://") for e in self.entries)
        self.placeholder_uri = "voiceassist://dummy_positive" if is_voiceassist else "bixby://dummy_positive"

        corpus_texts = [
            f"{e.description} {e.message} {e.qna_description}".strip()
            for e in self.entries
        ]

        tokenized = [_tokenize(t) for t in corpus_texts]
        self._bm25 = BM25Okapi(tokenized)

        self._model = SentenceTransformer(self.EMBED_MODEL)
        passage_texts = [self._format_passage(t) for t in corpus_texts]
        self._dense_matrix = self._model.encode(
            passage_texts, convert_to_numpy=True, normalize_embeddings=True
        )
        self._reranker = None

    def get_placeholder_entry(self) -> Optional[DeeplinkEntry]:
        """Fetches the canonical static generic placeholder entry directly from the catalog."""
        return next((e for e in self.entries if "dummy_positive" in e.deeplink), None)

    def _format_query(self, query: str) -> str:
        """Applies model-specific query prefixes for asymmetric models (e.g. BGE or E5)."""
        if "bge" in self.EMBED_MODEL.lower():
            return f"Represent this sentence for searching relevant passages: {query}"
        if "e5" in self.EMBED_MODEL.lower():
            return f"query: {query}"
        return query

    def _format_passage(self, text: str) -> str:
        """Applies model-specific passage prefixes for asymmetric models (e.g. E5)."""
        if "e5" in self.EMBED_MODEL.lower():
            return f"passage: {text}"
        return text

    def _get_reranker(self):
        if self._reranker is None:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder(self.RERANKER_MODEL)
        return self._reranker

    def search(
        self,
        query: str,
        top_k: int = 5,
        dense_weight: float = 0.75,
        rrf_k: int = 60,
    ) -> List[DeeplinkEntry]:
        """Score-normalized weighted fusion of dense embeddings and BM25."""
        bm25_weight = 1.0 - dense_weight

        formatted_q = self._format_query(query)
        q_vec = self._model.encode([formatted_q], convert_to_numpy=True, normalize_embeddings=True)[0]
        dense_scores = self._dense_matrix @ q_vec
        d_min, d_max = float(np.min(dense_scores)), float(np.max(dense_scores))
        dense_norm = (dense_scores - d_min) / (d_max - d_min + 1e-6)

        bm25_scores = np.array(self._bm25.get_scores(_tokenize(query)))
        b_max = float(np.max(bm25_scores)) if len(bm25_scores) > 0 else 0.0
        bm25_norm = bm25_scores / (b_max + 1e-6) if b_max > 0 else np.zeros_like(bm25_scores)

        fused = dense_weight * dense_norm + bm25_weight * bm25_norm
        ranked_idx = np.argsort(-fused)[:top_k]
        return [self.entries[i] for i in ranked_idx]

    def rerank(self, query: str, candidates: List[DeeplinkEntry], top_k: int = 1) -> List[DeeplinkEntry]:
        """Scores candidate pool jointly with query via cross-encoder."""
        if not candidates:
            return []
        reranker = self._get_reranker()
        pairs = [[query, f"{c.description} {c.message}".strip()] for c in candidates]
        scores = reranker.predict(pairs)
        ranked_idx = np.argsort(-scores)[:top_k]
        return [candidates[i] for i in ranked_idx]

    def best_match(self, query: str) -> Optional[DeeplinkEntry]:
        results = self.search(query, top_k=1)
        return results[0] if results else None

    def search_with_scores(
        self,
        query: str,
        top_k: int = 5,
        dense_weight: float = 0.75,
    ) -> List[tuple[DeeplinkEntry, float]]:
        """Score-normalized weighted fusion returning pairs of (entry, fusion_score)."""
        bm25_weight = 1.0 - dense_weight

        formatted_q = self._format_query(query)
        q_vec = self._model.encode([formatted_q], convert_to_numpy=True, normalize_embeddings=True)[0]
        dense_scores = self._dense_matrix @ q_vec
        d_min, d_max = float(np.min(dense_scores)), float(np.max(dense_scores))
        dense_norm = (dense_scores - d_min) / (d_max - d_min + 1e-6)

        bm25_scores = np.array(self._bm25.get_scores(_tokenize(query)))
        b_max = float(np.max(bm25_scores)) if len(bm25_scores) > 0 else 0.0
        bm25_norm = bm25_scores / (b_max + 1e-6) if b_max > 0 else np.zeros_like(bm25_scores)

        fused = dense_weight * dense_norm + bm25_weight * bm25_norm
        ranked_idx = np.argsort(-fused)[:top_k]
        return [(self.entries[i], round(float(fused[i]), 3)) for i in ranked_idx]

    def best_match_with_score(self, query: str) -> tuple[Optional[DeeplinkEntry], float]:
        """Returns best matching entry and its fused confidence score in [0.0, 1.0]."""
        results = self.search_with_scores(query, top_k=1)
        if results:
            return results[0][0], results[0][1]
        return None, 0.0

    @staticmethod
    def _feature_key(entry: DeeplinkEntry) -> str:
        """Extracts the underlying setting feature identity to group sibling actions."""
        if entry.validation and entry.validation.get("key"):
            return entry.validation["key"].strip().lower()
        desc = entry.description.lower()
        for prefix in ["opens the ", "enables ", "disables ", "open "]:
            if desc.startswith(prefix):
                desc = desc[len(prefix):]
                break
        for suffix in [
            " settings page in device settings on the device.",
            " via device settings on the device.",
            " in device settings on the device.",
            " settings page on the device.",
        ]:
            if desc.endswith(suffix):
                desc = desc[:-len(suffix)]
                break
        words = re.findall(r"[a-z0-9]+", desc)
        return " ".join(words[:4]) if words else entry.deeplink

    def best_match_with_margin(
        self, query: str, distinct_competitors: bool = True, min_raw_sim: float = 0.35
    ) -> tuple[Optional[DeeplinkEntry], float, float]:
        """Returns (best_entry, top1_score, margin_vs_competitor) to evaluate confidence calibration.
        When distinct_competitors=True, compares Top-1 against the highest-scoring candidate representing
        a DISTINCT physical feature/screen (skipping sibling open/enable/disable variations of the same setting).
        If raw dense similarity and BM25 score fall below the absolute confidence floor, returns None to
        trigger canonical fallback to dummy_positive.
        """
        # Absolute match quality check (detect out-of-catalog / low-confidence intents)
        formatted_q = self._format_query(query)
        q_vec = self._model.encode([formatted_q], convert_to_numpy=True, normalize_embeddings=True)[0]
        raw_dense_max = float(np.max(self._dense_matrix @ q_vec))
        raw_bm25_max = float(np.max(self._bm25.get_scores(_tokenize(query)))) if len(self.entries) > 0 else 0.0
        if raw_dense_max < min_raw_sim and raw_bm25_max < 10.0:
            return None, round(raw_dense_max, 3), 0.0

        results = self.search_with_scores(query, top_k=8 if distinct_competitors else 2)
        if not results:
            return None, 0.0, 0.0
        top1_entry, top1_score = results[0]
        if not distinct_competitors or len(results) == 1:
            top2_score = results[1][1] if len(results) > 1 else 0.0
            margin = round(float(top1_score - top2_score), 3)
            return top1_entry, top1_score, margin

        top1_feat = self._feature_key(top1_entry)
        competitor_score = None
        for entry, score in results[1:]:
            if self._feature_key(entry) != top1_feat:
                competitor_score = score
                break

        if competitor_score is None:
            competitor_score = results[-1][1] if len(results) > 1 else 0.0

        margin = round(float(top1_score - competitor_score), 3)
        return top1_entry, top1_score, margin

    def best_match_reranked(self, query: str, candidate_pool_k: int = 5) -> Optional[DeeplinkEntry]:
        """Retrieves top candidates via hybrid fusion and reranks them with cross-encoder."""
        candidates = self.search(query, top_k=candidate_pool_k)
        reranked = self.rerank(query, candidates, top_k=1)
        return reranked[0] if reranked else None

    def search_bm25_only(self, query: str, top_k: int = 5) -> List[DeeplinkEntry]:
        scores = self._bm25.get_scores(_tokenize(query))
        idx = np.argsort(-scores)[:top_k]
        return [self.entries[i] for i in idx]

    def search_dense_only(self, query: str, top_k: int = 5) -> List[DeeplinkEntry]:
        formatted_q = self._format_query(query)
        q_vec = self._model.encode([formatted_q], convert_to_numpy=True, normalize_embeddings=True)[0]
        scores = self._dense_matrix @ q_vec
        idx = np.argsort(-scores)[:top_k]
        return [self.entries[i] for i in idx]

