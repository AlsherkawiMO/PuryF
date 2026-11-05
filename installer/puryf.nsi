; PuryF source installer. Requires installed Python; dependencies are downloaded.
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "Sections.nsh"
; Always resolve source payload paths from the project root, regardless of
; the directory from which makensis is launched.
!cd "${__FILEDIR__}"
!define APP_VERSION "1.0.0"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\PuryF"
Name "PuryF v1 Source Setup (requires Python)"
OutFile "..\release\PuryF-v1-Source-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\PuryF"
InstallDirRegKey HKCU "Software\PuryF" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID zlib
ShowInstDetails show
ShowUninstDetails show
Icon "..\assets\PuryF.ico"
UninstallIcon "..\assets\PuryF.ico"
VIProductVersion "1.0.0.0"
VIAddVersionKey /LANG=1033 "ProductName" "PuryF"
VIAddVersionKey /LANG=1033 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion" "1.0.0.0"
VIAddVersionKey /LANG=1033 "FileDescription" "PuryF Python-required per-user setup"
VIAddVersionKey /LANG=1033 "LegalCopyright" "2026 AlsherkawiMO"
VIAddVersionKey /LANG=1033 "CompanyName" "AlsherkawiMO"
Var PythonCommand
!define MUI_WELCOMEPAGE_TEXT "Install PuryF, the local PDF toolkit.$\r$\n$\r$\nRequires Python 3.10 or newer with Tkinter, pip and venv already installed.$\r$\n$\r$\nSetup downloads core dependencies into a private environment. Internet access is required. Microsoft Office and optional converters are separate.$\r$\n$\r$\nThis is a v1 source preview; Windows execution has not yet been validated."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchPuryF
!define MUI_FINISHPAGE_RUN_TEXT "Open PuryF"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function LaunchPuryF
  SetOutPath "$INSTDIR"
  Exec '"$INSTDIR\.venv\Scripts\pythonw.exe" "$INSTDIR\PuryF.py"'
FunctionEnd

; Only remove verbs owned by this installation.
!macro RemoveExplorerVerbs
  ReadRegStr $0 HKCU "Software\Classes\*\shell\PuryF.Convert" "PuryFOwner"
  ${If} $0 == $INSTDIR
    DeleteRegKey HKCU "Software\Classes\*\shell\PuryF.Convert"
  ${EndIf}
  ReadRegStr $0 HKCU "Software\Classes\*\shell\PuryF.Queue" "PuryFOwner"
  ${If} $0 == $INSTDIR
    DeleteRegKey HKCU "Software\Classes\*\shell\PuryF.Queue"
  ${EndIf}
!macroend

Function .onInit
  SetShellVarContext current
  nsExec::ExecToStack /TIMEOUT=15000 '"py" -3 -c "import sys, tkinter, venv, ensurepip; sys.exit(0 if sys.version_info >= (3,10) else 1)"'
  Pop $0
  Pop $1
  ${If} $0 == 0
    StrCpy $PythonCommand '"py" -3'
  ${Else}
    nsExec::ExecToStack /TIMEOUT=15000 '"python" -c "import sys, tkinter, venv, ensurepip; sys.exit(0 if sys.version_info >= (3,10) else 1)"'
    Pop $0
    Pop $1
    ${If} $0 == 0
      StrCpy $PythonCommand '"python"'
    ${Else}
      MessageBox MB_OK|MB_ICONSTOP "Install Python 3.10 or newer with Tkinter, pip and the Python launcher first, then run this setup again. Download from python.org."
      SetErrorLevel 2
      Abort
    ${EndIf}
  ${EndIf}
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File /oname=install_guard.py "install_guard.py"
  nsExec::ExecToLog '$PythonCommand "$PLUGINSDIR\install_guard.py"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Close PuryF before installing or upgrading, then run setup again."
    Abort
  ${EndIf}
  ; Section 2 is Explorer (after required app and optional desktop shortcut).
  ReadRegDWORD $0 HKCU "Software\PuryF" "ExplorerEnabled"
  ${If} $0 == 1
    !insertmacro SelectSection 2
  ${EndIf}
  ReadRegDWORD $0 HKCU "Software\PuryF" "CommandEnabled"
  ${If} $0 == 1
    !insertmacro SelectSection 3
  ${EndIf}
FunctionEnd

Section "PuryF application and private runtime" SEC_APP
  SectionIn RO
  ; Do not adopt an existing unrelated project/venv directory.
  IfFileExists "$INSTDIR\puryf-install.marker" verify_marker
  IfFileExists "$INSTDIR\.venv\*.*" unsafe_directory
  IfFileExists "$INSTDIR\PuryF.py" unsafe_directory owned_directory
