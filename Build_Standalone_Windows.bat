@echo off
cd /d "%~dp0"
py -3.12 -m venv .build-venv
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" build_tools\build_standalone.py
if errorlevel 1 goto failed
echo Standalone candidate installer and portable ZIP are in release\.
echo Run Verify_Clean_PC.bat on a clean Windows PC before publishing.
pause
exit /b 0
:failed
echo Build failed. Use 64-bit Python 3.12 with Tkinter, and install NSIS.
pause
exit /b 1
