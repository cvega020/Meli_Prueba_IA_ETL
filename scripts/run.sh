#!/usr/bin/env bash
set -euo pipefail

# Ejecutar siempre desde la raiz del repositorio, sin depender del directorio actual.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ ! -d "docs_raw" ]]; then
	echo "Ejecucion cancelada: no existe docs_raw. Verifica la carpeta de entrada." >&2
	exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
	python3 -m venv .venv
fi
source .venv/bin/activate
PYTHON=".venv/bin/python"

if ! "${PYTHON}" -c "import orjson, typer, xxhash, pydantic, dotenv" >/dev/null 2>&1; then
	"${PYTHON}" -m pip install --upgrade pip
	"${PYTHON}" -m pip install -e .
fi

# Usar el modulo Python evita problemas cuando el entrypoint no esta en PATH.
"${PYTHON}" -m src.cli run --docs-root docs_raw --processed-dir data/processed --fallback-only

[[ -f "data/processed/corpus.jsonl" ]] && [[ -f "data/processed/qa_dataset.jsonl" ]] && [[ -f "data/processed/audit_pipeline.md" ]] || {
	echo "Ejecucion cancelada: no se generaron todos los archivos objetivo (corpus.jsonl, qa_dataset.jsonl, audit_pipeline.md)." >&2
	exit 1
}

corpus_size=$(wc -c < "data/processed/corpus.jsonl")
qa_size=$(wc -c < "data/processed/qa_dataset.jsonl")
audit_size=$(wc -c < "data/processed/audit_pipeline.md")
corpus_time=$(date -r "data/processed/corpus.jsonl" "+%Y-%m-%d %H:%M:%S")
qa_time=$(date -r "data/processed/qa_dataset.jsonl" "+%Y-%m-%d %H:%M:%S")
audit_time=$(date -r "data/processed/audit_pipeline.md" "+%Y-%m-%d %H:%M:%S")

echo "Resumen de salidas generadas:"
echo "- corpus.jsonl | ${corpus_size} bytes | actualizado: ${corpus_time}"
echo "- qa_dataset.jsonl | ${qa_size} bytes | actualizado: ${qa_time}"
echo "- audit_pipeline.md | ${audit_size} bytes | actualizado: ${audit_time}"
