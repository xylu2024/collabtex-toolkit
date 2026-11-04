# 3-Way Merge for Overleaf / Collabtex
# Combines local edits and collaborator's remote annotations into local source files
$projectDir = Join-Path $PSScriptRoot ".."
Set-Location $projectDir

python "$PSScriptRoot\collabtex_tool.py" merge
