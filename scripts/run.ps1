$ErrorActionPreference = "Stop"

# Ejecutar siempre desde la raiz del repositorio, sin depender del directorio actual.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path "docs_raw")) {
	throw "Ejecucion cancelada: no existe docs_raw. Verifica la carpeta de entrada."
}

$venvDir = ".venv312"
$venv312Exists = Test-Path "$venvDir\Scripts\python.exe"
$sharedVenvDir = "C:\v312_meli"
$sharedVenvExists = Test-Path "$sharedVenvDir\Scripts\python.exe"

function Test-EnvHealthy {
	param(
		[string]$PyExe
	)
	if (-not (Test-Path $PyExe)) {
		return $false
	}
	& $PyExe -c "import transformers" *> $null
	if ($LASTEXITCODE -ne 0) {
		return $false
	}
	& $PyExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('torch') else 1)" *> $null
	return ($LASTEXITCODE -eq 0)
}
$py312Command = $null

# 1) Permitir ruta explicita por variable de entorno.
if ($env:PYTHON312_PATH -and (Test-Path $env:PYTHON312_PATH)) {
	$py312Command = '"' + $env:PYTHON312_PATH + '"'
}

# 2) Launcher de Python en Windows.
if (-not $py312Command) {
	try {
		py -3.12 -c "import sys; print(sys.version)" *> $null
		if ($LASTEXITCODE -eq 0) {
			$py312Command = "py -3.12"
		}
	} catch {
		$py312Command = $null
	}
}

# 3) Comando alterno (MSYS/Git Bash/instalacion custom).
if (-not $py312Command) {
	try {
		python3.12 -c "import sys; print(sys.version)" *> $null
		if ($LASTEXITCODE -eq 0) {
			$py312Command = "python3.12"
		}
	} catch {
		$py312Command = $null
	}
}

if ($venv312Exists) {
	$localPy = "$venvDir\Scripts\python.exe"
	if (Test-EnvHealthy -PyExe $localPy) {
		Write-Host "Usando entorno existente Python 3.12 en $venvDir"
	} elseif ($sharedVenvExists -and (Test-EnvHealthy -PyExe "$sharedVenvDir\Scripts\python.exe")) {
		$venvDir = $sharedVenvDir
		Write-Warning "Entorno .venv312 no esta sano (transformers/torch). Se usara entorno compartido en $venvDir"
	} else {
		Write-Warning "Entorno .venv312 no esta sano; se intentara reparar durante la instalacion de dependencias."
	}
} elseif ($sharedVenvExists -and (Test-EnvHealthy -PyExe "$sharedVenvDir\Scripts\python.exe")) {
	$venvDir = $sharedVenvDir
	Write-Host "Usando entorno Python 3.12 compartido en $venvDir"
} elseif ($py312Command) {
	Write-Host "Creando entorno Python 3.12 en $venvDir ..."
	if ($py312Command -eq "py -3.12") {
		py -3.12 -m venv $venvDir
	} elseif ($py312Command -eq "python3.12") {
		python3.12 -m venv $venvDir
	} else {
		& $env:PYTHON312_PATH -m venv $venvDir
	}
} else {
	throw "Ejecucion cancelada: no se encontro Python 3.12 ni entorno .venv312. Instala Python 3.12, o define PYTHON312_PATH con la ruta a python.exe 3.12, o crea .venv312 manualmente."
}

if ([System.IO.Path]::IsPathRooted($venvDir)) {
	$activateScript = Join-Path $venvDir "Scripts\Activate.ps1"
	$pythonExe = Join-Path $venvDir "Scripts\python.exe"
} else {
	$activateScript = ".\$venvDir\Scripts\Activate.ps1"
	$pythonExe = ".\$venvDir\Scripts\python.exe"
}

& $activateScript
$pythonVersion = (& $pythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
Write-Host "Entorno seleccionado: $venvDir | Python $pythonVersion"

$dependenciasOk = $false
& $pythonExe -c "import orjson, typer, xxhash, pydantic, dotenv" 2>$null
if ($LASTEXITCODE -eq 0) {
	$dependenciasOk = $true
}

if ($dependenciasOk) {
	& $pythonExe -c "import transformers, sys; sys.exit(0 if int(transformers.__version__.split('.', 1)[0]) < 5 else 1)" *> $null
	if ($LASTEXITCODE -ne 0) {
		Write-Warning "Se detecto transformers>=5; se resincronizaran dependencias del proyecto."
		$dependenciasOk = $false
	}
}

if (-not $dependenciasOk) {
	& $pythonExe -m pip install --upgrade pip
	& $pythonExe -m pip install -e .
}

$torchOk = $false
& $pythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('torch') else 1)" *> $null
if ($LASTEXITCODE -eq 0) {
	$torchOk = $true
}

if (-not $torchOk -and $pythonVersion -lt "3.13") {
	Write-Host "Intentando instalar backend local de modelo (torch)..."
	# En Windows, instalar wheel CPU de torch mejora la reproducibilidad para evaluacion local.
	try {
		& $pythonExe -m pip install --index-url https://download.pytorch.org/whl/cpu torch
	} catch {
		Write-Warning "Instalacion directa de torch CPU fallo; se intentara extra local-model."
	}
	& $pythonExe -m pip install -e ".[local-model]"
	& $pythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('torch') else 1)" *> $null
	if ($LASTEXITCODE -ne 0) {
		Write-Warning "No se pudo instalar torch; se continuara con backend remoto y fallback como ultimo recurso."
	} else {
		Write-Host "Torch instalado correctamente en $venvDir"
	}
}

if ($pythonVersion -ge "3.13" -and -not ($env:QA_FALLBACK_ONLY -and $env:QA_FALLBACK_ONLY.ToLower() -in @("1", "true", "yes", "on"))) {
	Write-Warning "Python $pythonVersion detectado: para usar QA con modelo local se recomienda Python 3.11 o 3.12 (torch no suele estar disponible en 3.13)."
}

# Usar el modulo Python evita problemas cuando el entrypoint no esta en PATH.
# Solo forzar fallback si QA_FALLBACK_ONLY=true en el entorno.
$runArgs = @(
	"-m", "src.cli", "run",
	"--docs-root", "docs_raw",
	"--processed-dir", "data/processed",
	"--qa-max-new-tokens", "96"
)
if ($env:QA_FALLBACK_ONLY -and $env:QA_FALLBACK_ONLY.ToLower() -in @("1", "true", "yes", "on")) {
	$runArgs += "--fallback-only"
}
& $pythonExe @runArgs

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
