<#
  Put a portable Python for this Windows PC into <Root>\runtime\python\<os-arch>.

    powershell -NoProfile -ExecutionPolicy Bypass -File tools\fetch_python.ps1 -Root D:\

  Only the bootstrap: once Python is there, `python -m sparky runtime` fetches
  the rest (the model server and the libraries).
#>
param([Parameter(Mandatory = $true)][string]$Root)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # the progress bar makes Invoke-WebRequest many times slower

$PBS_TAG = "20261003"; $PBS_PY = "3.12.15"
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
$triple = if ($arch -eq "aarch64") { "aarch64-pc-windows-msvc" } else { "x86_64-pc-windows-msvc" }
$dest = Join-Path $Root "runtime\python\windows-$arch"
if (Test-Path (Join-Path $dest "python.exe")) { exit 0 }

$asset = "cpython-$PBS_PY+$PBS_TAG-$triple-install_only_stripped.tar.gz"
$base = "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG"
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("sparky-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
  Write-Host "Sparky: downloading a portable Python for Windows (about 22 MB, once)..."
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -UseBasicParsing -Uri "$base/$asset" -OutFile (Join-Path $tmp $asset)
  $sums = (Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS").Content
  $line = ($sums -split "`n") | Where-Object { $_ -match [regex]::Escape($asset) + '\s*$' } | Select-Object -First 1
  $expected = if ($line) { ($line -split '\s+')[0].ToLower() } else { "" }
  $got = (Get-FileHash -Algorithm SHA256 (Join-Path $tmp $asset)).Hash.ToLower()
  if (-not $expected -or $expected -ne $got) {
    throw "the Python download did not match its published checksum"
  }
  # tar.exe ships with Windows 10 (1803) and later
  tar -xzf (Join-Path $tmp $asset) -C $tmp
  $py = Join-Path $tmp "python"
  foreach ($rel in @("Lib\test", "Lib\idlelib", "Lib\tkinter", "Lib\turtledemo", "Lib\lib2to3", "Lib\ensurepip",
                   "Lib\pydoc_data", "tcl", "include", "libs")) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $py $rel)
  }
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  Copy-Item -Recurse -Force (Join-Path $py "*") $dest
  Set-Content -Path (Join-Path $dest "SPARKY_VERSION") -Value $PBS_PY
  Write-Host "Sparky: Python ready."
} finally {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tmp
}
