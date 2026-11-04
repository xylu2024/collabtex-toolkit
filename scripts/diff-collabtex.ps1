# Diff Local files against Overleaf / Collabtex Remote snapshot
# Non-destructive: Downloads remote files to cache and opens VS Code side-by-side diff
$projectDir = Join-Path $PSScriptRoot ".."
Set-Location $projectDir

python "$PSScriptRoot\collabtex_tool.py" diff
