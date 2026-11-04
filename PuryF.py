# SPDX-License-Identifier: MIT
"""Desktop launcher and compatibility exports; importing this module is headless."""
def __getattr__(name):
    if name == "App":
        from puryf.desktop import App
        return App
    from puryf import engine
    try:
        return getattr(engine, name)
    except AttributeError:
        raise AttributeError(name) from None

def main(argv=None):
    from puryf.explorer import launch
    try:
        return launch(argv)
    except Exception as error:
        import os
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), "PuryF could not open", 0x10)
        else:
            raise
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
