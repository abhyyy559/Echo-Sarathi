# One-command free-tier production deploy:
#   Vercel frontend + Render (free) API + Neon Postgres + LiveKit Cloud worker.
#
#   powershell -ExecutionPolicy Bypass -File scripts\deploy\deploy-all.ps1
#
# Everything is idempotent; re-run after changing .deploy.env or provider keys.

param(
    [switch]$SkipLiveKit,
    [switch]$SkipVercel
)

. (Join-Path $PSScriptRoot "common.ps1")

$cfg = Get-DeployConfig
Write-Section "Preflight"
Require-Values -Map $cfg -Keys @(
    "RENDER_API_KEY", "DATABASE_URL", "LIVEKIT_URL", "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET", "VERCEL_TOKEN", "JWT_SECRET",
    "INTERNAL_API_TOKEN", "DEMO_PASSWORD"
)
if ($cfg["LIVEKIT_URL"] -match "localhost|127\.0\.0\.1|^ws://") {
    throw "LIVEKIT_URL must be the LiveKit Cloud wss:// URL, not a local dev server."
}
if ($cfg["DATABASE_URL"] -notmatch "^postgres(ql)?://") {
    throw "DATABASE_URL must be a postgres connection string (Neon)."
}
if ($cfg["DATABASE_URL"] -match "localhost|127\.0\.0\.1|@db[:/]") {
    throw "DATABASE_URL points at a local database; paste the Neon connection string instead."
}
if ($cfg["DEMO_PASSWORD"].Length -lt 10) {
    throw "DEMO_PASSWORD must be at least 10 characters on a public deployment."
}
$local = Get-LocalEnv
foreach ($key in @("DEEPGRAM_API_KEY", "CARTESIA_API_KEY", "GROQ_API_KEY", "VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN")) {
    if (-not $local[$key]) { throw "Missing $key in the repo-root .env (needed by the backend and voice worker)." }
}
Write-Host "  credentials present"

$powershell = (Get-Command powershell).Source

Write-Section "Step 1/5 - resolve the Vercel production origin"
& $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "deploy-vercel.ps1") -OriginOnly
if ($LASTEXITCODE -ne 0) { throw "Could not resolve the Vercel origin." }
$cfg = Get-DeployConfig
$origin = $cfg["APP_ORIGIN"]

Write-Section "Step 2/5 - deploy the Render API"
& $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "deploy-render.ps1") -AppOrigin $origin
if ($LASTEXITCODE -ne 0) { throw "Render deploy failed." }
$cfg = Get-DeployConfig
$renderUrl = $cfg["RENDER_SERVICE_URL"]

if (-not $SkipVercel) {
    Write-Section "Step 3/5 - deploy the Vercel frontend"
    & $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "deploy-vercel.ps1") -RenderServiceUrl $renderUrl
    if ($LASTEXITCODE -ne 0) { throw "Vercel deploy failed." }
} else {
    Write-Host "  skipped (-SkipVercel)"
}

if (-not $SkipLiveKit) {
    Write-Section "Step 4/5 - deploy the LiveKit voice worker"
    & $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "deploy-livekit.ps1")
    if ($LASTEXITCODE -ne 0) { throw "LiveKit agent deploy failed." }
} else {
    Write-Host "  skipped (-SkipLiveKit)"
}

Write-Section "Step 5/5 - verify production"
& $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify-production.ps1")

Write-Section "Done"
Write-Host "  frontend : $origin"
Write-Host "  api      : $renderUrl"
Write-Host "  login    : $($cfg["DEMO_EMAIL"]) (password in .deploy.env: DEMO_PASSWORD)"
Write-Host ""
Write-Host "  Free-tier reminders:"
Write-Host "   - Render sleeps after 15 min idle; wake it before a demo:"
Write-Host "       powershell -File scripts\deploy\wake.ps1"
Write-Host "   - LiveKit Cloud agents cold-start in 10-20 s after idle."
Write-Host "   - Render free hours: 750/workspace/month shared by all free services."
