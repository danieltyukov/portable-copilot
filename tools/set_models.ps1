# Swap the local Qwen models on a Sparky stick (Windows) — for resizing to
# bigger/smaller USB drives. Pulls the chosen models into the stick's Ollama
# store and writes the tier overrides into data\sparky.env.
#
#   powershell -ExecutionPolicy Bypass -File tools\set_models.ps1 `
#       [-Mount D:\] [-Preset small|medium|large|xl] [-Fast TAG] [-Max TAG] `
#       [-RmOld] [-NoPull] [-List]
param(
  [string]$Mount = "",
  [string]$Preset = "large",
  [string]$Fast = "",
  [string]$Max = "",
  [switch]$RmOld,
  [switch]$NoPull,
  [switch]$List
)
$ErrorActionPreference = "Stop"

if (-not $Mount) {
  if ($env:SPARKY_ROOT) { $Mount = $env:SPARKY_ROOT }
  else {
    $v = Get-Volume | Where-Object { $_.FileSystemLabel -eq "Sparky" } | Select-Object -First 1
    if ($v) { $Mount = "$($v.DriveLetter):\" } else { throw "No 'Sparky' drive found. Pass -Mount." }
  }
}
if (-not (Test-Path $Mount)) { throw "Mount $Mount does not exist." }

switch ($Preset) {
  "small"  { $pFast = "qwen3.5:0.8b"; $pMax = "qwen3.5:4b" }
  "medium" { $pFast = "qwen3.5:4b";   $pMax = "qwen3.5:9b" }
  "large"  { $pFast = "qwen3.5:4b";   $pMax = "qwen3-coder:30b" }
  "xl"     { $pFast = "qwen3.5:9b";   $pMax = "qwen3.6:35b-a3b" }
  default  { throw "unknown preset: $Preset (small|medium|large|xl)" }
}
if (-not $Fast) { $Fast = $pFast }
if (-not $Max)  { $Max  = $pMax }

$env:OLLAMA_MODELS = Join-Path $Mount "runtime\ollama\models"
if (-not $env:OLLAMA_HOST) { $env:OLLAMA_HOST = "127.0.0.1:11500" }
New-Item -ItemType Directory -Force -Path $env:OLLAMA_MODELS | Out-Null

$ob = $null
$bundled = Join-Path $Mount "runtime\ollama\pkg\windows-x86_64\ollama.exe"
if (Test-Path $bundled) { $ob = $bundled }
elseif (Get-Command ollama -ErrorAction SilentlyContinue) { $ob = (Get-Command ollama).Source }
if (-not $ob) { throw "No ollama.exe found (bundled or host). Run setup first." }

$srv = Start-Process -FilePath $ob -ArgumentList "serve" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3
try {
  if ($List) {
    Write-Host "Models on $Mount :"; & $ob list
    return
  }
  Write-Host "Stick : $Mount"
  Write-Host "fast  : $Fast"
  Write-Host "max   : $Max   (default tier)"

  if (-not $NoPull) {
    foreach ($m in @($Fast, $Max)) { Write-Host "Pulling $m ..."; & $ob pull $m }
  }
  if ($RmOld) {
    $have = (& $ob list) | Select-Object -Skip 1 | ForEach-Object { ($_ -split "\s+")[0] }
    foreach ($m in $have) { if ($m -and $m -ne $Fast -and $m -ne $Max) { Write-Host "Removing $m ..."; & $ob rm $m } }
  }
} finally {
  if ($srv) { Stop-Process -Id $srv.Id -ErrorAction SilentlyContinue }
}

$envFile = Join-Path $Mount "data\sparky.env"
New-Item -ItemType Directory -Force -Path (Join-Path $Mount "data") | Out-Null
$lines = @()
if (Test-Path $envFile) {
  $lines = Get-Content $envFile | Where-Object { $_ -notmatch '^(SPARKY_FAST_MODEL|SPARKY_MAX_MODEL)=' }
}
if (-not ($lines -match '^#')) { $lines = @("# Sparky settings - fully local, no API keys needed.") + $lines }
$lines += "SPARKY_FAST_MODEL=$Fast"
$lines += "SPARKY_MAX_MODEL=$Max"
Set-Content -Path $envFile -Value $lines -Encoding UTF8

Write-Host ""
Write-Host "Done. data\sparky.env now points fast->$Fast, max->$Max."
Write-Host "Launch Sparky and use /model fast|max (or Ctrl-T) to switch."
