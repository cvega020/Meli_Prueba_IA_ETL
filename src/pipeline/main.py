"""Orquestacion end-to-end para corpus y generacion de Q&A sintetico."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
from time import perf_counter
from typing import Any

import orjson

from src.dedup import LSHDeduplicator
from src.processing import MarkdownProcessor
from src.qa import QAGenerator, QAPair

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    """Resumen compacto de una ejecucion."""

    ingested_count: int
    unique_count: int
    qa_pairs_count: int
    corpus_output_path: Path
    qa_output_path: Path
    audit_output_path: Path


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """Escribir filas en formato JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for row in rows:
            handle.write(orjson.dumps(row))
            handle.write(b"\n")


def _write_audit_markdown(
    path: Path,
    started_at: datetime,
    ended_at: datetime,
    params: dict[str, object],
    ingested_count: int,
    unique_count: int,
    qa_pairs_count: int,
    corpus_path: Path,
    qa_path: Path,
    ingest_seconds: float,
    dedup_seconds: float,
    corpus_seconds: float,
    qa_seconds: float,
    discarded_records: list[dict[str, str]],
) -> None:
    """Escribir reporte simple de auditoria en Markdown."""
    path.parent.mkdir(parents=True, exist_ok=True)
    total_seconds = max((ended_at - started_at).total_seconds(), 0.0)

    lines: list[str] = []
    lines.append("# Auditoria de ejecucion del pipeline")
    lines.append("")
    lines.append("## Metadatos")
    lines.append("")
    lines.append(f"- Inicio (UTC): {started_at.isoformat()}")
    lines.append(f"- Fin (UTC): {ended_at.isoformat()}")
    lines.append(f"- Duracion total (s): {total_seconds:.3f}")
    lines.append("")
    lines.append("## Parametros")
    lines.append("")
    for key, value in params.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Etapas")
    lines.append("")
    lines.append(f"- Ingesta y limpieza: {ingest_seconds:.3f}s | documentos: {ingested_count}")
    lines.append(f"- Deduplicacion: {dedup_seconds:.3f}s | documentos unicos: {unique_count}")
    lines.append(f"- Export corpus: {corpus_seconds:.3f}s")
    lines.append(f"- Generacion Q&A + export: {qa_seconds:.3f}s | filas Q&A: {qa_pairs_count}")
    lines.append("")
    lines.append("## Salidas")
    lines.append("")
    lines.append(f"- Corpus: {corpus_path.as_posix()}")
    lines.append(f"- Q&A: {qa_path.as_posix()}")
    lines.append("")
    lines.append("## Deduplicacion")
    lines.append("")
    lines.append(f"- Documentos descartados por similitud: {len(discarded_records)}")
    if discarded_records:
        lines.append("")
        lines.append("| discarded_id | discarded_file | kept_id |")
        lines.append("|---|---|---|")
        for row in discarded_records[:100]:
            lines.append(f"| {row['discarded_id']} | {row['discarded_file']} | {row['kept_id']} |")
        if len(discarded_records) > 100:
            lines.append("")
            lines.append(f"- Se omiten {len(discarded_records) - 100} registros adicionales por brevedad.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_pipeline(
    docs_root: str | Path = "docs_raw",
    processed_dir: str | Path = "data/processed",
    lsh_threshold: float = 0.9,
    lsh_num_perm: int = 128,
    lsh_shingle_size: int = 3,
    qa_model: str = "google/flan-t5-small",
    qa_chunk_size: int = 1800,
    questions_per_chunk: int = 2,
    qa_fallback_only: bool = False,
    qa_generator: Any = None,
) -> PipelineResult:
    """Ejecutar pipeline completo."""
    logger.info(
        "Pipeline iniciado | docs_root=%s | processed_dir=%s | fallback_only=%s",
        docs_root,
        processed_dir,
        qa_fallback_only,
    )
    run_started_at = datetime.now(timezone.utc)

    stage_t0 = perf_counter()
    logger.info("Etapa iniciada | nombre=ingesta")
    processor = MarkdownProcessor(docs_root=docs_root)
    docs = processor.process_all()
    ingest_seconds = perf_counter() - stage_t0
    logger.info("Etapa finalizada | nombre=ingesta | segundos=%.3f | documentos=%s", ingest_seconds, len(docs))

    stage_t1 = perf_counter()
    logger.info("Etapa iniciada | nombre=deduplicacion")
    deduplicator = LSHDeduplicator(
        threshold=lsh_threshold,
        num_perm=lsh_num_perm,
        shingle_size=lsh_shingle_size,
    )
    unique_docs = deduplicator.deduplicate(docs)
    dedup_seconds = perf_counter() - stage_t1
    logger.info(
        "Etapa finalizada | nombre=deduplicacion | segundos=%.3f | documentos_unicos=%s",
        dedup_seconds,
        len(unique_docs),
    )

    out_dir = Path(processed_dir)
    corpus_path = out_dir / "corpus.jsonl"
    qa_path = out_dir / "qa_dataset.jsonl"
    audit_path = out_dir / "audit_pipeline.md"

    stage_t2 = perf_counter()
    logger.info("Etapa iniciada | nombre=export_corpus")
    corpus_rows: list[dict[str, object]] = []
    for doc in unique_docs:
        corpus_rows.append(
            {
                "id": doc.id,
                "hash": doc.id,
                "project_id": doc.project_id,
                "file_path": doc.file_path,
                "content": doc.content,
                "metadata": doc.metadata,
                "timestamp": doc.timestamp.isoformat(),
            }
        )
    _write_jsonl(corpus_path, corpus_rows)
    corpus_seconds = perf_counter() - stage_t2
    logger.info("Etapa finalizada | nombre=export_corpus | segundos=%.3f | filas=%s", corpus_seconds, len(corpus_rows))

    stage_t3 = perf_counter()
    logger.info("Etapa iniciada | nombre=qa")
    qa = qa_generator or QAGenerator(
        model_name=qa_model,
        chunk_size=qa_chunk_size,
        questions_per_chunk=questions_per_chunk,
        fallback_only=qa_fallback_only,
    )

    generated: dict[str, list[QAPair]] = qa.generate_for_documents(unique_docs)
    docs_by_id = {doc.id: doc for doc in unique_docs}

    qa_rows: list[dict[str, object]] = []
    for doc_id, pairs in generated.items():
        src = docs_by_id.get(doc_id)
        if src is None:
            continue
        for pair in pairs:
            qa_rows.append(
                {
                    "question": pair.question,
                    "answer": pair.answer,
                    "source_document_id": src.id,
                    "source_hash": src.id,
                    "project_id": src.project_id,
                    "file_path": src.file_path,
                }
            )
    _write_jsonl(qa_path, qa_rows)
    qa_seconds = perf_counter() - stage_t3
    logger.info("Etapa finalizada | nombre=qa | segundos=%.3f | filas=%s", qa_seconds, len(qa_rows))

    run_ended_at = datetime.now(timezone.utc)
    _write_audit_markdown(
        path=audit_path,
        started_at=run_started_at,
        ended_at=run_ended_at,
        params={
            "docs_root": str(docs_root),
            "processed_dir": str(processed_dir),
            "lsh_threshold": lsh_threshold,
            "lsh_num_perm": lsh_num_perm,
            "lsh_shingle_size": lsh_shingle_size,
            "qa_model": qa_model,
            "qa_chunk_size": qa_chunk_size,
            "questions_per_chunk": questions_per_chunk,
            "qa_fallback_only": qa_fallback_only,
        },
        ingested_count=len(docs),
        unique_count=len(unique_docs),
        qa_pairs_count=len(qa_rows),
        corpus_path=corpus_path,
        qa_path=qa_path,
        ingest_seconds=ingest_seconds,
        dedup_seconds=dedup_seconds,
        corpus_seconds=corpus_seconds,
        qa_seconds=qa_seconds,
        discarded_records=deduplicator.discarded_records,
    )

    logger.info(
        "Pipeline finalizado | corpus=%s | qa=%s | auditoria=%s",
        corpus_path.as_posix(),
        qa_path.as_posix(),
        audit_path.as_posix(),
    )

    return PipelineResult(
        ingested_count=len(docs),
        unique_count=len(unique_docs),
        qa_pairs_count=len(qa_rows),
        corpus_output_path=corpus_path,
        qa_output_path=qa_path,
        audit_output_path=audit_path,
    )
