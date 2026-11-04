Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "Sections.nsh"
; Always resolve payload paths from the project root, regardless of the
; directory from which makensis is launched.
!cd "${__FILEDIR__}"
Name "PuryF v1"
OutFile "..\release\PuryF-v1-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\PuryF"
InstallDirRegKey HKCU "Software\PuryF" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
Icon "..\assets\PuryF.ico"
UninstallIcon "..\assets\PuryF.ico"
VIProductVersion "1.0.0.0"
VIAddVersionKey /LANG=1033 "ProductName" "PuryF v1"
VIAddVersionKey /LANG=1033 "FileVersion" "1.0.0.0"
VIAddVersionKey /LANG=1033 "FileDescription" "PuryF standalone Windows installer"
VIAddVersionKey /LANG=1033 "LegalCopyright" "2026 AlsherkawiMO"
VIAddVersionKey /LANG=1033 "CompanyName" "AlsherkawiMO"
!define MUI_WELCOMEPAGE_TEXT "PuryF v1 bundles Python and core dependencies.$\r$\nNo Python installation or internet download is needed on the target PC.$\r$\n$\r$\nOffice, OCR and optional external converters remain separate.$\r$\nClose all PuryF windows and background/MCP/API hosts before installing."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\PuryF.exe"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

!macro RemoveVerbs
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
  IfFileExists "$INSTDIR\puryf-install.marker" legacy
  IfFileExists "$INSTDIR\PuryF-cli.exe" 0 preferences
  nsExec::ExecToLog '"$INSTDIR\PuryF-cli.exe" installation guard'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Close PuryF and its background hosts, then retry."
    Abort
  ${EndIf}
  Goto preferences
legacy:
  MessageBox MB_OK|MB_ICONSTOP "Uninstall the earlier Python-required PuryF installation first. Your documents and saved session are preserved. Then install standalone PuryF v1."
  Abort
preferences:
  ReadRegDWORD $0 HKCU "Software\PuryF" "ExplorerEnabled"
  ${If} $0 == 1
    !insertmacro SelectSection 1
  ${EndIf}
  ReadRegDWORD $0 HKCU "Software\PuryF" "CommandEnabled"
  ${If} $0 == 1
    !insertmacro SelectSection 2
  ${EndIf}
FunctionEnd

Section "PuryF v1 and bundled runtime" SEC_APP
  SectionIn RO
  IfFileExists "$INSTDIR\puryf-standalone.marker" owned
  IfFileExists "$INSTDIR\*.*" unsafe owned
unsafe:
  MessageBox MB_OK|MB_ICONSTOP "Choose an empty folder dedicated to PuryF."
  Abort
owned:
  IfFileExists "$INSTDIR\puryf-standalone.marker" 0 install
  FileOpen $0 "$INSTDIR\puryf-standalone.marker" r
  FileRead $0 $1
  FileClose $0
  ${If} $1 != "PuryF standalone v1"
    Abort
  ${EndIf}
install:
  SetOutPath "$INSTDIR"
  File /r "..\dist\PuryF\*"
  FileOpen $0 "$INSTDIR\puryf-standalone.marker" w
  FileWrite $0 "PuryF standalone v1"
  FileClose $0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  nsExec::ExecToLog '"$INSTDIR\PuryF-cli.exe" installation guard'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Close PuryF and background/MCP/API hosts, then retry setup."
    Abort
  ${EndIf}
  nsExec::ExecToLog '"$INSTDIR\PuryF-cli.exe" installation path-remove --root "$INSTDIR"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Could not update the previous user PATH entry. Retry setup after resolving the error."
    Abort
  ${EndIf}
  !insertmacro RemoveVerbs
  Delete "$INSTDIR\bin\puryf.cmd"
  RMDir "$INSTDIR\bin"
  WriteRegDWORD HKCU "Software\PuryF" "ExplorerEnabled" 0
  WriteRegDWORD HKCU "Software\PuryF" "CommandEnabled" 0
  WriteRegStr HKCU "Software\PuryF" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PuryF" "DisplayName" "PuryF v1"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PuryF" "DisplayVersion" "1.0.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PuryF" "Publisher" "AlsherkawiMO"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PuryF" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  CreateDirectory "$SMPROGRAMS\PuryF"
  CreateShortCut "$SMPROGRAMS\PuryF\PuryF.lnk" "$INSTDIR\PuryF.exe"
