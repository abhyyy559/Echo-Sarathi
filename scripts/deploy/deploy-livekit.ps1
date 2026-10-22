# Deploy/refresh the LiveKit voice worker on LiveKit Cloud (free Build plan).
#
#   powershell -ExecutionPolicy Bypass -File scripts\deploy\deploy-livekit.ps1
#
# Requires RENDER_SERVICE_URL (written by deploy-render.ps1) and the LiveKit
# Cloud credentials in .deploy.env. LiveKit Cloud injects LIVEKIT_URL/KEY/SECRET
# at runtime; everything else is passed as agent secrets.

param(
    [switch]$StatusOnly
)

. (Join-Path $PSScriptRoot "common.ps1")

$cfg = Get-DeployConfig
$local = Get-LocalEnv
$required = @("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
if (-not $StatusOnly) {
    $required += @("RENDER_SERVICE_URL", "INTERNAL_API_TOKEN")
}
Require-Values -Map $cfg -Keys $required

function Get-LkCli {
    $localPath = Join-Path $script:RepoRoot ".tools\lk\lk.exe"
    if (Test-Path -LiteralPath $localPath) { return $localPath }
    if (Test-CommandExists "lk") { return "lk" }

    Write-Host "  downloading LiveKit CLI..."
    $toolsDir = Join-Path $script:RepoRoot ".tools\lk"
    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/livekit/livekit-cli/releases/latest" -Headers @{ "User-Agent" = "echo-sarathi-deploy" }
    $asset = $release.assets | Where-Object { $_.name -match "windows_amd64\.zip$" } | Select-Object -First 1
    if (-not $asset) { throw "No Windows amd64 LiveKit CLI asset found in the latest release." }
    $zip = Join-Path $toolsDir "lk.zip"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $toolsDir -Force
    Remove-Item -LiteralPath $zip -Force
    return $localPath
}

$lk = Get-LkCli

$voiceDir = Join-Path $script:RepoRoot "voice-agent"

if ($StatusOnly) {
    Write-Section "LiveKit agent status"
    $status = Invoke-Native -FilePath $lk -Arguments (@("--url", $cfg["LIVEKIT_URL"], "--api-key", $cfg["LIVEKIT_API_KEY"], "--api-secret", $cfg["LIVEKIT_API_SECRET"], "agent", "status", "--json"))
    $status.Output | ForEach-Object { Write-Host $_ }
    exit $status.ExitCode
}

Write-Section "LiveKit: agent secrets"
$secretsPath = Join-Path $script:DeployRunDir "livekit-secrets.env"
New-Item -ItemType Directory -Force -Path $script:DeployRunDir | Out-Null
$secrets = New-Object System.Collections.Generic.List[string]
function Add-Secret {
    param([string]$Key, [string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    # Newlines would corrupt the KEY=VALUE file.
    $clean = ($Value -replace "(`r`n|`n|`r)", " ").Trim()
    $script:secrets.Add("$Key=$clean")
}

Add-Secret "BACKEND_INTERNAL_URL" $cfg["RENDER_SERVICE_URL"]
Add-Secret "INTERNAL_API_TOKEN" $cfg["INTERNAL_API_TOKEN"]
Add-Secret "ENVIRONMENT" "production"
Add-Secret "LOG_LEVEL" "info"

# Everything else is forwarded verbatim from the working local .env, so the
# deployed worker speaks with the same STT/TTS/LLM providers that were tested
# locally (Cartesia is balance-exhausted, so .env points TTS at Sarvam; the
# agent would go silent if this script forced a provider instead).
foreach ($key in @(
    # STT / TTS
    "STT_PROVIDER", "TTS_PROVIDER", "TTS_LANGUAGE_ROUTING",
    "DEEPGRAM_API_KEY", "DEEPGRAM_TTS_MODEL",
    "CARTESIA_API_KEY", "CARTESIA_PRONUNCIATION_DICT_ID",
    "SARVAM_TTS_API", "SARVAM_API_KEY",
    "SARVAM_TTS_MODEL", "SARVAM_TTS_SPEAKER", "SARVAM_TTS_LANG",
    "SARVAM_TTS_SAMPLE_RATE", "SARVAM_STT_MODEL", "SARVAM_STT_LANG",
    # LLM + fallback chain
    "GROQ_API_KEY", "GROQ_API_KEYS", "GROQ_MODEL", "GROQ_SECONDARY_MODEL",
    "GROQ_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
    "CEREBRAS_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY",
    "LLM_FALLBACK_CHAIN",
    # turn detection / noise cancellation
    "TURN_DETECTOR", "VOICE_NC", "VOICE_NC_PROVIDER"
)) {
    Add-Secret $key (Get-ProviderValue -Maps @($local, $cfg) -Key $key)
}
# LiveKit Cloud injects LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET at
# runtime; passing them as secrets makes the deployment reject the build.

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($secretsPath, $secrets, $utf8NoBom)
Write-Host ("  prepared " + $secrets.Count + " secrets (values not printed)")

$region = if ($cfg["LIVEKIT_REGION"]) { $cfg["LIVEKIT_REGION"] } else { "ap-south" }
$tomlPath = Join-Path $voiceDir "livekit.toml"

Write-Section "LiveKit: deploy agent"
Push-Location $voiceDir
try {
    if (-not (Test-Path -LiteralPath $tomlPath)) {
        Write-Host "  first deploy: creating agent in $region"
        $deploy = Invoke-Native -FilePath $lk -Arguments (@(
            "--url", $cfg["LIVEKIT_URL"],
            "--api-key", $cfg["LIVEKIT_API_KEY"],
            "--api-secret", $cfg["LIVEKIT_API_SECRET"],
            "agent", "create", "--region", $region, "--secrets-file", $secretsPath, "--yes", "."
        )) -ShowOutput
    } else {
        Write-Host "  deploying new version from voice-agent/livekit.toml"
        $deploy = Invoke-Native -FilePath $lk -Arguments (@(
            "--url", $cfg["LIVEKIT_URL"],
            "--api-key", $cfg["LIVEKIT_API_KEY"],
            "--api-secret", $cfg["LIVEKIT_API_SECRET"],
            "agent", "deploy", "--secrets-file", $secretsPath, "--yes", "."
        )) -ShowOutput
    }
    if ($deploy.ExitCode -ne 0) { throw "LiveKit agent deploy failed (exit $($deploy.ExitCode))." }
} finally {
    Pop-Location
}

Write-Section "LiveKit: status"
$status = Invoke-Native -FilePath $lk -Arguments (@(
    "--url", $cfg["LIVEKIT_URL"],
    "--api-key", $cfg["LIVEKIT_API_KEY"],
    "--api-secret", $cfg["LIVEKIT_API_SECRET"],
    "agent", "status", "--json"
))
$status.Output | ForEach-Object { Write-Host $_ }

Write-Host ""
Write-Host "Agent deployed. It scales to zero on the free plan; the first session"
Write-Host "after idle can take 10-20 seconds to cold-start."
