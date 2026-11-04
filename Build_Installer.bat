@echo off
cd /d "%~dp0"
if not exist release mkdir release
where makensis >nul 2>&1
if not errorlevel 1 goto compile_path
if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" (
    pushd installer
    "%ProgramFiles(x86)%\NSIS\makensis.exe" puryf.nsi
    set "NSIS_RC=%errorlevel%"
    popd
    goto result
)
if exist "%ProgramFiles%\NSIS\makensis.exe" (
    pushd installer
    "%ProgramFiles%\NSIS\makensis.exe" puryf.nsi
    set "NSIS_RC=%errorlevel%"
    popd
    goto result
)
echo Install NSIS from nsis.sourceforge.io, then run this file again.
pause
exit /b 1
:compile_path
pushd installer
makensis puryf.nsi
set "NSIS_RC=%errorlevel%"
popd
:result
if not exist "release\PuryF-v1-Source-Setup.exe" (
    echo Installer output missing.
    pause
    exit /b 1
)
if not "%NSIS_RC%"=="0" (
    echo Installer build failed.
    pause
    exit /b 1
)
echo Installer built in release\
pause
