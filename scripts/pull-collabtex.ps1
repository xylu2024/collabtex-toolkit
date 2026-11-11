# Safe Pull Script for Overleaf / HZDR Collabtex
# Synchronizes remote changes down to local (Remote -> Local Only)
# Respects .olignore and verifies SHA-256 content parity for figures & text sources.

param(
    [switch]$Force
)

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
Write-Host "   Overleaf / Collabtex Pull Channel (SHA-256 Verified)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "[*] Target Project: $projectName" -ForegroundColor Gray
Write-Host "[*] Target Server:  $serverUrl" -ForegroundColor Gray
Write-Host "[>>] Fetching latest annotations and edits from Overleaf..." -ForegroundColor Cyan

# Perform unidirectional remote pull (-r)
ols -r --server $serverUrl -n $projectName

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[>>] Running SHA-256 post-pull check across text sources & figures..." -ForegroundColor Cyan
    if ($Force) {
        python "$PSScriptRoot\collabtex_tool.py" verify-pull --force
    } else {
        python "$PSScriptRoot\collabtex_tool.py" verify-pull
    }
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[OK] Successfully pulled & verified latest updates!" -ForegroundColor Green
        Write-Host "[*] Tip: Search for '\textcolor' or '%' in VS Code to review collaborator feedback." -ForegroundColor Yellow
    } else {
        Write-Host "`n[!] Post-pull check encountered an issue." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "`n[!] Pull encountered an issue. Please verify network or authentication." -ForegroundColor Red
    exit 1
}
