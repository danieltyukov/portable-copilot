<#
  Fetch the Windows runtime onto the stick ADDITIVELY (no wipe).
  Called automatically by START.bat the first time Sparky runs on a Windows PC.
  Adds runtime\python\windows-x86_64 and runtime\ollama\pkg\windows-x86_64; reuses
  the shared runtime\pylib and the OS-independent model already on the stick.

    powershell -ExecutionPolicy Bypass -File tools\fetch_runtime.ps1 -Root D:\ [-NoOllama]
#>
param(
  [Parameter(Mandatory = $true)][string]$Root,
  [switch]$NoOllama
)
$ErrorActionPreference = "Stop"
$PBS_TAG = "20260610"; $PBS_PY = "3.12.13"; $OLLAMA_TAG = "v0.30.8"
$RT = Join-Path $Root "runtime"
New-Item -ItemType Directory -Force -Path `
  "$RT\python\windows-x86_64", "$RT\pylib", "$RT\ollama\pkg\windows-x86_64", "$RT\ollama\models" | Out-Null

# ---- portable Python (relocatable, install_only) --------------------------
$pyDest = "$RT\python\windows-x86_64"
$py = "$pyDest\python.exe"
if (-not (Test-Path $py)) {
  $asset = "cpython-$PBS_PY+$PBS_TAG-x86_64-pc-windows-msvc-install_only.tar.gz"
  $url = "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/$asset"
  Write-Host "Sparky: downloading portable Python for Windows (~30 MB)..."
  $tmp = Join-Path $env:TEMP $asset
  Invoke-WebRequest -Uri $url -OutFile $tmp
  tar -xzf $tmp -C $pyDest --strip-components=1
  Remove-Item $tmp -ErrorAction SilentlyContinue
}

# ---- shared pure-Python deps (only if not already present from another OS) --
if (-not (Get-ChildItem $RT\pylib -ErrorAction SilentlyContinue)) {
  Write-Host "Sparky: installing Python deps..."
  & $py -m pip install --no-cache-dir --target "$RT\pylib" rich prompt_toolkit wcwidth pygments | Out-Null
}

# ---- Ollama for Windows (offline mode) ------------------------------------
$ollDest = "$RT\ollama\pkg\windows-x86_64"
if (-not $NoOllama -and -not (Test-Path "$ollDest\ollama.exe")) {
  $oasset = "ollama-windows-amd64.zip"
  $url = "https://github.com/ollama/ollama/releases/download/$OLLAMA_TAG/$oasset"
  Write-Host "Sparky: downloading Ollama for Windows (large, one-time; needed for OFFLINE mode)..."
  $tmp = Join-Path $env:TEMP $oasset
  Invoke-WebRequest -Uri $url -OutFile $tmp
  Expand-Archive -Path $tmp -DestinationPath $ollDest -Force
  Remove-Item $tmp -ErrorAction SilentlyContinue
  # If ollama.exe landed in a subfolder, flatten it to the dest root.
  if (-not (Test-Path "$ollDest\ollama.exe")) {
    $exe = Get-ChildItem $ollDest -Recurse -Filter ollama.exe | Select-Object -First 1
    if ($exe) { Move-Item "$($exe.Directory)\*" $ollDest -Force -ErrorAction SilentlyContinue }
  }
  # Drop GPU runner folders to save space (portable use is CPU-only).
  Get-ChildItem $ollDest -Recurse -Directory -Include "cuda*", "rocm*" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

# ---- model check (shared, OS-independent) ---------------------------------
if (-not (Get-ChildItem "$RT\ollama\models\blobs" -ErrorAction SilentlyContinue)) {
  Write-Host "Sparky: note - no local model found on the stick; offline answers need one (it is normally bundled at setup)."
}
Write-Host "Sparky: Windows runtime ready."
