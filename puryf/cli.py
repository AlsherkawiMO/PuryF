# SPDX-License-Identifier: MIT
"""Headless CLI adapter. All conversion and PDF work uses ConversionService."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

from . import __version__

class UsageError(ValueError):
    pass

class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)

def presentation(parser, root=False):
    default = False if root else argparse.SUPPRESS
    parser.add_argument('--json', action='store_true', default=default, help='one JSON result on stdout')
    parser.add_argument('--quiet', action='store_true', default=default, help='suppress progress and human summary')

def options(parser, convert=False):
    parser.add_argument('--overwrite', action='store_true', help='allow replacing outputs, never job sources')
    parser.add_argument('--password-env', metavar='NAME', help='encrypt output using password from an environment variable')
    if convert:
        parser.add_argument('-o','--output-dir', help='output folder (default: beside each source)')
        parser.add_argument('--preset','--quality',help='named preset: Original, Print, Balanced, Small or a saved name')
        parser.add_argument('--name',default='{stem}',help='batch filename pattern')
        parser.add_argument('--preserve-folders',action='store_true')
        parser.add_argument('--source-root',default='')
        parser.add_argument('--merge', action='store_true', help='also merge generated PDFs')
        parser.add_argument('--compress', action='store_true')
        parser.add_argument('--ocr', action='store_true')
        parser.add_argument('--ocr-language', default='eng')
        parser.add_argument('--image-paper', choices=['Original size','A4','Letter'], default='Original size')
        parser.add_argument('--excel-fit-width', action='store_true')
        parser.add_argument('--ppt-layout', default='Full-page slides', help='layout name; see CLI.md')
        parser.add_argument('--ppt-date-mode', default='Remove date', help='Remove date, Keep existing date, or Add today\'s date')
        parser.add_argument('--timeout', type=int, default=900, help='external command timeout, seconds')
    else:
        parser.add_argument('--input-password-env', metavar='NAME', help='password for encrypted source PDFs')

def build_parser():
    parser = Parser(prog='puryf', description='PuryF local PDF toolkit. GUI, conversions and PDF tools.')
    parser.add_argument('--version', action='version', version='PuryF '+__version__)
    presentation(parser, True)
    parser.add_argument('--state-dir',help='local presets/history directory')
    parser.add_argument('--plugin',action='append',default=[],help='explicitly load a trusted Python converter extension')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    gui = commands.add_parser('gui', help='launch or reuse the desktop window')
    presentation(gui); gui.add_argument('inputs', nargs='*'); gui.add_argument('--convert', action='store_true', help='convert files instead of adding waiting rows')
    convert = commands.add_parser('convert', help='convert files or folders')
    presentation(convert); options(convert, True)
    convert.add_argument('inputs', nargs='+'); convert.add_argument('-r','--recursive', action='store_true')
    merge = commands.add_parser('merge', help='merge PDFs in the given order')
    presentation(merge); options(merge)
    merge.add_argument('inputs', nargs='+'); merge.add_argument('-o','--output', required=True)
    split = commands.add_parser('split', help='extract page ranges or split into intervals')
    presentation(split); options(split)
    split.add_argument('source'); mode = split.add_mutually_exclusive_group(required=True)
    mode.add_argument('--pages', help='1-based inclusive ranges, e.g. 1-3,7')
    mode.add_argument('--every', type=int, help='pages per output PDF')
    split.add_argument('-o','--output'); split.add_argument('--output-dir')
    doctor = commands.add_parser('doctor', help='check core, optional converters, and selected inputs')
    presentation(doctor); doctor.add_argument('inputs', nargs='*')
    doctor.add_argument('-r','--recursive', action='store_true')
    doctor.add_argument('--all', action='store_true', help='require all implemented optional format capabilities')
    request = commands.add_parser('request', help='execute a versioned JSON request file; relative paths use its directory')
    presentation(request); request.add_argument('file')
    for name,description in [('mcp','run local stdio MCP'),('serve','run optional local/hosted HTTP API')]:
        command=commands.add_parser(name,help=description)
        command.add_argument('--config',required=True,help='integration JSON configuration')
    from .v1_cli import add_commands
    add_commands(commands)
    return parser

def secret(name):
    if not name:
        return ''
    value = os.environ.get(name)
    if not value:
        raise UsageError('Password environment variable is unset or empty: '+name)
    return value

def path_at(value, base):
    if not isinstance(value, str) or not value or '\0' in value:
        raise UsageError('Paths must be nonempty strings without NUL characters')
    path = Path(value).expanduser()
    return str((path if path.is_absolute() else base/path).resolve())

def normalize(args):
    """The same validated request shape is used for flags and request files."""
    command = args.command
    if command == 'request':
        file = Path(args.file).expanduser().resolve()
        try:
            if file.stat().st_size > 16*1024*1024:
                raise UsageError('Request file exceeds 16 MiB')
            data = json.loads(file.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as error:
            raise UsageError('Cannot read JSON request file: '+str(error)) from error
        base = file.parent
    else:
        base = Path.cwd()
        data = {'version':1, 'command':command, 'inputs':getattr(args,'inputs',[])}
        if command == 'split':
            data.update(inputs=[args.source], pages=args.pages, every=args.every,
                        output=args.output, output_dir=args.output_dir)
        if command in ('convert','merge','split'):
            data['options'] = {'overwrite':args.overwrite}
            data['password_env'] = args.password_env
            if command == 'convert':
                data['options'].update(output_folder=args.output_dir or '', merge_pdf=args.merge,
                    compress_pdf=args.compress, ocr_pdf=args.ocr, image_paper=args.image_paper,
                    excel_fit_width=args.excel_fit_width, ocr_language=args.ocr_language,
                    ppt_layout=args.ppt_layout, ppt_date_mode=args.ppt_date_mode, command_timeout=args.timeout)
                data['options'].update(naming_pattern=args.name,preserve_folders=args.preserve_folders,source_root=args.source_root)
                if args.preserve_folders and not args.source_root and len(args.inputs)==1 and Path(args.inputs[0]).is_dir():data['options']['source_root']=str(Path(args.inputs[0]).resolve())
                if args.preset:
                    from .engine import APP_DIR
                    from .state import Store
                    from .v1_cli import explicit_options
                    base=Store(args.state_dir or APP_DIR).preset(args.preset)
                    base.update({k:v for k,v in data['options'].items() if k in explicit_options(getattr(args,'_argv',[]))})
                    data['options']=base
            else:
                data['input_password_env'] = args.input_password_env
            if command == 'merge': data['output'] = args.output
        if command in ('convert','doctor'): data['recursive'] = args.recursive
        if command == 'doctor': data['all'] = args.all
        if command == 'gui': data['convert'] = args.convert
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        raise UsageError('Request must be an object with version: 1')
    command = data.get('command')
    allowed = {'convert': {'recursive','options','password_env'},
               'merge': {'options','output','password_env','input_password_env'},
               'split': {'options','output','output_dir','pages','every','password_env','input_password_env'},
               'doctor': {'recursive','all'}, 'gui': {'convert'}}
    if not isinstance(command,str) or command not in allowed or (args.command == 'request' and command == 'gui'):
        raise UsageError('Request command must be convert, merge, split or doctor')
    unknown = set(data) - {'version','command','inputs'} - allowed[command]
    if unknown: raise UsageError('Unknown request fields: '+', '.join(sorted(unknown)))
    data = dict(data)
    inputs = data.get('inputs',[])
    if not isinstance(inputs,list) or len(inputs) > 100000:
        raise UsageError('inputs must be a list of at most 100000 paths')
    data['inputs'] = [path_at(p,base) for p in inputs]
    if command not in ('doctor','gui') and not inputs:
        raise UsageError('At least one input is required')
    for key in ('recursive','all','convert'):
        if key in data and not isinstance(data[key],bool): raise UsageError(key+' must be boolean')
    for key in ('output','output_dir'):
        if data.get(key) is not None: data[key] = path_at(data[key],base)
    for key in ('password_env','input_password_env'):
        if data.get(key) is not None and (not isinstance(data[key],str) or not data[key]):
            raise UsageError(key+' must name an environment variable')
    if command in ('convert','merge','split'):
        from .options import ConversionOptions
        config = data.get('options',{})
        if not isinstance(config,dict): raise UsageError('options must be an object')
        config = dict(config)
        if 'pdf_password' in config or 'password_pdf' in config:
            raise UsageError('Use password_env instead of password values/toggles in requests')
        password = secret(data.get('password_env'))
        if password: config.update(password_pdf=True,pdf_password=password)
        if config.get('output_folder'): config['output_folder'] = path_at(config['output_folder'],base)
        if config.get('source_root'): config['source_root'] = path_at(config['source_root'],base)
        if command != 'convert' and any(config.get(k) for k in ('output_folder','merge_pdf','compress_pdf','ocr_pdf')):
            raise UsageError('PDF merge/split do not accept conversion output_folder/merge/compress/OCR options')
        data['_options'] = ConversionOptions.from_mapping(config)
        data['_input_password'] = secret(data.get('input_password_env'))
    if command == 'merge' and not data.get('output'): raise UsageError('Merge requires output')
    if command == 'split':
        if len(inputs) != 1: raise UsageError('Split requires exactly one input')
        if data.get('every') is not None:
            n = data['every']
            if type(n) is not int or n < 1 or not data.get('output_dir') or data.get('pages') is not None or data.get('output') is not None:
                raise UsageError('Use --every POSITIVE_INTEGER with --output-dir only')
        elif not isinstance(data.get('pages'),str) or not data['pages'].strip() or not data.get('output') or data.get('output_dir') is not None:
            raise UsageError('Use --pages RANGES with --output only')
    return data

def expand_inputs(inputs, recursive=False, output_dir=''):
    """Snapshot inputs before starting; deterministic folder scan, no linked dirs."""
    from .engine import ALL_EXTS
    supported = ALL_EXTS - {'.zip','.dwg','.dxf','.url'}
    found = []; errors = []; ignored = 0; seen = set()
    target = Path(output_dir).resolve() if output_dir else None
    def add(path):
        key = os.path.normcase(str(path))
        if key not in seen:
            found.append(str(path)); seen.add(key)
    def failure(error):
        errors.append({'code':'scan_failed','source':str(getattr(error,'filename','') or ''),'message':str(error)})
    for value in inputs:
        root = Path(value)
        if not root.is_dir():
            add(root); continue  # explicit unsupported/missing inputs become per-item errors
        for folder, directories, files in os.walk(root, followlinks=False, onerror=failure):
            directories[:] = sorted(d for d in directories if not (Path(folder)/d).is_symlink()
                and not (target is not None and target != root and (Path(folder)/d).resolve() == target)) if recursive else []
            for name in sorted(files):
                file = Path(folder)/name
                if file.suffix.lower() in supported and not name.startswith('~$'):
                    try: add(file.resolve())
                    except (OSError, RuntimeError) as error: failure(error)
                else: ignored += 1
    return found, {'ignored':ignored, 'errors':errors, 'count':len(found)}

def doctor(data):
    from . import engine
    from .jobs import ConversionService
    from .options import ConversionOptions
    sources, scan = expand_inputs(data['inputs'],data.get('recursive',False))
    core = [{'name':name,'ready':engine.module_available(module)} for name,module in
            [('Pillow','PIL'),('pypdf','pypdf'),('ReportLab','reportlab'),('cryptography','cryptography')]]
    inspector = engine.ConverterEngine(ConversionOptions().engine_settings(),lambda s:None,
                                     lambda *a:None,lambda *a:None,threading.Event())
    capabilities = []
    for ext in sorted(engine.ALL_EXTS - {'.zip','.dwg','.dxf','.url'}):
        issues = inspector.requirements(Path('sample'+ext))
        capabilities.append({'extension':ext,'ready':not issues,'issues':issues})
    with ConversionService() as service:
        checks = service.check_dependencies(sources)
    ready = all(c['ready'] for c in core) and all(c['ready'] for c in checks) and not scan['errors']
    if data.get('all'): ready = ready and all(c['ready'] for c in capabilities)
    if data['inputs'] and not sources: ready = False
    return {'ready':ready,'core':core,'capabilities':capabilities,'inputs':checks,'scan':scan,
            'gui_module_available':engine.module_available('tkinter'),
            'notes':['Optional converters are reported but not required unless selected or --all is used.',
                     'Office checks verify registration and pywin32, not an actual Office conversion.',
                     'GUI availability checks the module, not display connectivity.']}

def result_exit(result):
    if result['status'] == 'cancelled': return 130
    if result['status'] == 'succeeded':
        return 4 if any(i['status'] == 'Skipped' for i in result['inputs']) else 0
    if result['status'] == 'partial': return 4
    if result['status'] == 'skipped': return 5
    if result['errors'] and all(e['code']=='dependency_missing' for e in result['errors']): return 3
    return 1

def run_job(data, stream, progress=True):
    from .jobs import ConversionService, TERMINAL
    command = data['command']
    scan = {'count':len(data['inputs']),'ignored':0,'errors':[]}
    if command == 'convert':
        data['inputs'],scan = expand_inputs(data['inputs'],data.get('recursive',False),data['_options'].output_folder)
        if not data['inputs']:
            raise UsageError('No supported files found in the selected folders')
    with ConversionService() as service:
        events = service.subscribe()
        if command == 'convert': handle = service.submit_conversion(data['inputs'],data['_options'],origin='cli')
        elif command == 'merge':
            passwords = {p:data['_input_password'] for p in data['inputs']}
            handle = service.submit_merge(data['inputs'],data['output'],data['_options'],passwords=passwords,origin='cli')
        else:
            handle = service.submit_split(data['inputs'][0],data['_options'],output_file=data.get('output'),
                output_dir=data.get('output_dir'),page_ranges=data.get('pages'),every_n=data.get('every'),
                password=data['_input_password'],origin='cli')
        if progress: print('Queued '+command+' job '+handle.id, file=stream,flush=True)
        interrupted = False
        last_progress = None
        while True:
            try:
                try:
                    event = events.get(timeout=.1)
                    if progress and event['type'] == 'progress':
                        value = event['progress']
                        last_progress = dict(value)
                        print(f"{value['percent']:3}%  {value['completed']}/{value['total']}  {value['current']}",file=stream,flush=True)
                    elif progress and event['type'] == 'log' and 'Waiting for' in event['message']:
                        print(event['message'],file=stream,flush=True)
                except queue.Empty:
                    pass
                if handle.snapshot()['status'] in TERMINAL: break
            except KeyboardInterrupt:
                interrupted = True
                handle.cancel()
                if progress: print('Cancelling; an active Office call must return before cleanup.',file=stream,flush=True)
        result = handle.snapshot()
        if progress and result['progress'] != last_progress:
            value = result['progress']
            print(f"{value['percent']:3}%  {value['completed']}/{value['total']}  {value['current']}",file=stream,flush=True)
        service.unsubscribe(events)
    from .state import Store
    from .engine import APP_DIR
    Store(data.get('_state_dir') or APP_DIR).record(result)
    code = 130 if interrupted else result_exit(result)
    if scan['errors'] and code == 0: code = 4
    return {'result':result,'scan':scan},code

def gui(data):
    launcher = Path(__file__).resolve().parent.parent/'PuryF.py'
    python = Path(sys.executable)
    if os.name == 'nt' and python.with_name('pythonw.exe').is_file(): python = python.with_name('pythonw.exe')
    arguments = [str(Path(sys.executable).with_name('PuryF.exe'))] if getattr(sys,'frozen',False) else [str(python),str(launcher)]
    if not getattr(sys,'frozen',False) and not launcher.exists():arguments=[str(python),'-c','from puryf.explorer import launch; raise SystemExit(launch())']
    if data['inputs']: arguments += ['--explorer-convert' if data.get('convert') else '--explorer-queue','--',*data['inputs']]
    child = subprocess.Popen(arguments,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        start_new_session=os.name!='nt',creationflags=0x08000000 if os.name=='nt' else 0)
    return {'status':'launch_requested','pid':child.pid}

def emit(payload, stream, quiet, json_mode):
    if json_mode:
        print(json.dumps(payload,ensure_ascii=True),file=stream,flush=True)
    elif 'error' in payload:
        print('Error: '+payload['error']['message'],file=stream)
    elif not quiet:
        if 'result' in payload:
            job = payload['result']
            print(f"{job['status']}: {len(job['outputs'])} output(s); job {job['id']}",file=stream)
            for output in job['outputs']: print(output['path'],file=stream)
            for error in job['errors']: print(error['code']+': '+error['message'],file=stream)
            for item in job['inputs']:
                if item['status'] in ('Skipped','Cancelled'):
                    print(item['source']+': '+item['status']+': '+item['message'],file=stream)
            for error in payload['scan']['errors']: print(error['code']+': '+error['message'],file=stream)
        elif 'doctor' in payload:
            report = payload['doctor']
            print('Dependencies: '+('ready' if report['ready'] else 'issues found'),file=stream)
            for item in report['core']: print(('OK ' if item['ready'] else 'MISSING ')+item['name'],file=stream)
            for item in report['inputs']:
                print(item['source']+': '+('; '.join(item['issues']) or 'ready'),file=stream)
            unavailable = [c['extension'] for c in report['capabilities'] if not c['ready']]
            if unavailable: print('Unavailable optional formats: '+', '.join(unavailable),file=stream)
            for issue in sorted({issue for c in report['capabilities'] for issue in c['issues']}):
                print('Optional requirement: '+issue,file=stream)
            for note in report['notes']: print(note,file=stream)
        elif payload.get('status')=='launch_requested': print('GUI launch requested.',file=stream)
        else: print(json.dumps(payload,indent=2,ensure_ascii=True),file=stream)

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out,err = sys.stdout,sys.stderr
    json_mode = '--json' in argv; quiet = '--quiet' in argv
    command = None
    try:
        args = build_parser().parse_args(argv)
        args._argv=argv
        if args.plugin:
            if args.command in ('serve','mcp'):raise UsageError('Load extensions only in trusted local desktop/CLI automation hosts')
            from .extensions import load
            for path in args.plugin:load(path)
        json_mode,quiet = args.json,args.quiet
        from .v1_cli import dispatch,COMMANDS
        if args.command in COMMANDS:
            body,code=dispatch(args,err)
            emit({'schema_version':1,'command':args.command,'exit_code':code,**body},out,args.quiet,args.json)
            return code
        if args.command in ('mcp','serve'):
            if args.json: raise UsageError('Integration servers use their own transport output; omit --json')
            if args.command=='mcp':
                from .mcp_server import run
            else:
                from .http_server import run
            run(args.config)
            return 0
        data = normalize(args); data['_state_dir']=args.state_dir; command = data['command']
        if command == 'doctor':
            report = doctor(data); code = 0 if report['ready'] else 3
            body = {'doctor':report}
        elif command == 'gui': body,code = gui(data),0
        else: body,code = run_job(data,err,progress=not json_mode and not quiet)
        payload = {'schema_version':1,'command':command,'exit_code':code,**body}
    except (UsageError,ValueError) as error:
        code = 2; payload = {'schema_version':1,'command':command,'exit_code':code,'error':{'code':'invalid_request','message':str(error)}}
    except KeyboardInterrupt:
        code = 130; payload = {'schema_version':1,'command':command,'exit_code':code,'error':{'code':'cancelled','message':'Interrupted before submission'}}
    except OSError as error:
        code = 1; payload = {'schema_version':1,'command':command,'exit_code':code,'error':{'code':'io_error','message':str(error)}}
    except Exception:
        code = 70; payload = {'schema_version':1,'command':command,'exit_code':code,'error':{'code':'internal_error','message':'Unexpected internal failure; run puryf doctor and inspect the job report.'}}
    emit(payload,err if 'error' in payload and not json_mode else out,quiet,json_mode)
    return code