SectionEnd

Section /o "Explorer classic context menu" SEC_EXPLORER
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Convert" "" "Convert to PDF with PuryF"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Convert" "PuryFOwner" "$INSTDIR"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Convert" "Icon" "$INSTDIR\PuryF.exe"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Convert" "MultiSelectModel" "Player"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Convert\command" "" '$\"$INSTDIR\PuryF.exe$\" --explorer-convert -- $\"%1$\"'
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Queue" "" "Add to PuryF queue"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Queue" "PuryFOwner" "$INSTDIR"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Queue" "Icon" "$INSTDIR\PuryF.exe"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Queue" "MultiSelectModel" "Player"
  WriteRegStr HKCU "Software\Classes\*\shell\PuryF.Queue\command" "" '$\"$INSTDIR\PuryF.exe$\" --explorer-queue -- $\"%1$\"'
  WriteRegDWORD HKCU "Software\PuryF" "ExplorerEnabled" 1
SectionEnd

Section /o "Terminal command on user PATH" SEC_COMMAND
  SetOutPath "$INSTDIR\bin"
  FileOpen $0 "$INSTDIR\bin\puryf.cmd" w
  FileWrite $0 '@echo off$\r$\n"%~dp0..\PuryF-cli.exe" %*$\r$\nexit /b %errorlevel%$\r$\n'
  FileClose $0
  nsExec::ExecToLog '"$INSTDIR\PuryF-cli.exe" installation path-add --root "$INSTDIR"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Could not add PuryF to user PATH. Review the error and retry."
    Abort
  ${EndIf}
  WriteRegDWORD HKCU "Software\PuryF" "CommandEnabled" 1
SectionEnd
Section /o "Desktop shortcut" SEC_DESKTOP
  CreateShortCut "$DESKTOP\PuryF.lnk" "$INSTDIR\PuryF.exe"
SectionEnd
Function .onInstSuccess
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
FunctionEnd

Section "Uninstall"
  SetShellVarContext current
  FileOpen $0 "$INSTDIR\puryf-standalone.marker" r
  IfErrors unsafe_uninstall
  FileRead $0 $1
  FileClose $0
  StrCmp $1 "PuryF standalone v1" valid unsafe_uninstall
unsafe_uninstall:
  MessageBox MB_OK|MB_ICONSTOP "Standalone ownership marker is missing/invalid. Removal stopped."
  Abort
valid:
  nsExec::ExecToLog '"$INSTDIR\PuryF-cli.exe" installation guard'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Close all PuryF windows and background hosts, then retry uninstall."
    Abort
  ${EndIf}
  nsExec::ExecToLog '"$INSTDIR\PuryF-cli.exe" installation path-remove --root "$INSTDIR"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Could not clean the owned user PATH entry. Repair this install and retry."
    Abort
  ${EndIf}
  !insertmacro RemoveVerbs
  Delete "$DESKTOP\PuryF.lnk"
  Delete "$SMPROGRAMS\PuryF\PuryF.lnk"
  RMDir "$SMPROGRAMS\PuryF"
  ; Only bundled runtime, notices and shipped demos/config templates are removed.
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\THIRD_PARTY_LICENSES"
  RMDir /r "$INSTDIR\examples"
  Delete "$INSTDIR\integration-configs\*.example.json"
  RMDir "$INSTDIR\integration-configs"
  Delete "$INSTDIR\bin\puryf.cmd"
  RMDir "$INSTDIR\bin"
  Delete "$INSTDIR\PuryF.exe"
  Delete "$INSTDIR\PuryF-cli.exe"
  Delete "$INSTDIR\docs\screenshots\*.png"
  RMDir "$INSTDIR\docs\screenshots"
  RMDir "$INSTDIR\docs"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  Delete "$INSTDIR\Verify_Clean_PC.bat"
  Delete "$INSTDIR\puryf-standalone.marker"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\PuryF"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PuryF"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  ; User Data, Documents/PuryF, external server data and source/output documents are preserved.
SectionEnd
