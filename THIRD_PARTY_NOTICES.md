# Third-party components

The MIT license in this repository covers PuryF's own project files. It does not relicense
Python, Tk, installed packages, external converters, fonts or Microsoft Office.

The supplied source installer contains PuryF source/assets and the NSIS installer runtime.
It downloads Python dependencies using pip rather than embedding those dependency distributions.
Package license files remain with the installed packages in `.venv/Lib/site-packages`.
NSIS permits distribution of generated installers under the distributor's chosen terms:
https://nsis.sourceforge.io/License

Core dependency projects:

- Python and Tk: https://www.python.org/psf/license/ and https://www.tcl-lang.org/software/tcltk/license.html
- Pillow: https://github.com/python-pillow/Pillow
- pypdf: https://github.com/py-pdf/pypdf
- ReportLab: https://www.reportlab.com/opensource/
- cryptography: https://github.com/pyca/cryptography
- tkinterdnd2 / tkdnd: https://github.com/pmgagne/tkinterdnd2 and https://github.com/petasis/tkdnd
- arabic-reshaper: https://github.com/mpcabd/python-arabic-reshaper
- python-bidi: https://github.com/MeirKriheli/python-bidi
- pywin32: https://github.com/mhammond/pywin32

Optional image/media dependencies are listed separately in `requirements-optional.txt`.
Office, OCRmyPDF, Tesseract, Ghostscript, Calibre, draw.io, FFmpeg, Whisper and its models are not
bundled with this source installer. Each must be obtained under its own terms.
Do not treat a local dependency's availability as permission to redistribute its binaries or models.

If building a frozen app, include all applicable third-party notices and runtime licenses in that
distribution. This source package does not claim to be an audited frozen-binary distribution.


V1 preview/rendering dependency: pypdfium2 and PDFium.
https://github.com/pypdfium2-team/pypdfium2
PDFium includes third-party components; the native build collects their installed notices
and license files into THIRD_PARTY_LICENSES. Preserve that folder with portable distributions.

The bundled DejaVu font is accompanied by assets/DejaVu-LICENSE.txt.
PyInstaller's bootloader exception permits distributing the generated program; retain the
installed PyInstaller notices collected by the build. https://pyinstaller.org/en/stable/license.html
The build also collects installed package notices and Python/Tcl terms when available.
Review the produced Windows license bundle before publishing; this is not a legal audit.