verify_marker:
  FileOpen $0 "$INSTDIR\puryf-install.marker" r
  FileRead $0 $1
  FileClose $0
  StrCmp $1 "PuryF source install v1" owned_directory unsafe_directory
unsafe_directory:
  MessageBox MB_OK|MB_ICONSTOP "This folder already contains Python project files. Choose an empty folder dedicated to PuryF."
  SetErrorLevel 3
  Abort
owned_directory:
  SetOutPath "$INSTDIR"
  File "..\PuryF.py"
  File "..\PuryF_CLI.py"
  File "..\Run_CLI.bat"
  File "..\docs\CLI.md"
  File "..\docs\MCP_API.md"
  File "..\docs\HOSTING.md"
  File "..\openapi.json"
  File "..\requirements.txt"
  File "..\LICENSE"
  File "..\README.txt"
  File "..\README.md"
  File "..\docs\EXPLORER.md"
  File "..\docs\WINDOWS_CHECKLIST.txt"
  File "..\THIRD_PARTY_NOTICES.md"
  File "..\Start_PuryF.bat"
  File "runtime_setup.py"
  File "install_guard.py"
  File "path_setup.py"
  SetOutPath "$INSTDIR\puryf"
  File "..\puryf\__init__.py"
  File "..\puryf\engine.py"
  File "..\puryf\options.py"
  File "..\puryf\jobs.py"
  File "..\puryf\pdf_tools.py"
  File "..\puryf\desktop.py"
  File "..\puryf\explorer.py"
  File "..\puryf\cli.py"
  File "..\puryf\__main__.py"
  File "..\puryf\access.py"
  File "..\puryf\gateway.py"
  File "..\puryf\mcp_server.py"
  File "..\puryf\http_server.py"
  File "..\puryf\webhooks.py"
  File "..\puryf\automation.py"
  File "..\puryf\i18n.py"
  File "..\puryf\selftest.py"
  File "..\puryf\extensions.py"
  File "..\puryf\v1_cli.py"
  File "..\puryf\install_support.py"
  File "..\puryf\sdk.py"
  File "..\puryf\launchers.py"
  File "..\puryf\studio.py"
  File "..\puryf\documents.py"
  File "..\puryf\workbench.py"
  File "..\puryf\state.py"
  SetOutPath "$INSTDIR\examples"
  File "..\examples\notes.txt"
  File "..\examples\convert.request.json"
  SetOutPath "$INSTDIR\docs\screenshots"
  File "..\docs\screenshots\v1-main-dark.png"
  File "..\docs\screenshots\v1-studio-dark.png"
  File "..\docs\screenshots\v1-arabic-dark.png"
  SetOutPath "$INSTDIR\integration-configs"
  File "..\integration-configs\local.example.json"
  File "..\integration-configs\mcp.example.json"
  File "..\integration-configs\hosted.example.json"
  File "..\integration-configs\webhook.example.json"
  SetOutPath "$INSTDIR\assets"
  File "..\assets\PuryF-logo-light.png"
  File "..\assets\PuryF-logo-dark.png"
  File "..\assets\PuryF-icon-64.png"
  File "..\assets\PuryF.ico"
  File "..\assets\favicon.ico"
  File "..\assets\DejaVuSans.ttf"
  File "..\assets\DejaVu-LICENSE.txt"
  SetOutPath "$INSTDIR"
  FileOpen $0 "$INSTDIR\puryf-install.marker" w
  FileWrite $0 "PuryF source install v1"
  FileClose $0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\PuryF" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "PuryF"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "AlsherkawiMO"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\assets\PuryF.ico"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  DetailPrint "Installing PuryF dependencies. This may take several minutes."
  nsExec::ExecToLog '$PythonCommand "$INSTDIR\runtime_setup.py" "$INSTDIR"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Dependency installation failed. Check the setup details and your internet connection. Re-run setup to retry, or use Uninstall.exe in the install folder to remove the partial installation."
    SetErrorLevel 4
    Abort
  ${EndIf}
  nsExec::ExecToLog '$PythonCommand "$INSTDIR\path_setup.py" remove "$INSTDIR"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Could not update the previous PuryF PATH entry. Review setup details and retry."
    SetErrorLevel 6
    Abort
  ${EndIf}
  Delete "$INSTDIR\bin\puryf.cmd"
  RMDir "$INSTDIR\bin"
  WriteRegDWORD HKCU "Software\PuryF" "CommandEnabled" 0
  !insertmacro RemoveExplorerVerbs
  WriteRegDWORD HKCU "Software\PuryF" "ExplorerEnabled" 0
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  CreateDirectory "$SMPROGRAMS\PuryF"
  CreateShortCut "$SMPROGRAMS\PuryF\PuryF.lnk" "$INSTDIR\.venv\Scripts\pythonw.exe" '"$INSTDIR\PuryF.py"' "$INSTDIR\assets\PuryF.ico"
  CreateShortCut "$SMPROGRAMS\PuryF\Uninstall PuryF.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section /o "Desktop shortcut" SEC_DESKTOP
  CreateShortCut "$DESKTOP\PuryF.lnk" "$INSTDIR\.venv\Scripts\pythonw.exe" '"$INSTDIR\PuryF.py"' "$INSTDIR\assets\PuryF.ico"
