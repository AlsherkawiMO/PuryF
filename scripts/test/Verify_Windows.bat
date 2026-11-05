@echo off
cd /d "%~dp0..\.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m unittest discover -s tests -v
    pause
    exit /b
)
where py >nul 2>&1
if errorlevel 1 (
    python -m unittest discover -s tests -v
) else (
    py -3 -m unittest discover -s tests -v
)
pause
