# SPDX-License-Identifier: MIT
"""PDF Studio operations. PDFium rendering + pypdf editing; originals stay intact."""
from contextlib import nullcontext
import io
import json
import math
import os
from pathlib import Path
import tempfile
import threading

from .engine import PdfReader,PdfWriter,ConversionCancelled,parse_page_ranges
from .options import ConversionOptions
from .pdf_tools import read_pdf,_save

_RENDER_LOCK=threading.RLock()

def cancelled(event):
    if event.is_set():raise ConversionCancelled('Document operation cancelled')

def validate_spec(spec,source_count):
    if not isinstance(spec,dict) or not isinstance(spec.get('action'),str):raise ValueError('Document spec requires action')
    allowed={'compose':{'pages','output','title','course_pack','page_numbers'},
        'decorate':{'output','watermark','logo','header','footer','page_numbers'},
        'metadata':{'output','metadata','remove_metadata'},
        'text':{'output','reviewed_text'},'export':{'output_dir','format','dpi','pages'},
        'compress':{'output','target_bytes','allow_raster'}}
    action=spec['action']
    if action not in allowed or set(spec)-{'action'}-allowed[action]:raise ValueError('Invalid document action or fields')
    if source_count<1 or action!='compose' and source_count!=1:raise ValueError('This action requires one PDF; compose accepts several')
    result=dict(spec)
    for key in ('output','output_dir','logo'):
        if key in result and result[key]:result[key]=str(Path(result[key]).expanduser().resolve())
    if action=='export':
        if not result.get('output_dir') or result.get('format','png') not in ('png','jpeg'):raise ValueError('Export requires output_dir and png/jpeg format')
        if type(result.get('dpi',144)) is not int or not 36<=result.get('dpi',144)<=300:raise ValueError('DPI must be 36..300')
    elif not result.get('output'):raise ValueError('Output path is required')
    if action=='compress' and (type(result.get('target_bytes')) is not int or result['target_bytes']<1024):raise ValueError('Compression requires target_bytes >= 1024')
    for key in ('course_pack','page_numbers','remove_metadata','allow_raster'):
        if key in result and not isinstance(result[key],bool):raise ValueError(key+' must be boolean')
    return result

def inspect(path,password=''):
    reader=read_pdf(path,password)
    bookmarks=[]
    def walk(items,depth=0):
        for item in items:
            if isinstance(item,list):walk(item,depth+1)
            else:
                try:bookmarks.append({'title':str(item.title),'page':reader.get_destination_page_number(item),'depth':depth})
                except (ValueError,AttributeError):pass
    walk(reader.outline)
    return {'pages':len(reader.pages),'encrypted':reader.is_encrypted,
        'metadata':{str(k):str(v) for k,v in dict(reader.metadata or {}).items()},'bookmarks':bookmarks,
        'page_sizes':[(float(p.mediabox.width),float(p.mediabox.height)) for p in reader.pages]}

def render(path,page=0,width=760,password='',dpi=None):
    import pypdfium2 as pdfium
    with _RENDER_LOCK:
        pdf=pdfium.PdfDocument(str(path),password=password or None)
        try:
            if type(page) is not int or not 0<=page<len(pdf):raise ValueError('Page index is out of range')
            leaf=pdf[page]
            try:
                w,h=leaf.get_size();scale=dpi/72 if dpi else width/max(w,1)
                if w*h*scale*scale>25_000_000:scale=(25_000_000/(w*h))**.5
                bitmap=leaf.render(scale=scale)
                try:return bitmap.to_pil().convert('RGB').copy()
                finally:bitmap.close()
            finally:leaf.close()
        finally:pdf.close()

def commit_bytes(data,output,sources,event,guard=None):
    output=Path(output).resolve()
    if output in {Path(p).resolve() for p in sources}:raise ValueError('Output must differ from sources')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.puryf_doc_',dir=output.parent) as folder:
        staged=Path(folder)/'result';staged.write_bytes(data);cancelled(event)
        with guard(output) if guard else nullcontext():
            cancelled(event);os.link(staged,output)
    return output

def font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import sys
    candidates=[Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))/'assets/DejaVuSans.ttf',
        Path(__file__).resolve().parent/'assets/DejaVuSans.ttf',
        Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/arial.ttf',Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    path=next((p for p in candidates if p.is_file()),None)
    if path:
        if 'PuryFStudio' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('PuryFStudio',str(path)))
        return 'PuryFStudio'
    return 'Helvetica'

