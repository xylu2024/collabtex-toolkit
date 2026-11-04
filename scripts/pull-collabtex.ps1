# Safe Pull Script for Overleaf / HZDR Collabtex
# Synchronizes remote changes down to local (Remote -> Local Only)
# Used when supervisor/collaborator has made annotations or text edits on Overleaf

$projectDir = Join-Path $PSScriptRoot ".."
Set-Location $projectDir

# Determine project name: 1. From .olproject, 2. Hardcoded fallback
$projectName = "YOUR_OVERLEAF_PROJECT_NAME"
$olprojectFile = Join-Path $projectDir ".olproject"
if (Test-Path $olprojectFile) {
    $lines = Get-Content $olprojectFile
    foreach ($l in $lines) {
        $trimmed = $l.Trim()
        if ($trimmed -and -not $trimmed.StartsWith("#")) {
            $projectName = $trimmed
            break
        }
    }
}

# Determine server URL from .olauth if available
$serverUrl = "https://collabtex.helmholtz.cloud"
$authFile = Join-Path $projectDir ".olauth"
if (-not (Test-Path $authFile)) { $authFile = Join-Path $env:USERPROFILE ".olauth" }
if (Test-Path $authFile) {
    try {
        $authJson = Get-Content $authFile -Raw | ConvertFrom-Json
        if ($authJson.server) { $serverUrl = $authJson.server }
    } catch {}
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Overleaf / Collabtex Pull Channel" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "[*] Target Project: $projectName" -ForegroundColor Gray
Write-Host "[*] Target Server:  $serverUrl" -ForegroundColor Gray
Write-Host "[>>] Fetching latest annotations and edits from Overleaf..." -ForegroundColor Cyan

# Perform unidirectional remote pull (-r)
ols -r --server $serverUrl -n $projectName

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[OK] Successfully pulled latest annotations!" -ForegroundColor Green
    python "$PSScriptRoot\collabtex_tool.py" update-base
    Write-Host "[*] Tip: Search for '\textcolor' or '%' in VS Code to review collaborator feedback." -ForegroundColor Yellow
} else {
    Write-Host "`n[!] Pull encountered an issue. Please verify network or authentication." -ForegroundColor Red
}
