# scripts/test_call.ps1 — one-command telephony test call (demo helper)
#
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\test_call.ps1            # uses TEST_PHONE_NUMBERS[0]
#   powershell -ExecutionPolicy Bypass -File scripts\test_call.ps1 -To +919391470646 -Hold 45
#
# Places a REAL call via /api/test-call (uses real Vobiz minutes), then polls
# the call status so you can watch it progress. Ctrl+C to stop polling — the
# call itself is not cancelled.

param(
    [string]$To = "",
    [int]$Hold = 60,
    [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

# --- config from .env ---------------------------------------------------------
$envMap = @{}
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$' -and $_ -notmatch '^\s*#') {
        $envMap[$matches[1]] = $matches[2].Trim()
    }
}

$demoEmail = $envMap["DEMO_EMAIL"];    if (-not $demoEmail) { $demoEmail = "demo@example.com" }
$demoPass  = $envMap["DEMO_PASSWORD"]; if (-not $demoPass)  { $demoPass  = "demo1234" }

# --- 1. login ------------------------------------------------------------------
$loginBody = @{ email = $demoEmail; password = $demoPass } | ConvertTo-Json
try {
    $login = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -Body $loginBody -ContentType "application/json" -TimeoutSec 15
} catch {
    Write-Host "LOGIN FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
$token = $login.token
Write-Host "Logged in as $demoEmail" -ForegroundColor Green

# --- 2. place test call ----------------------------------------------------------
$headers = @{ Authorization = "Bearer $token" }
$callBody = @{}
if ($To -ne "") { $callBody.to = $To }
$callJson = $callBody | ConvertTo-Json

Write-Host "Placing test call..." -ForegroundColor Cyan
try {
    $resp = Invoke-RestMethod -Uri "$BaseUrl/api/test-call" -Method Post -Body $callJson -ContentType "application/json" -Headers $headers -TimeoutSec 60
} catch {
    $detail = ""
    try { $detail = ($_.ErrorDetails.Message | ConvertFrom-Json).detail } catch {}
    Write-Host "TEST CALL FAILED: $detail$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "Call placed: call_id=$($resp.call_id) provider_id=$($resp.provider_call_id) room=$($resp.room_name)" -ForegroundColor Green

# --- 3. poll status ---------------------------------------------------------------
Write-Host "Polling for $Hold seconds (Ctrl+C to stop polling; the call continues)..." -ForegroundColor Cyan
$deadline = (Get-Date).AddSeconds($Hold)
$last = ""
while ((Get-Date) -lt $deadline) {
    try {
        $call = Invoke-RestMethod -Uri "$BaseUrl/api/calls/$($resp.call_id)" -Method Get -Headers $headers -TimeoutSec 10
        $line = "status=$($call.status)  duration=$($call.duration_s)s"
        if ($line -ne $last) { Write-Host $line -ForegroundColor Yellow; $last = $line }
        if ($call.status -in @("completed", "failed", "no_answer", "busy", "canceled")) { break }
    } catch { # call detail endpoint may differ; keep polling silently
    }
    Start-Sleep -Seconds 2
}
Write-Host "Done. Check http://localhost:3000 (Calls page) for transcript and events." -ForegroundColor Green
