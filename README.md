<p align="center">
  <img src="assets/logo.png" width="140" alt="PuryF logo">
</p>

<h1 align="center">PuryF</h1>
<p align="center"><strong>Your files. Simply PDF.</strong></p>

PuryF is a Windows desktop app for converting files to PDF, editing PDF pages, and automating repeat jobs. It runs locally, with a dark interface, an optional light theme, and Arabic right-to-left navigation.

**Version:** 1.0.0 · **Status:** Windows release candidate

## What you can do

- **Convert files:** Process supported documents and images, singly or in batches.
- **Work with PDFs:** Preview, rearrange, rotate, delete, extract and combine pages in PDF Studio.
- **Finish a document:** Add watermarks, logos, page numbers, headers and footers; edit metadata; export pages as images; or try target-size compression.
- **Build course packs:** Combine slides, notes and handouts with contents pages and bookmarks.
- **Save time:** Use presets, naming patterns, watch folders, schedules and a background queue.
- **Work your way:** Use the desktop app, command line, Python SDK, local MCP integration or local HTTP API.

Some file types use separate installed tools—for example Microsoft Office for Office formats and Tesseract/OCRmyPDF for OCR. See [Requirements](#optional-tools-and-supported-formats).

## Screenshots

![PuryF main window](docs/screenshots/v1-main-dark.png)

![PDF Studio](docs/screenshots/v1-studio-dark.png)

![Arabic interface](docs/screenshots/v1-arabic-dark.png)

## Get PuryF

| Download | Best for | Needs Python installed? |
| --- | --- | --- |
| **`PuryF-v1-Setup.exe`** | Regular Windows installation | No |
| `PuryF-v1-Windows-portable.zip` | Running from an extracted folder | No |
| `PuryF-v1-Source-Setup.exe` | Source-based setup | Yes |

Download the files from this repository's **Releases** page once they are published. The standalone installer is the intended main download. Release checksums are recorded in `release/SHA256SUMS.txt` in the release package.

### Install on Windows

1. Run `PuryF-v1-Setup.exe`.
2. Select any optional Start menu, Explorer right-click, or terminal integrations.
3. Launch **PuryF** from the Start menu.

For the portable edition, extract the **whole** ZIP and start `PuryF.exe`. Keep its `_internal` folder beside the executable. Your portable settings and history live in its `Data` folder.

**Release note:** The Windows builds, bundled self-tests, and installer install/uninstall checks are reported as completed. Final testing on a fresh Windows machine or Windows Sandbox—including visual UI and real Office/OCR workflows—is still required before calling this a fully verified production release. Hosted operation is a developer preview, not a deployed public service.

## Quick start

### Convert your first file

1. Open PuryF and click **Add files** or **Add folder**. Drag-and-drop is also available.
2. Choose where to save the PDFs. If you leave the destination blank, output goes next to each source file.
3. Adjust any options, such as a preset, merge, compression or OCR.
4. Click **Start** (or press **F5**). Monitor progress in the queue.

Existing outputs are skipped by default so that PuryF doesn't accidentally replace your files.

### Edit a PDF

1. Open **PDF Studio** and choose **Add PDFs**.
2. Select pages to preview, move, rotate, delete or extract.
3. Use **Save arrangement** to create a new PDF in your chosen order.

PDF Studio also includes course packs, metadata editing, stamping, image export, text review and compression. Changes are saved to a new file rather than editing the source PDF in place.

### Automate routine work

Use **Automation** to load a JSON configuration for watched folders, recurring schedules or background jobs. The automation process runs while your computer and process are active; it isn't an always-on Windows service.

See the [detailed guide](docs/DETAILED_GUIDE.md) for example configuration files, presets, naming rules and troubleshooting.

## Command line and Python

If you enabled the terminal command during setup, open a new Command Prompt:

```bat
puryf --help
puryf convert "C:\Training\notes.txt" --output-dir "C:\PDFs"
puryf merge first.pdf second.pdf --output combined.pdf
puryf split combined.pdf --every 5 --output-dir parts
puryf doctor
```

The portable ZIP includes `PuryF-cli.exe` for the same command-line features. From source, you can use `python -m puryf` after installing the project dependencies.

A Python SDK, a local stdio MCP server and a local HTTP API are also included. They are optional and need explicit configuration. Read the [detailed guide](docs/DETAILED_GUIDE.md) before enabling their integrations.

## Run from source

On Windows, install 64-bit Python 3.12 and then run these commands from the project folder:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe PuryF.py
```

To build the standalone release on Windows, install NSIS as well, then run `Build_Standalone_Windows.bat`. The build produces its installer, portable ZIP and checksums in `release/`. Full build and verification instructions are in the [detailed guide](docs/DETAILED_GUIDE.md).

## Optional tools and supported formats

Core PDF tools, text files and common raster images use bundled libraries in the standalone Windows build. Other formats need additional software:

| Feature | Additional software |
| --- | --- |
| Word, Excel, PowerPoint and related Office formats | Matching Microsoft Office desktop application |
| Outlook `.msg` files | Outlook desktop |
| OCR and scanned documents | OCRmyPDF, Tesseract, Ghostscript and language packs |
| Ebooks | Calibre |
| draw.io files | draw.io desktop CLI |
| Audio transcripts | Whisper CLI, FFmpeg and a local model |
| HEIF, RAW, SVG or video | Optional libraries or a custom build |

CAD conversion is not implemented. Run `puryf doctor` to check the converters available on your machine.

## Documentation

The README covers the everyday workflow. For more details, see:

- [Detailed guide](docs/DETAILED_GUIDE.md) — installation, PDF Studio, automation, CLI, Explorer, SDK, MCP, APIs and hosting considerations.
- `TEST_REPORT.txt` and `WINDOWS_CHECKLIST.txt` — test evidence and remaining Windows checks.
- `THIRD_PARTY_NOTICES.md` — third-party license notices.

## About and license

Created and published by **AlsherkawiMO** · [Instagram](https://instagram.com/alsherkawiMO)

Copyright © 2026 AlsherkawiMO. PuryF source code is licensed under the **MIT License**. Third-party software keeps its own licenses.
