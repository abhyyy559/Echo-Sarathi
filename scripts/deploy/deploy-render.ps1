# Deploy/refresh the FastAPI backend on Render's FREE web-service tier.
#
#   powershell -ExecutionPolicy Bypass -File scripts\deploy\deploy-render.ps1 -AppOrigin https://your-app.vercel.app
#
# Idempotent: creates the service if missing, then pushes the full environment
# and triggers a deploy. Secrets are read from .deploy.env (account/DB) and the
# repo-root .env (provider keys); nothing is printed except presence booleans.

param(
    [Parameter(Mandatory = $true)][string]$AppOrigin,
    [switch]$SkipDeploy
)

. (Join-Path $PSScriptRoot "common.ps1")

$cfg = Get-DeployConfig
$local = Get-LocalEnv
Require-Values -Map $cfg -Keys @(
    "RENDER_API_KEY", "DATABASE_URL", "LIVEKIT_URL",
    "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "JWT_SECRET",
    "INTERNAL_API_TOKEN", "DEMO_PASSWORD"
)

$apiKey = $cfg["RENDER_API_KEY"]
$serviceName = if ($cfg["RENDER_SERVICE_NAME"]) { $cfg["RENDER_SERVICE_NAME"] } else { "echosarathi-api" }
$region = if ($cfg["RENDER_REGION"]) { $cfg["RENDER_REGION"] } else { "singapore" }
$repoUrl = "https://github.com/abhyyy559/Echo-Sarathi"
$branch = "master"

