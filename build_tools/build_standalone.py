# SPDX-License-Identifier: MIT
"""Native Windows build, portable packaging, notices and installer compilation."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def licenses(destination):
    destination.mkdir(parents=True,exist_ok=True)
    for dist in importlib.metadata.distributions():
        name=dist.metadata.get('Name','unknown').replace('/','_')
        for entry in dist.files or []:
            if any(x in str(entry).lower() for x in ('license','copying','notice','copyright')):
                source=Path(dist.locate_file(entry))
                if source.is_file() and source.stat().st_size<5*1024*1024:
                    target=destination/name/str(entry).replace('..','_');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    for source in [Path(sys.base_prefix)/'LICENSE.txt',*Path(sys.base_prefix).glob('tcl/**/license.terms')]:
        if source.is_file():shutil.copy2(source,destination/('Python-'+source.parent.name+'-'+source.name))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native-smoke-only',action='store_true');args=parser.parse_args()
    if sys.platform!='win32' and not args.native_smoke_only:raise SystemExit('Windows EXEs must be built on Windows. Run Build_Standalone_Windows.bat there.')
    required=('PIL','pypdf','pypdfium2','reportlab','cryptography','arabic_reshaper','bidi','tkinter')
    missing=[name for name in required if importlib.util.find_spec(name) is None]
    if missing:raise SystemExit('Missing build dependencies: '+', '.join(missing)+'. Install requirements.txt before building.')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean',str(ROOT/'PuryF.spec')],cwd=ROOT,check=True)
    folder=ROOT/'dist/PuryF'
    if not folder.is_dir():
        raise RuntimeError(f'PyInstaller payload is missing: {folder}. Check the PyInstaller build log.')
    required_payload=('PuryF.exe','PuryF-cli.exe','_internal')
    missing=[name for name in required_payload if not (folder/name).exists()]
    if missing:
        raise RuntimeError('Frozen payload is incomplete; missing: '+', '.join(missing))
    for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md','Verify_Clean_PC.bat'):shutil.copy2(ROOT/name,folder/name)
    for name in ('examples','integration-configs'):shutil.copytree(ROOT/name,folder/name,dirs_exist_ok=True)
    shutil.copytree(ROOT/'docs/screenshots',folder/'docs/screenshots',dirs_exist_ok=True)
    licenses(folder/'THIRD_PARTY_LICENSES')
    executable=folder/('PuryF-cli.exe' if sys.platform=='win32' else 'PuryF-cli')
    result=subprocess.run([str(executable),'self-test','--json'],capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Bundled smoke failed: '+result.stdout+' '+result.stderr)
    report=json.loads(result.stdout)
    if not report['self_test']['core_passed'] or not report['self_test']['frozen']:raise RuntimeError('Bundled core smoke test failed')
    release=ROOT/'release';release.mkdir(exist_ok=True)
    (release/'bundle-smoke.json').write_text(json.dumps(report,indent=2))
    if args.native_smoke_only:return
    portable=ROOT/'build/portable/PuryF';shutil.copytree(folder,portable,dirs_exist_ok=True)
    (portable/'portable.marker').write_text('PuryF portable v1')
    zip_path=release/'PuryF-v1-Windows-portable.zip'
    with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in portable.rglob('*'):
            if path.is_file():archive.write(path,Path('PuryF')/path.relative_to(portable))
    nsis=shutil.which('makensis')
    if nsis is None:
        nsis=next((str(p) for p in [Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'NSIS/makensis.exe',Path(os.environ.get('ProgramFiles','C:/Program Files'))/'NSIS/makensis.exe'] if p.exists()),None)
    if nsis is None:raise RuntimeError('Install NSIS to compile the standalone installer. Portable ZIP is already built.')
    # The NSIS scripts deliberately move from installer\ to the project root.
    # Invoke makensis from installer\ so every relative File/OutFile path has
    # one deterministic base, independent of the caller's working directory.
    subprocess.run([nsis,'standalone.nsi'],cwd=ROOT/'installer',check=True)
    source_setup=release/'PuryF-v1-Source-Setup.exe'
    files=[release/'PuryF-v1-Setup.exe',zip_path]
    if source_setup.exists():
        files.append(source_setup)
    missing=[str(path) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError('NSIS/package output is missing: '+', '.join(missing))
    (release/'SHA256SUMS.txt').write_text('\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name for p in files)+'\n')
    (release/'downloads.json').write_text(json.dumps({'version':'1.0.0','main_download':'PuryF-v1-Setup.exe','portable':'PuryF-v1-Windows-portable.zip',
       'status':'candidate; run Verify_Clean_PC.bat on Windows without Python before publishing'},indent=2))
    print('Built standalone installer and portable ZIP in release/. Native clean-PC validation is still required.')
if __name__=='__main__':main()
