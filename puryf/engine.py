# SPDX-License-Identifier: MIT
"""
Complete Office + Image + PDF + Multi-Format Workstation v17
Local Windows desktop app.

Office conversion requires Microsoft Office desktop apps installed.
PDF tools use bundled/installed Python packages when built with build_windows_exe.bat.
OCR requires OCRmyPDF, Tesseract, and Ghostscript installed locally.

v17: safer output writes, collision protection, dependency checks, session recovery,
Arabic text layout, readable EML, AES-256 PDF encryption, and cancellable external commands.
CAD export remains unavailable; Office automation requires Windows and installed Office.
"""
from __future__ import annotations

import csv
from contextlib import nullcontext
import json
import importlib.util
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from email import policy
from email.parser import BytesParser
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from pathlib import Path

try:
    import pythoncom
    import win32com.client
except Exception:
    pythoncom = None
    win32com = None

try:
    from PIL import Image
except Exception:
    Image = None


try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.utils import ImageReader
except Exception:
    pdf_canvas = None
    ImageReader = None

try:
    import cairosvg
except Exception:
    cairosvg = None

try:
    import pillow_heif
except Exception:
    pillow_heif = None

if pillow_heif is not None:
    try:
        pillow_heif.register_heif_opener()
    except Exception:
        pass

try:
    import cv2
except Exception:
    cv2 = None

try:
    from pypdf import PdfReader, PdfWriter
except Exception:
    PdfReader = None
    PdfWriter = None

APP_NAME = "PuryF"
APP_VERSION = "1.0.0"
APP_DIR = Path(os.environ.get("PURYF_DATA_DIR", Path(sys.executable).parent / "Data" if getattr(sys,"frozen",False) and (Path(sys.executable).parent/"portable.marker").exists() else Path.home() / "Documents" / APP_NAME))
REPORTS_DIR = APP_DIR / "Reports"
STATE_PATH = APP_DIR / "session.json"
RAW_EXTS = {".raw", ".cr2", ".nef", ".arw"}


class ConversionCancelled(RuntimeError):
    pass


def office_available(name):
    if os.name != "nt" or pythoncom is None:
        return False
    import winreg
    progid = {"Project": "MSProject.Application"}.get(name, name + ".Application")
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + "\\CLSID"):
            return True
    except OSError:
        return False


def module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def parse_page_ranges(text, count):
    pages = []
    for part in text.replace(" ", "").split(","):
        if not part:
            raise ValueError("Enter page numbers or ranges, for example 1-3,5.")
        bounds = part.split("-")
        if len(bounds) > 2 or not all(x.isdigit() for x in bounds):
            raise ValueError(f"Invalid page range: {part}")
        a, b = int(bounds[0]), int(bounds[-1])
        if not 1 <= a <= b <= count:
            raise ValueError(f"Pages must be between 1 and {count}, in ascending range order.")
        pages.extend(range(a - 1, b))
    return pages
ZIP_MAX_FILES = 2_000
ZIP_MAX_MEMBER_BYTES = 500 * 1024 * 1024
ZIP_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024

OFFICE_EXTS = {
    ".doc": "Word", ".docx": "Word", ".docm": "Word", ".dot": "Word", ".dotx": "Word", ".rtf": "Word", ".odt": "Word",
    ".xls": "Excel", ".xlsx": "Excel", ".xlsm": "Excel", ".xlsb": "Excel", ".csv": "Excel", ".ods": "Excel",
    ".ppt": "PowerPoint", ".pptx": "PowerPoint", ".pptm": "PowerPoint", ".pps": "PowerPoint", ".ppsx": "PowerPoint", ".odp": "PowerPoint",
    ".vsd": "Visio", ".vsdx": "Visio", ".vss": "Visio", ".vst": "Visio",
    ".pub": "Publisher",
    ".mpp": "Project", ".mpt": "Project",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".heic", ".heif", ".svg", ".ico", ".psd", ".raw", ".cr2", ".nef", ".arw"}