# --- environment -----------------------------------------------------------
Write-Section "Render: environment variables"
$envVars = New-Object System.Collections.Generic.List[object]
function Add-EnvVar {
    param([string]$Key, [string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    $script:envVars.Add(@{ key = $Key; value = $Value })
}

# Provider + telephony secrets live in the repo .env (never committed).
foreach ($key in @(
    "DEEPGRAM_API_KEY", "CARTESIA_API_KEY", "SARVAM_TTS_API",
    "GROQ_API_KEY", "GROQ_API_KEYS", "GROQ_MODEL", "GROQ_SECONDARY_MODEL",
    "LLM_FALLBACK_CHAIN", "CARTESIA_PRONUNCIATION_DICT_ID",
    "VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN", "VOBIZ_PHONE_NUMBER",
    "TEST_PHONE_NUMBERS", "DLT_ENTITY_ID", "DLT_TEMPLATE_ID",
    "GOOGLE_CLIENT_ID"
)) {
    Add-EnvVar $key (Get-ProviderValue -Maps @($local, $cfg) -Key $key)
}

Add-EnvVar "ENVIRONMENT" "production"
Add-EnvVar "LOG_LEVEL" "info"
Add-EnvVar "PYTHON_VERSION" "3.11"
# Neon hands out `postgresql://...` and SQLAlchemy >=2.0.36 then picks psycopg
# (v3), which prepares statements server-side after 5 executions. Neon's pooled
# endpoint is PgBouncer in transaction mode and rejects those. Forcing psycopg2
# (also installed) uses server-side *cursors* only, so pooled and direct Neon
# URLs both work without extra connect_args.
$dbUrl = $cfg["DATABASE_URL"]
if ($dbUrl -match "^postgres://") {
    $dbUrl = "postgresql://" + $dbUrl.Substring("postgres://".Length)
}
if ($dbUrl -match "^postgresql://") {
    $dbUrl = "postgresql+psycopg2://" + $dbUrl.Substring("postgresql://".Length)
}
Add-EnvVar "DATABASE_URL" $dbUrl
Add-EnvVar "REDIS_URL" ""
Add-EnvVar "CORS_ORIGINS" $AppOrigin
Add-EnvVar "JWT_SECRET" $cfg["JWT_SECRET"]
Add-EnvVar "INTERNAL_API_TOKEN" $cfg["INTERNAL_API_TOKEN"]
Add-EnvVar "JWT_EXPIRE_MINUTES" "10080"
# Self-serve sign-up. "true" opens public org creation (needed for the pricing
# CTAs and Google sign-up); "false" keeps onboarding invite-only. Read from
# .deploy.env / .env so flipping it never requires editing this script.
$registration = Get-ProviderValue -Maps @($local, $cfg) -Key "ALLOW_PUBLIC_REGISTRATION"
if ([string]::IsNullOrWhiteSpace($registration)) { $registration = "false" }
Add-EnvVar "ALLOW_PUBLIC_REGISTRATION" $registration
# Deliberately off in production: operator top-ups only. Customer purchases go
# through Razorpay checkout and are credited only after signature verification.
Add-EnvVar "ALLOW_MANUAL_PAYMENTS" "false"
Add-EnvVar "RAZORPAY_KEY_ID" (Get-ProviderValue -Maps @($local, $cfg) -Key "RAZORPAY_KEY_ID")
Add-EnvVar "RAZORPAY_KEY_SECRET" (Get-ProviderValue -Maps @($local, $cfg) -Key "RAZORPAY_KEY_SECRET")
Add-EnvVar "RAZORPAY_WEBHOOK_SECRET" (Get-ProviderValue -Maps @($local, $cfg) -Key "RAZORPAY_WEBHOOK_SECRET")

# --- SaaS billing, email and tax invoices ----------------------------------
# Invite, reset and invoice-email links must point at the deployed frontend.
# config.py otherwise falls back to http://localhost:5173.
Add-EnvVar "FRONTEND_BASE_URL" $AppOrigin.TrimEnd("/")
# Empty SMTP_HOST means log-only delivery: invites and resets would never
# reach the user on a deployed stack. COMPANY_* feed the invoice seller block;
# PLATFORM_ADMIN_EMAILS unlocks /api/platform. Absent values keep the code
# defaults (invoice GSTIN blank, no platform admin).
foreach ($key in @(
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
    "SMTP_FROM", "SMTP_TLS",
    "COMPANY_LEGAL_NAME", "COMPANY_GSTIN", "COMPANY_ADDRESS", "COMPANY_STATE",
    "PLATFORM_ADMIN_EMAILS"
)) {
    Add-EnvVar $key (Get-ProviderValue -Maps @($local, $cfg) -Key $key)
}
Add-EnvVar "BILLING_LIFECYCLE_INTERVAL_HOURS" "6"
Add-EnvVar "DEMO_EMAIL" $cfg["DEMO_EMAIL"]
Add-EnvVar "DEMO_PASSWORD" $cfg["DEMO_PASSWORD"]

Add-EnvVar "TELEPHONY_PROVIDER" "vobiz"
Add-EnvVar "CONSENT_ENFORCEMENT" "true"
# Written out rather than left to config.py's default: this PUT replaces the
# whole service environment, and an unset gate would let the test-call route
# dial any number the operator types (see the 2026 misdial).
Add-EnvVar "ALLOW_ANY_OUTBOUND_NUMBER" "false"
Add-EnvVar "DIALER_ENABLED" "true"
Add-EnvVar "DEFAULT_CPS_LIMIT" "1"
# One live call at a time. A second leg dialled while the single cold-starting
# worker is still busy rings with nobody answering, and the campaign is being
# validated as sequential right now; raise this once multi-job capacity is proven.
Add-EnvVar "DEFAULT_CONCURRENCY_LIMIT" "1"
Add-EnvVar "RETRY_MAX_ATTEMPTS" "3"
Add-EnvVar "RETRY_BACKOFF_MINUTES" "15"
Add-EnvVar "TIMEZONE" "Asia/Kolkata"
# The quiet-hours window comes from the local .env (gitignored), so an
# operator-approved, temporary extension is never committed to the repo. The
# shipped default stays 09:00-21:00 IST.
foreach ($window in @(
    @{ Key = "CALLING_HOURS_START"; Default = "9" },
    @{ Key = "CALLING_HOURS_END"; Default = "21" }
)) {
    $value = Get-ProviderValue -Maps @($local, $cfg) -Key $window.Key
    if ([string]::IsNullOrWhiteSpace($value)) { $value = $window.Default }
    Add-EnvVar $window.Key $value
}
Add-EnvVar "RECORDING_RETENTION_DAYS" "90"
Add-EnvVar "RETENTION_JOB_ENABLED" "true"
Add-EnvVar "DOMAIN_CONFIGS_DIR" "../domain-configs"

# PUBLIC_BASE_URL is intentionally omitted: config.py falls back to Render's
# own RENDER_EXTERNAL_URL so the webhook/TwiML base URL is correct on the very
# first boot without a second deploy.
Add-EnvVar "LIVEKIT_URL" $cfg["LIVEKIT_URL"]
Add-EnvVar "LIVEKIT_URL_INTERNAL" $cfg["LIVEKIT_URL"]
Add-EnvVar "LIVEKIT_API_KEY" $cfg["LIVEKIT_API_KEY"]
Add-EnvVar "LIVEKIT_API_SECRET" $cfg["LIVEKIT_API_SECRET"]

$envPayload = @($envVars | ForEach-Object { $_ })
Write-Host ("  prepared " + $envPayload.Count + " variables (values not printed)")

# --- workspace -------------------------------------------------------------
Write-Section "Render: workspace"
$ownerId = $cfg["RENDER_OWNER_ID"]
if ([string]::IsNullOrWhiteSpace($ownerId)) {
    $owners = Invoke-RenderApi -ApiKey $apiKey -Method GET -Path "/owners?limit=20"
    foreach ($item in @($owners)) {
        $owner = if ($item.owner) { $item.owner } else { $item }
        if ($owner -and $owner.id) { $ownerId = [string]$owner.id; break }
    }
    if ([string]::IsNullOrWhiteSpace($ownerId)) { throw "Could not resolve a Render workspace/owner ID." }
    Write-DotEnvValue -Path $script:DeployEnvPath -Key "RENDER_OWNER_ID" -Value $ownerId
}
Write-Host "  owner: $ownerId"

# --- service ---------------------------------------------------------------
Write-Section "Render: service '$serviceName'"
$service = Get-RenderService -ApiKey $apiKey -Name $serviceName
$createdDeployId = ""
$isNew = $false
if ($null -eq $service) {
    $isNew = $true
    Write-Host "  creating free web service (region: $region)"
    $payload = @{
        type        = "web_service"
        name        = $serviceName
        ownerId     = $ownerId
        repo        = $repoUrl
        branch      = $branch
        autoDeployTrigger = "commit"
        envVars     = $envPayload
        serviceDetails = @{
            runtime          = "python"
            plan             = "free"
            region           = $region
            healthCheckPath  = "/"
            envSpecificDetails = @{
                buildCommand = "pip install -r backend/requirements.txt"
                startCommand = "cd backend && alembic upgrade head && python scripts/seed_demo.py && uvicorn app.main:app --host 0.0.0.0 --port `$PORT"
            }
        }
    }
    try {
        $created = Invoke-RenderApi -ApiKey $apiKey -Method POST -Path "/services" -Body $payload
    } catch {
        $detail = $_.Exception.Message
        throw ("Render refused to create the service. $detail" + `
            "`n  Most common cause: the GitHub repo is not connected to Render yet." + `
            "`n  One-time fix: https://dashboard.render.com/select-repo?type=web -> connect" + `
            "`n  'abhyyy559/Echo-Sarathi', then re-run this script (no service is created there).")
    }
    $service = if ($created.service) { $created.service } else { $created }
    if ($created.deployId) { $createdDeployId = [string]$created.deployId }
} else {
    Write-Host "  service exists: $($service.id)"
}
$serviceId = [string]$service.id
if ([string]::IsNullOrWhiteSpace($serviceId)) { throw "Render did not return a service id." }
Write-DotEnvValue -Path $script:DeployEnvPath -Key "RENDER_SERVICE_ID" -Value $serviceId

# Existing services keep their own env vars, so push the full set again.
# (A newly created service already received them in the create payload.)
if (-not $isNew) {
    Invoke-RenderApi -ApiKey $apiKey -Method PUT -Path "/services/$serviceId/env-vars" -Body $envPayload | Out-Null
    Write-Host "  refreshed environment variables"
}

# --- deploy ----------------------------------------------------------------
if (-not $SkipDeploy) {
    Write-Section "Render: deploy"
    $deployId = $createdDeployId
    if ([string]::IsNullOrWhiteSpace($deployId)) {
        $deploy = Invoke-RenderApi -ApiKey $apiKey -Method POST -Path "/services/$serviceId/deploys" -Body @{ clearCache = "do_not_clear" }
        $deployId = if ($deploy.id) { $deploy.id } elseif ($deploy.deploy.id) { $deploy.deploy.id } else { "" }
    } else {
        Write-Host "  using the deploy created with the service"
    }
    if ([string]::IsNullOrWhiteSpace($deployId)) { throw "Render did not return a deploy id." }
    Write-Host "  deploy: $deployId"
    $final = Wait-RenderDeploy -ApiKey $apiKey -ServiceId $serviceId -DeployId $deployId
    if ($final.service) { $service = $final.service } else {
        $service = Invoke-RenderApi -ApiKey $apiKey -Method GET -Path "/services/$serviceId"
    }
}

$serviceUrl = ""
if ($service.serviceDetails -and $service.serviceDetails.url) { $serviceUrl = [string]$service.serviceDetails.url }
if ([string]::IsNullOrWhiteSpace($serviceUrl) -and $service.slug) {
    $serviceUrl = "https://$($service.slug).onrender.com"
}
if ([string]::IsNullOrWhiteSpace($serviceUrl)) {
    $serviceUrl = "https://$serviceName.onrender.com"
}
$serviceUrl = $serviceUrl.TrimEnd("/")
Write-DotEnvValue -Path $script:DeployEnvPath -Key "RENDER_SERVICE_URL" -Value $serviceUrl

Write-Section "Render: ready"
Write-Host "  url: $serviceUrl"
Write-Host "  dashboard: https://dashboard.render.com/web/$serviceId"
Write-Host "  note: free instances sleep after 15 min; first request can take ~1 min."

# Helpful for the next script / the user's shell.
$global:RENDER_SERVICE_URL = $serviceUrl
