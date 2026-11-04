# Build on the target OS. Windows output is PuryF.exe + PuryF-cli.exe.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all,collect_submodules
root=Path(SPECPATH)
datas=[(str(root/'assets'),'assets')]
binaries=[];hidden=collect_submodules('puryf')
for package in ('pypdfium2','pypdfium2_raw','tkinterdnd2'):
 d,b,h=collect_all(package);datas+=d;binaries+=b;hidden+=h
common=dict(pathex=[str(root)],binaries=binaries,datas=datas,hiddenimports=hidden,
 excludes=['cv2','torch','tensorflow','pandas','scipy','matplotlib','rawpy','cairosvg','pillow_heif'])
gui=Analysis([str(root/'PuryF.py')],**common)
cli=Analysis([str(root/'PuryF_CLI.py')],**common)
gui_exe=EXE(PYZ(gui.pure),gui.scripts,[],exclude_binaries=True,name='PuryF',console=False,icon=str(root/'assets/PuryF.ico'))
cli_exe=EXE(PYZ(cli.pure),cli.scripts,[],exclude_binaries=True,name='PuryF-cli',console=True,icon=str(root/'assets/PuryF.ico'))
COLLECT(gui_exe,cli_exe,gui.binaries,gui.datas,cli.binaries,cli.datas,name='PuryF')
