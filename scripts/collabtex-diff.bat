@echo off
if exist "%CD%\scripts\collabtex_tool.py" (
    python "%CD%\scripts\collabtex_tool.py" diff
) else if exist "%~dp0collabtex_tool.py" (
    python "%~dp0collabtex_tool.py" diff
) else (
    echo [!] Error: Please run collabtex-diff from within your paper directory.
)
