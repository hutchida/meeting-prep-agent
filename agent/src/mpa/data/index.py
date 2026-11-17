"""A small BM25 index over a fixed list of documents."""

from __future__ import annotations

from collections.abc import Sequence

from rank_bm25 import BM25Okapi

from mpa.data.text import tokenise

# An item whose subject entity (e.g. a news item's `about`) is fully named by the query beats
# one that merely contains those words inside a longer name ("Brightmoor Renewables Pty Ltd").
ENTITY_BOOST = 1.5


class BM25Index:
    def __init__(
        self,
        ids: Sequence[str],  # ties are broken by position, so pass ids in natural order
        corpus: Sequence[list[str]],
        multipliers: Sequence[float] | None = None,
        entities: Sequence[frozenset[str]] | None = None,
    ) -> None:
        self._ids = list(ids)
        self._multipliers = list(multipliers) if multipliers else [1.0] * len(self._ids)
        self._entities = list(entities) if entities else [frozenset()] * len(self._ids)
        self._bm25 = BM25Okapi([doc or ["<empty>"] for doc in corpus])

    def search(self, query: str, limit: int) -> tuple[list[tuple[str, float]], list[str]]:
        """Return up to `limit` (id, score) pairs with score > 0, and the query terms used."""
        terms = tokenise(query)
        if not terms or limit <= 0:
            return [], terms
        raw = self._bm25.get_scores(list(dict.fromkeys(terms)))
        wanted = set(terms)
        scored = [
            (
                i,
                max(float(s), 0.0)
                * self._multipliers[i]
                * (ENTITY_BOOST if self._entities[i] and self._entities[i] <= wanted else 1.0),
            )
            for i, s in enumerate(raw)
        ]
        ranked = sorted((p for p in scored if p[1] > 0), key=lambda p: (-p[1], p[0]))
        return [(self._ids[i], score) for i, score in ranked[:limit]], terms
