<#
  Install Sparky onto a USB stick (Windows).

    powershell -ExecutionPolicy Bypass -File tools\setup_usb.ps1 [-Drive E:] [-NoModel] [-Yes]

  The stick should already be named "Sparky" (rename it in Explorer, or
  `label E: SPARKY`). Auto-detects a volume labeled "Sparky" if -Drive is omitted.
  DESTRUCTIVE: wipes the target drive's contents.
#>
param(
  [string]$Drive = "",
  [switch]$NoModel,
  [switch]$Yes,
  [switch]$InPlace,
  [string]$LocalModel = "qwen2.5-coder:3b"
)

$ErrorActionPreference = "Stop"
$PBS_TAG = "20260610"; $PBS_PY = "3.12.13"; $OLLAMA_TAG = "v0.30.8"
$Src = (Resolve-Path "$PSScriptRoot\..").Path

if (-not $Drive) {
  $vol = Get-Volume -FileSystemLabel "Sparky" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($vol) { $Drive = "$($vol.DriveLetter):" }
}
if (-not $Drive) { Write-Error "No 'Sparky' volume found. Pass -Drive E:"; exit 1 }
$Root = "$Drive\"
Write-Host "Installing Sparky to $Root (label should be 'Sparky')"
Write-Host "WARNING: this DELETES everything on $Drive."
if (-not $Yes) {
  $ans = Read-Host "Type 'wipe' to continue"
  if ($ans -ne "wipe") { Write-Host "Aborted."; exit 1 }
}

# ---- wipe + copy app -------------------------------------------------------
Get-ChildItem -Force -LiteralPath $Root | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
foreach ($item in @("sparky","tools","docs")) {
  if (Test-Path "$Src\$item") { Copy-Item "$Src\$item" "$Root\$item" -Recurse -Force }
}
foreach ($f in @("start.sh","start.command","START.bat","README.md")) {
  if (Test-Path "$Src\$f") { Copy-Item "$Src\$f" "$Root\$f" -Force }
}
New-Item -ItemType Directory -Force -Path "$Root\context","$Root\data\sessions" | Out-Null
"Drop files here for Sparky to always know about (auto-loaded every launch)." |
  Set-Content "$Root\context\README.txt"

# ---- fetch windows runtime -------------------------------------------------
$RT = "$Root\runtime"
New-Item -ItemType Directory -Force -Path "$RT\python","$RT\pylib","$RT\ollama\pkg\windows-x86_64","$RT\ollama\models" | Out-Null

$pyDest = "$RT\python\windows-x86_64"
if (-not (Test-Path "$pyDest\python.exe")) {
  $asset = "cpython-$PBS_PY+$PBS_TAG-x86_64-pc-windows-msvc-install_only.tar.gz"
  $url = "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/$asset"
  Write-Host "Downloading portable Python…"
  Invoke-WebRequest -Uri $url -OutFile "$env:TEMP\$asset"
  tar -xzf "$env:TEMP\$asset" -C $pyDest --strip-components=1
}
$py = "$pyDest\python.exe"

$ollDest = "$RT\ollama\pkg\windows-x86_64"
if (-not (Test-Path "$ollDest\ollama.exe")) {
  $oasset = "ollama-windows-amd64.zip"
  $url = "https://github.com/ollama/ollama/releases/download/$OLLAMA_TAG/$oasset"
  Write-Host "Downloading Ollama…"
  Invoke-WebRequest -Uri $url -OutFile "$env:TEMP\$oasset"
  Expand-Archive -Path "$env:TEMP\$oasset" -DestinationPath $ollDest -Force
}

Write-Host "Installing Python deps…"
& $py -m pip install --no-cache-dir --target "$RT\pylib" rich prompt_toolkit wcwidth pygments

# ---- pull model ------------------------------------------------------------
if (-not $NoModel) {
  $env:OLLAMA_MODELS = "$RT\ollama\models"
  $env:OLLAMA_HOST = "127.0.0.1:11434"
  $ob = "$ollDest\ollama.exe"
  if (Test-Path $ob) {
    Write-Host "Pulling $LocalModel …"
    $p = Start-Process -FilePath $ob -ArgumentList "serve" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5
    & $ob pull $LocalModel
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  }
}

Write-Host "Done. Double-click START.bat on the stick to launch Sparky."