PDF_EXTS = {".pdf"}
EMAIL_EXTS = {".msg", ".eml"}
ARCHIVE_EXTS = {".zip"}
TEXT_EXTS = {".txt", ".log", ".md", ".json", ".xml", ".csv"}
WEB_EXTS = {".html", ".htm", ".mht", ".mhtml", ".url"}
EBOOK_EXTS = {".epub", ".mobi", ".azw", ".azw3"}
CAD_EXTS = {".dwg", ".dxf"}
DIAGRAM_EXTS = {".drawio"}
CAL_CONTACT_EXTS = {".ics", ".vcf"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac"}
ALL_EXTS = set(OFFICE_EXTS) | IMAGE_EXTS | PDF_EXTS | EMAIL_EXTS | ARCHIVE_EXTS | TEXT_EXTS | WEB_EXTS | EBOOK_EXTS | CAD_EXTS | DIAGRAM_EXTS | CAL_CONTACT_EXTS | VIDEO_EXTS | AUDIO_EXTS
PLUGIN_CONVERTERS = {}

PPT_LAYOUTS = ["Full-page slides", "1 slide per page handout", "2 slides per page handout", "3 slides per page handout", "4 slides per page handout", "6 slides per page handout", "9 slides per page handout", "Speaker notes under each slide"]
PPT_DATE_MODES = ["Remove date", "Keep existing date", "Add today's date"]
PP_OUTPUT = {"Full-page slides": 1, "1 slide per page handout": 10, "2 slides per page handout": 2, "3 slides per page handout": 3, "4 slides per page handout": 8, "6 slides per page handout": 4, "9 slides per page handout": 9, "Speaker notes under each slide": 5}

@dataclass
class QueueItem:
    source: Path
    uid: str = dataclass_field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "Queued"
    output: str = ""
    message: str = ""
    seconds: float = 0.0

class ConverterEngine:
    def __init__(self, settings, log, update_item, progress, stop_event, reports_dir=None):
        self.commit_guard = None
        self.settings = settings
        self.reports_dir = Path(reports_dir) if reports_dir is not None else REPORTS_DIR
        self.report_path = None
        self.merged_output = None
        self.log = log
        self.update_item = update_item
        self.progress = progress
        self.stop_event = stop_event
        self.word = self.excel = self.ppt = self.visio = self.publisher = self.project = self.outlook = None
        self.com_ready = False
        self.generated = []
        self.merge_temp = None
        self.reserved_outputs = set()
        self.source_paths = set()
        self.merge_output_dir = None

    def requirements(self, src):
        ext = src.suffix.lower()
        errors = []
        if ext in PLUGIN_CONVERTERS:
            check=PLUGIN_CONVERTERS[ext].get("check")
            return list(check() if check else [])
        if ext in OFFICE_EXTS:
            app = OFFICE_EXTS[ext]
            if not office_available(app):
                errors.append(f"{app} desktop and pywin32 are required on Windows")
        elif ext == ".msg" and not office_available("Outlook"):
            errors.append("Outlook desktop and pywin32 are required")
        elif ext in CAD_EXTS:
            errors.append("CAD export is not implemented; export to PDF from your CAD application first")
        elif ext in RAW_EXTS and not module_available("rawpy"):
            errors.append("Camera RAW images require rawpy; generic .raw files may need camera metadata")
        elif ext in WEB_EXTS and not office_available("Word"):
            errors.append("HTML/MHT rendering requires Word desktop; source-code fallback has been removed")
        elif ext in EBOOK_EXTS and not shutil.which("ebook-convert"):
            errors.append("Install Calibre and add ebook-convert to PATH")
        elif ext in DIAGRAM_EXTS and not any(shutil.which(x) for x in ("drawio", "draw.io", "drawio.exe")):
            errors.append("Install draw.io desktop and add its command to PATH")
        elif ext in AUDIO_EXTS:
            if not shutil.which("whisper") or not shutil.which("ffmpeg"):
                errors.append("Audio requires local Whisper and FFmpeg commands; download a Whisper model before offline use")
        if ext in IMAGE_EXTS and Image is None:
            errors.append("Install Pillow")
        if ext == ".url":
            errors.append("Internet shortcuts are unsupported; save the web page as HTML first")
        if ext in IMAGE_EXTS and self.settings.get("image_paper", "Original size") != "Original size" and pdf_canvas is None:
            errors.append("Image paper sizes require reportlab")
        if ext == ".svg" and cairosvg is None:
            errors.append("Install CairoSVG and the Cairo runtime")
        if ext in {".heic", ".heif"} and pillow_heif is None:
            errors.append("Install pillow-heif")
        if ext in VIDEO_EXTS and (cv2 is None or Image is None):
            errors.append("Video requires opencv-python and Pillow")
        needs_text = ext in TEXT_EXTS | CAL_CONTACT_EXTS | {".eml"} | AUDIO_EXTS
        if (needs_text or ext in VIDEO_EXTS) and pdf_canvas is None:
            errors.append("Install reportlab")
        if (self.settings.get("merge_pdf") or self.settings.get("compress_pdf") or self.settings.get("password_pdf")) and PdfWriter is None:
            errors.append("Selected PDF tools require pypdf; no requested tool will be silently skipped")
        if self.settings.get("password_pdf") and not module_available("cryptography"):
            errors.append("AES-256 password protection requires cryptography")
        if self.settings.get("ocr_pdf"):
            missing = [x for x in ("ocrmypdf", "tesseract") if not shutil.which(x)]
            if missing:
                errors.append("OCR commands missing: " + ", ".join(missing))
        return errors

    def run_command(self, args, **kwargs):
        """Cancel only our own child process; never kill the user's Office apps."""
        timeout = int(self.settings.get("command_timeout", 900))
        started = time.monotonic()
        with tempfile.TemporaryFile(mode="w+b") as output:
            process = subprocess.Popen(args, stdout=output, stderr=subprocess.STDOUT, **kwargs)
            try:
                while process.poll() is None:
                    if self.stop_event.wait(0.1):
                        raise ConversionCancelled("Cancelled by user")
                    if time.monotonic() - started > timeout:
                        raise TimeoutError(f"External conversion exceeded {timeout} seconds")
                if process.returncode:
                    output.seek(max(0, output.tell() - 4000))
                    details = output.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"{Path(args[0]).name} failed ({process.returncode}): {details}")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

    def init_com(self):
        if pythoncom is None or win32com is None:
            raise RuntimeError("pywin32 is missing or this is not Windows. Build/run on Windows.")
        if not self.com_ready:
            pythoncom.CoInitialize()
            self.com_ready = True

    def quit_all(self):
        for name, app in [("Word", self.word), ("Excel", self.excel), ("PowerPoint", self.ppt), ("Visio", self.visio), ("Publisher", self.publisher), ("Project", self.project), ("Outlook", self.outlook)]:
            if app is not None and name != "Outlook":
                try: app.Quit()
                except Exception: self.log(f"Warning: could not close {name}")
        if self.com_ready:
            try: pythoncom.CoUninitialize()
            except Exception: pass
        self.word = self.excel = self.ppt = self.visio = self.publisher = self.project = self.outlook = None
        self.com_ready = False

    def app_word(self):
        self.init_com()
        if self.word is None:
            self.log("Opening Microsoft Word...")
            self.word = win32com.client.DispatchEx("Word.Application")
            self.word.Visible = False
            self.word.DisplayAlerts = 0
            self.word.AutomationSecurity = 3
        return self.word

    def app_excel(self):
        self.init_com()
        if self.excel is None:
            self.log("Opening Microsoft Excel...")
            self.excel = win32com.client.DispatchEx("Excel.Application")
            self.excel.Visible = False
            self.excel.DisplayAlerts = False
            self.excel.AutomationSecurity = 3
        return self.excel

    def app_ppt(self):
        self.init_com()
        if self.ppt is None:
            self.log("Opening Microsoft PowerPoint...")
            self.ppt = win32com.client.DispatchEx("PowerPoint.Application")
            self.ppt.AutomationSecurity = 3
        return self.ppt

    def app_visio(self):
        self.init_com()
        if self.visio is None:
            self.log("Opening Microsoft Visio...")
            self.visio = win32com.client.DispatchEx("Visio.Application")
            try: self.visio.Visible = False
            except Exception: pass
        return self.visio

    def app_publisher(self):
        self.init_com()
        if self.publisher is None:
            self.log("Opening Microsoft Publisher...")
            self.publisher = win32com.client.DispatchEx("Publisher.Application")
        return self.publisher

    def app_project(self):
        self.init_com()
        if self.project is None:
            self.log("Opening Microsoft Project...")
            self.project = win32com.client.DispatchEx("MSProject.Application")
            try: self.project.Visible = False
            except Exception: pass
        return self.project

    def app_outlook(self):
        self.init_com()
        if self.outlook is None:
            self.log("Opening Microsoft Outlook...")
            self.outlook = win32com.client.DispatchEx("Outlook.Application")
        return self.outlook

    def output_for(self, src: Path) -> Path:
        out_dir = Path(self.settings["output_folder"]) if self.settings["output_folder"] else src.parent
        if self.settings.get("preserve_folders"):
            relative=src.resolve().relative_to(Path(self.settings["source_root"]).resolve()).parent
            out_dir=out_dir/relative
        out_dir.mkdir(parents=True, exist_ok=True)
        pattern=self.settings.get("naming_pattern","{stem}")
        digest=""
        if "{hash8}" in pattern:
            from .state import content_hash
            digest=content_hash(src)[:8]
        name=pattern.format(stem=src.stem,ext=src.suffix.lstrip('.'),index=getattr(self,'input_index',1),
            date=datetime.now().strftime('%Y-%m-%d'),parent=src.parent.name,hash8=digest)
        from .state import safe_basename
        safe_basename(name+'.pdf')  # same safe basename rules as managed uploads
        out = out_dir / (name + ".pdf")
        same_path = os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(src))
        if src.suffix.lower() == ".pdf" and same_path:
            out = out_dir / (src.stem + "_processed.pdf")
        # Different inputs must never share an output or overwrite a batch source.
        key = lambda p: os.path.normcase(str(p.resolve())).casefold()
        if key(out) in self.reserved_outputs or key(out) in self.source_paths:
            base = out.stem + "_" + src.suffix.lstrip(".")
            out = out_dir / (base + ".pdf")
            n = 2
            while key(out) in self.reserved_outputs or key(out) in self.source_paths:
                out = out_dir / f"{base}_{n}.pdf"
                n += 1
        self.reserved_outputs.add(key(out))
        return out

    @staticmethod
    def read_pdf(path, password=""):
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(password):
            raise RuntimeError(f"Password required or incorrect for {Path(path).name}")
        return reader

    def convert(self, src: Path) -> Path:
        problems = self.requirements(src)
        if problems:
            raise RuntimeError("; ".join(problems))
        # Convert beside the destination, then commit only a complete result.
        final = self.output_for(src)
        if final.exists() and not self.settings["overwrite"]:
            raise FileExistsError(f"Output already exists: {final}")
        with tempfile.TemporaryDirectory(prefix=".puryf_", dir=final.parent) as folder:
            result = self._convert_to(src, Path(folder) / "result.pdf")
            if self.stop_event.is_set():
                raise ConversionCancelled("Cancelled before saving output")
            if not result.is_file() or result.stat().st_size == 0:
                raise RuntimeError("Converter did not produce a nonempty PDF")
            if PdfReader is not None:
                check = PdfReader(str(result))
                if check.is_encrypted:
                    if not check.decrypt(self.settings["pdf_password"]):
                        raise RuntimeError("Could not validate encrypted output")
                if not len(check.pages):
                    raise RuntimeError("Converter produced an empty PDF")
            with self.commit_guard(final) if self.commit_guard else nullcontext():
                if self.stop_event.is_set():
                    raise ConversionCancelled("Cancelled before saving output")
                if self.settings["overwrite"]:
                    os.replace(result, final)
                else:
                    # Hard-link creation is atomic and refuses an existing filename.
                    os.link(result, final)
            if self.settings["merge_pdf"]:
                if self.merge_output_dir is None:
                    self.merge_output_dir = final.parent
                if self.merge_temp is None:
                    self.merge_temp = tempfile.TemporaryDirectory(prefix="puryf_merge_")
                merge_copy = Path(self.merge_temp.name) / f"{uuid.uuid4().hex}.pdf"
                shutil.copy2(final, merge_copy)
                self.generated.append(merge_copy)
            else:
                self.generated.append(final)
            return final

    def _convert_to(self, src: Path, out: Path) -> Path:
        ext = src.suffix.lower()
        if ext in PLUGIN_CONVERTERS:
            PLUGIN_CONVERTERS[ext]['convert'](src,out,dict(self.settings),self.log,self.stop_event)
        elif ext in OFFICE_EXTS:
            app = OFFICE_EXTS[ext]
            if app == "Word": self.convert_word(src, out)
            elif app == "Excel": self.convert_excel(src, out)
            elif app == "PowerPoint": self.convert_ppt(src, out)
            elif app == "Visio": self.convert_visio(src, out)
            elif app == "Publisher": self.convert_publisher(src, out)
            elif app == "Project": self.convert_project(src, out)
        elif ext in IMAGE_EXTS:
            self.convert_image(src, out)
        elif ext in EMAIL_EXTS:
            self.convert_email(src, out)
        elif ext in TEXT_EXTS or ext in CAL_CONTACT_EXTS:
            self.convert_text_like(src, out)
        elif ext in WEB_EXTS:
            self.convert_web(src, out)
        elif ext in EBOOK_EXTS:
            self.convert_ebook(src, out)
        elif ext in CAD_EXTS:
            self.convert_cad(src, out)
        elif ext in DIAGRAM_EXTS:
            self.convert_drawio(src, out)
        elif ext in VIDEO_EXTS:
            self.convert_video_contact_sheet(src, out)
        elif ext in AUDIO_EXTS:
            self.convert_audio_transcript(src, out)
        elif ext == ".pdf":
            shutil.copy2(src, out)
        else:
            raise RuntimeError("Unsupported file type")
        if self.settings["compress_pdf"] and out.exists():
            out = self.compress_pdf(out)
        if self.settings["ocr_pdf"] and out.exists():
            out = self.ocr_pdf(out)
        if self.settings["password_pdf"] and self.settings["pdf_password"] and out.exists():
            out = self.password_pdf(out, self.settings["pdf_password"])
        return out

    def convert_word(self, src, out):
        doc = None
        try:
            self.log(f"Word: opening {src.name}")
            doc = self.app_word().Documents.Open(str(src), ReadOnly=True, AddToRecentFiles=False, ConfirmConversions=False)
            self.log(f"Word: exporting PDF {out.name}")
            doc.ExportAsFixedFormat(str(out), ExportFormat=17, OpenAfterExport=False)
        finally:
            if doc is not None: doc.Close(False)

    def convert_excel(self, src, out):
        wb = None
        try:
            self.log(f"Excel: opening {src.name}")
            wb = self.app_excel().Workbooks.Open(str(src), ReadOnly=True, UpdateLinks=0, AddToMru=False)
            if self.settings.get("excel_fit_width"):
                for sheet in wb.Worksheets:
                    sheet.PageSetup.Zoom = False
                    sheet.PageSetup.FitToPagesWide = 1
                    sheet.PageSetup.FitToPagesTall = False
            self.log(f"Excel: exporting PDF {out.name}")
            wb.ExportAsFixedFormat(0, str(out))
        finally:
            if wb is not None: wb.Close(False)

    def convert_ppt(self, src, out):
        ppt = self.app_ppt()
        deck = None
        layout = self.settings["ppt_layout"]
        output_type = PP_OUTPUT.get(layout, 1)
        try:
            self.log(f"PowerPoint: opening {src.name}")
            deck = ppt.Presentations.Open(str(src), ReadOnly=-1, Untitled=0, WithWindow=-1 if output_type != 1 else 0)
            try:
                deck.PrintOptions.OutputType = output_type
                deck.PrintOptions.HandoutOrder = 1
                deck.PrintOptions.PrintHiddenSlides = 0
            except Exception as e:
                self.log(f"PowerPoint option warning: {e}")
            self.set_ppt_date(deck)
            self.log(f"PowerPoint: exporting {layout}")
            if output_type == 1:
                deck.SaveAs(str(out), 32)
            else:
                # PrintRange is required by PowerPoint even when exporting all slides.
                # None passes the COM equivalent of Nothing; RangeType=1 means all.
                # Do not fall back to SaveAs here: it silently discards the layout.
                deck.ExportAsFixedFormat(str(out), 2, 2, 0, 1, output_type, 0, None, 1)
        finally:
            if deck is not None:
                try: deck.Close()
                except Exception: pass

    def set_ppt_date(self, deck):
        mode = self.settings["ppt_date_mode"]
        if mode == "Keep existing date":
            return
        if mode not in PPT_DATE_MODES:
            raise ValueError(f"Unknown PowerPoint date mode: {mode}")
        targets = []
        for name in ("HandoutMaster", "NotesMaster", "SlideMaster"):
            try: targets.append(getattr(deck, name))
            except Exception: pass
        try: targets.extend(design.SlideMaster for design in deck.Designs)
        except Exception: pass
        try: targets.extend(deck.Slides)
        except Exception: pass
        changed = 0
        errors = []
        for target in targets:
            try:
                date = target.HeadersFooters.DateAndTime
                if mode == "Remove date":
                    date.Visible = 0
                else:
                    date.UseFormat = 0
                    date.Text = datetime.now().strftime("%m/%d/%Y")
                    date.Visible = -1
                changed += 1
            except Exception as e:
                errors.append(str(e))
        if not changed or errors:
            raise RuntimeError(
                f"Could not apply PowerPoint date option '{mode}' to every slide/master "
                f"({changed} updated, {len(errors)} failed). "
                + (errors[0] if errors else "No editable date fields were found.")
            )

    def convert_visio(self, src, out):
        doc = None
        try:
            doc = self.app_visio().Documents.Open(str(src))
            self.log(f"Visio: exporting {out.name}")
            try: doc.ExportAsFixedFormat(1, str(out), 1, 0)
            except Exception: doc.Export(str(out))
        finally:
            if doc is not None:
                try: doc.Close()
                except Exception: pass

    def convert_publisher(self, src, out):
        doc = None
        try:
            doc = self.app_publisher().Open(str(src), ReadOnly=True)
            self.log(f"Publisher: exporting {out.name}")
            try: doc.SaveAs(str(out), 2)
            except Exception: doc.ExportAsFixedFormat(2, str(out))
        finally:
            if doc is not None:
                try: doc.Close()
                except Exception: pass

    def convert_project(self, src, out):
        app = self.app_project()
        self.log(f"Project: opening {src.name}")
        app.FileOpen(str(src), ReadOnly=True)
        self.log(f"Project: exporting {out.name}")
        try: app.DocumentExport(str(out))
        finally:
            try: app.FileClose(0)
            except Exception: pass

    def convert_image(self, src, out):
        if Image is None:
            raise RuntimeError("Pillow is missing. Rebuild using the included build script.")
        self.log(f"Image: converting {src.name}")
        if src.suffix.lower() in RAW_EXTS:
            import rawpy
            with rawpy.imread(str(src)) as raw:
                im = Image.fromarray(raw.postprocess())
                self.save_image_pdf([im], out)
            return
        if src.suffix.lower() == ".svg":
            if cairosvg is None:
                raise RuntimeError("SVG conversion needs CairoSVG and its Cairo runtime.")
            cairosvg.svg2pdf(url=str(src), write_to=str(out))
            return
        with Image.open(src) as im:
            frames = []
            try:
                for i in range(getattr(im, "n_frames", 1)):
                    im.seek(i)
                    from PIL import ImageOps
                    frame = ImageOps.exif_transpose(im).convert("RGBA")
                    background = Image.new("RGB", frame.size, "white")
                    background.paste(frame, mask=frame.getchannel("A"))
                    frames.append(background)
            except Exception:
                frames = [im.convert("RGB")]
            if not frames: raise RuntimeError("No image frames found")
            self.save_image_pdf(frames, out)

    def save_image_pdf(self, frames, out):
        original_sizes=[frame.size for frame in frames]
        edge=self.settings.get('image_max_edge',0)
        if edge:
            for frame in frames:frame.thumbnail((edge,edge),Image.Resampling.LANCZOS)
        paper = self.settings.get("image_paper", "Original size")
        if paper == "Original size" and edge:
            c=pdf_canvas.Canvas(str(out))
            for frame,size in zip(frames,original_sizes):
                c.setPageSize(size);c.drawImage(ImageReader(frame),0,0,width=size[0],height=size[1]);c.showPage()
            c.save();return
        if paper == "Original size":
            frames[0].save(str(out), "PDF", save_all=True, append_images=frames[1:])
            return
        if pdf_canvas is None:
            raise RuntimeError("Paper size controls require reportlab")
        from reportlab.lib.pagesizes import A4
        size = A4 if paper == "A4" else letter
        c = pdf_canvas.Canvas(str(out), pagesize=size)
        for frame in frames:
            if self.stop_event.is_set():
                raise ConversionCancelled("Image conversion cancelled")
            c.drawImage(ImageReader(frame), 24, 24, width=size[0]-48, height=size[1]-48,
                        preserveAspectRatio=True, anchor="c")
            c.showPage()
        c.save()

    def compress_pdf(self, src: Path) -> Path:
        if PdfReader is None:
            raise RuntimeError("Compression requires pypdf")
        self.log(f"Compressing PDF: {src.name}")
        reader = PdfReader(str(src))
        writer = PdfWriter()
        for page in reader.pages:
            try: page.compress_content_streams()
            except Exception: pass
            writer.add_page(page)
        try: writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        except Exception: pass
        self._replace_pdf_safely(src, writer)
        return src

    def password_pdf(self, src: Path, password: str) -> Path:
        if PdfReader is None:
            raise RuntimeError("Password protection requires pypdf")
        self.log(f"Applying PDF password: {src.name}")
        reader = PdfReader(str(src))
        writer = PdfWriter()
        for page in reader.pages: writer.add_page(page)
        writer.encrypt(password, algorithm="AES-256")
        self._replace_pdf_safely(src, writer)
        return src

    @staticmethod
    def _replace_pdf_safely(src: Path, writer: PdfWriter):
        fd, tmp_name = tempfile.mkstemp(prefix=f".{src.stem}_", suffix=".pdf", dir=str(src.parent))
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            with tmp.open("wb") as f:
                writer.write(f)
            os.replace(tmp, src)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def ocr_pdf(self, src: Path) -> Path:
        ocrmypdf = shutil.which("ocrmypdf")
        if not ocrmypdf:
            raise RuntimeError("OCR requires the local OCRmyPDF command (which uses Tesseract).")
        with tempfile.TemporaryDirectory(prefix=f".{src.stem}_ocr_", dir=str(src.parent)) as td:
            tmp = Path(td) / "ocr.pdf"
            self.log(f"OCR: processing {src.name}")
            self.run_command([ocrmypdf, "--skip-text", "--quiet", "-l", self.settings.get("ocr_language", "eng"), str(src), str(tmp)])
            os.replace(tmp, src)
        return src


    def convert_email(self, src, out):
        ext = src.suffix.lower()
        if ext == ".msg":
            mail = None
            try:
                outlook = self.app_outlook()
                mail = outlook.Session.OpenSharedItem(str(src))
                self.log(f"Outlook: exporting {src.name}")
                with tempfile.TemporaryDirectory(prefix="puryf_mail_") as td:
                    tmp_html = Path(td) / (src.stem + ".html")
                    mail.SaveAs(str(tmp_html), 5)  # olHTML
                    self.convert_web(tmp_html, out)
                return
            finally:
                try:
                    if mail is not None: mail.Close(0)
                except Exception: pass
        mail = BytesParser(policy=policy.default).parsebytes(src.read_bytes())
        headers = "\n".join(f"{key}: {mail.get(key, '')}" for key in ("From", "To", "Date", "Subject"))
        body = mail.get_body(preferencelist=("plain", "html"))
        content = body.get_content() if body else "(No message body)"
        if body and body.get_content_type() == "text/html":
            from html.parser import HTMLParser
            class PlainHTML(HTMLParser):
                def __init__(self):
                    super().__init__(); self.parts = []; self.hidden = 0
                def handle_starttag(self, tag, attrs):
                    if tag in ("script", "style"): self.hidden += 1
                    if tag in ("p", "div", "br", "li"): self.parts.append("\n")
                def handle_endtag(self, tag):
                    if tag in ("script", "style"): self.hidden = max(0, self.hidden - 1)
                def handle_data(self, data):
                    if not self.hidden: self.parts.append(data)
            parser = PlainHTML(); parser.feed(content); content = "".join(parser.parts)
        attachments = [str(p.get_filename()) for p in mail.iter_attachments() if p.get_filename()]
        text = headers + "\n\n" + content
        if attachments:
            text += "\n\nAttachments (not embedded):\n" + "\n".join(attachments)
        with tempfile.TemporaryDirectory() as folder:
            txt = Path(folder) / "message.txt"; txt.write_text(text, encoding="utf-8")
            self.convert_text_like(txt, out)

    def convert_text_like(self, src, out):
        if pdf_canvas is None:
            raise RuntimeError("reportlab is missing. Rebuild using the included build script.")
        self.log(f"Text/markup: creating PDF for {src.name}")
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = src.read_text(errors="replace")
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import re
        arabic = bool(re.search(r"[\u0600-\u06ff\u0750-\u077f]", text))
        candidates = [Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent.parent))/"assets/DejaVuSans.ttf", Path(__file__).resolve().parent/"assets/DejaVuSans.ttf",Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
                      Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
        font = next((p for p in candidates if p.is_file()), None)
        font_name = "Courier"
        if font:
            font_name = "PuryFUnicode"
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, str(font)))
        if arabic:
            if not font or not module_available("arabic_reshaper") or not module_available("bidi"):
                raise RuntimeError("Arabic text requires an Arabic font, arabic-reshaper, and python-bidi")
            import arabic_reshaper
            from bidi.algorithm import get_display
        def display(line):
            return get_display(arabic_reshaper.reshape(line)) if arabic else line
        c = pdf_canvas.Canvas(str(out), pagesize=letter)
        width, height = letter
        margin = 40
        y = height - margin
        c.setFont(font_name, 10)
        for raw_line in text.splitlines() or [""]:
            line = raw_line.replace("\t", "    ")
            while line or raw_line == "":
                if self.stop_event.is_set():
                    raise ConversionCancelled("Text conversion cancelled")
                # Bound measurements so a long unbroken line cannot freeze wrapping.
                low, high = 1, min(len(line), 2048)
                n = high
                while low <= high:
                    mid = (low + high) // 2
                    if pdfmetrics.stringWidth(display(line[:mid]), font_name, 10) <= width - 2 * margin:
                        n = mid; low = mid + 1
                    else:
                        high = mid - 1
                if high == 0: n = 1
                if n < len(line) and " " in line[:n]:
                    n = line.rfind(" ", 0, n) + 1
                rendered = display(line[:n])
                if y < margin:
                    c.showPage(); c.setFont(font_name, 10); y = height - margin
                if arabic:
                    c.drawRightString(width-margin, y, rendered)
                else:
                    c.drawString(margin, y, rendered)
                y -= 13
                line = line[n:]
                if not line: break
        c.save()

    def convert_web(self, src, out):
        if src.suffix.lower() == ".url":
            raise RuntimeError("Internet shortcuts are not local web pages. Save the page as HTML first.")
        self.convert_word(src, out)

    def convert_ebook(self, src, out):
        exe = shutil.which("ebook-convert")
        if not exe:
            raise RuntimeError("Ebook conversion needs Calibre installed locally and ebook-convert in PATH.")
        self.log(f"Calibre: converting ebook {src.name}")
        self.run_command([exe, str(src), str(out)])

    def convert_cad(self, src, out):
        # AutoCAD PDF export varies by installation/profile. This placeholder gives a clear local requirement.
        raise RuntimeError("CAD conversion needs AutoCAD/DWG TrueView local CLI automation configured. Install Autodesk tools or add a DWG-to-PDF command path.")

    def convert_drawio(self, src, out):
        drawio = shutil.which("drawio") or shutil.which("draw.io") or shutil.which("drawio.exe")
        if not drawio:
            raise RuntimeError("draw.io conversion needs the draw.io desktop app CLI installed locally and available in PATH.")
        self.log(f"draw.io: exporting {src.name}")
        self.run_command([drawio, "--export", "--format", "pdf", "--output", str(out), str(src)])

    def convert_video_contact_sheet(self, src, out):
        if cv2 is None or Image is None or pdf_canvas is None or ImageReader is None:
            raise RuntimeError("Video contact sheets need opencv-python, Pillow, and reportlab. Rebuild using build script.")
        self.log(f"Video: creating contact-sheet PDF for {src.name}")
        cap = cv2.VideoCapture(str(src))
        if not cap.isOpened():
            raise RuntimeError("Could not open video.")
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 1)
        duration = frames / fps if frames else 0
        sample_count = 12
        thumbs = []
        for i in range(sample_count):
            pos = int((frames - 1) * i / max(sample_count - 1, 1)) if frames else 0
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, frame = cap.read()
            if ok:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                im = Image.fromarray(frame)
                im.thumbnail((220, 125))
                thumbs.append((im.copy(), pos / fps if fps else 0))
        cap.release()
        c = pdf_canvas.Canvas(str(out), pagesize=letter)
        w, h = letter
        c.setFont("Helvetica-Bold", 14); c.drawString(40, h-40, f"Video contact sheet: {src.name}")
        c.setFont("Helvetica", 10); c.drawString(40, h-58, f"Duration: {duration:.1f}s | Frames sampled: {len(thumbs)}")
        x0, y0 = 40, h-210
        x, y = x0, y0
        for n, (im, sec) in enumerate(thumbs, 1):
            c.drawImage(ImageReader(im), x, y, width=160, height=90, preserveAspectRatio=True)
            c.drawString(x, y-12, f"{sec:.1f}s")
            x += 180
            if n % 3 == 0:
                x = x0; y -= 125
                if y < 80:
                    c.showPage(); y = h-150
        c.save()

    def convert_audio_transcript(self, src, out):
        whisper = shutil.which("whisper")
        if not whisper:
            raise RuntimeError("Audio transcription requires the local Whisper CLI in PATH.")
        with tempfile.TemporaryDirectory() as td:
            self.log(f"Audio: transcribing locally with Whisper {src.name}")
            self.run_command([whisper, str(src), "--output_dir", td, "--output_format", "txt"])
            txt = Path(td) / (src.stem + ".txt")
            if not txt.exists():
                raise RuntimeError("Whisper finished but transcript file was not found.")
            self.convert_text_like(txt, out)

    def run_queue(self, indexed_items: list[tuple[int, QueueItem]]):
        total = len(indexed_items)
        ok = fail = skip = 0
        self.generated = []
        self.reserved_outputs.clear()
        self.source_paths = {os.path.normcase(str(item.source.resolve())).casefold() for _, item in indexed_items}
        try:
            for idx, (_, item) in enumerate(indexed_items, 1):
                if self.stop_event.is_set(): break
                src = item.source
                t0 = time.time()
                self._set_item(item, "Running", "", "")
                self.log(f"START {idx}/{total}: {src}")
                try:
                    out = self.convert(src)
                    secs = round(time.time() - t0, 2)
                    self._set_item(item, "Success", str(out), f"{secs}s", secs)
                    self.log(f"SUCCESS {idx}/{total}: {out}")
                    ok += 1
                except ConversionCancelled as e:
                    self._set_item(item, "Cancelled", "", str(e))
                    self.log(f"CANCELLED: {src.name}")
                    break
                except FileExistsError as e:
                    secs = round(time.time() - t0, 2)
                    self._set_item(item, "Skipped", "", str(e), secs)
                    self.log(f"SKIPPED {idx}/{total}: {src.name} - {e}")
                    skip += 1
                except Exception as e:
                    secs = round(time.time() - t0, 2)
                    self._set_item(item, "Failed", "", str(e), secs)
                    self.log(f"FAILED {idx}/{total}: {src.name} - {e}")
                    fail += 1
                self.progress(idx, total, src.name)
            try:
                if self.settings["merge_pdf"] and self.generated and not self.stop_event.is_set():
                    self.merge_generated()
            except Exception as e:
                fail += 1
                self.log(f"MERGE FAILED: {e}")
            try:
                self.write_report([item for _, item in indexed_items])
            except Exception as e:
                self.log(f"REPORT FAILED: {e}")
            self.log(f"{'STOPPED' if self.stop_event.is_set() else 'DONE'}. Success: {ok}, Skipped: {skip}, Failed: {fail}")
        finally:
            try:
                self.quit_all()
            finally:
                try:
                    if self.merge_temp is not None:
                        self.merge_temp.cleanup()
                        self.merge_temp = None
                finally:
                    self.update_item(None, "batch_done", "", "")

    def _set_item(self, item, status, output, message, seconds=0.0):
        item.status = status
        item.output = output
        item.message = message
        item.seconds = seconds
        self.update_item(item.uid, status, output, message)

    def merge_generated(self):
        if PdfWriter is None:
            raise RuntimeError("Merge requires pypdf")
        out_dir = Path(self.settings["output_folder"]) if self.settings["output_folder"] else self.merge_output_dir or Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        out = self._unique_timestamped_path(out_dir, "Merged", ".pdf")
        writer = PdfWriter()
        self.log(f"Merging {len(self.generated)} PDFs...")
        for p in self.generated:
            if self.stop_event.is_set():
                raise ConversionCancelled("PDF merge cancelled")
            if p.suffix.lower() == ".pdf" and p.exists():
                reader = PdfReader(str(p))
                if reader.is_encrypted and not reader.decrypt(self.settings.get("pdf_password", "")):
                    raise RuntimeError(f"Cannot unlock merge input: {p.name}")
                for page in reader.pages:
                    if self.stop_event.is_set():
                        raise ConversionCancelled("PDF merge cancelled")
                    writer.add_page(page)
        if self.settings["password_pdf"] and self.settings["pdf_password"]:
            writer.encrypt(self.settings["pdf_password"], algorithm="AES-256")
        with self.commit_guard(out) if self.commit_guard else nullcontext():
            if self.stop_event.is_set():
                raise ConversionCancelled("PDF merge cancelled before saving")
            self._replace_pdf_safely(out, writer)
        self.merged_output = out
        self.log(f"Merged PDF saved: {out}")
        return out

    def write_report(self, items):
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report = self._unique_timestamped_path(self.reports_dir, "ConversionReport", ".csv")
        with open(report, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["File Name", "File Location", "Status", "Output", "Message"])
            for it in items: w.writerow([it.source.name, str(it.source.parent), it.status, it.output, it.message])
        self.report_path = report
        self.log(f"Report saved: {report}")
        return report

    @staticmethod
    def _unique_timestamped_path(folder: Path, prefix: str, suffix: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return folder / f"{prefix}_{stamp}_{uuid.uuid4().hex[:6]}{suffix}"

