# Wake the sleeping Render free instance and wait until the API answers.
#   powershell -File scripts\deploy\wake.ps1

. (Join-Path $PSScriptRoot "common.ps1")
$cfg = Get-DeployConfig
$url = $cfg["RENDER_SERVICE_URL"]
if ([string]::IsNullOrWhiteSpace($url)) {
    throw "RENDER_SERVICE_URL is empty. Run deploy-render.ps1 first."
}
$url = $url.TrimEnd("/")

Write-Host "Waking $url (free instances take up to ~1 minute)..."
$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri "$url/" -UseBasicParsing -TimeoutSec 90
        if ($response.StatusCode -eq 200) {
            Write-Host "Awake." -ForegroundColor Green
            exit 0
        }
    } catch {
        Write-Host "  still waking..."
    }
    Start-Sleep -Seconds 5
}
throw "The API did not wake within 3 minutes."
