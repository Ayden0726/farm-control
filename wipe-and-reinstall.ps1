# Wipe Print FarmOS shop data and reinstall the stack.
# Usage (from the folder that contains this file):
#   .\wipe-and-reinstall.ps1
#   .\wipe-and-reinstall.ps1 -HostUrl http://192.168.1.50:3000
param(
  [string]$HostUrl = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\install.ps1") -or -not (Test-Path ".\docker-compose.yml")) {
  Write-Error "Run this from the Print FarmOS folder (the one with install.ps1 and docker-compose.yml)."
}

Write-Host ""
Write-Host "==> Wiping Print FarmOS and reinstalling"
Write-Host "    This deletes the database (orders, queue, users, settings)."
Write-Host "    .env (passwords and the public URL) is kept."
Write-Host ""

if (Test-Path ".\.git") {
  Write-Host "==> Pulling latest code from Git"
  git pull --ff-only
}

if ($HostUrl) {
  & (Join-Path $PSScriptRoot "install.ps1") -Reset -HostUrl $HostUrl
} else {
  & (Join-Path $PSScriptRoot "install.ps1") -Reset
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