def display(text):
    if any('\u0600'<=c<='\u06ff' for c in text):
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    return text

def stamp(writer,settings,event):
    from reportlab.pdfgen.canvas import Canvas
    name=font();count=len(writer.pages)
    for index,page in enumerate(writer.pages):
        cancelled(event)
        page.transfer_rotation_to_content()
        w,h=float(page.mediabox.width),float(page.mediabox.height)
        data=io.BytesIO();canvas=Canvas(data,pagesize=(w,h));canvas.setFont(name,10)
        for text,y in [(settings.get('header',''),h-22),(settings.get('footer',''),18)]:
            if text:canvas.drawCentredString(w/2,y,display(text))
        if settings.get('page_numbers'):canvas.drawRightString(w-22,18,f'{index+1} / {count}')
        if settings.get('watermark'):
            canvas.saveState();canvas.setFillAlpha(.18);canvas.setFont(name,max(18,min(w/8,64)))
            canvas.translate(w/2,h/2);canvas.rotate(35);canvas.drawCentredString(0,0,display(settings['watermark']));canvas.restoreState()
        if settings.get('logo'):
            canvas.drawImage(settings['logo'],22,h-80,width=64,height=48,preserveAspectRatio=True,mask='auto')
        canvas.save();page.merge_page(PdfReader(io.BytesIO(data.getvalue())).pages[0])

