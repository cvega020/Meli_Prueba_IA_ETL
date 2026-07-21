"""Generacion de Q&A con modelo local y fallback offline."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from textwrap import dedent
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.document import Document

DEFAULT_MODEL = "google/flan-t5-small"
RECOMMENDED_HEAVY_MODEL = "google/flan-t5-base"


class QAPair(BaseModel):
    """Par de pregunta-respuesta."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(..., min_length=10)
    answer: str = Field(..., min_length=20)


@dataclass(frozen=True)
class QAConfig:
    """Configuracion de ejecucion para generacion de Q&A."""

    model_name: str = DEFAULT_MODEL
    chunk_size: int = 1800
    questions_per_chunk: int = 2
    max_new_tokens: int = 160
    fallback_only: bool = False


class QAGenerator:
    """Generar pares Q&A desde documentos con modelo local o fallback deterministico."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        chunk_size: int = 1800,
        questions_per_chunk: int = 2,
        max_new_tokens: int = 160,
        fallback_only: bool = False,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size debe ser > 0")
        if questions_per_chunk <= 0:
            raise ValueError("questions_per_chunk debe ser > 0")
        if max_new_tokens <= 0:
            raise ValueError("max_new_tokens debe ser > 0")

        self.config = QAConfig(
            model_name=model_name,
            chunk_size=chunk_size,
            questions_per_chunk=questions_per_chunk,
            max_new_tokens=max_new_tokens,
            fallback_only=fallback_only,
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self._generator: Any = None
        self.backend = "deterministic"

        if not fallback_only:
            self._initialize_local_model()

    def _initialize_local_model(self) -> None:
        """Cargar pipeline local text2text.

        La primera ejecucion descarga el modelo desde cache de Hugging Face.
        Si falla la carga (sin internet o sin torch), se usa fallback deterministico.
        """
        try:
            from transformers import pipeline
        except Exception as exc:  # pragma: no cover - environment-specific import path
            self.logger.warning("transformers no esta disponible; se usa fallback deterministico (%s)", exc)
            return

        try:
            self._generator = pipeline(
                task="text2text-generation",
                model=self.config.model_name,
                tokenizer=self.config.model_name,
                device=-1,
            )
            self.backend = f"hf:{self.config.model_name}"
            self.logger.info("Backend local cargado: %s", self.backend)
        except Exception as exc:  # pragma: no cover - network/runtime specific
            self.logger.warning(
                "No se pudo cargar el modelo local '%s'; se usa fallback deterministico (%s)",
                self.config.model_name,
                exc,
            )
            self._generator = None
            self.backend = "deterministic"

    def chunk_text(self, content: str) -> list[str]:
        """Dividir texto largo en chunks por parrafos."""
        text = content.strip()
        if len(text) <= self.config.chunk_size:
            return [text]

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[str] = []
        current: list[str] = []
        current_size = 0

        for paragraph in paragraphs:
            extra = len(paragraph) + (2 if current else 0)
            if current and current_size + extra > self.config.chunk_size:
                chunks.append("\n\n".join(current))
                current = [paragraph]
                current_size = len(paragraph)
                continue

            current.append(paragraph)
            current_size += extra

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    def _build_model_prompt(self, document: Document, chunk: str) -> str:
        return dedent(
            f"""
            Genera exactamente {self.config.questions_per_chunk} pares de pregunta-respuesta en espanol.
            Usa este formato por par:
            P: <pregunta>
            R: <respuesta>

            Restricciones:
            - Las preguntas deben ser tecnicas y no triviales.
            - Las respuestas deben ser factuales y estar sustentadas en el texto.
            - No uses ingles.

            Documento origen id: {document.id}
            Proyecto: {document.project_id}
            Ruta archivo: {document.file_path}

            Texto:
            {chunk}
            """
        ).strip()

    @staticmethod
    def _extract_sentences(chunk: str) -> list[str]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", chunk) if s.strip()]
        if sentences:
            return sentences
        return [line.strip() for line in chunk.splitlines() if line.strip()]

    def _deterministic_pairs(self, document: Document, chunk: str) -> list[QAPair]:
        """Generar pares deterministas cuando el backend de modelo no esta disponible."""
        sentences = self._extract_sentences(chunk)
        templates = [
            "Cual es el punto tecnico principal descrito en el fragmento {idx}?",
            "Como se relaciona el fragmento {idx} con el comportamiento o la arquitectura del sistema?",
            "Que detalle de implementacion del fragmento {idx} es mas relevante para la operacion?",
        ]

        pairs: list[QAPair] = []
        for idx in range(self.config.questions_per_chunk):
            sentence = sentences[idx % len(sentences)]
            question = templates[idx % len(templates)].format(idx=idx + 1)
            answer = (
                f"En el documento {document.file_path}, el texto indica: {sentence} "
                "Esa es la evidencia principal usada para este par de entrenamiento."
            )
            pairs.append(QAPair(question=question, answer=answer))

        return pairs

    @staticmethod
    def _parse_model_output(text: str) -> list[QAPair]:
        """Parsear pares P:/R: o Q:/A: desde salida del modelo."""
        pairs: list[QAPair] = []
        pattern = re.compile(
            r"(?:Q|P):\s*(.*?)\s*(?:A|R):\s*(.*?)(?=\n\s*(?:Q|P):|\Z)",
            flags=re.DOTALL | re.IGNORECASE,
        )

        for match in pattern.finditer(text):
            question = " ".join(match.group(1).strip().split())
            answer = " ".join(match.group(2).strip().split())
            if question and answer and len(question) >= 10 and len(answer) >= 20:
                pairs.append(QAPair(question=question, answer=answer))

        return pairs

    @staticmethod
    def _looks_spanish(text: str) -> bool:
        low = text.lower()
        stopwords = [" el ", " la ", " los ", " las ", " de ", " para ", " que ", " con ", " y "]
        wrapped = f" {low} "
        score = sum(1 for token in stopwords if token in wrapped)
        return score >= 2 or any(ch in low for ch in "áéíóúñ")

    def _ensure_spanish(self, pairs: list[QAPair], document: Document, chunk: str) -> list[QAPair]:
        spanish_pairs = [p for p in pairs if self._looks_spanish(p.question) and self._looks_spanish(p.answer)]
        if len(spanish_pairs) >= self.config.questions_per_chunk:
            return spanish_pairs[: self.config.questions_per_chunk]

        fallback_pairs = self._deterministic_pairs(document, chunk)
        merged = list(spanish_pairs)
        needed = self.config.questions_per_chunk - len(merged)
        merged.extend(fallback_pairs[:needed])
        return merged

    def _generate_chunk_qa(self, document: Document, chunk: str) -> list[QAPair]:
        if self._generator is None:
            return self._deterministic_pairs(document, chunk)

        prompt = self._build_model_prompt(document, chunk)

        try:
            output = self._generator(
                prompt,
                max_new_tokens=self.config.max_new_tokens,
                do_sample=False,
                truncation=True,
            )
            generated_text = output[0].get("generated_text", "") if output else ""
            parsed = self._parse_model_output(generated_text)
            if parsed:
                return self._ensure_spanish(parsed, document, chunk)
        except Exception as exc:  # pragma: no cover - runtime specific model errors
            self.logger.warning("Fallo generacion con modelo local; se usa fallback deterministico (%s)", exc)

        return self._deterministic_pairs(document, chunk)

    def generate_for_document(self, doc: Document) -> list[QAPair]:
        """Generar Q&A para un documento."""
        chunks = self.chunk_text(doc.content)
        pairs_all: list[QAPair] = []
        for chunk in chunks:
            pairs_all.extend(self._generate_chunk_qa(doc, chunk))
        return pairs_all

    def generate_for_documents(self, docs: list[Document]) -> dict[str, list[QAPair]]:
        """Generar Q&A para varios documentos."""
        out: dict[str, list[QAPair]] = {}
        for doc in docs:
            out[doc.id] = self.generate_for_document(doc)
        return out

    def to_sft_examples(self, generated: dict[str, list[QAPair]]) -> list[dict[str, str]]:
        """Aplanar salida Q&A."""
        rows: list[dict[str, str]] = []
        for pairs in generated.values():
            for pair in pairs:
                rows.append({"question": pair.question, "answer": pair.answer})
        return rows
