# Host-side loop that applies Settings → Update Print FarmOS on Windows.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
Set-Location $Root
$Dir = Join-Path $Root "data\update"
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$PID | Set-Content -Path (Join-Path $Dir "agent.pid")

function Write-Status([string]$Status, [string]$Message) {
  $payload = @{ status = $Status; message = $Message; at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ") } | ConvertTo-Json -Compress
  Set-Content -Path (Join-Path $Dir "status.json") -Value $payload -Encoding utf8
}

Write-Status "idle" "Waiting for an update from Settings."

while ($true) {
  [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) | Set-Content -Path (Join-Path $Dir "heartbeat") -Encoding ascii
  $request = Join-Path $Dir "request"
  if (Test-Path $request) {
    Remove-Item $request -Force
    Write-Status "updating" "Pulling the latest Print FarmOS and rebuilding. This can take several minutes."
    $log = Join-Path $Dir "log.txt"
    $env:UPDATE_FROM_AGENT = "1"
    & (Join-Path $Root "update.ps1") *> $log
    if ($LASTEXITCODE -eq 0) {
      Write-Status "ok" "Update finished. Hard-refresh the browser if the UI looks old."
    } else {
      Write-Status "error" "Update failed. Check data\\update\\log.txt or run .\\update.ps1 in a terminal."
    }
  }
  Start-Sleep -Seconds 2
}
