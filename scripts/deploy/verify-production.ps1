# End-to-end production smoke test for the free-tier stack.
#   powershell -File scripts\deploy\verify-production.ps1
#
# Exit code 0 = every check passed. Any failure prints FAIL and exits 1.

. (Join-Path $PSScriptRoot "common.ps1")

$cfg = Get-DeployConfig
$renderUrl = $cfg["RENDER_SERVICE_URL"]
$origin = $cfg["APP_ORIGIN"]
if ([string]::IsNullOrWhiteSpace($renderUrl)) { throw "RENDER_SERVICE_URL is empty." }
if ([string]::IsNullOrWhiteSpace($origin)) { throw "APP_ORIGIN is empty." }
$renderUrl = $renderUrl.TrimEnd("/")
$origin = $origin.TrimEnd("/")

$failures = New-Object System.Collections.Generic.List[string]
function Check {
    param([string]$Name, [scriptblock]$Test)
    try {
        $result = & $Test
        if ($result -eq $false) { throw "returned false" }
        Write-Host ("  PASS  " + $Name) -ForegroundColor Green
        return $result
    } catch {
        Write-Host ("  FAIL  " + $Name + " - " + $_.Exception.Message) -ForegroundColor Red
        $script:failures.Add($Name)
        return $null
    }
}

Write-Section "Backend (Render)"
$root = Check "GET / (API awake)" {
    (Invoke-WebRequest -Uri "$renderUrl/" -UseBasicParsing -TimeoutSec 120).StatusCode -eq 200
}

$health = $null
$health = Check "GET /api/health" {
    $h = Invoke-RestMethod -Uri "$renderUrl/api/health" -TimeoutSec 120
    if (-not $h.db) { throw "database is not reachable" }
    if (-not $h.providers.deepgram -or -not $h.providers.cartesia -or -not $h.providers.groq) {
        throw "one or more provider keys are missing on the backend"
    }
    if (-not $h.llm_chain -or @($h.llm_chain).Count -eq 0) { throw "LLM fallback chain is empty" }
    $h
}
if ($health) {
    Write-Host ("        db=" + $health.db + " livekit_ws=" + $health.livekit_ws)
    Write-Host ("        llm chain: " + ((@($health.llm_chain) | ForEach-Object { $_.name + "/" + $_.model }) -join ", "))
}

$token = $null
$null = Check "POST /api/auth/login (demo user)" {
    $body = @{ email = $cfg["DEMO_EMAIL"]; password = $cfg["DEMO_PASSWORD"] } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "$renderUrl/api/auth/login" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 60
    if (-not $r.token) { throw "no token returned" }
    $script:token = $r.token
    $true
}

$null = Check "GET /api/agents (seed present)" {
    $headers = @{ Authorization = "Bearer $script:token" }
    $payload = Invoke-RestMethod -Uri "$renderUrl/api/agents" -Headers $headers -TimeoutSec 60
    # Today this endpoint returns a JSON array; accept {value: [...]} too.
    $payload = Invoke-RestMethod -Uri "$renderUrl/api/agents" -Headers $headers -TimeoutSec 60
    $agents = @($payload)
    if ($payload -is [System.Management.Automation.PSCustomObject] -and
        $payload.PSObject.Properties.Name -contains "value") {
        $agents = @($payload.value)
    }
    if ($agents.Count -lt 1) { throw "no seeded agent" }
    Write-Host ("        agents: " + ((@($agents) | ForEach-Object { $_.name }) -join ", "))
    $true
}

$null = Check "CORS allows the Vercel origin" {
    $headers = @{
        Origin                        = $origin
        "Access-Control-Request-Method" = "GET"
    }
    $r = Invoke-WebRequest -Uri "$renderUrl/api/health" -Method OPTIONS -Headers $headers -UseBasicParsing -TimeoutSec 30
    $allow = $r.Headers["Access-Control-Allow-Origin"]
    if ($allow -ne $origin) { throw "allow-origin was '$allow'" }
    $true
}

Write-Section "Frontend (Vercel)"
$null = Check "GET $origin" {
    $r = Invoke-WebRequest -Uri $origin -UseBasicParsing -TimeoutSec 60
    if ($r.StatusCode -ne 200) { throw "status $($r.StatusCode)" }
    if ($r.Content -notmatch '<div id="root"') { throw "unexpected HTML (SPA shell missing)" }
    $true
}

$null = Check "Frontend proxy /api/health" {
    $r = Invoke-RestMethod -Uri "$origin/api/health" -TimeoutSec 120
    if (-not $r.db) { throw "proxied health says database down" }
    $true
}

Write-Section "Voice worker (LiveKit Cloud)"
$lk = Join-Path $script:RepoRoot ".tools\lk\lk.exe"
if ((Test-Path -LiteralPath $lk) -and $cfg["LIVEKIT_API_SECRET"]) {
    $livekit = Check "LiveKit agent is deployed" {
        $res = Invoke-Native -FilePath $lk -Arguments @(
            "--url", $cfg["LIVEKIT_URL"],
            "--api-key", $cfg["LIVEKIT_API_KEY"],
            "--api-secret", $cfg["LIVEKIT_API_SECRET"],
            "agent", "status", "--json"
        )
        # The CLI prints "Using agent [...]" and similar notices to stderr;
        # the JSON body starts at the first line that opens an object.
        $lines = @($res.Output)
        $start = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i].TrimStart().StartsWith("{")) { $start = $i; break }
        }
        if ($start -lt 0) { throw "no JSON in the CLI output (exit $($res.ExitCode))" }
        $json = $lines[$start..($lines.Count - 1)] -join "`n"
        $parsed = $json | ConvertFrom-Json -ErrorAction Stop
        $agents = @($parsed.agents)
        if ($agents.Count -eq 0) { throw "no agent registered on this LiveKit project" }
        # The free plan scales to zero: "Sleeping" is a healthy, deployed
        # worker that will cold-start on the next call, not an outage.
        $running = @($agents | ForEach-Object { $_.agentDeployments } | Where-Object { $_.status -in @("Running", "Sleeping") })
        if ($running.Count -eq 0) {
            $states = @($agents | ForEach-Object { $_.agentDeployments } | ForEach-Object { $_.status }) -join ", "
            throw "agent not deployed (state: $states)"
        }
        $agents
    }
    if ($livekit) {
        foreach ($agent in $livekit) {
            $regions = @($agent.agentDeployments | ForEach-Object { $_.region + "=" + $_.status }) -join ", "
            Write-Host ("        " + $agent.agentId + " version " + $agent.version + " (" + $regions + ")")
        }
    }
} else {
    Write-Host "  SKIP  LiveKit CLI not installed locally" -ForegroundColor Yellow
}

Write-Section "Result"
if ($failures.Count -eq 0) {
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
}
Write-Host ("Failed checks: " + ($failures -join ", ")) -ForegroundColor Red
exit 1
