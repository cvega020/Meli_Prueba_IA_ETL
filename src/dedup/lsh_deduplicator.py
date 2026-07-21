"""Deteccion de duplicados y casi duplicados con MinHash + LSH."""

from __future__ import annotations

import hashlib
import logging
import re

from src.schemas.document import Document


class LSHDeduplicator:
    """Deduplicar documentos con estrategia MinHash LSH."""

    def __init__(
        self,
        threshold: float = 0.9,
        num_perm: int = 128,
        shingle_size: int = 3,
    ) -> None:
        """Configurar parametros de deduplicacion."""
        if not 0.0 < threshold <= 1.0:
            raise ValueError("threshold debe estar en (0.0, 1.0]")
        if num_perm <= 0:
            raise ValueError("num_perm debe ser > 0")
        if shingle_size <= 0:
            raise ValueError("shingle_size debe ser > 0")

        self.threshold = threshold
        self.num_perm = num_perm
        self.shingle_size = shingle_size
        self.logger = logging.getLogger(self.__class__.__name__)
        self.discarded_records: list[dict[str, str]] = []
        # Sales estables para firmas deterministicas entre ejecuciones.
        self._salts = [f"perm-{idx}".encode("utf-8") for idx in range(self.num_perm)]
        self._max_hash = (1 << 64) - 1

    def tokenize(self, content: str) -> set[str]:
        """Tokenizar texto en shingles de palabras."""
        words = re.findall(r"\w+", content.lower())

        if not words:
            return {"<empty>"}

        if len(words) < self.shingle_size:
            return {" ".join(words)}

        shingles = {
            " ".join(words[i : i + self.shingle_size])
            for i in range(len(words) - self.shingle_size + 1)
        }
        return shingles

    def deduplicate(self, docs: list[Document]) -> list[Document]:
        """Conservar documentos unicos y omitir casi duplicados."""
        self.discarded_records = []
        bands = self._build_band_index(docs)

        unique: list[Document] = []
        seen_tokens: dict[str, set[str]] = {}
        seen_signatures: dict[str, tuple[int, ...]] = {}

        for doc in docs:
            tokens = self.tokenize(doc.content)
            sig = self._signature(tokens)

            collisions = self._query_candidates(sig, bands, seen_signatures)

            if collisions:
                kept_id = self._find_duplicate(collisions, tokens, seen_tokens)
                if kept_id is None:
                    self._insert_signature(doc.id, sig, bands)
                    seen_tokens[doc.id] = tokens
                    seen_signatures[doc.id] = sig
                    unique.append(doc)
                    continue

                self.logger.info(
                    "Descartado documento casi duplicado id=%s (archivo=%s) por colision con id=%s",
                    doc.id,
                    doc.file_path,
                    kept_id,
                )
                self.discarded_records.append(
                    {
                        "discarded_id": doc.id,
                        "discarded_file": doc.file_path,
                        "kept_id": kept_id,
                    }
                )
                continue

            self._insert_signature(doc.id, sig, bands)
            seen_tokens[doc.id] = tokens
            seen_signatures[doc.id] = sig
            unique.append(doc)

        return unique

    def _signature(self, tokens: set[str]) -> tuple[int, ...]:
        """Calcular firma tipo MinHash deterministica sin dependencias externas."""
        mins = [self._max_hash] * self.num_perm
        for token in tokens:
            token_bytes = token.encode("utf-8")
            for idx, salt in enumerate(self._salts):
                digest = hashlib.blake2b(salt + token_bytes, digest_size=8).digest()
                value = int.from_bytes(digest, "big", signed=False)
                if value < mins[idx]:
                    mins[idx] = value
        return tuple(mins)

    def _build_band_index(self, docs: list[Document]) -> dict[tuple[int, tuple[int, ...]], set[str]]:
        """Crear buckets vacios para claves de banding LSH."""
        _ = docs
        return {}

    def _band_slices(self) -> list[tuple[int, int, int]]:
        """Obtener (band_idx, start, end) para banding de firmas."""
        rows_per_band = 4 if self.num_perm >= 4 else 1
        slices: list[tuple[int, int, int]] = []
        start = 0
        band_idx = 0
        while start < self.num_perm:
            end = min(start + rows_per_band, self.num_perm)
            slices.append((band_idx, start, end))
            start = end
            band_idx += 1
        return slices

    def _insert_signature(
        self,
        doc_id: str,
        signature: tuple[int, ...],
        buckets: dict[tuple[int, tuple[int, ...]], set[str]],
    ) -> None:
        for band_idx, start, end in self._band_slices():
            key = (band_idx, signature[start:end])
            buckets.setdefault(key, set()).add(doc_id)

    def _query_candidates(
        self,
        signature: tuple[int, ...],
        buckets: dict[tuple[int, tuple[int, ...]], set[str]],
        seen_signatures: dict[str, tuple[int, ...]],
    ) -> list[str]:
        candidates: set[str] = set()
        for band_idx, start, end in self._band_slices():
            key = (band_idx, signature[start:end])
            candidates.update(buckets.get(key, set()))

        # Orden deterministico para estabilidad entre ejecuciones.
        return sorted(candidates, key=lambda doc_id: seen_signatures.get(doc_id, ()))

    def _find_duplicate(
        self,
        candidate_ids: list[str],
        tokens: set[str],
        seen_tokens: dict[str, set[str]],
    ) -> str | None:
        for candidate_id in candidate_ids:
            candidate_tokens = seen_tokens.get(candidate_id)
            if not candidate_tokens:
                continue
            if self._jaccard(tokens, candidate_tokens) >= self.threshold:
                return candidate_id
        return None

    @staticmethod
    def _jaccard(a: set[str], b: set[str]) -> float:
        union = a | b
        if not union:
            return 1.0
        return len(a & b) / len(union)
