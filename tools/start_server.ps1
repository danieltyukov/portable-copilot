<#
  Start the stick's model server for START.bat, unless one is already running.
  Prints the process id it started, or 0 when it reused one (or could not
  start one), so the launcher only stops what it started.
  Reads ROOT, OLLAMA_BIN and OLLAMA_HOST from the environment START.bat sets.
#>
$ErrorActionPreference = "SilentlyContinue"
$hostPort = $env:OLLAMA_HOST -replace '^https?://', ''
$h, $p = $hostPort -split ':'

function Test-Listening {
  $c = New-Object System.Net.Sockets.TcpClient
  try {
    $ar = $c.BeginConnect($h, [int]$p, $null, $null)
    return ($ar.AsyncWaitHandle.WaitOne(300) -and $c.Connected)
  } finally { $c.Close() }
}

if (Test-Listening) { Write-Output 0; exit 0 }
if (-not (Test-Path $env:OLLAMA_BIN)) {
  [Console]::Error.WriteLine("Sparky: no model server on this stick for Windows; run setup to add it.")
  Write-Output 0; exit 0
}
$log = Join-Path $env:ROOT "data\ollama.log"
$err = Join-Path $env:ROOT "data\ollama.err.log"
$proc = Start-Process -FilePath $env:OLLAMA_BIN -ArgumentList "serve" -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput $log -RedirectStandardError $err
for ($i = 0; $i -lt 80; $i++) {
  if (Test-Listening) { break }
  if ($proc.HasExited) {
    [Console]::Error.WriteLine("Sparky: the model server did not start; see data\ollama.err.log")
    break
  }
  Start-Sleep -Milliseconds 250
}
Write-Output $proc.Id
