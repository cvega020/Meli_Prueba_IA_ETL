"""Generacion de Q&A con modelo local y fallback offline."""

from __future__ import annotations

import json
import importlib.util
import logging
import os
import platform
import re
import socket
from dataclasses import dataclass
from textwrap import dedent
from typing import Any
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.document import Document

DEFAULT_MODEL = "google/flan-t5-small"
RECOMMENDED_HEAVY_MODEL = "google/flan-t5-base"
MIN_QUESTION_LEN = 8
MIN_ANSWER_LEN = 8


class QAPair(BaseModel):
    """Par de pregunta-respuesta."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(..., min_length=MIN_QUESTION_LEN)
    answer: str = Field(..., min_length=MIN_ANSWER_LEN)


@dataclass(frozen=True)
class QAConfig:
    """Configuracion de ejecucion para generacion de Q&A."""

    model_name: str = DEFAULT_MODEL
    chunk_size: int = 1800
    questions_per_chunk: int = 2
    max_new_tokens: int = 160
    fallback_only: bool = False
    show_progress: bool = True
    cpu_threads: int = 0


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
            show_progress=os.getenv("QA_PROGRESS", "1").strip().lower() in {"1", "true", "yes", "on"},
            cpu_threads=int(os.getenv("QA_CPU_THREADS", "0") or "0"),
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self._generator: Any = None
        self._use_remote_inference = False
        self._remote_ready = False
        self._remote_timeout_seconds = 90
        self._hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
        self._hf_inference_base = os.getenv("HF_INFERENCE_ENDPOINT", "https://api-inference.huggingface.co")
        self.backend = "deterministic"

        if not fallback_only:
            self._initialize_local_model()
            if self._generator is None:
                self._initialize_remote_backend()
            else:
                self.logger.info("Backend local activo; no se requiere backend remoto")

    def _configure_local_runtime(self) -> None:
        """Ajustar runtime local para CPU multinucleo en equipos ARM/x64."""
        try:
            import torch
        except Exception:
            return

        cpu_count = os.cpu_count() or 1
        target_threads = self.config.cpu_threads if self.config.cpu_threads > 0 else max(1, cpu_count - 1)
        interop_threads = max(1, min(4, target_threads))

        try:
            torch.set_num_threads(target_threads)
        except Exception:
            pass
        try:
            torch.set_num_interop_threads(interop_threads)
        except Exception:
            pass

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "true")
        self.logger.info(
            "Runtime local CPU configurado | arch=%s | threads=%s | interop=%s",
            platform.machine(),
            target_threads,
            interop_threads,
        )

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

        has_torch = importlib.util.find_spec("torch") is not None
        if not has_torch:
            self.logger.warning(
                "PyTorch no esta disponible en el entorno; se omite backend local y se intenta backend remoto"
            )
            self._generator = None
            self.backend = "deterministic"
            return

        attempts: list[tuple[str | None, str]] = [
            ("text2text-generation", "task=text2text-generation"),
            ("text-generation", "task=text-generation"),
            ("any-to-any", "task=any-to-any"),
            (None, "task=autodeteccion"),
        ]
        last_error: Exception | None = None
        for task_name, label in attempts:
            try:
                kwargs: dict[str, Any] = {
                    "model": self.config.model_name,
                    "tokenizer": self.config.model_name,
                    "device": -1,
                }
                if task_name is not None:
                    kwargs["task"] = task_name
                self._generator = pipeline(**kwargs)
                self.backend = f"hf:{self.config.model_name}:{label}"
                self._configure_local_runtime()
                self.logger.info("Backend local cargado: %s", self.backend)
                return
            except Exception as exc:  # pragma: no cover - network/runtime specific
                last_error = exc
                self.logger.warning("Intento fallido de backend (%s): %s", label, exc)

        self.logger.warning(
            "No se pudo cargar el modelo '%s' tras varios intentos; se usa fallback deterministico (%s)",
            self.config.model_name,
            last_error,
        )
        self._generator = None
        self.backend = "deterministic"

    def _initialize_remote_backend(self) -> None:
        self._use_remote_inference = True
        try:
            host = url_parse.urlparse(self._hf_inference_base).hostname or "api-inference.huggingface.co"
            socket.getaddrinfo(host, 443)
            self._remote_ready = True
        except Exception as exc:  # pragma: no cover - environment-specific DNS resolution
            self._remote_ready = False
            self.logger.warning("Backend remoto deshabilitado por fallo DNS/red (%s)", exc)
        if not self._remote_ready:
            if self._generator is None:
                self.backend = "deterministic"
                self.logger.warning("Backend remoto no disponible; se usara fallback deterministico")
            return

        if self._generator is None:
            self.backend = f"hf-remote:{self.config.model_name}"
            self.logger.info("Backend remoto habilitado: %s", self.backend)
        else:
            self.logger.info("Backend remoto habilitado como respaldo para: %s", self.backend)

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
            "Que supuesto operativo explicito o implicito aparece en el fragmento {idx} y como impacta al sistema?",
            "Que riesgo tecnico o de mantenimiento se desprende del fragmento {idx} y por que?",
            "Que validacion o prueba concreta se podria derivar del fragmento {idx} para evitar regresiones?",
        ]

        # Si el sistema cae en fallback, ampliar cobertura con 3 pares extra.
        fallback_questions = self.config.questions_per_chunk + 3
        pairs: list[QAPair] = []
        for idx in range(fallback_questions):
            sentence = sentences[idx % len(sentences)]
            question = f"[FALLBACK] {templates[idx % len(templates)].format(idx=idx + 1)}"
            answer = (
                f"En el documento {document.file_path}, el texto indica: {sentence} "
                "Este hallazgo se toma como evidencia textual directa para entrenamiento, "
                "y permite razonar sobre comportamiento, operacion o validacion tecnica del sistema."
            )
            pairs.append(QAPair(question=question, answer=answer))

        return pairs

    @staticmethod
    def _parse_model_output(text: str) -> list[QAPair]:
        """Parsear pares Q/A desde formatos comunes de salida de modelos."""
        pairs: list[QAPair] = []

        # Permitir etiquetas frecuentes: Q/A, P/R, Question/Answer, Pregunta/Respuesta.
        pattern = re.compile(
            r"(?:Q(?:uestion)?|P(?:regunta)?):\s*(.*?)\s*(?:A(?:nswer)?|R(?:espuesta)?):\s*(.*?)(?=\n\s*(?:Q(?:uestion)?|P(?:regunta)?):|\Z)",
            flags=re.DOTALL | re.IGNORECASE,
        )

        for match in pattern.finditer(text):
            question = " ".join(match.group(1).strip().split())
            answer = " ".join(match.group(2).strip().split())
            if question and answer and len(question) >= MIN_QUESTION_LEN and len(answer) >= MIN_ANSWER_LEN:
                pairs.append(QAPair(question=question, answer=answer))

        return pairs

    @staticmethod
    def _parse_semistructured_output(text: str) -> list[QAPair]:
        """Intentar extraer pares desde texto semiestructurado del modelo."""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        pairs: list[QAPair] = []
        current_q = ""
        current_a_parts: list[str] = []

        question_starts = (
            "q:",
            "question:",
            "p:",
            "pregunta:",
            "pregunta ",
            "question ",
        )
        answer_starts = (
            "a:",
            "answer:",
            "r:",
            "respuesta:",
            "respuesta ",
            "answer ",
        )

        def flush() -> None:
            nonlocal current_q, current_a_parts
            if not current_q:
                return
            answer = " ".join(current_a_parts).strip()
            if len(current_q) >= MIN_QUESTION_LEN and len(answer) >= MIN_ANSWER_LEN:
                pairs.append(QAPair(question=current_q, answer=answer))
            current_q = ""
            current_a_parts = []

        for raw in lines:
            low = raw.lower()
            if low.startswith(question_starts) or ("?" in raw and not current_q):
                flush()
                if ":" in raw:
                    current_q = raw.split(":", 1)[1].strip()
                else:
                    current_q = raw
                continue

            if low.startswith(answer_starts):
                content = raw.split(":", 1)[1].strip() if ":" in raw else raw
                current_a_parts.append(content)
                continue

            if current_q:
                current_a_parts.append(raw)

        flush()
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

        # Si el modelo devolvio pares validos pero no todos pasan el detector,
        # priorizar esos pares antes de caer al fallback deterministico.
        if pairs:
            self.logger.warning("Salida de modelo valida pero detector de espanol insuficiente; se usan pares del modelo")
            return pairs[: self.config.questions_per_chunk]

        fallback_pairs = self._deterministic_pairs(document, chunk)
        merged = list(spanish_pairs)
        needed = self.config.questions_per_chunk - len(merged)
        merged.extend(fallback_pairs[:needed])
        return merged

    def _generate_chunk_qa(self, document: Document, chunk: str) -> list[QAPair]:
        prompt = self._build_model_prompt(document, chunk)
        json_prompt = dedent(
            f"""
            Devuelve unicamente JSON valido en una sola linea.
            Estructura esperada:
            {{"pairs":[{{"question":"...","answer":"..."}}]}}

            Reglas:
            - Genera exactamente {self.config.questions_per_chunk} pares.
            - Todo debe estar en espanol tecnico.
            - Cada question debe tener al menos 10 caracteres.
            - Cada answer debe tener al menos 20 caracteres.
            - No agregues texto fuera del JSON.

            Documento origen id: {document.id}
            Proyecto: {document.project_id}
            Ruta archivo: {document.file_path}

            Texto:
            {chunk}
            """
        ).strip()

        def _run_local_model(prompt_text: str, max_new_tokens_override: int | None = None) -> str:
            if self._generator is None:
                return ""
            args = {
                "max_new_tokens": max_new_tokens_override or self.config.max_new_tokens,
                "do_sample": False,
                "truncation": True,
            }
            output = self._generator(prompt_text, **args)

            if isinstance(output, list) and output:
                first = output[0]
                if isinstance(first, dict):
                    text = first.get("generated_text") or first.get("summary_text") or first.get("text")
                    return str(text or "")
                return str(first)
            if isinstance(output, dict):
                text = output.get("generated_text") or output.get("summary_text") or output.get("text")
                return str(text or "")
            return str(output or "")

        def _run_remote_model(prompt_text: str) -> str:
            if not self._use_remote_inference or not self._remote_ready:
                return ""

            endpoint = (
                f"{self._hf_inference_base.rstrip('/')}/models/"
                f"{url_parse.quote(self.config.model_name, safe='/-_.')}"
            )
            payload = {
                "inputs": prompt_text,
                "parameters": {
                    "max_new_tokens": self.config.max_new_tokens,
                    "do_sample": False,
                    "return_full_text": False,
                },
                "options": {"wait_for_model": True},
            }
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            if self._hf_token:
                headers["Authorization"] = f"Bearer {self._hf_token}"

            req = url_request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )

            try:
                with url_request.urlopen(req, timeout=self._remote_timeout_seconds) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
            except url_error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                self.logger.warning("HF remoto HTTP %s: %s", exc.code, body[:300])
                return ""
            except Exception as exc:  # pragma: no cover - environment-specific network errors
                self.logger.warning("Fallo backend remoto de HF: %s", exc)
                self._remote_ready = False
                return ""

            try:
                parsed_raw = json.loads(raw)
            except json.JSONDecodeError:
                return raw

            if isinstance(parsed_raw, list) and parsed_raw:
                first = parsed_raw[0]
                if isinstance(first, dict):
                    return str(first.get("generated_text", ""))
                return str(first)
            if isinstance(parsed_raw, dict):
                if "generated_text" in parsed_raw:
                    return str(parsed_raw.get("generated_text", ""))
                if "error" in parsed_raw:
                    self.logger.warning("HF remoto respondio error: %s", parsed_raw.get("error"))
                    return ""
            return ""

        def _parse_json_pairs(text: str) -> list[QAPair]:
            candidates: list[dict[str, Any]] = []
            clean = text.strip()
            if not clean:
                return []

            try:
                payload = json.loads(clean)
            except json.JSONDecodeError:
                # Permitir JSON embebido en bloques markdown ```json ... ```.
                md_block = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", clean, flags=re.DOTALL | re.IGNORECASE)
                if md_block:
                    try:
                        payload = json.loads(md_block.group(1))
                    except json.JSONDecodeError:
                        payload = None
                else:
                    payload = None

                if payload is None:
                    first = clean.find("{")
                    last = clean.rfind("}")
                    if first < 0 or last <= first:
                        return []
                    try:
                        payload = json.loads(clean[first : last + 1])
                    except json.JSONDecodeError:
                        return []

            if isinstance(payload, dict) and isinstance(payload.get("pairs"), list):
                candidates = [row for row in payload["pairs"] if isinstance(row, dict)]
            elif isinstance(payload, list):
                candidates = [row for row in payload if isinstance(row, dict)]

            parsed: list[QAPair] = []
            for row in candidates:
                question = str(row.get("question", "")).strip()
                answer = str(row.get("answer", "")).strip()
                if question and answer and len(question) >= MIN_QUESTION_LEN and len(answer) >= MIN_ANSWER_LEN:
                    parsed.append(QAPair(question=question, answer=answer))
            return parsed

        try:
            generated_text = _run_local_model(prompt)
            if generated_text:
                parsed = self._parse_model_output(generated_text)
                if parsed:
                    return self._ensure_spanish(parsed, document, chunk)
                parsed_semistructured = self._parse_semistructured_output(generated_text)
                if parsed_semistructured:
                    return self._ensure_spanish(parsed_semistructured, document, chunk)

            # Reintento local con mas tokens si la primera salida fue insuficiente para parseo.
            generated_text_retry = _run_local_model(prompt, max(self.config.max_new_tokens * 2, 192))
            if generated_text_retry:
                parsed_retry = self._parse_model_output(generated_text_retry)
                if parsed_retry:
                    return self._ensure_spanish(parsed_retry, document, chunk)
                parsed_retry_semistructured = self._parse_semistructured_output(generated_text_retry)
                if parsed_retry_semistructured:
                    return self._ensure_spanish(parsed_retry_semistructured, document, chunk)

            json_generated_text = _run_local_model(json_prompt)
            if json_generated_text:
                json_parsed = _parse_json_pairs(json_generated_text)
                if json_parsed:
                    return self._ensure_spanish(json_parsed, document, chunk)
                json_semistructured = self._parse_semistructured_output(json_generated_text)
                if json_semistructured:
                    return self._ensure_spanish(json_semistructured, document, chunk)

            json_generated_text_retry = _run_local_model(json_prompt, max(self.config.max_new_tokens * 2, 192))
            if json_generated_text_retry:
                json_retry_parsed = _parse_json_pairs(json_generated_text_retry)
                if json_retry_parsed:
                    return self._ensure_spanish(json_retry_parsed, document, chunk)
                json_retry_semistructured = self._parse_semistructured_output(json_generated_text_retry)
                if json_retry_semistructured:
                    return self._ensure_spanish(json_retry_semistructured, document, chunk)

            remote_text = _run_remote_model(prompt)
            if remote_text:
                parsed_remote = self._parse_model_output(remote_text)
                if parsed_remote:
                    return self._ensure_spanish(parsed_remote, document, chunk)
                parsed_remote_semistructured = self._parse_semistructured_output(remote_text)
                if parsed_remote_semistructured:
                    return self._ensure_spanish(parsed_remote_semistructured, document, chunk)

            remote_json_text = _run_remote_model(json_prompt)
            if remote_json_text:
                parsed_remote_json = _parse_json_pairs(remote_json_text)
                if parsed_remote_json:
                    return self._ensure_spanish(parsed_remote_json, document, chunk)

            # Ultimo intento antes de fallback: parseo semiestructurado en salida JSON prompt.
            if remote_json_text:
                parsed_remote_json_semistructured = self._parse_semistructured_output(remote_json_text)
                if parsed_remote_json_semistructured:
                    return self._ensure_spanish(parsed_remote_json_semistructured, document, chunk)
        except Exception as exc:  # pragma: no cover - runtime specific model errors
            self.logger.warning("Fallo generacion con backend de modelo; se usa fallback deterministico (%s)", exc)

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
        iterator: Any = docs
        if self.config.show_progress:
            try:
                from tqdm import tqdm

                iterator = tqdm(docs, total=len(docs), desc="QA", unit="doc")
            except Exception:
                iterator = docs

        total = len(docs)
        for idx, doc in enumerate(iterator, start=1):
            out[doc.id] = self.generate_for_document(doc)
            if not self.config.show_progress and (idx == 1 or idx % 10 == 0 or idx == total):
                self.logger.info("Progreso QA: %s/%s documentos", idx, total)
        return out

    def to_sft_examples(self, generated: dict[str, list[QAPair]]) -> list[dict[str, str]]:
        """Aplanar salida Q&A."""
        rows: list[dict[str, str]] = []
        for pairs in generated.values():
            for pair in pairs:
                rows.append({"question": pair.question, "answer": pair.answer})
        return rows
