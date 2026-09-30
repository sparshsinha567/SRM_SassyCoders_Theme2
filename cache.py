import threading
from typing import Optional, Tuple, List
import numpy as np

from schema import ContextDeeplinkResponse

SIMILARITY_THRESHOLD = 0.48


class SemanticCache:
    """Two-tier exact and semantic embedding cache."""

    def __init__(self, embed_model):
        self._model = embed_model
        self._exact: dict[str, ContextDeeplinkResponse] = {}
        self._variations: dict[str, List[str]] = {}
        self._keys: List[str] = []
        self._vectors: Optional[np.ndarray] = None
        self._responses: List[ContextDeeplinkResponse] = []
        self._response_variations: List[List[str]] = []
        self._lock = threading.Lock()

    def get(self, cache_key: str, canonical_query: str) -> Tuple[Optional[ContextDeeplinkResponse], str]:
        """Returns (response_or_None, hit_type) where hit_type in {'exact', 'semantic', 'miss'}."""
        with self._lock:
            if cache_key in self._exact:
                return self._exact[cache_key], "exact"

            vectors = self._vectors
            keys_len = len(self._keys)
            responses = list(self._responses)

        if vectors is not None and keys_len > 0:
            q_vec = self._model.encode([canonical_query], convert_to_numpy=True,
                                        normalize_embeddings=True)[0]
            sims = vectors @ q_vec
            best_idx = int(np.argmax(sims))
            if sims[best_idx] >= SIMILARITY_THRESHOLD:
                return responses[best_idx], "semantic"

        return None, "miss"

    def get_variations(self, cache_key: str, canonical_query: str = "") -> List[str]:
        """Returns cached query variations associated with the cache hit if present."""
        with self._lock:
            if cache_key in self._variations:
                return list(self._variations[cache_key])
            vectors = self._vectors
            keys_len = len(self._keys)
            resp_vars = list(self._response_variations)

        if canonical_query and vectors is not None and keys_len > 0:
            q_vec = self._model.encode([canonical_query], convert_to_numpy=True,
                                        normalize_embeddings=True)[0]
            sims = vectors @ q_vec
            best_idx = int(np.argmax(sims))
            if sims[best_idx] >= SIMILARITY_THRESHOLD and best_idx < len(resp_vars):
                return list(resp_vars[best_idx])
        return []

    def set(
        self,
        cache_key: str,
        canonical_query: str,
        response: ContextDeeplinkResponse,
        variations: Optional[List[str]] = None,
    ) -> None:
        vec = self._model.encode([canonical_query], convert_to_numpy=True,
                                  normalize_embeddings=True)[0]
        var_list = list(variations) if variations else []
        with self._lock:
            self._exact[cache_key] = response
            if var_list:
                self._variations[cache_key] = var_list
            self._keys.append(cache_key)
            self._responses.append(response)
            self._response_variations.append(var_list)
            self._vectors = vec[None, :] if self._vectors is None else np.vstack([self._vectors, vec])

    def stats(self) -> dict:
        with self._lock:
            return {"exact_entries": len(self._exact), "semantic_entries": len(self._keys)}
