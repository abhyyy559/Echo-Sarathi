# Point the Vercel frontend at the deployed Render API and ship a production build.
#
#   powershell -ExecutionPolicy Bypass -File scripts\deploy\deploy-vercel.ps1
#
# - resolves the project's production domain
# - sets VITE_API_URL (direct calls, so Render's ~1 min free-tier cold start
#   cannot be cut off by the Vercel rewrite proxy) AND refreshes the /api proxy
#   fallback in frontend/vercel.json
# - deploys with `vercel deploy --prod`
#
# Requires VERCEL_TOKEN in .deploy.env.

param(
    [string]$RenderServiceUrl = "",
    [switch]$SkipDeploy,
    [switch]$OriginOnly
)

. (Join-Path $PSScriptRoot "common.ps1")

$cfg = Get-DeployConfig
Require-Values -Map $cfg -Keys @("VERCEL_TOKEN", "VERCEL_PROJECT_ID", "VERCEL_ORG_ID")

if ([string]::IsNullOrWhiteSpace($RenderServiceUrl)) {
    $RenderServiceUrl = $cfg["RENDER_SERVICE_URL"]
}
if (-not $OriginOnly -and [string]::IsNullOrWhiteSpace($RenderServiceUrl)) {
    throw "RENDER_SERVICE_URL is empty. Run deploy-render.ps1 first or pass -RenderServiceUrl."
}
if ($RenderServiceUrl) { $RenderServiceUrl = $RenderServiceUrl.TrimEnd("/") }

$token = $cfg["VERCEL_TOKEN"]
$projectId = $cfg["VERCEL_PROJECT_ID"]
$teamId = $cfg["VERCEL_ORG_ID"]
$authHeaders = @{ Authorization = "Bearer $token" }
$apiBase = "https://api.vercel.com"

function Invoke-VercelApi {
    param([string]$Method, [string]$Path, $Body = $null)
    $sep = if ($Path.Contains("?")) { "&" } else { "?" }
    $uri = "$apiBase$Path$sep" + "teamId=$teamId"
    $params = @{ Uri = $uri; Method = $Method; Headers = $authHeaders; TimeoutSec = 60; ErrorAction = "Stop" }
    if ($null -ne $Body) {
        $params["Body"] = ($Body | ConvertTo-Json -Depth 15 -Compress)
        $params["ContentType"] = "application/json"
    }
    return Invoke-RestMethod @params
}

Write-Section "Vercel: project"
$project = Invoke-VercelApi -Method GET -Path "/v9/projects/$projectId"
Write-Host ("  project: " + $project.name)

Write-Section "Vercel: production domain"
$origin = $cfg["APP_ORIGIN"]
if ([string]::IsNullOrWhiteSpace($origin)) {
    $domains = Invoke-VercelApi -Method GET -Path "/v9/projects/$projectId/domains"
    $names = @($domains.domains | ForEach-Object { $_.name })
    if ($names.Count -eq 0) {
        throw "No domain found on the Vercel project. Set APP_ORIGIN in .deploy.env."
    }
    $custom = $names | Where-Object { $_ -notmatch "\.vercel\.app$" } | Select-Object -First 1
    $chosen = if ($custom) { $custom } else { $names[0] }
    $origin = "https://$chosen"
    Write-DotEnvValue -Path $script:DeployEnvPath -Key "APP_ORIGIN" -Value $origin
}
$origin = $origin.TrimEnd("/")
Write-Host "  origin: $origin"

if ($OriginOnly) {
    $global:APP_ORIGIN = $origin
    exit 0
}

Write-Section "Vercel: environment"
$existing = Invoke-VercelApi -Method GET -Path "/v9/projects/$projectId/env"
foreach ($item in @($existing.envs)) {
    if ($item.key -eq "VITE_API_URL") {
        Invoke-VercelApi -Method DELETE -Path "/v9/projects/$projectId/env/$($item.id)" | Out-Null
        Write-Host "  replaced existing VITE_API_URL"
    }
}
Invoke-VercelApi -Method POST -Path "/v10/projects/$projectId/env" -Body @{
    key    = "VITE_API_URL"
    value  = $RenderServiceUrl
    type   = "plain"
    target = @("production", "preview", "development")
} | Out-Null
Write-Host "  VITE_API_URL -> $RenderServiceUrl"

