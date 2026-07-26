# Meli Data Pipeline

Pipeline local y reproducible que transforma documentacion Markdown en dos datasets JSONL para entrenamiento/evaluacion de soluciones LLM, con trazabilidad por documento, deduplicacion por similitud y generacion de pares Q&A en espanol.

## Objetivo de la solucion

La solucion implementa, de forma simple y portable, un flujo ETL para:

1. Ingerir documentacion tecnica en Markdown.
2. Normalizar y estructurar cada documento.
3. Eliminar duplicados y casi duplicados.
4. Generar pares de pregunta/respuesta en espanol.
5. Exportar artefactos auditables para revision tecnica.

Salidas principales:

- `data/processed/corpus.jsonl`
- `data/processed/qa_dataset.jsonl`
- `data/processed/audit_pipeline.md`

## Arquitectura general

```text
docs_raw/*.md
  -> MarkdownProcessor (limpieza + hash + metadata)
  -> LSHDeduplicator (MinHash-like + banding + Jaccard)
  -> QAGenerator (HF local o fallback deterministico)
  -> Export JSONL + auditoria markdown
```

## Flujo end-to-end por modulos

### 1) CLI de orquestacion

Archivo: `src/cli.py`

Responsabilidades:

- Exponer comandos `run` y `healthcheck`.
- Cargar variables de entorno con `python-dotenv`.
- Configurar logging estandar.
- Ejecutar el pipeline completo y reportar metricas.

Parametros operativos relevantes:

- `--docs-root`: ruta de entrada Markdown.
- `--processed-dir`: ruta de salida.
- `--lsh-threshold`: umbral de similitud para deduplicacion.
- `--qa-model`: modelo local de Hugging Face.
- `--fallback-only`: fuerza modo deterministico offline.

### 2) Ingesta y normalizacion

Archivo: `src/processing/markdown_processor.py`

Responsabilidades:

- Buscar recursivamente archivos `.md`.
- Limpiar contenido (scripts HTML, comentarios, espacios, saltos de linea).
- Generar hash deterministico con `xxhash`.
- Construir `Document` con trazabilidad (`project_id`, `file_path`, metadata).

Modelo de datos:

- `src/schemas/document.py` define la entidad `Document` con validaciones de contenido y timestamp UTC.

### 3) Deduplicacion por similitud

Archivo: `src/dedup/lsh_deduplicator.py`

Responsabilidades:

- Tokenizar en shingles de palabras.
- Generar firma MinHash-like deterministica (sin dependencias nativas pesadas).
- Indexar por bandas (LSH) para candidatos.
- Confirmar duplicado con similitud Jaccard y umbral configurable.
- Registrar descartes para auditoria (`discarded_records`).

Resultado:

- Conserva documentos unicos.
- Reduce ruido repetido entre versiones/copias de documentacion.

### 4) Generacion de Q&A

Archivo: `src/qa/qa_generator.py`

Responsabilidades:

- Dividir cada documento en chunks.
- Generar pares Q&A por chunk.
- Forzar salida en espanol.

Estrategias de generacion:

1. Backend local Hugging Face (si esta disponible).
2. Fallback deterministico offline (si no hay modelo o se usa `--fallback-only`).

Esto garantiza continuidad operativa en entornos sin internet o con restricciones corporativas.

### 5) Pipeline y exportacion

Archivo: `src/pipeline/main.py`

Responsabilidades:

- Orquestar etapas en secuencia.
- Medir tiempos por etapa.
- Exportar `corpus.jsonl` y `qa_dataset.jsonl`.
- Generar `audit_pipeline.md` con:
  - metadatos de ejecucion,
  - parametros usados,
  - tiempos por etapa,
  - resumen de deduplicacion.

## Modelos utilizados

### Modo local (opcional)

- Modelo por defecto: `google/flan-t5-small`
- Modelo recomendado para mayor capacidad: `google/flan-t5-base`
- Backend: `transformers` (serie 4.x) en tarea `text2text-generation`
- Requisito practico: Python 3.12 con `torch` instalado.
- Dependencia fijada: `transformers<5` para compatibilidad estable con FLAN-T5.
- Se incluye `hf_xet` para mejorar descarga/cache cuando el repositorio usa Xet Storage.

Prioridad de ejecucion QA:

1. Modelo local (transformers + torch).
2. Inferencia remota de Hugging Face (si local no produce salida usable).
3. Fallback deterministico como ultimo recurso.

Los scripts `scripts/run.ps1` y `scripts/run.sh` intentan instalar automaticamente el extra `local-model` para facilitar la evaluacion.

Variables opcionales para operacion:

