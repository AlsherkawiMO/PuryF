@echo off
"%~dp0..\.venv\Scripts\python.exe" "%~dp0..\PuryF_CLI.py" %*
exit /b %errorlevel%
