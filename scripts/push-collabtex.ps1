# One-click Push Script for Overleaf / HZDR Collabtex
# Synchronizes local files to Overleaf (Local -> Remote Only)
# Respects .olignore and verifies 100% SHA-256 content parity for figures & text sources.

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
Write-Host "   Overleaf / Collabtex Push Channel (SHA-256 Verified)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "[*] Target Project: $projectName" -ForegroundColor Gray
Write-Host "[*] Target Server:  $serverUrl" -ForegroundColor Gray
Write-Host "[!] Safety Notice:  If collaborators made changes on the cloud," -ForegroundColor Yellow
Write-Host "    pushing will overwrite remote files with your local version!" -ForegroundColor Yellow
Write-Host "    If unsure, run 'collabtex-diff' or 'collabtex-merge' first.`n" -ForegroundColor Yellow

if (-not $Force) {
    $confirm = Read-Host "Confirm pushing local version to remote? (Press Enter to proceed / 'N' to cancel)"
    if ($confirm -eq "N" -or $confirm -eq "n") {
        Write-Host "[x] Push cancelled." -ForegroundColor Gray
        exit 0
    }
}

Write-Host "`n[>>] Pushing local updates to remote..." -ForegroundColor Cyan

# Perform unidirectional local mirror (-l)
ols -l --server $serverUrl -n $projectName

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[>>] Running SHA-256 post-push verification across text sources & figures..." -ForegroundColor Cyan
    if ($Force) {
        python "$PSScriptRoot\collabtex_tool.py" verify-push --force
    } else {
        python "$PSScriptRoot\collabtex_tool.py" verify-push
    }
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[OK] Successfully pushed & verified on Overleaf!" -ForegroundColor Green
    } else {
        Write-Host "`n[!] Post-push verification encountered an issue." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "`n[!] Push encountered an issue. Please verify network or authentication." -ForegroundColor Red
    exit 1
}
