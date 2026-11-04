@echo off
if exist "%CD%\scripts\collabtex_tool.py" (
    python "%CD%\scripts\collabtex_tool.py" merge
) else if exist "%~dp0collabtex_tool.py" (
    python "%~dp0collabtex_tool.py" merge
) else (
    echo [!] Error: Please run collabtex-merge from within your paper directory.
)
