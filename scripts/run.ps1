$ErrorActionPreference = "Stop"

# Ejecutar siempre desde la raiz del repositorio, sin depender del directorio actual.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path "docs_raw")) {
	throw "Ejecucion cancelada: no existe docs_raw. Verifica la carpeta de entrada."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
	python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
$pythonExe = ".\.venv\Scripts\python.exe"

$dependenciasOk = $false
& $pythonExe -c "import orjson, typer, xxhash, pydantic, dotenv" 2>$null
if ($LASTEXITCODE -eq 0) {
	$dependenciasOk = $true
}

if (-not $dependenciasOk) {
	& $pythonExe -m pip install --upgrade pip
	& $pythonExe -m pip install -e .
}

# Usar el modulo Python evita problemas cuando el entrypoint no esta en PATH.
& $pythonExe -m src.cli run --docs-root docs_raw --processed-dir data/processed --fallback-only

if (-not (Test-Path "data/processed/corpus.jsonl") -or -not (Test-Path "data/processed/qa_dataset.jsonl") -or -not (Test-Path "data/processed/audit_pipeline.md")) {
	throw "Ejecucion cancelada: no se generaron todos los archivos objetivo (corpus.jsonl, qa_dataset.jsonl, audit_pipeline.md)."
}

$corpus = Get-Item "data/processed/corpus.jsonl"
$qa = Get-Item "data/processed/qa_dataset.jsonl"
$audit = Get-Item "data/processed/audit_pipeline.md"

Write-Host "Resumen de salidas generadas:"
Write-Host ("- {0} | {1} bytes | actualizado: {2}" -f $corpus.Name, $corpus.Length, $corpus.LastWriteTime)
Write-Host ("- {0} | {1} bytes | actualizado: {2}" -f $qa.Name, $qa.Length, $qa.LastWriteTime)
Write-Host ("- {0} | {1} bytes | actualizado: {2}" -f $audit.Name, $audit.Length, $audit.LastWriteTime)
