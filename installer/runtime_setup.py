"""Create PuryF's private runtime. Called by the per-user Windows installer."""
from pathlib import Path
import subprocess
import sys
import venv


MARKER = "PuryF source install v1"


def setup(root):
    root = Path(root).resolve()
    marker = root / "puryf-install.marker"
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != MARKER:
        raise RuntimeError("PuryF installation marker is missing or invalid.")
    if not (root / "PuryF.py").is_file() or not (root / "requirements.txt").is_file():
        raise RuntimeError("Required installation files are missing.")
    environment = root / ".venv"
    # Never follow a user-created link to another environment.
    if environment.is_symlink() or (hasattr(environment, "is_junction") and environment.is_junction()):
        raise RuntimeError("The private environment must not be a link or junction.")
    print("Creating PuryF's private Python environment...", flush=True)
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                    "-r", str(root / "requirements.txt")], check=True)
    subprocess.run([str(python), "-c", "import tkinter, PIL, pypdf, reportlab, cryptography; from puryf import ConversionService; from puryf.cli import build_parser; from puryf.gateway import Gateway; from puryf.mcp_server import Protocol; build_parser(); from PIL import ImageTk; import tkinterdnd2"], check=True)
    print("PuryF runtime installed successfully.", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: runtime_setup.py INSTALL_DIRECTORY")
    try:
        setup(sys.argv[1])
    except Exception as error:
        print(f"PuryF setup failed: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
