# SPDX-License-Identifier: MIT
"""V1 document/automation CLI commands, keeping legacy command contracts intact."""
import argparse
import json
from pathlib import Path
import time
from .engine import APP_DIR
from .sdk import Client
from .state import Store,duplicates
from .jobs import TERMINAL

COMMANDS={'document','inspect','preflight','preset','history','background','background-control','diagnostics','self-test','installation'}

def explicit_options(argv):
    mapping={'-o':'output_folder','--output-dir':'output_folder','--overwrite':'overwrite','--merge':'merge_pdf','--compress':'compress_pdf',
    '--ocr':'ocr_pdf','--ocr-language':'ocr_language','--image-paper':'image_paper','--excel-fit-width':'excel_fit_width',
    '--ppt-layout':'ppt_layout','--ppt-date-mode':'ppt_date_mode','--timeout':'command_timeout','--name':'naming_pattern',
    '--preserve-folders':'preserve_folders','--source-root':'source_root','--password-env':'password_pdf'}
    fields={mapping[arg.split('=')[0]] for arg in argv if arg.split('=')[0] in mapping}
    if 'preserve_folders' in fields:fields.add('source_root')
    if 'password_pdf' in fields:fields.add('pdf_password')
    return fields

def add_commands(commands):
    from .cli import presentation
    for name in COMMANDS:
        parser=commands.add_parser(name,help={'document':'PDF Studio operation from a JSON spec','background':'watch folders and interval schedules','background-control':'pause/resume/stop/retry the background queue'}.get(name,name+' tools'))
        presentation(parser)
        if name=='document':
            parser.add_argument('inputs',nargs='+');parser.add_argument('--spec',required=True);parser.add_argument('--password-env')
        elif name=='inspect':parser.add_argument('source');parser.add_argument('--password-env')
        elif name=='preflight':parser.add_argument('inputs',nargs='+');parser.add_argument('-r','--recursive',action='store_true')
        elif name=='preset':
            parser.add_argument('action',choices=['list','show','save']);parser.add_argument('name',nargs='?');parser.add_argument('--options')
        elif name=='history':parser.add_argument('--repeat');parser.add_argument('--limit',type=int,default=30)
        elif name=='background':parser.add_argument('--config',required=True)
        elif name=='background-control':parser.add_argument('action',choices=['pause','resume','stop','retry']);parser.add_argument('--state',required=True)
        elif name=='diagnostics':parser.add_argument('--output',required=True)
        elif name=='installation':parser.add_argument('action',choices=['guard','path-add','path-remove']);parser.add_argument('--root')
        elif name=='self-test':parser.add_argument('--clean-pc',action='store_true');parser.add_argument('--output')

def wait(client,handle,stream,progress):
    from .cli import result_exit
    last=None;interrupted=False
    while True:
        try:
            result=handle.snapshot()
            if progress and result['progress']!=last:
                last=result['progress'];print(f"{last['percent']}% {last['completed']}/{last['total']}",file=stream)
            if result['status'] in TERMINAL:break
            time.sleep(.1)
        except KeyboardInterrupt:handle.cancel();interrupted=True
    return {'result':result,'scan':{'count':len(result['inputs']),'ignored':0,'errors':[]}},130 if interrupted else result_exit(result)

def dispatch(args,stream):
    from .cli import secret,expand_inputs
    from .documents import inspect,validate_spec,commit_bytes
    import threading
    root=args.state_dir or APP_DIR;store=Store(root);command=args.command
    if command=='installation':
        from .install_support import install_guard,update
        if args.action=='guard':return {'installation_guard':True},install_guard()
        if not args.root:raise ValueError('--root is required')
        update('add' if args.action=='path-add' else 'remove',args.root)
        return {'path_updated':True},0
    if command=='self-test':
        from .selftest import run
        return {'self_test':run(args.clean_pc,args.output)},0
    if command=='inspect':return {'inspection':inspect(args.source,secret(args.password_env))},0
    if command=='preflight':
        paths,scan=expand_inputs(args.inputs,args.recursive)
        with Client(root) as client:checks=client.doctor(paths)
        from .pdf_tools import inspect_pdf
        inspections=[]
        for path in paths:
            if Path(path).suffix.lower()=='.pdf':
                try:inspections.append({'source':path,**inspect_pdf(path)})
                except Exception:inspections.append({'source':path,'readable':False})
        return {'preflight':checks,'inspections':inspections,'duplicates':duplicates(paths),'scan':scan},0 if paths and all(c['ready'] for c in checks) and not scan['errors'] else 3
    if command=='preset':
        if args.action=='list':return {'presets':store.preset_names()},0
        if not args.name:raise ValueError('Preset name is required')
        if args.action=='save':
            if not args.options:raise ValueError('--options JSON file is required')
            store.save_preset(args.name,json.loads(Path(args.options).read_text()))
        return {'name':args.name,'options':store.preset(args.name)},0
    if command=='history' and not args.repeat:return {'history':store.history(args.limit)},0
    if command=='diagnostics':
        output=commit_bytes(json.dumps(store.diagnostic(),indent=2).encode(),args.output,[],threading.Event())
        return {'output':str(output)},0
    if command=='background':
        from .automation import run
        run(args.config);return {'status':'stopped'},0
    if command=='background-control':
        from .automation import control
        control(args.state,args.action);return {'requested':args.action},0
    with Client(root) as client:
        if command=='history':return wait(client,client.repeat(args.repeat),stream,not args.json and not args.quiet)
        spec_file=Path(args.spec).resolve();spec=json.loads(spec_file.read_text(encoding='utf-8-sig'))
        for key in ('output','output_dir','logo'):
            if spec.get(key):spec[key]=str((spec_file.parent/Path(spec[key])).resolve())
        handle=client.document(args.inputs,spec,password=secret(args.password_env))
        return wait(client,handle,stream,not args.json and not args.quiet)