Write-Section "Vercel: /api proxy fallback"
$vercelJsonPath = Join-Path $script:RepoRoot "frontend\vercel.json"
$proxyDest = "$RenderServiceUrl/api/`$1"
$raw = [System.IO.File]::ReadAllText($vercelJsonPath)
$current = $raw | ConvertFrom-Json
$proxyRoute = @($current.routes) | Where-Object { $_.src -eq "/api/(.*)" } | Select-Object -First 1
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if ($proxyRoute -and $proxyRoute.dest -eq $proxyDest) {
    Write-Host "  proxy already -> $proxyDest"
} else {
    if ($proxyRoute -and $proxyRoute.dest) {
        # Surgical substitution keeps the committed formatting intact
        # (ConvertTo-Json on Windows PowerShell reflows the whole file).
        $updated = $raw.Replace([string]$proxyRoute.dest, $proxyDest)
    } else {
        # Unexpected shape: rebuild from the parsed object instead.
        $current.routes = @(@{ src = "/api/(.*)"; dest = $proxyDest }) + @($current.routes)
        $updated = $current | ConvertTo-Json -Depth 10
    }
    # Never write a file the deploy step cannot parse.
    $check = @(($updated | ConvertFrom-Json).routes) | Where-Object { $_.src -eq "/api/(.*)" } | Select-Object -First 1
    if (-not $check -or $check.dest -ne $proxyDest) {
        throw "Patched frontend/vercel.json does not contain the expected /api rewrite; fix it by hand and re-run."
    }
    [System.IO.File]::WriteAllText($vercelJsonPath, $updated, $utf8NoBom)
    Write-Host "  proxy -> $proxyDest"
}

if (-not $SkipDeploy) {
    Write-Section "Vercel: production deploy"
    if (-not (Test-CommandExists "npx")) {
        throw "npx was not found. Install Node.js 18+ and re-run."
    }
    $frontendDir = Join-Path $script:RepoRoot "frontend"
    $linkedPath = Join-Path $frontendDir ".vercel\project.json"

    # Link to the EXISTING project: `vercel deploy --yes` in an unlinked
    # directory silently creates a brand-new project. An existing
    # .vercel/project.json for the same project id is enough, and skips a
    # `link` round-trip that can 404 on a personal token + team scope.
    $alreadyLinked = $false
    if (Test-Path -LiteralPath $linkedPath) {
        try {
            $linked = Get-Content -LiteralPath $linkedPath -Raw | ConvertFrom-Json
            $alreadyLinked = ($linked.projectId -eq $projectId)
        } catch { $alreadyLinked = $false }
    }

    Push-Location $frontendDir
    # Vercel CLI writes its banner to stderr; with ErrorActionPreference=Stop
    # (set by common.ps1) that would abort the script before the exit code is
    # even readable.
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if (-not $alreadyLinked) {
            & npx --yes vercel@latest link --yes --project $project.name --token $token 2>&1 |
                ForEach-Object { Write-Host "  $_" }
            if ($LASTEXITCODE -ne 0) { throw "vercel link failed (exit $LASTEXITCODE)." }
        } else {
            Write-Host "  already linked to $projectId"
        }

        & npx --yes vercel@latest deploy --prod --yes --token $token 2>&1 |
            ForEach-Object { Write-Host "  $_" }
        $deployExit = $LASTEXITCODE
        if ($deployExit -ne 0) { throw "Vercel deploy failed (exit $deployExit)." }
    } finally {
        $ErrorActionPreference = $previousEap
        Pop-Location
    }
}

Write-Section "Vercel: ready"
Write-Host "  url: $origin"
$global:APP_ORIGIN = $origin
