# Clean LaTeX compilation auxiliary files safely (Preserves synctex and PDFs)
$projectDir = Join-Path $PSScriptRoot ".."
Set-Location $projectDir

$auxExtensions = @("*.aux", "*.bbl", "*.blg", "*.log", "*.out", "*.fls", "*.fdb_latexmk", "*.toc", "*.lof", "*.lot", "*.bcf", "*.run.xml", "*Notes.bib", "*.xdv")

Write-Host "Cleaning LaTeX build artifacts in $projectDir..." -ForegroundColor Cyan
foreach ($ext in $auxExtensions) {
    Get-ChildItem -Path $projectDir -Filter $ext -Recurse -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}

# Clean build directory if exists
$buildDir = Join-Path $projectDir "build"
if (Test-Path $buildDir) {
    Get-ChildItem -Path $buildDir -Exclude "*.synctex.gz", "*.pdf" -Recurse -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}

Write-Host "[OK] Cleaned LaTeX auxiliary files. SyncTeX and PDFs preserved." -ForegroundColor Green
