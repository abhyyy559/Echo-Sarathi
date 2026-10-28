<#
.SYNOPSIS
    Bring up the full local dev stack: db, backend (:8000), LiveKit
    (:7880), voice-agent worker, frontend (:3000). Waits for backend health.

.DESCRIPTION
    - Verifies the Docker daemon is reachable (starts nothing itself).
    - Creates .env from .env.example on first run and warns loudly to fill in
      provider API keys.
    - Runs: docker compose up --build -d  (compose file: infra/docker-compose.yml)
    - Polls http://localhost:8000/api/health until ready, then prints a URL
      cheat-sheet.

.USAGE
    powershell -ExecutionPolicy Bypass -File scripts\dev-up.ps1
#>

$ErrorActionPreference = 'Stop'

$Root        = Split-Path -Parent $PSScriptRoot          # repo root
$ComposeFile = Join-Path $Root 'infra\docker-compose.yml'
$EnvExample  = Join-Path $Root '.env.example'
$EnvFile     = Join-Path $Root '.env'
$HealthUrl   = 'http://localhost:8000/api/health'

Write-Host '=== AI Voice Calling Agent - dev-up ===' -ForegroundColor Cyan

# --- 1) Docker daemon reachable? ---------------------------------------------
# PS 5.1 quirk: redirecting native stderr (*>) while $ErrorActionPreference is
# 'Stop' can raise NativeCommandError. Relax EAP for the probe only, and judge
# by $LASTEXITCODE, not $?.
$PrevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
docker info *> $null
$DockerOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $PrevEap
if (-not $DockerOk) {
    Write-Host '[dev-up] ERROR: Docker daemon is not reachable.' -ForegroundColor Red
    Write-Host '[dev-up] Start Docker Desktop, wait for it to finish loading, then re-run.' -ForegroundColor Red
    exit 1
}

# --- 2) .env present? If not, create it with a loud warning. ------------------
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
    Write-Host ''
    Write-Host '+===========================================================+' -ForegroundColor Yellow
    Write-Host '|  .env WAS MISSING - created it from .env.example.         |' -ForegroundColor Yellow
    Write-Host '|                                                           |' -ForegroundColor Yellow
    Write-Host '|  OPEN .env NOW AND FILL IN YOUR PROVIDER API KEYS:        |' -ForegroundColor Yellow
    Write-Host '|    DEEPGRAM_API_KEY   (speech-to-text)                    |' -ForegroundColor Yellow
    Write-Host '|    CARTESIA_API_KEY   (text-to-speech)                    |' -ForegroundColor Yellow
    Write-Host '|    GROQ_API_KEY  or  OPENAI_API_KEY  (LLM)                |' -ForegroundColor Yellow
    Write-Host '|                                                           |' -ForegroundColor Yellow
    Write-Host '|  The stack will still start, but playground conversations |' -ForegroundColor Yellow
    Write-Host '|  degrade until those keys are real. JWT/LiveKit/internal  |' -ForegroundColor Yellow
    Write-Host '|  dev defaults are fine as-is for local testing.           |' -ForegroundColor Yellow
    Write-Host '+===========================================================+' -ForegroundColor Yellow
    Write-Host ''
}

# --- 3) Build + start ----------------------------------------------------------
Write-Host '[dev-up] Building and starting containers (first build takes a few minutes)...'
& docker compose -f $ComposeFile --env-file $EnvFile up --build -d
if ($LASTEXITCODE -ne 0) {
    Write-Host '[dev-up] ERROR: docker compose up failed.' -ForegroundColor Red
    Write-Host "[dev-up] Try: docker compose -f `"$ComposeFile`" --env-file `"$EnvFile`" logs" -ForegroundColor Red
    exit 1
}

# --- 4) Wait for backend health -------------------------------------------------
Write-Host '[dev-up] Waiting for backend health at http://localhost:8000/api/health ...'
$Healthy  = $false
$MaxTries = 60   # ~2 minutes at 2s per attempt
for ($i = 1; $i -le $MaxTries; $i++) {
    $Ok = $false
    try {
        $Resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 3
        if ($Resp.StatusCode -eq 200) { $Ok = $true }
    } catch {
        # not up yet - keep polling
    }
    if ($Ok) { $Healthy = $true; break }
    if ($i % 5 -eq 0) { Write-Host "  ...still waiting ($($i * 2)s)" }
    Start-Sleep -Seconds 2
}
Write-Host ''

if ($Healthy) {
    Write-Host '[dev-up] Backend is healthy.' -ForegroundColor Green
    try {
        $Resp  = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
        Write-Host '[dev-up] /api/health says:'
        Write-Host $Resp.Content
    } catch {
        # non-fatal; health already confirmed above
    }
} else {
    Write-Host '[dev-up] WARNING: backend did not report healthy within the timeout.' -ForegroundColor Yellow
    Write-Host '[dev-up] Check logs:' -ForegroundColor Yellow
    Write-Host '[dev-up]   docker compose -f infra\docker-compose.yml --env-file .env logs backend' -ForegroundColor Yellow
}

# --- 5) Cheat sheet ---------------------------------------------------------------
Write-Host ''
Write-Host '==================== DEV STACK UP - CHEAT SHEET ====================' -ForegroundColor Cyan
Write-Host '  Frontend (React)     : http://localhost:3000'
Write-Host '  API docs (Swagger)   : http://localhost:8000/docs'
Write-Host '  Health               : http://localhost:8000/api/health'
Write-Host '  LiveKit (signaling)  : ws://localhost:7880'
Write-Host ''
Write-Host '  Next step - seed the demo tenant (one command):'
Write-Host '    powershell -ExecutionPolicy Bypass -File scripts\seed.ps1'
Write-Host ''
Write-Host '  Then log in at http://localhost:3000:'
Write-Host '    demo@example.com / demo1234'
Write-Host '=====================================================================' -ForegroundColor Cyan
