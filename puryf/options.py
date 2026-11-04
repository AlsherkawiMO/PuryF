# SPDX-License-Identifier: MIT
"""Immutable, UI-independent conversion settings shared by every adapter."""
from dataclasses import dataclass, field, fields
from typing import Mapping

from .engine import PPT_LAYOUTS, PPT_DATE_MODES


@dataclass(frozen=True)
class ConversionOptions:
    output_folder: str = ""
    overwrite: bool = False
    merge_pdf: bool = False
    compress_pdf: bool = False
    password_pdf: bool = False
    pdf_password: str = field(default="", repr=False)
    ocr_pdf: bool = False
    image_paper: str = "Original size"
    excel_fit_width: bool = False
    ocr_language: str = "eng"
    ppt_layout: str = "Full-page slides"
    ppt_date_mode: str = "Remove date"
    command_timeout: int = 900
    naming_pattern: str = "{stem}"
    preserve_folders: bool = False
    source_root: str = ""
    image_max_edge: int = 0

    def __post_init__(self):
        for name in ("overwrite", "merge_pdf", "compress_pdf", "password_pdf", "ocr_pdf", "excel_fit_width"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        for name in ("output_folder", "pdf_password", "image_paper", "ocr_language", "ppt_layout", "ppt_date_mode"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
        if self.image_paper not in ("Original size", "A4", "Letter"):
            raise ValueError("Unsupported image paper size")
        if self.ppt_layout not in PPT_LAYOUTS or self.ppt_date_mode not in PPT_DATE_MODES:
            raise ValueError("Unsupported PowerPoint layout or date mode")
        if isinstance(self.command_timeout, bool) or not isinstance(self.command_timeout, int) or self.command_timeout < 1:
            raise ValueError("command_timeout must be a positive integer")
        if not self.ocr_language.strip():
            raise ValueError("ocr_language must not be empty")
        if self.password_pdf and not self.pdf_password:
            raise ValueError("A password is required when PDF protection is enabled")
        import string
        from pathlib import Path
        if not isinstance(self.preserve_folders,bool) or not isinstance(self.source_root,str):
            raise ValueError("Invalid folder preservation settings")
        if self.preserve_folders and (not self.output_folder or not self.source_root):
            raise ValueError("Folder preservation requires output_folder and source_root")
        if type(self.image_max_edge) is not int or not 0<=self.image_max_edge<=16000:
            raise ValueError("image_max_edge must be between 0 and 16000")
        if not isinstance(self.naming_pattern,str) or not self.naming_pattern or len(self.naming_pattern)>120:
            raise ValueError("Invalid naming pattern")
        if any(c in self.naming_pattern for c in '/\\:<>|?*\"'):
            raise ValueError("Naming pattern must not contain path separators or reserved characters")
        for _,field,fmt,conversion in string.Formatter().parse(self.naming_pattern):
            if field is not None and (field not in {'stem','ext','index','date','parent','hash8'} or fmt or conversion):
                raise ValueError("Use only stem, ext, index, date, parent and hash8 placeholders")

    @classmethod
    def from_mapping(cls, value=None):
        if isinstance(value, cls):
            return value
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("Options must be ConversionOptions or a mapping")
        allowed = {f.name for f in fields(cls)}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("Unknown conversion options: " + ", ".join(sorted(map(str, unknown))))
        return cls(**dict(value))

    def engine_settings(self):
        """Private worker-only copy. Do not log or serialize this mapping."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def public_settings(self):
        result = self.engine_settings()
        result.pop("pdf_password")
        result["password_supplied"] = bool(self.pdf_password)
        return result
