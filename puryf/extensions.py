# SPDX-License-Identifier: MIT
"""Explicit trusted Python converter extensions. Never load plugins from documents."""
import importlib.util
from pathlib import Path
import uuid

def load(path):
    from . import engine
    path=Path(path).resolve()
    if not path.is_file() or path.suffix.lower()!='.py':raise ValueError('Choose a trusted Python extension file')
    spec=importlib.util.spec_from_file_location('puryf_user_'+uuid.uuid4().hex,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if getattr(module,'API_VERSION',None)!=1 or not callable(getattr(module,'convert',None)):raise ValueError('Extension needs API_VERSION=1 and convert(source, output, settings, log, cancel)')
    exts=getattr(module,'EXTENSIONS',[])
    if not isinstance(exts,(list,tuple)) or not exts:raise ValueError('Extension needs EXTENSIONS')
    import re
    if any(not isinstance(x,str) or not re.fullmatch(r'\.[a-z0-9]{1,12}',x) or x in engine.ALL_EXTS for x in exts):raise ValueError('Invalid or already registered extension')
    for ext in exts:
        engine.PLUGIN_CONVERTERS[ext]={'convert':module.convert,'check':getattr(module,'check_dependencies',None),'name':getattr(module,'NAME',path.stem)}
        engine.ALL_EXTS.add(ext)
    return {'name':getattr(module,'NAME',path.stem),'extensions':list(exts)}
