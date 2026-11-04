# ==============================================================================
# Overleaf / Collabtex Toolkit Setup Script for New Machine
# Registers global commands: collabtex-push / pull / diff / merge
# ==============================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Initializing Overleaf / Collabtex Toolkit for this PC...   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Unlock PowerShell Execution Policy for CurrentUser
try {
    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force -ErrorAction SilentlyContinue
    Write-Host "[1/4] PowerShell ExecutionPolicy set to RemoteSigned" -ForegroundColor Green
} catch {
    Write-Host "[1/4] PowerShell ExecutionPolicy skipped (already ready)" -ForegroundColor Gray
}

# 2. Check and install overleaf-sync
Write-Host "[2/4] Checking and installing overleaf-sync..." -ForegroundColor Cyan
& python -m pip install --upgrade --user overleaf-sync

# 3. Apply custom Overleaf CE / Collabtex patches
Write-Host "[3/4] Applying protocol patch for Overleaf Community Edition..." -ForegroundColor Cyan
$patchScript = Join-Path $PSScriptRoot "patch-olsync.py"
if (Test-Path $patchScript) {
    & python $patchScript
} else {
    Write-Host "[!] patch-olsync.py not found in $PSScriptRoot" -ForegroundColor Yellow
}

# 4. Register global commands
Write-Host "[4/4] Registering global commands (push / pull / diff / merge)..." -ForegroundColor Cyan

# 4.1 Copy command batch files to Python Scripts directory (double insurance)
try {
    $pyScripts = & python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
    if ($pyScripts -and (Test-Path $pyScripts)) {
        Copy-Item "$PSScriptRoot\collabtex-push.bat" $pyScripts -Force -ErrorAction SilentlyContinue
        Copy-Item "$PSScriptRoot\collabtex-pull.bat" $pyScripts -Force -ErrorAction SilentlyContinue
        Copy-Item "$PSScriptRoot\collabtex-diff.bat" $pyScripts -Force -ErrorAction SilentlyContinue
        Copy-Item "$PSScriptRoot\collabtex-merge.bat" $pyScripts -Force -ErrorAction SilentlyContinue
        Copy-Item "$PSScriptRoot\collabtex_tool.py" $pyScripts -Force -ErrorAction SilentlyContinue
        Write-Host "  -> Copied batch shortcuts and tool to Python Scripts: $pyScripts" -ForegroundColor Gray
    }
} catch {
    Write-Host "  -> Python Scripts copy skipped" -ForegroundColor Gray
}

# 4.2 Add scripts directory to Windows User PATH environment variable
try {
    $userPath = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::User)
    if ($userPath -notlike "*$PSScriptRoot*") {
        $newUserPath = if ([string]::IsNullOrWhiteSpace($userPath)) { $PSScriptRoot } else { "$userPath;$PSScriptRoot" }
        [Environment]::SetEnvironmentVariable("Path", $newUserPath, [EnvironmentVariableTarget]::User)
        $env:Path += ";$PSScriptRoot"
        Write-Host "  -> Added scripts directory to User PATH environment" -ForegroundColor Gray
    } else {
        Write-Host "  -> User PATH already contains scripts directory" -ForegroundColor Gray
    }
} catch {
    Write-Host "  -> User PATH modification skipped" -ForegroundColor Gray
}

# 4.3 Write aliases into PowerShell Profile
try {
    $profileDir = Split-Path $PROFILE -Parent
    if (-not (Test-Path $profileDir)) { New-Item -ItemType Directory -Path $profileDir -Force | Out-Null }
    
    $profileFunc = @'

# Overleaf / Collabtex Toolkit
function collabtex-push {
    if (Test-Path "scripts\push-collabtex.ps1") {
        & powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\push-collabtex.ps1"
    } else {
        ols -l
    }
}
function collabtex-pull {
    if (Test-Path "scripts\pull-collabtex.ps1") {
        & powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\pull-collabtex.ps1"
    } else {
        ols -r
    }
}
function collabtex-diff {
    if (Test-Path "scripts\diff-collabtex.ps1") {
        & powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\diff-collabtex.ps1"
    } else {
        python -c "print('Please run collabtex-diff from within your paper directory')"
    }
}
function collabtex-merge {
    if (Test-Path "scripts\merge-collabtex.ps1") {
        & powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\merge-collabtex.ps1"
    } else {
        python -c "print('Please run collabtex-merge from within your paper directory')"
    }
}
'@
    $existing = ""
    if (Test-Path $PROFILE) { $existing = Get-Content $PROFILE -Raw }
    if ($existing -notmatch "collabtex-merge") {
        Add-Content -Path $PROFILE -Value $profileFunc -Encoding UTF8
        Write-Host "  -> Added toolkit functions to PowerShell Profile" -ForegroundColor Gray
    } else {
        Write-Host "  -> PowerShell Profile already configured" -ForegroundColor Gray
    }
} catch {
    Write-Host "  -> Profile configuration skipped" -ForegroundColor Gray
}

# 4.4 Synchronize .olauth credentials to user home if available
try {
    $projectRoot = Join-Path $PSScriptRoot ".."
    $localAuth = Join-Path $projectRoot ".olauth"
    $homeAuth = Join-Path $env:USERPROFILE ".olauth"
    if ((Test-Path $localAuth) -and (-not (Test-Path $homeAuth))) {
        Copy-Item $localAuth $homeAuth -Force -ErrorAction SilentlyContinue
        Write-Host "  -> Synchronized .olauth to user home ($homeAuth)" -ForegroundColor Gray
    }
} catch {
    Write-Host "  -> Credential sync skipped" -ForegroundColor Gray
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " [SUCCESS] Overleaf / Collabtex Toolkit fully configured for this PC!" -ForegroundColor Green
Write-Host " Available commands: collabtex-push | collabtex-pull | collabtex-diff | collabtex-merge" -ForegroundColor Cyan
Write-Host " NOTE: In current terminal, run: . `$PROFILE (or open a new terminal) to take effect!" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Green
