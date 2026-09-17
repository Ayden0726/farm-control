# Update Print FarmOS from git and rebuild containers. Database and uploads are kept.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\docker-compose.yml")) {
  Write-Error "Run this from the Print FarmOS folder."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Error "Docker is not installed. Start Docker Desktop, then re-run .\update.ps1"
}
if (-not (Test-Path ".\.git")) {
  Write-Error "This folder is not a git clone. Copy a new release over it, then re-run .\update.ps1"
}

Write-Host "==> Pulling latest code"
git pull --ff-only
$version = (git rev-parse --short HEAD).Trim()
$env:APP_VERSION = $version

if (Test-Path ".\.env") {
  $text = Get-Content ".\.env" -Raw
  if ($text -match "(?m)^APP_VERSION=") {
    $text = [regex]::Replace($text, "(?m)^APP_VERSION=.*$", "APP_VERSION=$version")
  } else {
    $text = $text.TrimEnd() + "`nAPP_VERSION=$version`n"
  }
  Set-Content -Path ".\.env" -Value $text -Encoding ascii -NoNewline
}

Write-Host "==> Rebuilding Print FarmOS $version (database and G-code uploads are kept)"
docker compose up -d --build db redis backend worker slicer-worker frontend
if ($LASTEXITCODE -ne 0) { Write-Error "docker compose failed" }
docker compose up -d --no-build update-agent

Write-Host ""
Write-Host "Update complete. Open the FarmOS URL in your browser."
Write-Host "If the UI looks old, hard-refresh (Ctrl+Shift+R)."

if (-not $env:UPDATE_FROM_AGENT) {
  $agentDir = Join-Path $PSScriptRoot "data\update"
  New-Item -ItemType Directory -Force -Path $agentDir | Out-Null
  $pidFile = Join-Path $agentDir "agent.pid"
  $running = $false
  if (Test-Path $pidFile) {
    $oldId = Get-Content $pidFile | Select-Object -First 1
    if ($oldId -and (Get-Process -Id $oldId -ErrorAction SilentlyContinue)) { $running = $true }
  }
  if (-not $running) {
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
      "-NoProfile", "-WindowStyle", "Hidden", "-File", (Join-Path $PSScriptRoot "scripts\update-agent.ps1")
    ) -PassThru
    $proc.Id | Set-Content $pidFile
  }
}
