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

VENV_DIR=".venv"
if command -v python3.12 >/dev/null 2>&1; then
	VENV_DIR=".venv312"
	if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
		echo "Creando entorno Python 3.12 en ${VENV_DIR} ..."
		python3.12 -m venv "${VENV_DIR}"
	fi
elif [[ ! -x "${VENV_DIR}/bin/python" ]]; then
	echo "Advertencia: python3.12 no esta disponible. Se usara .venv actual." >&2
	python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"
PYTHON="${VENV_DIR}/bin/python"
PYTHON_VERSION="$(${PYTHON} -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
echo "Entorno seleccionado: ${VENV_DIR} | Python ${PYTHON_VERSION}"

if ! "${PYTHON}" -c "import orjson, typer, xxhash, pydantic, dotenv" >/dev/null 2>&1; then
	"${PYTHON}" -m pip install --upgrade pip
	"${PYTHON}" -m pip install -e .
elif ! "${PYTHON}" -c "import transformers, sys; sys.exit(0 if int(transformers.__version__.split('.', 1)[0]) < 5 else 1)" >/dev/null 2>&1; then
	echo "Advertencia: se detecto transformers>=5; se resincronizaran dependencias del proyecto." >&2
	"${PYTHON}" -m pip install --upgrade pip
	"${PYTHON}" -m pip install -e .
fi

TORCH_SUPPORTED="$(${PYTHON} -c "import sys; print(int((sys.version_info.major, sys.version_info.minor) < (3, 13)))")"
if ! "${PYTHON}" -c "import torch" >/dev/null 2>&1 && [[ "${TORCH_SUPPORTED}" == "1" ]]; then
	echo "Intentando instalar backend local de modelo (torch)..."
	"${PYTHON}" -m pip install --index-url https://download.pytorch.org/whl/cpu torch || true
	if ! "${PYTHON}" -m pip install -e ".[local-model]"; then
		echo "Advertencia: no se pudo instalar torch; se continuara con backend remoto y fallback como ultimo recurso." >&2
	elif "${PYTHON}" -c "import torch" >/dev/null 2>&1; then
		echo "Torch instalado correctamente en ${VENV_DIR}"
	fi
fi

if [[ "${PYTHON_VERSION}" > "3.12" && ! "${QA_FALLBACK_ONLY:-}" =~ ^(1|true|yes|on)$ ]]; then
	echo "Advertencia: Python ${PYTHON_VERSION} detectado. Para QA con modelo local se recomienda Python 3.11 o 3.12 (torch puede no estar disponible en 3.13+)." >&2
fi

# Usar el modulo Python evita problemas cuando el entrypoint no esta en PATH.
# Solo forzar fallback si QA_FALLBACK_ONLY=true en el entorno.
RUN_ARGS=(-m src.cli run --docs-root docs_raw --processed-dir data/processed)
if [[ "${QA_FALLBACK_ONLY:-}" =~ ^(1|true|yes|on)$ ]]; then
	RUN_ARGS+=(--fallback-only)
fi
"${PYTHON}" "${RUN_ARGS[@]}"

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
