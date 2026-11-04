@echo off
setlocal
cd /d "%~dp0"
if not exist "PuryF-cli.exe" (
 echo Place this script in the built PuryF folder on a Windows PC without Python installed.
 pause
 exit /b 1
)
set "PATH=%SystemRoot%\System32;%SystemRoot%"
set "PURYF_DATA_DIR=%TEMP%\PuryF-clean-check"
"PuryF-cli.exe" self-test --clean-pc --output "%TEMP%\PuryF-v1-clean-report.json" --json
if errorlevel 1 (
 echo FAILED. Read the error above. Remove an old report file before retrying.
 pause
 exit /b 1
)
echo Core checks passed. Report: %TEMP%\PuryF-v1-clean-report.json
echo Open PuryF.exe and manually verify preview, Arabic layout, scrolling and resizing.
echo Separately test installer upgrade, Explorer actions, PATH and uninstall.
pause
exit /b 0
