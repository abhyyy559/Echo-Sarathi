<#
.SYNOPSIS
    Stop the local dev stack. Data volumes are KEPT by default.

.PARAMETER Clean
    Also delete the postgres volume - ALL local data (tenants, agents,
    call records) is permanently lost. Prompts nothing; read the warning.

.USAGE
    powershell -ExecutionPolicy Bypass -File scripts\dev-down.ps1           # keep data
    powershell -ExecutionPolicy Bypass -File scripts\dev-down.ps1 -Clean    # wipe data too
#>
param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

$Root        = Split-Path -Parent $PSScriptRoot          # repo root
$ComposeFile = Join-Path $Root 'infra\docker-compose.yml'
$EnvFile     = Join-Path $Root '.env'

Write-Host '=== AI Voice Calling Agent - dev-down ===' -ForegroundColor Cyan

if ($Clean) {
    Write-Host '[dev-down] WARNING: -Clean removes named volumes (postgres_data).' -ForegroundColor Yellow
    Write-Host '[dev-down] ALL local data (organizations, agents, calls, transcripts) is deleted.' -ForegroundColor Yellow
    & docker compose -f $ComposeFile --env-file $EnvFile down -v
} else {
    Write-Host '[dev-down] Stopping stack (volumes are KEPT - rerun with -Clean to wipe data).'
    & docker compose -f $ComposeFile --env-file $EnvFile down
}

if ($LASTEXITCODE -ne 0) {
    Write-Host '[dev-down] ERROR: docker compose down failed.' -ForegroundColor Red
    exit 1
}

Write-Host '[dev-down] Stack stopped.' -ForegroundColor Green
