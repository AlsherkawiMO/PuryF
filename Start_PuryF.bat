@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" PuryF.py
    goto result
)
where py >nul 2>&1
if errorlevel 1 (
    python PuryF.py
) else (
    py -3 PuryF.py
)
:result
if errorlevel 1 pause
