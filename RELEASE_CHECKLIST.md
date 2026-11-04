# PuryF v1 release checklist

1. [x] Recover and verify source, complete README, screenshots and prior test evidence.
2. [x] Finish the native Linux bundled-runtime check, including Arabic text conversion,
   PDF preview/image export, MCP initialization and authenticated local API.
3. [x] Package source, tutorials, screenshots, SDK wheel and Python-required source installer.
4. [x] Build native Windows standalone installer and portable ZIP.
   Verified on Windows with install, bundled self-test and uninstall lifecycle checks.
5. [x] Run available regression checks: 121 tests on Tk 8.6 and 121 tests on Tk 9.
   [x] Run the bundled core check with Python removed from PATH; conversion, PDF/image export,
   MCP initialization and authenticated local API passed.
   [ ] Run Verify_Clean_PC.bat on a fresh Windows VM/Sandbox and complete WINDOWS_CHECKLIST.txt.
6. [x] Save the source release package and include per-file SHA256 checksums.
   [x] Publish-ready Windows binaries are in `release/`; the standalone installer is the main download.

## Progress rule for remaining work

- Record each step as complete, failed or blocked before moving on.
- Use bounded command timeouts; after a repeated failure capture its error and continue
  independent checks. Do not mark a failed check as passed.
- Save a checkpoint before installing build tools or running a long build.
- Use README.md for all tutorials; TEST_REPORT.txt and the actual test logs for evidence.

## Current release status

Version 1.0.0 Windows release candidate. The included release/PuryF-v1-Source-Setup.exe requires
Python and Internet access to install dependencies. It is not the standalone installer. The
standalone installer, source installer and portable ZIP passed Windows lifecycle/self-test checks.
Fresh clean-PC validation remains pending, as do public hosted deployment and external Office/OCR/
media integration validation.
