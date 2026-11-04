# SPDX-License-Identifier: MIT
"""Headless PDF tools. No dialogs, GUI imports, or Office calls."""
import os
from contextlib import nullcontext
from pathlib import Path
import tempfile

from .engine import ConversionCancelled, PdfReader, PdfWriter, parse_page_ranges


def read_pdf(path, password=""):
    if PdfReader is None:
        raise RuntimeError("pypdf is required")
    reader = PdfReader(str(path))
    if reader.is_encrypted and not reader.decrypt(password):
        raise ValueError(f"Password required or incorrect for {Path(path).name}")
    return reader


def inspect_pdf(path, password=""):
    if PdfReader is None:
        raise RuntimeError("pypdf is required")
    reader = PdfReader(str(path))
    encrypted = reader.is_encrypted
    unlocked = not encrypted or bool(reader.decrypt(password))
    return {"encrypted": encrypted, "unlocked": unlocked,
            "pages": len(reader.pages) if unlocked else None}


def _check_cancel(stop_event):
    if stop_event.is_set():
        raise ConversionCancelled("PDF operation cancelled")


def apply_password(writer, options):
    if options.password_pdf:
        writer.encrypt(options.pdf_password, algorithm="AES-256")


def _save(writer, output, sources, options, stop_event, commit_guard=None):
    output = Path(output).resolve()
    if output in {Path(s).resolve() for s in sources}:
        raise ValueError("Output must differ from every source PDF")
    output.parent.mkdir(parents=True, exist_ok=True)
    _check_cancel(stop_event)
    apply_password(writer, options)
    with tempfile.TemporaryDirectory(prefix=".puryf_pdf_", dir=output.parent) as folder:
        staged = Path(folder) / "result.pdf"
        with staged.open("wb") as stream:
            writer.write(stream)
        reader = read_pdf(staged, options.pdf_password)
        if not len(reader.pages):
            raise ValueError("PDF operation produced no pages")
        _check_cancel(stop_event)
        with commit_guard(output) if commit_guard else nullcontext():
            _check_cancel(stop_event)
            if options.overwrite:
                os.replace(staged, output)
            else:
                os.link(staged, output)  # Atomic refusal of an existing output.
    return output


def merge(sources, output, options, stop_event, passwords=None, progress=None, commit_guard=None):
    if PdfWriter is None:
        raise RuntimeError("pypdf is required")
    passwords = passwords or {}
    writer = PdfWriter()
    for index, source in enumerate(sources, 1):
        _check_cancel(stop_event)
        for page in read_pdf(source, passwords.get(str(source), "")).pages:
            _check_cancel(stop_event)
            writer.add_page(page)
        if progress:
            progress(index, len(sources), Path(source).name)
    return _save(writer, output, sources, options, stop_event, commit_guard)


def split(source, options, stop_event, *, output_file=None, output_dir=None,
          page_ranges=None, every_n=None, password="", progress=None, commit_guard=None):
    reader = read_pdf(source, password)
    if every_n is not None:
        if isinstance(every_n, bool) or not isinstance(every_n, int) or every_n < 1:
            raise ValueError("every_n must be a positive integer")
        groups = [list(range(i, min(i + every_n, len(reader.pages))))
                  for i in range(0, len(reader.pages), every_n)]
        folder = Path(output_dir)
        outputs = [folder / f"{Path(source).stem}_pages_{g[0]+1}-{g[-1]+1}.pdf" for g in groups]
    else:
        groups = [parse_page_ranges(page_ranges, len(reader.pages))]
        outputs = [Path(output_file)]
    # Validate the whole destination set before writing any part.
    for out in outputs:
        if out.resolve() == Path(source).resolve():
            raise ValueError("Output must differ from the source PDF")
        if out.exists() and not options.overwrite:
            raise FileExistsError(f"Output already exists: {out}")
    for index, (pages, output) in enumerate(zip(groups, outputs), 1):
        _check_cancel(stop_event)
        writer = PdfWriter()
        for page in pages:
            _check_cancel(stop_event)
            writer.add_page(reader.pages[page])
        result = _save(writer, output, [source], options, stop_event, commit_guard)
        # Yield each committed output so it remains discoverable if a later part fails.
        yield result
        if progress:
            progress(index, len(groups), result.name)
