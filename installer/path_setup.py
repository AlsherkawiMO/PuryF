# SPDX-License-Identifier: MIT
"""Own one per-user PATH entry; preserve raw values, types and unrelated entries."""
import ctypes
import ntpath
from pathlib import Path
import sys

OWNER = r'Software\PuryF'

def key(value):
    return ntpath.normcase(ntpath.normpath(value.strip().strip('"')))

def add_entry(raw, entry):
    if any(key(p) == key(entry) for p in raw.split(';') if p.strip()):
        return raw, False
    return raw + (';' if raw else '') + entry, True

def remove_entry(raw, entry):
    # Ownership records exactly one inserted entry; do not erase other duplicates.
    parts = raw.split(';')
    for n, part in enumerate(parts):
        if key(part) == key(entry):
            del parts[n]
            break
    return ';'.join(parts)

def notify():
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    function = user32.SendMessageTimeoutW
    function.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM,
                         wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
    function.restype = wintypes.LPARAM
    text = ctypes.create_unicode_buffer('Environment'); result = ctypes.c_size_t()
    function(0xffff,0x001a,0,ctypes.cast(text,ctypes.c_void_p).value,2,5000,ctypes.byref(result))

def update(mode, root, registry=None, broadcast=notify):
    if registry is None:
        import winreg as registry
    entry = str(Path(root).resolve()/'bin')
    with registry.CreateKey(registry.HKEY_CURRENT_USER, OWNER) as owner:
        try: owned,_ = registry.QueryValueEx(owner,'PathEntryOwned')
        except FileNotFoundError: owned = ''
        if mode == 'remove' and (not owned or key(owned) != key(entry)):
            return  # no owned entry: do not inspect or touch the user's PATH
        with registry.CreateKey(registry.HKEY_CURRENT_USER,'Environment') as environment:
            try: raw,kind = registry.QueryValueEx(environment,'Path')
            except FileNotFoundError: raw,kind = '',registry.REG_EXPAND_SZ
            if kind not in (registry.REG_SZ,registry.REG_EXPAND_SZ) or not isinstance(raw,str):
                raise RuntimeError('User PATH has an unsupported registry type; no changes made')
            if mode == 'remove':
                if owned and key(owned) == key(entry):
                    changed = remove_entry(raw,owned)
                    if changed != raw: registry.SetValueEx(environment,'Path',0,kind,changed)
                    registry.DeleteValue(owner,'PathEntryOwned')
            elif mode == 'add':
                if owned and key(owned) != key(entry):
                    raise RuntimeError('Another PuryF location owns the PATH entry; upgrade in place')
                changed,added = add_entry(raw,entry)
                if added:
                    registry.SetValueEx(environment,'Path',0,kind,changed)
                    registry.SetValueEx(owner,'PathEntryOwned',0,registry.REG_SZ,entry)
            else: raise ValueError('Expected add or remove')
    broadcast()

if __name__ == '__main__':
    if len(sys.argv)!=3 or sys.argv[1] not in ('add','remove'):
        raise SystemExit('Usage: path_setup.py add|remove INSTALL_DIRECTORY')
    try: update(sys.argv[1],sys.argv[2])
    except Exception as error:
        print('PuryF PATH setup failed: '+str(error),file=sys.stderr)
        raise SystemExit(1)
