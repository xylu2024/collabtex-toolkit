@echo off
if exist "%CD%\scripts\push-collabtex.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\push-collabtex.ps1"
) else if exist "%~dp0push-collabtex.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0push-collabtex.ps1"
) else (
    ols -l
)
