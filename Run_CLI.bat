@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0PuryF_CLI.py" %*
) else (
  py -3 "%~dp0PuryF_CLI.py" %*
)
exit /b %errorlevel%
