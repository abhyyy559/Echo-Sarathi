# Shared helpers for the free-tier deployment scripts.
# Dot-source from deploy-*.ps1: . (Join-Path $PSScriptRoot "common.ps1")

$ErrorActionPreference = "Stop"

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$script:DeployEnvPath = Join-Path $script:RepoRoot ".deploy.env"
$script:LocalEnvPath = Join-Path $script:RepoRoot ".env"
$script:DeployRunDir = Join-Path $script:RepoRoot ".deploy"

function Read-DotEnv {
    param([string]$Path)
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $map }
    foreach ($rawLine in [System.IO.File]::ReadAllLines($Path)) {
        $line = $rawLine.Trim().TrimStart([char]0xFEFF)
        if (-not $line -or $line.StartsWith("#")) { continue }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { continue }
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if ($value.Length -ge 2) {
            $first = $value.Substring(0, 1)
            $last = $value.Substring($value.Length - 1, 1)
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $map[$key] = $value
    }
    return $map
}

function Write-DotEnvValue {
    param([string]$Path, [string]$Key, [string]$Value)
    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        $lines = [System.IO.File]::ReadAllLines($Path)
    }
    $found = $false
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))=") {
            $out.Add("$Key=$Value")
            $found = $true
        } else {
            $out.Add($line)
        }
    }
    if (-not $found) { $out.Add("$Key=$Value") }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, $out, $utf8NoBom)
}

function Get-DeployConfig {
    $cfg = Read-DotEnv -Path $script:DeployEnvPath
    if ($cfg.Count -eq 0) {
        throw ".deploy.env not found. Copy .deploy.env.example to .deploy.env and fill it in."
    }
    return $cfg
}

function Get-LocalEnv {
    return Read-DotEnv -Path $script:LocalEnvPath
}

function Require-Values {
    param([hashtable]$Map, [string[]]$Keys)
    $missing = @()
    foreach ($key in $Keys) {
        if (-not $Map.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($Map[$key])) {
            $missing += $key
        }
    }
    if ($missing.Count -gt 0) {
        throw ("Missing required values in .deploy.env: " + ($missing -join ", "))
    }
}

function Get-FirstNonEmpty {
    param([hashtable[]]$Maps, [string]$Key)
    foreach ($map in $Maps) {
        if ($map.ContainsKey($Key) -and -not [string]::IsNullOrWhiteSpace($map[$Key])) {
            return $map[$Key]
        }
    }
    return ""
}

function Get-ProviderValue {
    param([hashtable[]]$Maps, [string]$Key)
    $value = Get-FirstNonEmpty -Maps $Maps -Key $Key
    if ([string]::IsNullOrWhiteSpace($value)) { return "" }
    # `.env` still carries unfilled template rows (OPENAI_API_KEY=your_...).
    # Forwarding one would make /api/health claim a provider is configured and
    # arm a fallback that 401s on every turn, so treat placeholders as unset.
    if ($value -match "(?i)(your_|change_me|placeholder|dummy_|_here$|^example)") {
        Write-Host "  skipping $Key (template placeholder)" -ForegroundColor DarkGray
        return ""
    }
    return $value
}

function Invoke-RenderApi {
    param(
        [string]$ApiKey,
        [string]$Method,
        [string]$Path,
        $Body = $null
    )
    $uri = "https://api.render.com/v1$Path"
    $headers = @{
        Authorization  = "Bearer $ApiKey"
        Accept         = "application/json"
    }
    $params = @{
        Uri         = $uri
        Method      = $Method
        Headers     = $headers
        TimeoutSec  = 60
        ErrorAction = "Stop"
    }
    if ($null -ne $Body) {
        $params["Body"] = ($Body | ConvertTo-Json -Depth 20 -Compress)
        $params["ContentType"] = "application/json"
    }
    return Invoke-RestMethod @params
}

function Get-RenderService {
    param([string]$ApiKey, [string]$Name)
    $result = $null
    try {
        $result = Invoke-RenderApi -ApiKey $ApiKey -Method GET -Path "/services?name=$([uri]::EscapeDataString($Name))&limit=50"
    } catch {
        # Older API versions ignore the name filter differently; fall back to
        # listing every service and matching locally.
        $result = Invoke-RenderApi -ApiKey $ApiKey -Method GET -Path "/services?limit=100"
    }
    if ($null -eq $result) { return $null }
    foreach ($item in @($result)) {
        $svc = if ($item.service) { $item.service } else { $item }
        if ($svc -and $svc.name -eq $Name) { return $svc }
    }
    return $null
}

function Wait-RenderDeploy {
    param([string]$ApiKey, [string]$ServiceId, [string]$DeployId, [int]$TimeoutMinutes = 20)
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $last = ""
    while ((Get-Date) -lt $deadline) {
        $deploy = Invoke-RenderApi -ApiKey $ApiKey -Method GET -Path "/services/$ServiceId/deploys/$DeployId"
        $status = [string]$deploy.status
        if ($status -ne $last) {
            Write-Host ("  deploy status: " + $status)
            $last = $status
        }
        if ($status -eq "live") { return $deploy }
        if ($status -in @("build_failed", "update_failed", "pre_deploy_failed", "canceled", "deactivated")) {
            throw "Render deploy $DeployId ended with status '$status'. Open the service logs in the Render dashboard."
        }
        Start-Sleep -Seconds 10
    }
    throw "Timed out waiting for Render deploy $DeployId."
}

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=== " + $Text + " ===") -ForegroundColor Cyan
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Native {
    <#
    Run a native executable without letting its stderr abort the script.

    common.ps1 sets $ErrorActionPreference = "Stop", and PowerShell turns any
    native stderr line into a NativeCommandError under that setting (the
    LiveKit and Vercel CLIs both print progress/info banners to stderr). This
    runs the command under Continue and returns the real exit code.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$ShowOutput,
        [switch]$Quiet
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = & $FilePath @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($ShowOutput -and -not $Quiet) {
        foreach ($line in $lines) { Write-Host "  $line" }
    }
    return [pscustomobject]@{ ExitCode = $code; Output = @($lines) }
}
