@echo off
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
    echo Python launcher not found. Install Python with the py launcher, or run the commands in README.txt.
    pause
    exit /b 1
)
py -3 -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto failed
py -3 -m PyInstaller --noconfirm --clean --windowed --onedir --name PuryF --icon assets\PuryF.ico --add-data "assets;assets" --collect-all tkinterdnd2 PuryF.py
if errorlevel 1 goto failed
echo.
echo Built: dist\PuryF\PuryF.exe
echo Keep the complete dist\PuryF folder together.
pause
exit /b 0
:failed
echo Build failed. Review the error above.
pause
exit /b 1