SectionEnd

Section /o "Explorer right-click actions (classic menu)" SEC_EXPLORER
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Convert" "" "Convert to PDF with PuryF"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Convert" "Icon" "$INSTDIR\assets\PuryF.ico"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Convert" "MultiSelectModel" "Player"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Convert" "PuryFOwner" "$INSTDIR"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Convert\command" "" '$\"$INSTDIR\.venv\Scripts\pythonw.exe$\" $\"$INSTDIR\PuryF.py$\" --explorer-convert -- $\"%1$\"'
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Queue" "" "Add to PuryF queue"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Queue" "Icon" "$INSTDIR\assets\PuryF.ico"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Queue" "MultiSelectModel" "Player"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Queue" "PuryFOwner" "$INSTDIR"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Queue\command" "" '$\"$INSTDIR\.venv\Scripts\pythonw.exe$\" $\"$INSTDIR\PuryF.py$\" --explorer-queue -- $\"%1$\"'
  WriteRegDWORD HKCU "Software\PuryF" "ExplorerEnabled" 1
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd

Section /o "Terminal puryf command on user PATH" SEC_COMMAND
  SetOutPath "$INSTDIR\bin"
  File "..\bin\puryf.cmd"
  SetOutPath "$INSTDIR"
  nsExec::ExecToLog '$PythonCommand "$INSTDIR\path_setup.py" add "$INSTDIR"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Could not add the PuryF command to user PATH. Review setup details and retry."
    SetErrorLevel 6
    Abort
  ${EndIf}
  WriteRegDWORD HKCU "Software\PuryF" "CommandEnabled" 1
SectionEnd

Function un.RemoveCommandPath
  ReadRegStr $0 HKCU "Software\PuryF" "PathEntryOwned"
  StrCmp $0 "" path_done
  IfFileExists "$INSTDIR\.venv\Scripts\python.exe" 0 global_python
  nsExec::ExecToLog '"$INSTDIR\.venv\Scripts\python.exe" "$INSTDIR\path_setup.py" remove "$INSTDIR"'
  Pop $0
  Goto path_result
global_python:
  nsExec::ExecToLog '"py" -3 "$INSTDIR\path_setup.py" remove "$INSTDIR"'
  Pop $0
  ${If} $0 != 0
    nsExec::ExecToLog '"python" "$INSTDIR\path_setup.py" remove "$INSTDIR"'
    Pop $0
  ${EndIf}
path_result:
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Could not remove PuryF's user PATH entry. Restore Python and retry uninstall."
    Abort
  ${EndIf}
path_done:
FunctionEnd

Function un.onInit
  SetOutPath "$INSTDIR"
  IfFileExists "$INSTDIR\.venv\Scripts\python.exe" 0 guard_done
  IfFileExists "$INSTDIR\install_guard.py" 0 guard_done
  nsExec::ExecToLog '"$INSTDIR\.venv\Scripts\python.exe" "$INSTDIR\install_guard.py"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Close PuryF before uninstalling, then retry."
    Abort
  ${EndIf}
guard_done:
FunctionEnd

Section "Uninstall"
  SetShellVarContext current
  IfFileExists "$INSTDIR\puryf-install.marker" marker_present
  MessageBox MB_OK|MB_ICONSTOP "PuryF installation marker is missing. Automatic removal has stopped."
  Abort
