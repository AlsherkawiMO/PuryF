# SPDX-License-Identifier: MIT
"""Tk desktop adapter. Conversion logic lives in puryf.engine and puryf.jobs."""
from __future__ import annotations
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None
from .engine import (
    APP_NAME, APP_VERSION, APP_DIR, REPORTS_DIR, STATE_PATH, ALL_EXTS,
    PPT_LAYOUTS, PPT_DATE_MODES, ZIP_MAX_FILES, ZIP_MAX_MEMBER_BYTES,
    ZIP_MAX_TOTAL_BYTES, QueueItem, ConverterEngine, Image, PdfReader,
    PdfWriter, module_available, office_available, parse_page_ranges,
)
from .jobs import ConversionOptions, get_default_service
from . import pdf_tools
from . import INSTAGRAM_URL, PUBLISHER

from .workbench import WorkbenchMixin

class App(WorkbenchMixin, (TkinterDnD.Tk if TkinterDnD is not None else tk.Tk)):
    FOLDER_SCAN_LIMIT = 10000

    def __init__(self):
        super().__init__()
        self.title(APP_NAME + " v1 — Local PDF toolkit")
        self.geometry("1200x880")
        self.minsize(900, 620)
        self.q = queue.Queue()
        self.service = get_default_service(reports_dir=REPORTS_DIR)
        self.job_events = self.service.subscribe()
        self.active_job_id = None
        self._manual_jobs = {}
        self.items: list[QueueItem] = []
        self.worker = None
        self.stop_event = threading.Event()
        self.output_folder = tk.StringVar()
        self.overwrite = tk.BooleanVar(value=False)
        self.merge_pdf = tk.BooleanVar(value=False)
        self.compress_pdf = tk.BooleanVar(value=False)
        self.password_pdf = tk.BooleanVar(value=False)
        self.ocr_pdf = tk.BooleanVar(value=False)
        self.pdf_password = tk.StringVar()
        self.ppt_layout = tk.StringVar(value="Full-page slides")
        self.ppt_date_mode = tk.StringVar(value="Remove date")
        self.status = tk.StringVar(value="Ready")
        self.progress_text = tk.StringVar(value="0 / 0")
        self.show_password = tk.BooleanVar(value=False)
        self.log_visible = tk.BooleanVar(value=False)
        self.image_paper = tk.StringVar(value="Original size")
        self.excel_fit_width = tk.BooleanVar(value=False)
        self.ocr_language = tk.StringVar(value="eng")
        self._closing = False
        self.mutation_widgets = []
        self.run_locked_widgets = []
        self._tooltip = None
        self._tooltip_after = None
        self.theme = tk.StringVar(value="dark")
        self.advanced_visible = tk.BooleanVar(value=False)
        self._images = []
        self._page_canvases = {}
        self._themed_texts = []
        self._themed_canvases = []
        self.init_v1(APP_DIR)
        self.build_ui()
        self.install_scrolling()
        self.load_session()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_after = self.after(100, self.process_queue)
        self._bind_action(self, "<Control-d>", self.duplicate_selected)
        self._bind_action(self, "<Control-i>", self.invert_selection)
        self._bind_action(self, "<Control-l>", self.clear_log)
        self._bind_action(self, "<Control-s>", self.save_log)

    def apply_theme(self):
        dark = self.theme.get() == "dark"
        self.colors = c = {
            "bg": "#15171B" if dark else "#F7F8FA",
            "panel": "#202329" if dark else "#FFFFFF",
            "text": "#F5F6F7" if dark else "#202124",
            "sub": "#A6ADB8" if dark else "#616873",
            "line": "#383E47" if dark else "#DFE3E8",
            "soft": "#392719" if dark else "#FFF0E5",
            "orange": "#FF6B00",
        }
        style = ttk.Style(self)
        style.theme_use("clam")
        from tkinter import font as tkfont
        families = set(tkfont.families(self))
        family = next((f for f in ("Inter", "Segoe UI", "DejaVu Sans") if f in families), "TkDefaultFont")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(family=family, size=10)
        style.configure(".", background=c["bg"], foreground=c["text"], bordercolor=c["line"], font=(family, 10))
        style.configure("TFrame", background=c["bg"])
        style.configure("Card.TFrame", background=c["panel"])
        style.configure("TLabel", background=c["bg"], foreground=c["text"])
        style.configure("Card.TLabel", background=c["panel"])
        style.configure("Muted.TLabel", foreground=c["sub"])
        style.configure("CardMuted.TLabel", background=c["panel"], foreground=c["sub"])
        style.configure("Title.TLabel", font=(family, 20, "bold"))
        style.configure("Section.TLabel", background=c["panel"], font=(family, 12, "bold"))
        style.configure("TButton", background=c["panel"], padding=(12, 8), borderwidth=1, relief="flat")
        style.map("TButton", background=[("disabled", c["bg"]), ("active", c["soft"])], foreground=[("disabled", c["sub"])])
        style.configure("Accent.TButton", background=c["orange"], foreground="#202124", font=(family, 10, "bold"))
        style.map("Accent.TButton", background=[("disabled", c["line"]), ("active", "#E85E00")], foreground=[("disabled", c["sub"]), ("!disabled", "#202124")])
        style.configure("Nav.TButton", anchor="w", padding=(14, 11), background=c["panel"], borderwidth=0)
        style.configure("Active.Nav.TButton", background=c["soft"], anchor="w", padding=(14, 11), borderwidth=0)
        style.map("Active.Nav.TButton", background=[("active", c["soft"]), ("!active", c["soft"])])
        style.configure("TCheckbutton", background=c["panel"], padding=(0, 4))
        style.map("TCheckbutton", background=[("active", c["panel"])], foreground=[("disabled", c["sub"])])
        for widget in ("TEntry", "TCombobox"):
            style.configure(widget, fieldbackground=c["bg"], foreground=c["text"], insertcolor=c["text"], padding=6, arrowcolor=c["text"])
            style.map(widget, fieldbackground=[("readonly", c["bg"]), ("disabled", c["panel"])], foreground=[("readonly", c["text"]), ("disabled", c["sub"])], selectbackground=[("readonly", c["soft"])], selectforeground=[("readonly", c["text"])])
        style.configure("Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["text"], rowheight=34, borderwidth=0)
        style.configure("Treeview.Heading", background=c["bg"], foreground=c["sub"], padding=(8, 9), relief="flat")
        style.map("Treeview", background=[("selected", c["soft"])], foreground=[("selected", c["text"])])
        style.configure("Horizontal.TProgressbar", background=c["orange"], troughcolor=c["line"], borderwidth=0, lightcolor=c["orange"], darkcolor=c["orange"])
        self.configure(background=c["bg"])
        self.option_add("*TCombobox*Listbox.background", c["panel"])
        self.option_add("*TCombobox*Listbox.foreground", c["text"])
        for canvas in self._themed_canvases:
            canvas.configure(background=c["bg"])
        for box in self._themed_texts:
            box.configure(background=c["bg"], foreground=c["text"], insertbackground=c["text"], selectbackground=c["orange"], selectforeground="#202124")
        if hasattr(self, "tree"):
            for status, color in (("Queued", c["sub"]), ("Pending", c["orange"]), ("Running", "#7DB3FF" if dark else "#175CD3"), ("Success", "#80DBA5" if dark else "#067647"), ("Failed", "#FFA299" if dark else "#B42318"), ("Skipped", "#F9C369" if dark else "#995C00"), ("Cancelled", "#F9C369" if dark else "#995C00")):
                self.tree.tag_configure(status, foreground=color)
        if hasattr(self, "logo_label"):
            self.logo_label.configure(image=self.logo_dark if dark else self.logo_light)

    def toggle_theme(self):
        self.theme.set("dark" if self.theme.get() == "light" else "light")
        self.apply_theme()
        self.theme_button.configure(text="Light theme" if self.theme.get() == "dark" else "Dark theme")
        self.localize_window(self)

    @staticmethod
    def asset_path(filename):
        # Also works when bundled with PyInstaller --add-data assets;assets.
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        candidate=root / "assets" / filename
        return candidate if candidate.exists() else Path(__file__).resolve().parent/"assets"/filename

    def load_brand_image(self, filename, width, height):
        path = self.asset_path(filename)
        try:
            try:
                from PIL import ImageTk
            except ImportError:
                ImageTk = None
            if Image is not None and ImageTk is not None:
                with Image.open(path) as source:
                    im = source.convert("RGBA")
                    im.thumbnail((width, height), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(im, master=self)
            else:
                photo = tk.PhotoImage(file=str(path), master=self)
                factor = max(1, (photo.width() + width - 1) // width, (photo.height() + height - 1) // height)
                photo = photo.subsample(factor)
            self._images.append(photo)
            return photo
        except (OSError, tk.TclError):
            return ""

    def make_page(self, name):
        page = ttk.Frame(self.page_host)
        page.grid(row=0, column=0, sticky="nsew")
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        canvas = tk.Canvas(page, highlightthickness=0, borderwidth=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        body = ttk.Frame(canvas, padding=(22, 18))
        body.columnconfigure(0, weight=1)
        window = canvas.create_window(0, 0, window=body, anchor="nw")
        body.bind("<Configure>", lambda e, cv=canvas: cv.configure(scrollregion=cv.bbox("all")))
        canvas.bind("<Configure>", lambda e, cv=canvas, win=window: cv.itemconfigure(win, width=e.width))
        self.pages[name] = page
        self._page_canvases[name] = canvas
        self._themed_canvases.append(canvas)
        self._scrollbar_targets[scrollbar] = canvas
        return body

    def show_page(self, name):
        self.pages[name].tkraise()
        self.body_canvas = self._page_canvases[name]
        self.current_page = name
        for key, button in self.nav_buttons.items():
            button.configure(style="Active.Nav.TButton" if key == name else "Nav.TButton")
        if name == "dependencies":
            self.refresh_dependencies()

    def card(self, parent, title, row):
        box = ttk.Frame(parent, padding=16, style="Card.TFrame")
        box.grid(row=row, column=0, sticky="nsew", pady=(0, 14))
        box.columnconfigure(0, weight=1)
        ttk.Label(box, text=title, style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        return box

    def build_ui(self):
        self.apply_theme()
        self.rowconfigure(1, weight=1)
        self.columnconfigure(1, weight=1)
        self.pages = {}
        self.nav_buttons = {}
        self._scrollbar_targets = {}
        header = ttk.Frame(self, padding=(20, 12), style="Card.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(1, weight=1)
        self.logo_light = self.load_brand_image("PuryF-logo-light.png", 168, 56)
        self.logo_dark = self.load_brand_image("PuryF-logo-dark.png", 168, 56)
        self.logo_label = ttk.Label(header, image=self.logo_dark, style="Card.TLabel")
        if not self.logo_light:
            self.logo_label.configure(text="PuryF", font=("Segoe UI", 24, "bold"))
        self.logo_label.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 22))
        ttk.Label(header, text="Your files. Simply PDF.", style="Card.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="Local PDF toolkit", style="CardMuted.TLabel").grid(row=1, column=1, sticky="w")
        self.about_button = ttk.Button(header, text="About", command=self.show_about)
        self.about_button.grid(row=0, column=2, rowspan=2, padx=5)
        self.theme_button = ttk.Button(header, text="Light theme", command=self.toggle_theme)
        self.theme_button.grid(row=0, column=3, rowspan=2, padx=5)
        icon = self.load_brand_image("PuryF-icon-64.png", 64, 64)
        if icon:
            self.iconphoto(True, icon)
        if os.name == "nt" and self.asset_path("PuryF.ico").is_file():
            try:
                self.iconbitmap(str(self.asset_path("PuryF.ico")))
            except tk.TclError:
                pass

        nav = ttk.Frame(self, padding=(10, 18), style="Card.TFrame")
        nav.grid(row=1, column=0, sticky="ns")
        for index, (key, label) in enumerate((("convert", "Convert"), ("tools", "PDF tools"), ("dependencies", "Dependencies"))):
            button = ttk.Button(nav, text=label, width=15, style="Nav.TButton", command=lambda n=key: self.show_page(n))
            button.grid(row=index, column=0, sticky="ew", pady=3)
            self.nav_buttons[key] = button
        ttk.Button(nav, text="Shortcuts", width=15, style="Nav.TButton", command=self.show_shortcuts).grid(row=4, column=0, sticky="ew", pady=(24, 0))
        self.page_host = ttk.Frame(self)
        self.page_host.grid(row=1, column=1, sticky="nsew")
        self.page_host.rowconfigure(0, weight=1)
        self.page_host.columnconfigure(0, weight=1)
        body = self.convert_body = self.make_page("convert")
        ttk.Label(body, text="Make room for simpler files.", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="Convert documents and media to PDF, locally on your computer.", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 18))
        src = self.card(body, "File queue", 2)
        btns = ttk.Frame(src, style="Card.TFrame")
        btns.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for text, command in (("Add files", self.add_files), ("Add folder", self.add_folder), ("Retry failed", self.retry_failed)):
            button = ttk.Button(btns, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self.mutation_widgets.append(button)
        more = ttk.Menubutton(btns, text="Queue actions")
        more_menu = tk.Menu(more, tearoff=0)
        actions = (("Select all", lambda: self.select_all_queue()), ("Invert selection", self.invert_selection),
                   ("Remove selected", self.remove_selected), ("Duplicate selected", self.duplicate_selected),
                   ("Retry selected", self.retry_selected), ("Move up", self.move_selected_up),
                   ("Move down", self.move_selected_down), ("Move to top", self.move_selected_top),
                   ("Move to bottom", self.move_selected_bottom), ("Remove completed", self.remove_completed),
                   ("Remove failed", self.remove_failed), ("Clear queue", self.clear_queue))
        for text, action in actions:
            more_menu.add_command(label=text, command=action)
        more.configure(menu=more_menu)
        more.pack(side="left")
        self.mutation_widgets.append(more)
        self.queue_count = tk.StringVar(value="0 files")
        ttk.Label(src, textvariable=self.queue_count, style="CardMuted.TLabel").grid(row=0, column=0, sticky="e")
        self.drop_label = ttk.Label(src, text="Drop files, folders or ZIP archives here", anchor="center", style="CardMuted.TLabel", padding=10, wraplength=580)
        self.drop_label.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        queue_frame = ttk.Frame(src, style="Card.TFrame")
        queue_frame.grid(row=3, column=0, sticky="nsew")
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.rowconfigure(0, weight=1)
        cols = ("name", "location", "status", "output", "message")
        self.tree = ttk.Treeview(queue_frame, columns=cols, show="headings", height=5, selectmode="extended")
        for name, heading, width in (("name", "File name", 220), ("location", "File location", 180), ("status", "Status", 95), ("output", "Output", 170), ("message", "Details", 240)):
            self.tree.heading(name, text=heading)
            self.tree.column(name, width=width, minwidth=75, stretch=False, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        ts_y = ttk.Scrollbar(queue_frame, orient="vertical", command=self.tree.yview)
        ts_y.grid(row=0, column=1, sticky="ns")
        ts_x = ttk.Scrollbar(queue_frame, orient="horizontal", command=self.tree.xview)
        ts_x.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=ts_y.set, xscrollcommand=ts_x.set)
        self.empty_label = ttk.Label(self.tree, text="Your queue is empty. Add files to get started.", style="CardMuted.TLabel", anchor="center")
        self.bind_queue_actions()
        self.enable_external_drop()
        self._update_empty_state()
        settings = self.card(body, "Conversion settings", 3)
        path = ttk.Frame(settings, style="Card.TFrame")
        path.grid(row=1, column=0, sticky="ew")
        path.columnconfigure(0, weight=1)
        ttk.Label(path, text="Output folder (leave blank to save beside each source)", style="CardMuted.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Entry(path, textvariable=self.output_folder).grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(6, 10))
        ttk.Button(path, text="Browse", command=self.pick_output).grid(row=1, column=1, padx=(0, 8))
        ttk.Button(path, text="Open folder", command=self.open_output).grid(row=1, column=2)
        toggles = ttk.Frame(settings, style="Card.TFrame")
        toggles.grid(row=2, column=0, sticky="ew")
        for col in (0, 1):
            toggles.columnconfigure(col, weight=1)
        for text, var, row, col in (("Merge converted PDFs", self.merge_pdf, 0, 0), ("Lossless PDF compression", self.compress_pdf, 1, 0), ("Overwrite existing PDFs", self.overwrite, 1, 1)):
            ttk.Checkbutton(toggles, text=text, variable=var).grid(row=row, column=col, sticky="w")
        self.ocr_control = ttk.Checkbutton(toggles, text="OCR PDFs and images", variable=self.ocr_pdf)
        self.ocr_control.grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(settings, text="Advanced settings — images, Office, OCR and protection", variable=self.advanced_visible, command=self.toggle_advanced).grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.advanced = ttk.Frame(settings, style="Card.TFrame")
        self.advanced.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.advanced.columnconfigure(0, weight=1, uniform="advanced")
        self.advanced.columnconfigure(1, weight=1, uniform="advanced")
        left = ttk.Frame(self.advanced, style="Card.TFrame", padding=(0, 0, 14, 0))
        right = ttk.Frame(self.advanced, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew")
        for panel in (left, right):
            panel.columnconfigure(0, weight=1)
        ttk.Label(left, text="Image paper size", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Combobox(left, values=["Original size", "A4", "Letter"], textvariable=self.image_paper, state="readonly").grid(row=1, column=0, sticky="ew", pady=(4, 10))
        ttk.Checkbutton(left, text="Excel: fit columns to one page", variable=self.excel_fit_width).grid(row=2, column=0, sticky="w")
        ttk.Label(left, text="OCR languages", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(left, textvariable=self.ocr_language).grid(row=4, column=0, sticky="ew", pady=4)
        ttk.Label(left, text="Example: eng+ara. Install matching Tesseract language packs.", style="CardMuted.TLabel", wraplength=260).grid(row=5, column=0, sticky="w")
        ttk.Label(right, text="PowerPoint export", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Combobox(right, values=PPT_LAYOUTS, textvariable=self.ppt_layout, state="readonly").grid(row=1, column=0, sticky="ew", pady=(4, 10))
        ttk.Label(right, text="PowerPoint date", style="Card.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Combobox(right, values=PPT_DATE_MODES, textvariable=self.ppt_date_mode, state="readonly").grid(row=3, column=0, sticky="ew", pady=4)
        ttk.Checkbutton(right, text="Password protect PDFs", variable=self.password_pdf, command=self.update_password_controls).grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.password_entry = ttk.Entry(right, textvariable=self.pdf_password, show="*")
        self.password_entry.grid(row=5, column=0, sticky="ew", pady=4)
        ttk.Checkbutton(right, text="Show password", variable=self.show_password, command=self.update_password_controls).grid(row=6, column=0, sticky="w")
        self.advanced.grid_remove()
        self.update_password_controls()
        self.run_locked_widgets = [w for w in self._descendants(settings) if isinstance(w, (ttk.Entry, ttk.Combobox, ttk.Checkbutton, ttk.Button))]
        ttk.Checkbutton(body, text="Show activity log", variable=self.log_visible, command=self.toggle_log).grid(row=4, column=0, sticky="w", pady=(0, 10))
        self.logbox = ttk.Frame(body, style="Card.TFrame", padding=16)
        self.logbox.columnconfigure(0, weight=1)
        logbar = ttk.Frame(self.logbox, style="Card.TFrame")
        logbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        ttk.Label(logbar, text="Activity log", style="Section.TLabel").pack(side="left", padx=(0, 14))
        ttk.Button(logbar, text="Save log", command=self.save_log).pack(side="left", padx=4)
        ttk.Button(logbar, text="Clear log", command=self.clear_log).pack(side="left", padx=4)
        ttk.Button(logbar, text="Reports folder", command=self.open_reports).pack(side="left", padx=4)
        self.log_text = tk.Text(self.logbox, height=8, wrap="none", borderwidth=0, font=("Consolas", 10))
        self.log_text.grid(row=1, column=0, sticky="nsew")
        ly = ttk.Scrollbar(self.logbox, orient="vertical", command=self.log_text.yview)
        ly.grid(row=1, column=1, sticky="ns")
        lx = ttk.Scrollbar(self.logbox, orient="horizontal", command=self.log_text.xview)
        lx.grid(row=2, column=0, sticky="ew")
        self.log_text.configure(yscrollcommand=ly.set, xscrollcommand=lx.set)
        self._themed_texts.append(self.log_text)
        self._scrollbar_targets.update({ts_y: self.tree, ts_x: self.tree, ly: self.log_text, lx: self.log_text})
        self.build_pdf_page()
        self.build_dependencies_page()
        # The action bar stays outside the scrollable pages.
        run = ttk.Frame(self, padding=(20, 12), style="Card.TFrame")
        run.grid(row=2, column=0, columnspan=2, sticky="ew")
        run.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(run, textvariable=self.status, style="CardMuted.TLabel", wraplength=800)
        self.status_label.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(run, textvariable=self.progress_text, style="Card.TLabel", wraplength=700).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 6))
        self.pb = ttk.Progressbar(run, mode="determinate")
        self.pb.grid(row=2, column=0, sticky="ew", padx=(0, 18))
        self.stop_button = ttk.Button(run, text="Stop  ·  F8", command=self.stop, state="disabled")
        self.stop_button.grid(row=2, column=1, padx=(0, 8))
        self.start_button = ttk.Button(run, text="Start conversion  ·  F5", command=self.start, style="Accent.TButton")
        self.start_button.grid(row=2, column=2)
        self.bind("<Configure>", self.on_resize, add="+")
        self.show_page("convert")
        self.apply_theme()
        self.set_running_state(False)
        self.build_v1(nav,header,run)

    def show_about(self):
        about = tk.Toplevel(self)
        about.title("About PuryF")
        about.transient(self)
        about.resizable(False, False)
        frame = ttk.Frame(about, padding=24, style="Card.TFrame")
        frame.grid(sticky="nsew")
        ttk.Label(frame, text=f"PuryF v{APP_VERSION}", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=f"Published by {PUBLISHER}", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(frame, text=f"© 2026 {PUBLISHER}", style="CardMuted.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Label(frame, text="Open-source software under the MIT License.", style="CardMuted.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 10))
        instagram = ttk.Label(frame, text="Instagram: @alsherkawiMO", style="CardMuted.TLabel", cursor="hand2")
        instagram.grid(row=4, column=0, sticky="w", pady=(0, 16))
        instagram.bind("<Button-1>", lambda _event: webbrowser.open(INSTAGRAM_URL))
        ttk.Button(frame, text="Close", command=about.destroy).grid(row=5, column=0, sticky="e")
        about.grab_set()

    def bind_queue_actions(self):
        self.tree.bind("<ButtonPress-1>", self.queue_drag_start)
        self.tree.bind("<B1-Motion>", self.queue_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self.queue_drag_drop)
        for sequence, action in (("<Alt-Up>", self.move_selected_up), ("<Alt-Down>", self.move_selected_down), ("<Control-Up>", self.move_selected_up), ("<Control-Down>", self.move_selected_down), ("<Control-Shift-Up>", self.move_selected_top), ("<Control-Shift-Down>", self.move_selected_bottom), ("<Control-r>", self.retry_selected), ("<Control-Delete>", self.remove_selected), ("<Control-Shift-Delete>", self.clear_queue), ("<Return>", self.open_selected_source), ("<Shift-Return>", self.open_selected_output_pdf), ("<Control-Return>", self.open_selected_containing_folder)):
            self._bind_action(self.tree, sequence, action)
        for sequence, action in (("<Delete>", self.delete_selected_from_queue), ("<Control-a>", self.select_all_queue), ("<Control-c>", self.copy_selected_paths), ("<Control-v>", self.paste_from_clipboard), ("<Button-3>", self.show_context_menu), ("<Escape>", self.handle_escape)):
            self.tree.bind(sequence, action)
        self.tree.bind("<Motion>", self.schedule_path_tooltip, add="+")
        self.tree.bind("<Leave>", self.hide_path_tooltip, add="+")
        self._bind_action(self, "<F5>", self.start)
        self._bind_action(self, "<F8>", self.stop)

    def toggle_advanced(self):
        if self.advanced_visible.get():
            self.advanced.grid()
        else:
            self.advanced.grid_remove()

    def on_resize(self, event):
        if event.widget is self and hasattr(self, "status_label"):
            self.status_label.configure(wraplength=max(400, event.width - 60))
            self.drop_label.configure(wraplength=max(400, event.width - 290))

    def build_pdf_page(self):
        body = self.make_page("tools")
        ttk.Label(body, text="PDF tools", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(body, text="Combine PDFs or extract pages. Source files stay intact.", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 16))
        merge = self.card(body, "Merge PDFs", 2)
        ttk.Label(merge, text="Merge selected queue PDFs in queue order, or browse for PDFs.", style="CardMuted.TLabel", wraplength=580).grid(row=1, column=0, sticky="w")
        row = ttk.Frame(merge, style="Card.TFrame")
        row.grid(row=2, column=0, sticky="w", pady=(12, 0))
        b = ttk.Button(row, text="Merge queue selection", command=self.merge_queue_pdfs, style="Accent.TButton")
        b.pack(side="left", padx=(0, 8))
        self.run_locked_widgets.append(b)
        b = ttk.Button(row, text="Browse PDFs to merge", command=self.merge_selected_pdfs)
        b.pack(side="left")
        self.run_locked_widgets.append(b)
        split = self.card(body, "Split or extract pages", 3)
        ttk.Label(split, text="Extract ranges such as 1-3,5,8-10, or split every N pages.\nEncrypted source PDFs prompt for their password.", style="CardMuted.TLabel", wraplength=580).grid(row=1, column=0, sticky="w")
        b = ttk.Button(split, text="Choose PDF to split", command=self.split_pdf_dialog)
        b.grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.run_locked_widgets.append(b)
        security = self.card(body, "Output protection", 4)
        ttk.Label(security, text="Merge and split use the password protection settings from Convert → Advanced settings.", style="CardMuted.TLabel", wraplength=580).grid(row=1, column=0, sticky="w")
        ttk.Button(security, text="Open protection settings", command=self.show_protection).grid(row=2, column=0, sticky="w", pady=(12, 0))

    def show_protection(self):
        self.show_page("convert")
        self.advanced_visible.set(True)
        self.toggle_advanced()
        self.update_idletasks()
        self.body_canvas.yview_moveto(1)
        self.password_entry.focus_set()

    def build_dependencies_page(self):
        body = self.make_page("dependencies")
        ttk.Label(body, text="Dependencies", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="Check installed converters and requirements for the current queue.", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 16))
        ttk.Button(body, text="Refresh checks", command=self.refresh_dependencies).grid(row=2, column=0, sticky="w", pady=(0, 12))
        frame = ttk.Frame(body)
        frame.grid(row=3, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        self.dependency_text = tk.Text(frame, height=28, wrap="word", borderwidth=0, padx=16, pady=16, font=("Consolas", 10))
        self.dependency_text.grid(row=0, column=0, sticky="ew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.dependency_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.dependency_text.configure(yscrollcommand=scrollbar.set)
        self._scrollbar_targets[scrollbar] = self.dependency_text
        self._themed_texts.append(self.dependency_text)

    def open_reports(self):
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.open_local(REPORTS_DIR)

    @staticmethod
    def open_local(path):
        if os.name == "nt":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def show_shortcuts(self):
        messagebox.showinfo("Keyboard shortcuts", "Queue: Ctrl+A select all · Ctrl+I invert · Delete remove\nCtrl+C copy paths · Ctrl+V paste paths · Ctrl+D duplicate\nCtrl+R retry selected · Ctrl+Delete remove\nCtrl+Shift+Delete clear queue\nAlt/Ctrl+Up or Down reorder\nCtrl+Shift+Up/Down move to top/bottom\nEnter open source · Shift+Enter open output\nCtrl+Enter open source folder · Escape cancel drag/selection\n\nF5 start · F8 stop · Ctrl+S save log · Ctrl+L clear log")

    def merge_queue_pdfs(self):
        selected = {item.uid for _, item in self._selected_queue_items()}
        files = [str(item.source) for item in self.items if item.uid in selected and item.source.suffix.lower() == ".pdf"]
        if len(files) < 2:
            messagebox.showinfo("Select PDFs", "Select at least two PDF source files in the conversion queue first.")
            return
        self.merge_selected_pdfs(files)

    def install_scrolling(self):
        """Handle both Tk 8 mouse wheels and Tk 9 precision touchpads.

        TouchpadScroll is a distinct event, not a small MouseWheel event.
        Use Tcl's raw %D substitution: some Python versions do not expose
        its packed deltas through tkinter.Event correctly. No native hooks,
        window-procedure replacements, extra threads, or dependencies.
        """
        self._scroll_remainder = {}
        self._scroll_tag = "PuryFScroll_" + str(id(self))
        self._scroll_system = self.tk.call("tk", "windowingsystem")
        for kind, sequence in (("wheel", "<MouseWheel>"),
                               ("touchpad", "<TouchpadScroll>"),
                               ("up", "<Button-4>"),
                               ("down", "<Button-5>")):
            command = self.register(
                lambda w, d, x, y, s, k=kind: self._scroll_input(k, w, d, x, y, s))
            script = 'if {[' + command + ' %W %D %X %Y %s] eq "break"} {break}'
            try:
                self.tk.call("bind", self._scroll_tag, sequence, script)
            except tk.TclError:
                # Older Tk releases do not know TouchpadScroll.
                self.deletecommand(command)
                if kind != "touchpad":
                    raise
        # First tag runs before Text/Treeview/Combobox class bindings. Only
        # this window's existing widgets are tagged; dialogs retain defaults.
        for widget in [self] + self._descendants(self):
            widget.bindtags((self._scroll_tag,) + widget.bindtags())

    @staticmethod
    def _touchpad_deltas(packed):
        value = int(packed) & 0xffffffff
        def signed16(n):
            return n - 65536 if n & 32768 else n
        return signed16(value >> 16), signed16(value & 65535)

    def _scroll_input(self, kind, path, delta, x_root, y_root, state):
        if self._closing:
            return "break"
        try:
            # Event window is authoritative, including a label over the queue.
            widget = self.nametowidget(path)
            if widget.winfo_toplevel() is not self:
                return ""
            state = int(state)
            if state & 4:  # Leave Ctrl+wheel available to other bindings.
                return ""
            if kind == "touchpad":
                dx, dy = self._touchpad_deltas(delta)
                if state & 1 and dx == 0:
                    dx, dy = dy, 0
                dx, dy = -dx, -dy
            else:
                if kind in ("up", "down"):
                    amount = -48 if kind == "up" else 48
                else:
                    amount = -float(delta) * (10 if self._scroll_system == "aqua" else 0.4)
                dx, dy = (amount, 0) if state & 1 else (0, amount)
            target = self._scrollbar_targets.get(widget)
            if target is None:
                target = next((w for w in (self.tree, self.log_text, self.dependency_text)
                               if self._is_child_of(widget, w)), self.body_canvas)
            for axis, pixels in (("x", dx), ("y", dy)):
                if not pixels:
                    continue
                pixels = max(-160, min(160, pixels))
                if not self._scroll_pixels(target, axis, pixels) and axis == "y" and target is not self.body_canvas:
                    self._scroll_pixels(self.body_canvas, axis, pixels)
            return "break"
        except (tk.TclError, ValueError, KeyError):
            # Widgets may be destroyed while a queued event is dispatched.
            return ""

    def _scroll_pixels(self, target, axis, pixels):
        view = target.yview if axis == "y" else target.xview
        first, last = view()
        key = (str(target), axis)
        if last - first >= 0.999999 or (pixels < 0 and first <= 0) or (pixels > 0 and last >= 1):
            self._scroll_remainder.pop(key, None)
            return False
        if isinstance(target, tk.Canvas):
            region = target.bbox("all")
            if region:
                length = region[3] - region[1] if axis == "y" else region[2] - region[0]
                if length > 0:
                    move = target.yview_moveto if axis == "y" else target.xview_moveto
                    move(first + pixels / length)
            return True
        # Text and Treeview have discrete units on older Tk. Accumulate pixel
        # fractions instead of rounding each small gesture down to zero.
        if axis == "y" and target is self.tree:
            unit = int(ttk.Style(self).lookup("Treeview", "rowheight") or 20)
        elif isinstance(target, tk.Text):
            from tkinter import font as tkfont
            font = tkfont.Font(root=self, font=target.cget("font"))
            unit = font.metrics("linespace") if axis == "y" else font.measure("0")
        else:
            unit = 20
        previous = self._scroll_remainder.get(key, 0.0)
        if previous * pixels < 0:
            previous = 0.0
        unit = max(unit, 1)
        total = previous + pixels
        steps = int(total / unit)
        self._scroll_remainder[key] = total - steps * unit
        if steps:
            scroll = target.yview_scroll if axis == "y" else target.xview_scroll
            scroll(steps, "units")
        return True

    @staticmethod
    def _is_child_of(widget, parent):
        while widget is not None:
            if widget == parent:
                return True
            widget = getattr(widget, "master", None)
        return False

    @staticmethod
    def _bind_action(widget, sequence, action):
        def callback(event=None):
            if event is not None:
                editing = isinstance(event.widget, (ttk.Entry, ttk.Combobox, tk.Entry, tk.Text))
                log_action = event.widget is getattr(widget, "log_text", None) and sequence in ("<Control-s>", "<Control-l>")
                if editing and not log_action and sequence not in ("<F5>", "<F8>"):
                    return None
            action()
            return "break"
        widget.bind(sequence, callback)

    def is_running(self):
        return self.service.busy

    @staticmethod
    def _descendants(widget):
        found = []
        for child in widget.winfo_children():
            found.append(child)
            found.extend(App._descendants(child))
        return found

    def set_running_state(self, running):
        for widget in self.mutation_widgets:
            widget.state(["disabled"] if running else ["!disabled"])
        for widget in self.run_locked_widgets:
            widget.state(["disabled"] if running else ["!disabled"])
        self.start_button.state(["disabled"] if running else ["!disabled"])
        self.stop_button.state(["!disabled"] if running else ["disabled"])
        if not running:
            if shutil.which("ocrmypdf") is None:
                self.ocr_control.state(["disabled"])
            self.update_password_controls()

    def update_password_controls(self):
        enabled = self.password_pdf.get()
        self.password_entry.configure(state="normal" if enabled else "disabled", show="" if self.show_password.get() else "*")

    def toggle_log(self):
        if self.log_visible.get():
            self.logbox.grid(row=5, column=0, sticky="nsew", pady=(0, 14))
        else:
            self.logbox.grid_remove()

    def handle_escape(self, event=None):
        if getattr(self, "_queue_dragging", False):
            return self.queue_drag_cancel(event)
        self.tree.selection_remove(self.tree.selection())
        return "break"

    def schedule_path_tooltip(self, event):
        self.hide_path_tooltip()
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        x, y = event.x_root + 12, event.y_root + 16
        self._tooltip_after = self.after(500, lambda: self.show_path_tooltip(iid, x, y))

    def show_path_tooltip(self, iid, x, y):
        item = next((entry for entry in self.items if entry.uid == iid), None)
        if item is None:
            return
        tip = tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        ttk.Label(tip, text=str(item.source), padding=(6, 3), relief="solid").pack()
        self._tooltip = tip

    def hide_path_tooltip(self, event=None):
        if self._tooltip_after is not None:
            try:
                self.after_cancel(self._tooltip_after)
            except Exception:
                pass
            self._tooltip_after = None
        if self._tooltip is not None:
            self._tooltip.destroy()
            self._tooltip = None

    @staticmethod
    def _item_values(item):
        output = Path(item.output).name if item.output else ""
        return (item.source.name, str(item.source.parent), item.status, output, item.message)

    def _insert_item(self, item):
        self.tree.insert("", "end", iid=item.uid, values=self._item_values(item), tags=(item.status,))
        self._update_empty_state()

    def _update_empty_state(self):
        if hasattr(self, "queue_count"):
            self.queue_count.set(f"{len(self.items)} files")
        if self.items:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        if getattr(self, "drop_enabled", True) is False:
            self.drop_label.configure(text="Drag/drop unavailable; use Add files or Add folder")
            return
        if self.items:
            self.drop_label.configure(text="Drop more files or folders here")
        else:
            self.drop_label.configure(text="Drop files here or select Add files")

    def enable_external_drop(self):
        """Enable Windows Explorer drag-and-drop when tkinterdnd2 is installed."""
        if DND_FILES is None:
            self.drop_enabled = False
            self.drop_label.configure(text="Drag/drop needs tkinterdnd2. Use Add files or Add folder, or install drag/drop support.")
            return
        self.drop_enabled = True
        for widget in (self, self.tree, self.drop_label):
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self.on_external_drop)
            except Exception:
                pass

    def on_external_drop(self, event):
        if self.is_running():
            self.status.set("Wait for the current conversion to finish before editing the queue.")
            return "break"
        paths = []
        try:
            raw_paths = self.tk.splitlist(event.data)
        except Exception:
            raw_paths = [event.data]
        for raw in raw_paths:
            p = Path(str(raw).strip())
            if p.is_dir():
                scanned, truncated = self._scan_folder_paths(p)
                paths.extend(scanned)
                if truncated:
                    self.log(f"Drag/drop scan limited to {self.FOLDER_SCAN_LIMIT:,} supported files: {p}")
            elif p.is_file():
                paths.append(str(p))
        self.add_paths(paths)
        return "break"

    def extract_zip_to_app(self, zip_path: Path):
        dest = APP_DIR / "ExtractedZIP" / (zip_path.stem + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        dest.mkdir(parents=True, exist_ok=True)
        extracted = []
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                members = [info for info in z.infolist() if not info.is_dir()]
                if len(members) > ZIP_MAX_FILES:
                    raise RuntimeError(f"ZIP contains too many files ({len(members):,}; limit {ZIP_MAX_FILES:,}).")
                total = sum(info.file_size for info in members)
                if total > ZIP_MAX_TOTAL_BYTES:
                    raise RuntimeError("ZIP expanded size exceeds the 2 GB safety limit.")
                root = dest.resolve()
                targets = []
                for info in members:
                    if info.file_size > ZIP_MAX_MEMBER_BYTES:
                        raise RuntimeError(f"ZIP member is larger than 500 MB: {info.filename}")
                    target = (dest / info.filename).resolve()
                    try:
                        target.relative_to(root)
                    except ValueError:
                        raise RuntimeError(f"Unsafe path in ZIP: {info.filename}")
                    targets.append((info, target))
                for info, target in targets:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        for p in dest.rglob("*"):
            if p.is_file() and p.suffix.lower() in ALL_EXTS and p.suffix.lower() != ".zip" and not p.name.startswith("~$"):
                extracted.append(p)
        self.log(f"Extracted ZIP {zip_path.name}: {len(extracted)} supported file(s) found")
        return extracted

    def _selected_indexes(self):
        return sorted(self.tree.index(iid) for iid in self.tree.selection())

    def _refresh_tree_from_items(self):
        selected_ids = set(self.tree.selection())
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for it in self.items:
            self._insert_item(it)
            if it.uid in selected_ids:
                self.tree.selection_add(it.uid)
        self._update_empty_state()
        self.status.set(f"Queue order updated. Total: {len(self.items)}")

    def move_selected_up(self):
        if self.is_running(): return
        indexes = self._selected_indexes()
        if not indexes or indexes[0] == 0: return
        for idx in indexes:
            self.items[idx-1], self.items[idx] = self.items[idx], self.items[idx-1]
        self._refresh_tree_from_items()

    def move_selected_down(self):
        if self.is_running(): return
        indexes = self._selected_indexes()
        if not indexes or indexes[-1] >= len(self.items)-1: return
        for idx in reversed(indexes):
            self.items[idx+1], self.items[idx] = self.items[idx], self.items[idx+1]
        self._refresh_tree_from_items()

    def move_selected_top(self):
        if self.is_running(): return
        indexes = self._selected_indexes()
        if not indexes: return
        selected = [self.items[i] for i in indexes]
        rest = [it for i, it in enumerate(self.items) if i not in set(indexes)]
        self.items = selected + rest
        self._refresh_tree_from_items()

    def move_selected_bottom(self):
        if self.is_running(): return
        indexes = self._selected_indexes()
        if not indexes: return
        selected = [self.items[i] for i in indexes]
        rest = [it for i, it in enumerate(self.items) if i not in set(indexes)]
        self.items = rest + selected
        self._refresh_tree_from_items()

    def queue_drag_start(self, event):
        """Start drag-to-reorder inside the queue.

        This is separate from Explorer file/folder drop. Click and hold a row,
        drag it above/below another row, then release. Multiple selected rows
        move together while keeping their relative order.
        """
        if self.is_running():
            return
        if event.state & 5:  # Ctrl/Shift click uses Treeview extended selection.
            self._queue_dragging = False
            return None
        region = self.tree.identify_region(event.x, event.y)
        row = self.tree.identify_row(event.y)
        if region not in ("cell", "tree") or not row:
            self._queue_dragging = False
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        self._drag_iids = list(self.tree.selection())
        self._queue_dragging = True
        self._last_drop_index = self.tree.index(row)
        self.status.set("Drag selected queue item(s) up or down, then release to reorder.")
        return "break"

    def queue_drag_motion(self, event):
        """Move selected rows live while dragging inside the queue."""
        if not getattr(self, "_queue_dragging", False):
            return

        # Auto-scroll when the pointer is near the top or bottom of the visible queue.
        height = self.tree.winfo_height()
        if event.y < 20:
            self.tree.yview_scroll(-1, "units")
        elif event.y > height - 20:
            self.tree.yview_scroll(1, "units")

        target = self.tree.identify_row(event.y)
        if not target:
            return "break"

        target_index = self.tree.index(target)
        selected = list(self.tree.selection())
        if not selected or target in selected:
            return "break"

        first_selected_index = min(self.tree.index(iid) for iid in selected)
        # Put the selected block before the target when dragging upward,
        # and after the target when dragging downward.
        insert_index = target_index if target_index < first_selected_index else target_index + 1
        for iid in selected:
            self.tree.move(iid, "", insert_index)
        self._last_drop_index = insert_index
        return "break"

    def queue_drag_drop(self, event):
        """Commit the visual Treeview order back to the real conversion queue."""
        if not getattr(self, "_queue_dragging", False):
            return
        by_uid = {it.uid: it for it in self.items}
        self.items = [by_uid[iid] for iid in self.tree.get_children() if iid in by_uid]
        self._queue_dragging = False
        self._drag_iids = []
        self.status.set(f"Queue reordered. Total: {len(self.items)}")
        return "break"

    def queue_drag_cancel(self, event=None):
        """Cancel an in-progress row drag and redraw from the saved queue order."""
        if getattr(self, "_queue_dragging", False):
            self._queue_dragging = False
            self._drag_iids = []
            self._refresh_tree_from_items()
            self.status.set("Queue reorder cancelled.")
        return "break"

    def settings(self):
        return {
            "output_folder": self.output_folder.get().strip(), "overwrite": self.overwrite.get(), "merge_pdf": self.merge_pdf.get(),
            "compress_pdf": self.compress_pdf.get(), "password_pdf": self.password_pdf.get(), "pdf_password": self.pdf_password.get(),
            "ocr_pdf": self.ocr_pdf.get(), "ppt_layout": self.ppt_layout.get(), "ppt_date_mode": self.ppt_date_mode.get(),
            "image_paper": self.image_paper.get(), "excel_fit_width": self.excel_fit_width.get(),
            "ocr_language": self.ocr_language.get().strip() or "eng", "command_timeout": 900, **getattr(self,"v1_options",{})
        }

    def show_dependencies(self):
        self.show_page("dependencies")

    def refresh_dependencies(self):
        lines = ["Office applications (desktop, Windows):"]
        for name in ("Word", "Excel", "PowerPoint", "Visio", "Publisher", "Project", "Outlook"):
            lines.append(f"  {name}: {'detected' if office_available(name) else 'not detected'}")
        lines.append("\nPython packages:")
        for module in ("PIL", "pypdf", "reportlab", "cryptography", "tkinterdnd2", "cairosvg", "pillow_heif", "cv2", "rawpy", "arabic_reshaper", "bidi"):
            lines.append(f"  {module}: {'installed' if module_available(module) else 'missing'}")
        lines.append("\nExternal commands:")
        for name in ("ocrmypdf", "tesseract", "gswin64c", "ebook-convert", "drawio", "whisper", "ffmpeg"):
            lines.append(f"  {name}: {'detected' if shutil.which(name) else 'not detected'}")
        lines.append("\nCAD export is not implemented. Detection does not guarantee a working installation.")
        try:
            for check in self.service.check_dependencies([item.source for item in self.items], self.settings()):
                for issue in check["issues"]:
                    lines.append(f"\n{Path(check['source']).name}: {issue}")
        except ValueError as error:
            lines.append(f"\nSettings need attention: {error}")
        self.dependency_text.configure(state="normal")
        self.dependency_text.delete("1.0", "end")
        self.dependency_text.insert("1.0", "\n".join(lines))
        self.dependency_text.configure(state="disabled")

    def save_session(self):
        settings = self.settings()
        settings["theme"] = self.theme.get()
        settings.pop("pdf_password", None)
        settings["password_pdf"] = False  # Never restore a protection toggle without its password.
        payload = {"version": 2, "settings": settings, "items": [
            {"source": str(i.source), "status": i.status, "output": i.output, "message": i.message}
            for i in self.items]}
        APP_DIR.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="session_", suffix=".json", dir=APP_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(path, STATE_PATH)
        finally:
            Path(path).unlink(missing_ok=True)

    def load_session(self):
        if not STATE_PATH.exists(): return
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            for key, value in data.get("settings", {}).items():
                if key in ("pdf_password", "password_pdf", "command_timeout"): continue
                if key == "theme" and (data.get("version", 1) < 2 or value not in ("light", "dark")):
                    continue
                variable = getattr(self, key, None)
                if isinstance(variable, tk.Variable) and isinstance(value, (str, bool)):
                    variable.set(value)
            for saved in data.get("items", []):
                item = QueueItem(Path(saved["source"]), status=saved.get("status", "Queued"),
                                 output=saved.get("output", ""), message=saved.get("message", ""))
                if item.status in ("Running", "Pending", "Cancelled"):
                    item.status = "Queued"; item.message = "Recovered interrupted job"
                if item.status == "Success" and (not item.output or not Path(item.output).is_file()):
                    item.status = "Queued"; item.message = "Previous output is missing; queued again"
                if not item.source.is_file():
                    item.status = "Failed"; item.message = "Source file no longer exists"
                self.items.append(item); self._insert_item(item)
            self.apply_theme()
            self.theme_button.configure(text="Light theme" if self.theme.get() == "dark" else "Dark theme")
            self.update_password_controls()
            self.status.set(f"Restored {len(self.items)} queue item(s). Passwords are never saved.")
        except Exception as e:
            self.log(f"Could not restore session: {e}")

    def on_close(self):
        if self._closing: return
        self._closing = True
        self.service.close(wait=False)
        if self.is_running():
            self.stop()
            self.status.set("Closing after current Office operation finishes; external commands are being cancelled.")
        self._finish_close()

    def _finish_close(self):
        if self.is_running():
            self.after(200, self._finish_close)
            return
        try:
            self.save_session()
        except Exception as e:
            messagebox.showerror("Session save failed", str(e))
        self.destroy()

    def destroy(self):
        if hasattr(self, "service"):
            self.service.unsubscribe(self.job_events)
            self.service.close(wait=True)
        if hasattr(self,"sdk"):self.sdk.close()
        # Cancel owned timers before Tcl deletes their Python commands.
        for timer in (getattr(self, "_poll_after", None), getattr(self, "_tooltip_after", None),
                      getattr(self, "_explorer_after", None)):
            if timer:
                try:
                    self.after_cancel(timer)
                except tk.TclError:
                    pass
        super().destroy()

    def log(self, msg): self.q.put(("log", msg))
    def update_item(self, uid, status, output, message): self.q.put(("item", uid, status, output, message))
    def progress(self, n, total, filename=""): self.q.put(("progress", n, total, filename))

    def attach_explorer(self, inbox):
        self._explorer_inbox = inbox
        self._explorer_after = self.after(100, self._poll_explorer)

    def _poll_explorer(self):
        self._explorer_after = None
        if self._closing:
            return
        self._explorer_inbox.drain(self.accept_explorer, self.log)
        self._explorer_after = self.after(250, self._poll_explorer)

    def accept_explorer(self, request):
        """Runs on Tk's thread, including while the Office worker is busy."""
        if self._closing:
            raise RuntimeError("Application is closing")
        self.deiconify()
        self.lift()
        if request["action"] == "show":
            return
        accepted = []
        seen = set()
        active_sources = {os.path.normcase(str(Path(i["source"]).resolve()))
            for job in self.service.list_jobs() if job["status"] in ("queued", "running", "cancelling")
            for i in job["inputs"]}
        existing = {os.path.normcase(str(i.source.resolve())): i for i in self.items}
        for value in request["paths"]:
            try:
                path = Path(value).resolve()
                usable = path.is_file() and path.suffix.lower() in ALL_EXTS - {".zip", ".dwg", ".dxf", ".url"} and not path.name.startswith("~$")
            except (OSError, RuntimeError, ValueError) as error:
                self.log(f"Explorer skipped inaccessible file {value}: {error}")
                continue
            if not usable:
                self.log(f"Explorer skipped unsupported or missing file: {path}")
                continue
            key = os.path.normcase(str(path))
            if key in seen or key in active_sources:
                continue
            seen.add(key)
            item = existing.get(key)
            if item is not None and item.status in ("Running", "Pending"):
                continue
            if request["action"] == "queue" and item is not None and item.status == "Queued":
                continue
            if item is None or item.status != "Queued":
                item = QueueItem(path)
                self.items.append(item)
                self._insert_item(item)
            existing[key] = item
            accepted.append(item)
        if request["action"] == "convert" and accepted:
            # Fixed defaults independent of saved GUI settings and passwords.
            handle = self.service.submit_conversion([i.source for i in accepted], ConversionOptions(),
                origin="explorer", item_ids=[i.uid for i in accepted])
            for item in accepted:
                item.status = "Pending"
                item.message = "Explorer conversion waiting in shared queue"
                self.tree.item(item.uid, values=self._item_values(item), tags=(item.status,))
            self.worker = handle
            self.set_running_state(True)
            self.log(f"Explorer submitted {len(accepted)} file(s), job {handle.id}")
        else:
            self.log(f"Explorer added {len(accepted)} file(s) without starting")
        self.status.set(f"Explorer: {len(accepted)} file(s) {'submitted' if request['action'] == 'convert' else 'added to queue'}")
        try:
            self.save_session()
        except OSError as error:
            # The submitted request must still be acknowledged: retrying it
            # solely because session persistence failed could duplicate work.
            self.log(f"Explorer session could not be saved: {error}")

    def add_files(self):
        if self.is_running(): return
        types = [("Supported files", " ".join(f"*{e}" for e in sorted(ALL_EXTS))), ("All files", "*.*")]
        files = filedialog.askopenfilenames(title="Select files", filetypes=types)
        self.add_paths(files)

    def add_folder(self):
        if self.is_running(): return
        folder = filedialog.askdirectory(title="Select folder")
        if not folder: return
        paths, truncated = self._scan_folder_paths(Path(folder))
        if truncated:
            self.log(f"Folder scan limited to {self.FOLDER_SCAN_LIMIT:,} supported files: {folder}")
        self.add_paths(paths)

    def _scan_folder_paths(self, root):
        """Bounded, non-linking folder scan used by GUI folder inputs."""
        root = Path(root)
        found = []
        if not root.is_dir():
            return found, False
        for folder, directories, files in os.walk(root, followlinks=False):
            directories[:] = sorted(d for d in directories if not (Path(folder) / d).is_symlink())
            for name in sorted(files):
                path = Path(folder) / name
                if name.startswith("~$") or path.suffix.lower() not in ALL_EXTS:
                    continue
                try:
                    if path.is_file():
                        found.append(str(path.resolve()))
                except OSError as error:
                    self.log(f"Folder scan skipped {path}: {error}")
                if len(found) >= self.FOLDER_SCAN_LIMIT:
                    return found, True
        return found, False

    def add_paths(self, paths):
        if self.is_running():
            self.status.set("Wait for the current conversion to finish before editing the queue.")
            return
        existing = {str(i.source).lower() for i in self.items}
        added = 0
        for p in paths:
            path = Path(p)
            if path.exists() and path.suffix.lower() == ".zip":
                try:
                    extracted = self.extract_zip_to_app(path)
                except Exception as e:
                    messagebox.showerror("ZIP extraction failed", f"{path.name}\n\n{e}")
                    self.log(f"ZIP FAILED: {path.name} - {e}")
                    continue
                for inner in extracted:
                    if str(inner).lower() not in existing:
                        self.items.append(QueueItem(inner))
                        self._insert_item(self.items[-1])
                        existing.add(str(inner).lower())
                        added += 1
                continue
            if path.exists() and path.suffix.lower() in ALL_EXTS and str(path).lower() not in existing:
                self.items.append(QueueItem(path))
                self._insert_item(self.items[-1])
                existing.add(str(path).lower())
                added += 1
        self.status.set(f"Added {added} file(s). Queue total: {len(self.items)}")

    def remove_selected(self):
        if self.is_running(): return
        selected = list(self.tree.selection())
        selected_ids = set(selected)
        self.items = [item for item in self.items if item.uid not in selected_ids]
        for iid in selected:
            self.tree.delete(iid)
        self._update_empty_state()
        self.status.set(f"Removed {len(selected)} item(s). Queue total: {len(self.items)}")

    def delete_selected_from_queue(self, event=None):
        """Delete key shortcut: remove selected queue rows."""
        self.remove_selected()
        return "break"

    def select_all_queue(self, event=None):
        """Ctrl+A shortcut: select every row in the queue."""
        self.tree.selection_set(self.tree.get_children())
        self.tree.focus_set()
        self.status.set(f"Selected {len(self.tree.selection())} queue item(s).")
        return "break"

    def _selected_queue_items(self):
        """Return selected Treeview item ids and matching QueueItem objects."""
        iids = list(self.tree.selection())
        pairs = []
        by_uid = {item.uid: item for item in self.items}
        for iid in iids:
            if iid in by_uid:
                pairs.append((iid, by_uid[iid]))
        return pairs

    def copy_selected_paths(self, event=None):
        """Ctrl+C shortcut: copy selected source file paths to the clipboard."""
        paths = [str(item.source) for _, item in self._selected_queue_items()]
        if not paths:
            return "break"
        text = "\n".join(paths)
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status.set(f"Copied {len(paths)} path(s) from queue.")
        except Exception as e:
            self.status.set(f"Copy failed: {e}")
        return "break"

    def paste_from_clipboard(self, event=None):
        """Ctrl+V shortcut: paste copied file/folder paths into the queue."""
        try:
            data = self.clipboard_get()
        except Exception:
            self.status.set("Clipboard does not contain paths.")
            return "break"

        paths = []
        # Handles normal newline-separated paths and Tcl/Explorer-style brace-wrapped paths.
        candidates = []
        try:
            candidates.extend(self.tk.splitlist(data))
        except Exception:
            pass
        candidates.extend(data.replace("\r", "\n").split("\n"))

        for raw in candidates:
            raw = str(raw).strip().strip('"').strip()
            if not raw:
                continue
            p = Path(raw)
            if p.is_dir():
                scanned, truncated = self._scan_folder_paths(p)
                paths.extend(scanned)
                if truncated:
                    self.log(f"Clipboard folder scan limited to {self.FOLDER_SCAN_LIMIT:,} supported files: {p}")
            elif p.is_file():
                paths.append(str(p))

        if not paths:
            self.status.set("No supported files found in clipboard.")
            return "break"

        self.add_paths(paths)
        return "break"

    def show_context_menu(self, event):
        """Right-click queue menu."""
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open Source File", command=self.open_selected_source)
        menu.add_command(label="Open Containing Folder", command=self.open_selected_containing_folder)
        menu.add_command(label="Open Output PDF", command=self.open_selected_output_pdf)
        menu.add_command(label="Open Output Folder", command=self.open_selected_output_folder)
        menu.add_separator()
        menu.add_command(label="Copy File Path", command=self.copy_selected_paths)
        menu.add_command(label="Retry Selected", command=self.retry_selected)
        menu.add_separator()
        menu.add_command(label="Move To Top", command=self.move_selected_top)
        menu.add_command(label="Move To Bottom", command=self.move_selected_bottom)
        menu.add_separator()
        menu.add_command(label="Remove Selected", command=self.remove_selected)
        menu.add_command(label="Remove Completed", command=self.remove_completed)
        menu.add_command(label="Remove Failed", command=self.remove_failed)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def open_selected_source(self):
        pairs = self._selected_queue_items()
        if not pairs:
            return
        p = pairs[0][1].source
        if Path(p).exists():
            self.open_local(p)
        else:
            messagebox.showwarning("File missing", f"Source file was not found:\n{p}")

    def open_selected_containing_folder(self):
        pairs = self._selected_queue_items()
        if not pairs:
            return
        p = Path(pairs[0][1].source)
        folder = p.parent
        if folder.exists():
            self.open_local(folder)
        else:
            messagebox.showwarning("Folder missing", f"Containing folder was not found:\n{folder}")

    def _output_path_for_item(self, item):
        out = str(getattr(item, "output", "") or "").strip()
        if out:
            return Path(out)
        folder = self.output_folder.get().strip()
        if folder:
            candidate = Path(folder) / (Path(item.source).stem + ".pdf")
        else:
            candidate = Path(item.source).with_suffix(".pdf")
        same_path = os.path.normcase(os.path.abspath(candidate)) == os.path.normcase(os.path.abspath(item.source))
        if Path(item.source).suffix.lower() == ".pdf" and same_path:
            return candidate.with_name(candidate.stem + "_processed.pdf")
        return candidate

    def open_selected_output_pdf(self):
        pairs = self._selected_queue_items()
        if not pairs:
            return
        out = self._output_path_for_item(pairs[0][1])
        if out.exists():
            self.open_local(out)
        else:
            messagebox.showinfo("Output PDF", f"No output PDF found yet:\n{out}")

    def open_selected_output_folder(self):
        pairs = self._selected_queue_items()
        if not pairs:
            self.open_output()
            return
        out = self._output_path_for_item(pairs[0][1])
        folder = out.parent
        folder.mkdir(parents=True, exist_ok=True)
        self.open_local(folder)

    def retry_selected(self):
        if self.is_running(): return
        pairs = self._selected_queue_items()
        if not pairs:
            return
        for iid, item in pairs:
            item.status = "Queued"
            item.output = ""
            item.message = ""
            self.tree.item(iid, values=self._item_values(item), tags=(item.status,))
        self.status.set(f"Re-queued {len(pairs)} selected item(s).")

    def remove_completed(self):
        if self.is_running(): return
        keep = []
        for it in self.items:
            if str(it.status).lower() not in ("success", "completed", "overwritten", "renamed"):
                keep.append(it)
        removed = len(self.items) - len(keep)
        self.items = keep
        self._refresh_tree_from_items()
        self.status.set(f"Removed {removed} completed item(s). Queue total: {len(self.items)}")

    def remove_failed(self):
        if self.is_running(): return
        keep = [it for it in self.items if str(it.status).lower() != "failed"]
        removed = len(self.items) - len(keep)
        self.items = keep
        self._refresh_tree_from_items()
        self.status.set(f"Removed {removed} failed item(s). Queue total: {len(self.items)}")

    def clear_queue(self):
        if self.is_running(): return
        if self.items and not messagebox.askyesno("Clear queue", "Remove every item from the queue?"):
            return
        self.items.clear()
        for i in self.tree.get_children(): self.tree.delete(i)
        self.pb["value"] = 0; self.progress_text.set("0 / 0")
        self._update_empty_state()

    def retry_failed(self):
        if self.is_running(): return
        self.start(only_failed=True)

    def pick_output(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder: self.output_folder.set(folder)

    def open_output(self):
        folder = self.output_folder.get().strip()
        if not folder:
            messagebox.showinfo("Output folder", "Choose an output folder first, or PDFs are saved beside source files.")
            return
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.open_local(folder)

    def start(self, only_failed=False):
        if self._closing:
            return
        if self.is_running():
            messagebox.showwarning("Running", "A conversion is already running.")
            return
        items = [i for i in self.items if (i.status == "Failed" if only_failed else i.status in ("Queued", "Failed", "Skipped", "Cancelled"))]
        if not items:
            messagebox.showinfo("Queue", "No files to convert.")
            return
        try:
            options = ConversionOptions.from_mapping(self.settings())
            self.save_session()
            self.stop_event.clear()
            self.worker = self.service.submit_conversion([i.source for i in items], options,
                origin="desktop", item_ids=[i.uid for i in items])
            self.active_job_id = self.worker.id
            self.pb["maximum"] = len(items)
            self.pb["value"] = 0
            self.set_running_state(True)
        except (ValueError, OSError, RuntimeError) as error:
            messagebox.showerror("Cannot start conversion", str(error))

    def stop(self):
        self.stop_event.set()
        if self.active_job_id:
            self.service.cancel(self.active_job_id)
        self.log("Stop requested. External commands cancel; an active Office call must return before stopping.")

    def _process_job_events(self):
        try:
            while True:
                event = self.job_events.get_nowait()
                kind = event["type"]
                job_id = event["job_id"]
                if kind == "job_submitted":
                    if event["operation"] == "convert":
                        known = {i.uid for i in self.items}
                        for item in self.service.get_job(job_id)["inputs"]:
                            if item["id"] not in known:
                                added = QueueItem(Path(item["source"]), uid=item["id"])
                                self.items.append(added)
                                self._insert_item(added)
                elif kind == "job_state" and event["status"] == "running":
                    self.active_job_id = job_id
                    self.status.set(f"Running {event['operation']} job {job_id[:8]}")
                elif kind == "log":
                    self.log(event["message"])
                elif kind == "error":
                    self.log(event["error"]["message"])
                elif kind == "item_updated":
                    item = event["item"]
                    existing = next((i for i in self.items if i.uid == item["id"]), None)
                    if existing is not None:
                        existing.status = item["status"]
                        existing.output = item["output"] or ""
                        existing.message = item["message"]
                        existing.seconds = item["seconds"]
                        if self.tree.exists(existing.uid):
                            self.tree.item(existing.uid, values=self._item_values(existing), tags=(existing.status,))
                elif kind == "progress":
                    progress = event["progress"]
                    self.pb["maximum"] = max(1, progress["total"])
                    self.pb["value"] = progress["completed"]
                    self.progress_text.set(f"{progress['completed']} of {progress['total']} · {progress['percent']}% · {progress['current']}")
                elif kind == "job_finished":
                    result = self.service.get_job(job_id)
                    self.notify_complete(result)
                    self.status.set(f"Job {job_id[:8]}: {result['status']} · {len(result['outputs'])} output(s)")
                    if job_id in self._manual_jobs:
                        label = self._manual_jobs.pop(job_id)
                        if result["status"] == "succeeded":
                            messagebox.showinfo(label + " complete", "Saved:\n" + "\n".join(o["path"] for o in result["outputs"]))
                        elif result["status"] != "cancelled":
                            messagebox.showerror(label + " failed", "\n".join(e["message"] for e in result["errors"]))
                    try:
                        self.save_session()
                    except OSError as error:
                        self.log(f"Session could not be saved: {error}")
        except queue.Empty:
            pass
        self.set_running_state(self.service.busy)

    def process_queue(self):
        try:
            while True:
                event = self.q.get_nowait()
                if event[0] == "ui":
                    event[1]()
                elif event[0] == "log":
                    stamp = datetime.now().strftime("%H:%M:%S")
                    self.log_text.insert("end", f"[{stamp}] {event[1]}\n")
                    self.log_text.see("end")
                    self.status.set(event[1])
                elif event[0] == "item":
                    _, uid, status, output, msg = event
                    if status == "batch_done":
                        self.set_running_state(False)
                        try:
                            self.save_session()
                        except Exception as e:
                            self.log(f"Session could not be saved: {e}")
                        continue
                    by_uid = {item.uid: item for item in self.items}
                    it = by_uid.get(uid)
                    if it is not None and self.tree.exists(uid):
                        rendered = (it.source.name, str(it.source.parent), status, Path(output).name if output else "", msg)
                        self.tree.item(uid, values=rendered, tags=(status,))
                elif event[0] == "progress":
                    _, n, total, filename = event
                    self.pb["maximum"] = total; self.pb["value"] = n
                    percent = round(n * 100 / total) if total else 0
                    self.progress_text.set(f"{n} of {total} · {percent}% · {filename}")
        except queue.Empty:
            pass
        self._process_job_events()
        self._poll_after = self.after(100, self.process_queue)

    def _source_pdf_password(self, path):
        info = pdf_tools.inspect_pdf(path)
        if info["unlocked"]:
            return ""
        password = simpledialog.askstring("Unlock PDF", f"Password for {Path(path).name}", show="*")
        if password is None:
            raise ValueError("PDF operation cancelled")
        if not pdf_tools.inspect_pdf(path, password)["unlocked"]:
            raise ValueError("Incorrect PDF password")
        return password

    def _tool_options(self):
        return ConversionOptions(overwrite=True, password_pdf=self.password_pdf.get(),
                                 pdf_password=self.pdf_password.get())

    def _track_pdf_job(self, handle, label):
        self.worker = handle
        self.active_job_id = handle.id
        self._manual_jobs[handle.id] = label
        self.stop_event.clear()
        self.set_running_state(True)
        self.status.set(f"Queued {label.lower()} job {handle.id[:8]}")

    def merge_selected_pdfs(self, files=None):
        if self.is_running():
            return
        if files is None:
            files = filedialog.askopenfilenames(title="Select PDFs to merge", filetypes=[("PDF files", "*.pdf")])
        if not files:
            return
        output = filedialog.asksaveasfilename(title="Save merged PDF", defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if not output:
            return
        try:
            options = self._tool_options()
            passwords = {str(path): self._source_pdf_password(path) for path in files}
            handle = self.service.submit_merge(files, output, options, passwords=passwords, origin="desktop")
            self._track_pdf_job(handle, "Merge")
        except Exception as error:
            messagebox.showerror("Merge failed", str(error))

    def split_pdf_dialog(self):
        if self.is_running():
            return
        source = filedialog.askopenfilename(title="Select PDF to split", filetypes=[("PDF files", "*.pdf")])
        if not source:
            return
        interval = messagebox.askyesno("Split mode", "Yes = split every N pages\nNo = extract page ranges")
        try:
            options = self._tool_options()
            password = self._source_pdf_password(source)
            if interval:
                n = simpledialog.askinteger("Every N pages", "Split every how many pages?", minvalue=1)
                if not n:
                    return
                folder = filedialog.askdirectory(title="Choose output folder")
                if not folder:
                    return
                count = pdf_tools.inspect_pdf(source, password)["pages"]
                outputs = [Path(folder) / f"{Path(source).stem}_pages_{i+1}-{min(i+n,count)}.pdf" for i in range(0, count, n)]
                if any(o.exists() for o in outputs) and not messagebox.askyesno("Replace split PDFs?", "Some split files already exist. Replace them?"):
                    return
                handle = self.service.submit_split(source, options, output_dir=folder, every_n=n,
                                                   password=password, origin="desktop")
            else:
                ranges = simpledialog.askstring("Page ranges", "Enter ranges, example: 1-3,5,8-10")
                if not ranges:
                    return
                output = filedialog.asksaveasfilename(title="Save extracted PDF", defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
                if not output:
                    return
                handle = self.service.submit_split(source, options, output_file=output, page_ranges=ranges,
                                                   password=password, origin="desktop")
            self._track_pdf_job(handle, "Split")
        except Exception as error:
            messagebox.showerror("Split failed", str(error))

    def read_pdf_dialog(self, path):
        # Compatibility helper; reading/decryption itself is headless.
        return pdf_tools.read_pdf(path, self._source_pdf_password(path))

    def apply_manual_password(self, writer):
        # Retained for integrations using the earlier desktop helper.
        options = self._tool_options()
        pdf_tools.apply_password(writer, options)

    def duplicate_selected(self):
        if self.is_running(): return
        pairs=self._selected_queue_items()
        added=0
        for _,item in pairs:
            new=QueueItem(source=item.source)
            self.items.append(new)
            self._insert_item(new)
            added+=1
        self.status.set(f"Duplicated {added} item(s).")

    def save_log(self, event=None):
        from tkinter import filedialog
        path=filedialog.asksaveasfilename(defaultextension=".txt")
        if path:
            Path(path).write_text(self.log_text.get("1.0","end"), encoding="utf-8")

    def clear_log(self, event=None):
        self.log_text.delete("1.0","end")
        return "break"

    def invert_selection(self, event=None):
        all_items=set(self.tree.get_children())
        selected=set(self.tree.selection())
        self.tree.selection_set(list(all_items-selected))
        return "break"

