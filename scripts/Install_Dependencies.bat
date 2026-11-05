@echo off
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    pause
    exit /b
)
where py >nul 2>&1
if errorlevel 1 (
    python -m pip install -r requirements.txt
) else (
    py -3 -m pip install -r requirements.txt
)
pause