marker_present:
  FileOpen $0 "$INSTDIR\puryf-install.marker" r
  FileRead $0 $1
  FileClose $0
  ${If} $1 != "PuryF source install v1"
    MessageBox MB_OK|MB_ICONSTOP "PuryF installation marker is invalid. Automatic removal has stopped."
    Abort
  ${EndIf}
  Call un.RemoveCommandPath
  !insertmacro RemoveExplorerVerbs
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  Delete "$DESKTOP\PuryF.lnk"
  Delete "$SMPROGRAMS\PuryF\PuryF.lnk"
  Delete "$SMPROGRAMS\PuryF\Uninstall PuryF.lnk"
  RMDir "$SMPROGRAMS\PuryF"
  ; Only the dedicated PuryF environment is recursively removed.
  RMDir /r "$INSTDIR\.venv"
  Delete "$INSTDIR\assets\PuryF-logo-light.png"
  Delete "$INSTDIR\assets\PuryF-logo-dark.png"
  Delete "$INSTDIR\assets\PuryF-icon-64.png"
  Delete "$INSTDIR\assets\PuryF.ico"
  Delete "$INSTDIR\assets\favicon.ico"
  Delete "$INSTDIR\assets\DejaVuSans.ttf"
  Delete "$INSTDIR\assets\DejaVu-LICENSE.txt"
  RMDir "$INSTDIR\assets"
  Delete "$INSTDIR\integration-configs\local.example.json"
  Delete "$INSTDIR\integration-configs\mcp.example.json"
  Delete "$INSTDIR\integration-configs\hosted.example.json"
  Delete "$INSTDIR\integration-configs\webhook.example.json"
  RMDir "$INSTDIR\integration-configs"
  Delete "$INSTDIR\puryf\__init__.py"
  Delete "$INSTDIR\puryf\engine.py"
  Delete "$INSTDIR\puryf\options.py"
  Delete "$INSTDIR\puryf\jobs.py"
  Delete "$INSTDIR\puryf\pdf_tools.py"
  Delete "$INSTDIR\puryf\desktop.py"
  Delete "$INSTDIR\puryf\explorer.py"
  Delete "$INSTDIR\puryf\cli.py"
  Delete "$INSTDIR\puryf\__main__.py"
  Delete "$INSTDIR\puryf\access.py"
  Delete "$INSTDIR\puryf\gateway.py"
  Delete "$INSTDIR\puryf\mcp_server.py"
  Delete "$INSTDIR\puryf\http_server.py"
  Delete "$INSTDIR\puryf\webhooks.py"
  Delete "$INSTDIR\puryf\automation.py"
  Delete "$INSTDIR\puryf\i18n.py"
  Delete "$INSTDIR\puryf\selftest.py"
  Delete "$INSTDIR\puryf\extensions.py"
  Delete "$INSTDIR\puryf\v1_cli.py"
  Delete "$INSTDIR\puryf\install_support.py"
  Delete "$INSTDIR\puryf\sdk.py"
  Delete "$INSTDIR\puryf\launchers.py"
  Delete "$INSTDIR\puryf\studio.py"
  Delete "$INSTDIR\puryf\documents.py"
  Delete "$INSTDIR\puryf\workbench.py"
  Delete "$INSTDIR\puryf\state.py"
  RMDir /r "$INSTDIR\puryf\__pycache__"
  RMDir "$INSTDIR\puryf"
  Delete "$INSTDIR\bin\puryf.cmd"
  RMDir "$INSTDIR\bin"
  Delete "$INSTDIR\PuryF_CLI.py"
  Delete "$INSTDIR\Run_CLI.bat"
  Delete "$INSTDIR\CLI.md"
  Delete "$INSTDIR\MCP_API.md"
  Delete "$INSTDIR\HOSTING.md"
  Delete "$INSTDIR\openapi.json"
  Delete "$INSTDIR\path_setup.py"
  Delete "$INSTDIR\PuryF.py"
  Delete "$INSTDIR\requirements.txt"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\examples\notes.txt"
  Delete "$INSTDIR\examples\convert.request.json"
  RMDir "$INSTDIR\examples"
  Delete "$INSTDIR\docs\screenshots\v1-main-dark.png"
  Delete "$INSTDIR\docs\screenshots\v1-studio-dark.png"
  Delete "$INSTDIR\docs\screenshots\v1-arabic-dark.png"
  RMDir "$INSTDIR\docs\screenshots"
  RMDir "$INSTDIR\docs"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\EXPLORER.md"
  Delete "$INSTDIR\WINDOWS_CHECKLIST.txt"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  Delete "$INSTDIR\Start_PuryF.bat"
  Delete "$INSTDIR\runtime_setup.py"
  Delete "$INSTDIR\install_guard.py"
  Delete "$INSTDIR\puryf-install.marker"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\PuryF"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  ; Documents/PuryF is intentionally left intact.
  ; Remove only transport-owned data, never the source files referenced by it.
  Delete "$LOCALAPPDATA\PuryF\Explorer\pending\*.json"
  Delete "$LOCALAPPDATA\PuryF\Explorer\pending\*.tmp"
  RMDir "$LOCALAPPDATA\PuryF\Explorer\pending"
  Delete "$LOCALAPPDATA\PuryF\Explorer\instance.lock"
  RMDir "$LOCALAPPDATA\PuryF\Explorer"
  Delete "$LOCALAPPDATA\PuryF\Conversion\instance.lock"
  RMDir "$LOCALAPPDATA\PuryF\Conversion"
  RMDir "$LOCALAPPDATA\PuryF"
SectionEnd
