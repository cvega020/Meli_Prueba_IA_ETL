"""Top-level CLI for end-to-end pipeline execution."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import typer
from dotenv import load_dotenv

from src.qa import DEFAULT_MODEL, RECOMMENDED_HEAVY_MODEL

app = typer.Typer(help="CLI del pipeline de datos")
logger = logging.getLogger("cli")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _setup_logging(level: str) -> None:
    """Configure root logging once for CLI executions."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


@app.command()
def run(
    docs_root: Path = typer.Option(Path("docs_raw"), help="Carpeta raiz con archivos markdown de entrada."),
    processed_dir: Path = typer.Option(
        Path("data/processed"),
        help="Carpeta de salida para corpus.jsonl y qa_dataset.jsonl.",
    ),
    lsh_threshold: float = typer.Option(0.9, min=0.01, max=1.0, help="Umbral de Jaccard para deduplicacion."),
    qa_model: str | None = typer.Option(
        None,
        help="Identificador de modelo local de Hugging Face para Q&A.",
    ),
    qa_chunk_size: int = typer.Option(1800, min=200, help="Tamano del chunk en caracteres."),
    questions_per_chunk: int = typer.Option(2, min=1, max=5, help="Cantidad de pares Q&A por chunk."),
    qa_max_new_tokens: int = typer.Option(120, min=32, max=512, help="Maximo de tokens nuevos por generacion QA."),
    fallback_only: bool | None = typer.Option(
        None,
        "--fallback-only/--no-fallback-only",
        help="Omitir carga del modelo y usar generacion deterministica offline.",
    ),
    log_level: str = typer.Option("INFO", help="Nivel de logging (DEBUG, INFO, WARNING, ERROR)."),
) -> None:
    """Ejecutar el pipeline completo desde markdown hasta export JSONL."""
    from src.pipeline.main import run_pipeline

    if not docs_root.exists() or not docs_root.is_dir():
        raise typer.BadParameter("docs_root debe existir y ser una carpeta valida.", param_hint="--docs-root")
    if processed_dir.exists() and not processed_dir.is_dir():
        raise typer.BadParameter(
            "processed_dir debe ser una carpeta valida.",
            param_hint="--processed-dir",
        )

    load_dotenv()
    _setup_logging(log_level)

    resolved_qa_model = qa_model or os.getenv("QA_MODEL", DEFAULT_MODEL)
    resolved_fallback_only = fallback_only if fallback_only is not None else _env_bool("QA_FALLBACK_ONLY", False)
    logger.info(
        "Inicio de ejecucion | docs_root=%s | processed_dir=%s | fallback_only=%s",
        docs_root.as_posix(),
        processed_dir.as_posix(),
        resolved_fallback_only,
    )

    result = run_pipeline(
        docs_root=docs_root,
        processed_dir=processed_dir,
        lsh_threshold=lsh_threshold,
        qa_model=resolved_qa_model,
        qa_chunk_size=qa_chunk_size,
        questions_per_chunk=questions_per_chunk,
        qa_max_new_tokens=qa_max_new_tokens,
        qa_fallback_only=resolved_fallback_only,
    )

    logger.info(
        "Fin de ejecucion | ingeridos=%s | unicos=%s | qa_rows=%s",
        result.ingested_count,
        result.unique_count,
        result.qa_pairs_count,
    )

    typer.echo("Pipeline ejecutado correctamente")
    typer.echo(f"- Documentos ingeridos: {result.ingested_count}")
    typer.echo(f"- Documentos unicos: {result.unique_count}")
    typer.echo(f"- Filas Q&A generadas: {result.qa_pairs_count}")
    typer.echo(f"- Salida corpus: {result.corpus_output_path.as_posix()}")
    typer.echo(f"- Salida Q&A: {result.qa_output_path.as_posix()}")
    typer.echo(f"- Auditoria Markdown: {result.audit_output_path.as_posix()}")


@app.command()
def healthcheck() -> None:
    """Verificacion basica de estado de la CLI."""
    typer.echo("ok")
    typer.echo(f"modelo_por_defecto={DEFAULT_MODEL}")
    typer.echo(f"modelo_pesado_opcional={RECOMMENDED_HEAVY_MODEL}")


if __name__ == "__main__":
    app()
