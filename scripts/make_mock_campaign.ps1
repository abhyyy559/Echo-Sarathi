<#
scripts/make_mock_campaign.ps1

Creates a "Mock Campaign" for testing the call pipeline WITHOUT dialling the
real numbers: it reads TEST_PHONE_NUMBERS from .env (the allowlist, never the
user's own number). The campaign is left as a DRAFT and a roster CSV is
written; to actually start dialling, launch it (see the end of the script).

Usage (PowerShell, from the repo root):
    powershell -ExecutionPolicy Bypass -File scripts\make_mock_campaign.ps1
#>

param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$Email = "demo@example.com",
    [string]$Password = "demo1234",
    [string]$CampaignName = "Mock Campaign",
    [int]$ContactCount = 3
)

# --- login -----------------------------------------------------------------
$login = Invoke-RestMethod "$BaseUrl/api/auth/login" -Method Post `
    -Body (@{email = $Email; password = $Password} | ConvertTo-Json) `
    -ContentType "application/json"
$token = $login.token
$h = @{Authorization = "Bearer $token"}

# --- allowlisted phones (never the user's own number) ----------------------
$envFile = Join-Path (Join-Path $PSScriptRoot '..') '.env'
$envText = Get-Content $envFile -Raw
$m = [regex]::Match($envText, '(?m)^TEST_PHONE_NUMBERS\s*=\s*([^#\r\n]*)')
if (-not $m.Success) { Write-Error "no TEST_PHONE_NUMBERS in .env"; exit 1 }
$phones = $m.Groups[1].Value -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
$phones = $phones | Where-Object { $_ -notmatch "9391470646" }  # the user's own number
if ($phones.Count -lt 1) { Write-Error "TEST_PHONE_NUMBERS is empty"; exit 1 }

# --- campaign ----------------------------------------------------------------
$campaign = Invoke-RestMethod "$BaseUrl/api/campaigns" -Method Post -Headers $h `
    -ContentType "application/json" -Body (@{name = $CampaignName; agent_version_id = 1} | ConvertTo-Json)

# --- roster file for the import step (Campaigns -> Import in the UI) ---------
$csvPath = Join-Path $env:TEMP "mock-campaign-$($campaign.id).csv"
$csv = "name,phone`n"
for ($i = 0; $i -lt [Math]::Min($ContactCount, $phones.Count); $i++) {
    $csv += "${CampaignName} Tester,$($phones[$i])`n"
}
Set-Content -Path $csvPath -Value $csv -Encoding utf8

Write-Host "Mock campaign created (draft): $BaseUrl/api/campaigns/$($campaign.id)"
Write-Host "Import the roster via the UI (Campaigns -> Import) with this file:"
Write-Host "  $csvPath"
Write-Host "Add, then launch when ready:"
Write-Host "  POST $BaseUrl/api/campaigns/$($campaign.id)/launch"