- `QA_PROGRESS=1|0`: habilita/deshabilita barra de progreso en etapa QA.
- `QA_CPU_THREADS=<n>`: fija cantidad de hilos CPU para backend local con torch (por defecto usa multinucleo automaticamente).

### Modo offline deterministico

- No depende de API externa.
- No requiere descarga de modelo.
- Genera pares consistentes y reproducibles para pruebas técnicas.

## Librerias y rol en la solucion

- `typer`: interfaz CLI.
- `pydantic`: esquema y validacion de documentos/Q&A.
- `orjson`: escritura JSONL rapida.
- `python-dotenv`: carga de configuracion local.
- `xxhash`: hash deterministico eficiente.
- `transformers` + `sentencepiece`: backend local de generacion (cuando se habilita).

Principio de diseño: minimizar dependencias frágiles para favorecer portabilidad en Windows/Linux/macOS.

## Estructura del proyecto

```text
src/
  cli.py
  pipeline/main.py
  processing/markdown_processor.py
  dedup/lsh_deduplicator.py
  qa/qa_generator.py
  schemas/document.py
scripts/
  run.ps1
  run.sh
docs_raw/
data/
  processed/
```

## Ejecucion recomendada

Requisito de entorno para esta version: Python 3.12.

En Windows, para evitar problemas de rutas largas al instalar `torch` en OneDrive, se recomienda usar un entorno corto compartido en `C:\v312_meli`.

### Opcion 1: script directo (mas simple)

Windows (PowerShell):

```powershell
./scripts/run.ps1
```

Linux/macOS:

```bash
bash ./scripts/run.sh
```

Estos scripts:

1. Se posicionan en la raiz del repo.
2. Priorizan entorno Python 3.12 sano:
  - `.venv312` en el repo, o
  - `C:\v312_meli` en Windows si existe y esta sano.
3. Instalan dependencias solo si no estan presentes.
4. Ejecutan el pipeline en modo reproducible.
5. Verifican los archivos objetivo.

### Limpieza de entorno

- Se recomienda no versionar entornos locales (`.venv`, `.venv312`).
- Si necesitas limpiar el repo, elimina carpetas de entorno locales y vuelve a ejecutar `scripts/run.ps1` o `scripts/run.sh`.

### Opcion 2: ejecucion manual por modulo Python

```bash
python -m src.cli healthcheck
python -m src.cli run --docs-root docs_raw --processed-dir data/processed
```

Para forzar modo offline deterministico de forma explicita:

```bash
python -m src.cli run --docs-root docs_raw --processed-dir data/processed --fallback-only
```

Nota operativa: en algunos entornos Windows con App Control, el entrypoint `mlops-pipeline.exe` puede quedar bloqueado. En esos casos, la via recomendada es `python -m src.cli ...`.

## Validacion de funcionamiento

Checklist de validacion:

1. `healthcheck` responde `ok` y muestra modelos configurados.
2. `run` finaliza sin error.
3. Se generan los 3 artefactos esperados en `data/processed`.
4. `audit_pipeline.md` refleja conteos, tiempos y descartes.

Validacion local reciente (entorno actual):

- Documentos ingeridos: 88
- Documentos unicos: 59
- Filas Q&A: 274
- Auditoria: `data/processed/audit_pipeline.md`

## Formato de salidas

### corpus.jsonl

Campos por fila:

- `id`, `hash`, `project_id`, `file_path`, `content`, `metadata`, `timestamp`

### qa_dataset.jsonl

Campos por fila:

- `question`, `answer`, `source_document_id`, `source_hash`, `project_id`, `file_path`

## Enfoque de simplicidad y eficiencia

Decisiones aplicadas en el diseño:

1. Flujo lineal, sin componentes innecesarios.
2. Dependencias acotadas y de uso claro.
3. Ejecucion local reproducible con scripts minimos.
4. Trazabilidad completa desde cada Q&A hasta su documento fuente.
5. Auditoria generada automaticamente en cada corrida.

## Checklist de mantenimiento rapido

1. Ejecutar `python -m src.cli healthcheck` antes de una corrida nueva.
2. Ejecutar `./scripts/run.ps1` (Windows) o `bash ./scripts/run.sh` (Linux/macOS).
3. Confirmar existencia y fecha de:
  - `data/processed/corpus.jsonl`
  - `data/processed/qa_dataset.jsonl`
  - `data/processed/audit_pipeline.md`
4. Revisar en auditoria los conteos clave:
  - documentos ingeridos,
  - documentos unicos,
  - filas Q&A.
5. Si cambian dependencias, actualizar `pyproject.toml` y volver a validar con una corrida completa.