def compose(paths,readers,spec,event):
    refs=spec.get('pages')
    if refs is None:refs=[{'source':n,'page':i,'rotation':0} for n,r in enumerate(readers) for i in range(len(r.pages))]
    if not isinstance(refs,list) or not refs:raise ValueError('Choose at least one page')
    normalized=[]
    for ref in refs:
        if not isinstance(ref,dict) or set(ref)-{'source','page','rotation'}:raise ValueError('Invalid page reference')
        source=ref.get('source');page=ref.get('page');rotation=ref.get('rotation',0)
        if type(source) is not int or not 0<=source<len(readers) or type(page) is not int or not 0<=page<len(readers[source].pages) or type(rotation) is not int or rotation%90:raise ValueError('Invalid page index/rotation')
        normalized.append((source,page,rotation))
    writer=PdfWriter();starts=[];seen=set();toc_pages=0
    if spec.get('course_pack'):
        from reportlab.pdfgen.canvas import Canvas
        entries=[]
        for pos,(source,_,_) in enumerate(normalized):
            if source not in seen:entries.append((source,pos));seen.add(source)
        toc_pages=max(1,math.ceil(len(entries)/36));data=io.BytesIO();canvas=Canvas(data,pagesize=(595,842));name=font()
        for toc in range(toc_pages):
            canvas.setFont(name,22);canvas.drawString(40,790,display(spec.get('title') or 'Course pack'))
            canvas.setFont(name,11)
            for offset,(source,pos) in enumerate(entries[toc*36:(toc+1)*36]):
                title=display(paths[source].stem[:65]);y=748-offset*18
                canvas.drawString(40,y,title);canvas.drawRightString(555,y,str(pos+toc_pages+1))
            canvas.showPage()
        canvas.save()
        for page in PdfReader(io.BytesIO(data.getvalue())).pages:writer.add_page(page)
        writer.add_outline_item('Contents',0)
        from pypdf.annotations import Link
        for entry,(source,pos) in enumerate(entries):
            writer.add_annotation(entry//36,Link(rect=(35,744-(entry%36)*18,560,761-(entry%36)*18),target_page_index=pos+toc_pages))
    seen=set();mapping={}
    for source,page_index,rotation in normalized:
        cancelled(event);position=len(writer.pages)
        page=writer.add_page(readers[source].pages[page_index])
        if rotation:page.rotate(rotation)
        mapping.setdefault((source,page_index),position)
        if source not in seen:
            writer.add_outline_item(paths[source].stem,position);seen.add(source)
    for source,reader in enumerate(readers):
        def bookmarks(items,parent=None):
            for item in items:
                if isinstance(item,list):bookmarks(item,parent)
                else:
                    try:
                        key=(source,reader.get_destination_page_number(item))
                        if key in mapping:parent=writer.add_outline_item(str(item.title),mapping[key],parent=None)
                    except (ValueError,AttributeError):pass
        bookmarks(reader.outline)
    if spec.get('page_numbers') or spec.get('course_pack'):stamp(writer,{'page_numbers':True},event)
    writer.add_metadata({'/Title':spec.get('title','') or 'PuryF document'})
    return writer

def run(paths,spec,options,event,passwords=None,progress=None,guard=None):
    paths=[Path(p).resolve() for p in paths];spec=validate_spec(spec,len(paths));passwords=passwords or {}
    readers=[read_pdf(p,passwords.get(str(p),'')) for p in paths];action=spec['action']
    progress=progress or (lambda *args:None)
    if action=='export':
        pages=parse_page_ranges(spec['pages'],len(readers[0].pages)) if spec.get('pages') else range(len(readers[0].pages))
        pages=list(pages)
        for index,n in enumerate(pages):
            cancelled(event);image=render(paths[0],n,password=passwords.get(str(paths[0]),''),dpi=spec.get('dpi',144))
            data=io.BytesIO();kind=spec.get('format','png');image.save(data,format='PNG' if kind=='png' else 'JPEG',quality=90)
            output=Path(spec['output_dir'])/f'{paths[0].stem}-page-{n+1}.{kind}'
            yield commit_bytes(data.getvalue(),output,paths,event,guard),{}
            progress(index+1,len(pages),f'Page {n+1}')
        return
    if action=='text':
        text=spec.get('reviewed_text')
        if text is None:text='\n\n'.join(p.extract_text() or '' for p in readers[0].pages)
        if not isinstance(text,str):raise ValueError('Reviewed text must be a string')
        yield commit_bytes(text.encode('utf-8'),spec['output'],paths,event,guard),{}
        return
    if action=='compose':writer=compose(paths,readers,spec,event)
    else:
        writer=PdfWriter();writer.append(readers[0])
        if action=='decorate':stamp(writer,spec,event)
        elif action=='metadata':
            if spec.get('remove_metadata'):
                writer.metadata=None
                writer.root_object.pop('/Metadata',None)
                for page in writer.pages:page.pop('/Metadata',None)
            else:
                values=spec.get('metadata',{})
                if not isinstance(values,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in values.items()):raise ValueError('Metadata requires string keys/values')
                writer.add_metadata({('/'+k.lstrip('/')):v for k,v in values.items()})
        elif action=='compress':
            for page in writer.pages:
                cancelled(event);page.compress_content_streams()
            writer.compress_identical_objects()
            stream=io.BytesIO();writer.write(stream);best=stream.getvalue()
            # Optional lossy raster attempts. Never silently discard selectable text.
            if len(best)>spec['target_bytes'] and spec.get('allow_raster'):
                from reportlab.pdfgen.canvas import Canvas
                from reportlab.lib.utils import ImageReader
                for dpi,quality in [(144,85),(110,70),(90,55),(72,40),(50,25)]:
                    cancelled(event);stream=io.BytesIO();canvas=Canvas(stream)
                    for index,page in enumerate(readers[0].pages):
                        progress(index+1,len(readers[0].pages),f'Raster attempt {dpi} DPI · page {index+1}')
                        cancelled(event);image=render(paths[0],index,password=passwords.get(str(paths[0]),''),dpi=dpi)
                        jpeg=io.BytesIO();image.save(jpeg,'JPEG',quality=quality,optimize=True)
                        w,h=float(page.mediabox.width),float(page.mediabox.height)
                        if int(page.get('/Rotate',0))%180:w,h=h,w
                        canvas.setPageSize((w,h));canvas.drawImage(ImageReader(io.BytesIO(jpeg.getvalue())),0,0,w,h);canvas.showPage()
                    canvas.save();candidate=stream.getvalue()
                    if len(candidate)<len(best):best=candidate
                    if len(best)<=spec['target_bytes']:break
                writer=PdfWriter();writer.append(PdfReader(io.BytesIO(best)))
                if readers[0].metadata:writer.add_metadata({str(k):str(v) for k,v in readers[0].metadata.items() if v is not None})
                for entry in inspect(paths[0],passwords.get(str(paths[0]),''))['bookmarks']:
                    if entry['page'] is not None and 0<=entry['page']<len(writer.pages):writer.add_outline_item(entry['title'],entry['page'])
    output=_save(writer,spec['output'],paths,options,event,guard)
    progress(1,1,Path(output).name)
    details={}
    if action=='compress':details={'target_bytes':spec['target_bytes'],'actual_bytes':output.stat().st_size,'target_met':output.stat().st_size<=spec['target_bytes'],'raster_allowed':spec.get('allow_raster',False)}
    yield output,details
