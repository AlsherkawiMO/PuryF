# SPDX-License-Identifier: MIT
"""Thumbnail page organizer, document preview, bookmarks, text review and PDF tools."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from PIL import ImageTk
from . import documents

class Studio(tk.Toplevel):
    def __init__(self,app,paths=()):
        super().__init__(app);self.app=app;self.title('PuryF v1 — PDF Studio');self.geometry('1120x780');self.minsize(820,560)
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix="PuryF-Preview");self.thumb_count=0
        self.paths=[];self.passwords={};self.refs={};self.images={};self.sequence=0;self.undo=[]
        toolbar=ttk.Frame(self,padding=8);toolbar.pack(fill='x')
        actions=[('Add PDFs',self.add_files),('Up',lambda:self.move(-1)),('Down',lambda:self.move(1)),('Rotate',self.rotate),('Delete',self.delete),('Undo',self.undo_edit),('Save arrangement',self.save),('Extract selection',lambda:self.save(selected=True))]
        for label,command in actions:ttk.Button(toolbar,text=label,command=command).pack(side='left',padx=2)
        tools=ttk.Frame(self,padding=8);tools.pack(fill='x')
        for label,command in [('Course pack',lambda:self.save(course=True)),('Stamp source PDF',self.decorate),('Metadata',self.metadata),('Export images',self.export),('Text / OCR review',self.review),('Target compression',self.compress)]:
            ttk.Button(tools,text=label,command=command).pack(side='left',padx=2)
        self.note=tk.StringVar(value='Add PDFs, select pages, then arrange and save a new document. Source PDFs are never changed.')
        ttk.Label(self,textvariable=self.note,wraplength=1050,padding=8).pack(fill='x')
        panes=ttk.Panedwindow(self,orient='horizontal');panes.pack(fill='both',expand=True,padx=8,pady=8)
        left=ttk.Frame(panes);right=ttk.Frame(panes);panes.add(left,weight=1);panes.add(right,weight=3)
        style=ttk.Style(self);style.configure('Studio.Treeview',rowheight=100)
        self.tree=ttk.Treeview(left,show='tree',selectmode='extended',style='Studio.Treeview');self.tree.pack(side='left',fill='both',expand=True)
        scrollbar=ttk.Scrollbar(left,command=self.tree.yview);scrollbar.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind('<<TreeviewSelect>>',self.preview);self.tree.bind('<Delete>',lambda e:self.delete());self.tree.bind('<Control-z>',lambda e:self.undo_edit())
        tabs=ttk.Notebook(right);tabs.pack(fill='both',expand=True)
        view=ttk.Frame(tabs);tabs.add(view,text='Preview')
        self.canvas=tk.Canvas(view,background='#15171b',highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        outline=ttk.Frame(tabs);tabs.add(outline,text='Bookmarks / Contents')
        self.bookmarks=ttk.Treeview(outline,columns=('page',),show='tree headings');self.bookmarks.heading('#0',text='Bookmark');self.bookmarks.heading('page',text='Page');self.bookmarks.pack(fill='both',expand=True)
        self.bookmark_refs={};self.bookmarks.bind('<<TreeviewSelect>>',self.jump_bookmark)
        for path in paths:self.add(path)
        app.localize_window(self)
    def destroy(self):
        self.pool.shutdown(wait=False,cancel_futures=True)
        super().destroy()
    def source(self):
        selected=self.tree.selection()
        if not selected:raise ValueError('Select a page first')
        ref=self.refs[selected[0]];return self.paths[ref['source']],ref
    def background(self,work,done):
        def run():
            try:value=work();self.app.q.put(('ui',lambda:self.winfo_exists() and done(value)))
            except Exception as error:
                text=str(error);self.app.q.put(('ui',lambda:self.winfo_exists() and self.note.set(text)))
        self.pool.submit(run)
    def add_files(self):
        for path in filedialog.askopenfilenames(parent=self,filetypes=[('PDF','*.pdf')]):self.add(path)
    def add(self,path):
        path=Path(path).resolve();password=''
        try:info=documents.inspect(path)
        except Exception:
            password=simpledialog.askstring('PDF password',path.name,parent=self,show='*')
            if password is None:return
            try:info=documents.inspect(path,password)
            except Exception as error:messagebox.showerror('Cannot read PDF',str(error),parent=self);return
        index=len(self.paths);self.paths.append(path);self.passwords[str(path)]=password
        for page in range(info['pages']):
            iid=self.tree.insert('','end',text=f'{path.name} · {page+1}')
            self.refs[iid]={'source':index,'page':page,'rotation':0}
            if self.thumb_count<48:self.thumbnail(iid);self.thumb_count+=1
        for item in info['bookmarks']:
            iid=self.bookmarks.insert('','end',text='  '*item['depth']+item['title'],values=(item['page']+1,));self.bookmark_refs[iid]=(index,item['page'])
        if self.tree.get_children() and not self.tree.selection():self.tree.selection_set(self.tree.get_children()[0])
    def thumbnail(self,iid):
        ref=dict(self.refs[iid]);path=self.paths[ref['source']]
        def work():
            image=documents.render(path,ref['page'],width=70,password=self.passwords[str(path)]);image.thumbnail((70,88));return image
        def done(image):
            if self.tree.exists(iid):self.images[iid]=ImageTk.PhotoImage(image,master=self);self.tree.item(iid,image=self.images[iid])
        self.background(work,done)
    def preview(self,event=None):
        try:path,ref=self.source()
        except ValueError:return
        self.sequence+=1;sequence=self.sequence;rotation=ref['rotation']
        def done(image):
            if sequence!=self.sequence:return
            image=image.rotate(-rotation,expand=True);image.thumbnail((max(200,self.canvas.winfo_width()-20),max(200,self.canvas.winfo_height()-20)))
            self.large_image=ImageTk.PhotoImage(image,master=self);self.canvas.delete('all');self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.large_image)
            self.note.set(f'{path.name} · Page {ref["page"]+1} · Additional rotation {rotation}°')
        self.background(lambda:documents.render(path,ref['page'],width=1000,password=self.passwords[str(path)]),done)
    def snapshot(self):self.undo.append([(iid,dict(self.refs[iid])) for iid in self.tree.get_children()])
    def move(self,direction):
        self.snapshot();ids=list(self.tree.selection());ids=ids if direction<0 else list(reversed(ids))
        for iid in ids:self.tree.move(iid,'',max(0,self.tree.index(iid)+direction))
    def rotate(self):
        self.snapshot()
        for iid in self.tree.selection():self.refs[iid]['rotation']=(self.refs[iid]['rotation']+90)%360
        self.preview()
    def delete(self):
        self.snapshot()
        for iid in self.tree.selection():self.tree.delete(iid)
    def undo_edit(self):
        if not self.undo:return
        rows=self.undo.pop();self.tree.delete(*self.tree.get_children())
        for iid,ref in rows:
            self.refs[iid]=ref;self.tree.insert('','end',iid=iid,text=f'{self.paths[ref["source"]].name} · {ref["page"]+1}',image=self.images.get(iid,''))
    def jump_bookmark(self,event=None):
        selected=self.bookmarks.selection()
        if not selected:return
        source,page=self.bookmark_refs[selected[0]]
        iid=next((i for i in self.tree.get_children() if self.refs[i]['source']==source and self.refs[i]['page']==page),None)
        if iid:self.tree.selection_set(iid);self.tree.see(iid)
    def submit(self,paths,spec):
        try:
            handle=self.app.service.submit_document(paths,spec,origin='desktop',passwords=self.passwords)
            self.app._manual_jobs[handle.id]='PDF Studio';self.note.set('Submitted '+handle.id+'; progress appears in the main window.')
        except Exception as error:messagebox.showerror('PDF Studio',str(error),parent=self)
    def output(self,name='edited.pdf'):
        return filedialog.asksaveasfilename(parent=self,initialfile=name,defaultextension='.pdf',filetypes=[('PDF','*.pdf')])
    def save(self,selected=False,course=False):
        ids=self.tree.selection() if selected else self.tree.get_children()
        if not ids:messagebox.showinfo('PDF Studio','Choose at least one page',parent=self);return
        title=simpledialog.askstring('Course pack','Course title',parent=self) if course else ''
        if course and title is None:return
        output=self.output('course-pack.pdf' if course else 'arranged.pdf')
        if output:self.submit(self.paths,{'action':'compose','output':output,'pages':[dict(self.refs[i]) for i in ids],'course_pack':course,'title':title or ''})
    def decorate(self):
        try:path,_=self.source()
        except ValueError:return
        window=tk.Toplevel(self);window.title('Stamp source PDF');values={}
        for row,name in enumerate(['watermark','header','footer','logo']):
            ttk.Label(window,text=name.title()).grid(row=row,column=0,padx=8,pady=8);values[name]=tk.StringVar();ttk.Entry(window,textvariable=values[name],width=45).grid(row=row,column=1,padx=8)
        ttk.Button(window,text='Choose logo',command=lambda:values['logo'].set(filedialog.askopenfilename(parent=window,filetypes=[('Images','*.png *.jpg *.jpeg')]))).grid(row=3,column=2)
        numbers=tk.BooleanVar(value=True);ttk.Checkbutton(window,text='Page numbers',variable=numbers).grid(row=4,column=1,sticky='w')
        def save():
            output=self.output('stamped.pdf')
            if output:self.submit([path],{'action':'decorate','output':output,'page_numbers':numbers.get(),**{k:v.get() for k,v in values.items()}});window.destroy()
        ttk.Button(window,text='Save new PDF',command=save).grid(row=5,column=1,pady=12);self.app.localize_window(window)
    def metadata(self):
        try:path,_=self.source();info=documents.inspect(path,self.passwords[str(path)])
        except ValueError:return
        window=tk.Toplevel(self);window.title('PDF metadata');variables={}
        for row,name in enumerate(['Title','Author','Subject','Keywords']):
            ttk.Label(window,text=name).grid(row=row,column=0,padx=8,pady=8);variables[name]=tk.StringVar(value=info['metadata'].get('/'+name,''));ttk.Entry(window,textvariable=variables[name],width=50).grid(row=row,column=1,padx=8)
        remove=tk.BooleanVar();ttk.Checkbutton(window,text='Remove document metadata',variable=remove).grid(row=4,column=1)
        def save():
            output=self.output('metadata-edited.pdf')
            if output:self.submit([path],{'action':'metadata','output':output,'remove_metadata':remove.get(),'metadata':{k:v.get() for k,v in variables.items()}});window.destroy()
        ttk.Button(window,text='Save new PDF',command=save).grid(row=5,column=1,pady=12);self.app.localize_window(window)
    def export(self):
        try:path,_=self.source()
        except ValueError:return
        kind=simpledialog.askstring('Export images','Format: png or jpeg',initialvalue='png',parent=self)
        if kind not in ('png','jpeg'):return
        folder=filedialog.askdirectory(parent=self,title='Export source PDF pages')
        if folder:self.submit([path],{'action':'export','output_dir':folder,'format':kind,'dpi':144})
    def compress(self):
        try:path,_=self.source()
        except ValueError:return
        kb=simpledialog.askinteger('Target compression','Target size in KiB (best effort)',minvalue=1,parent=self)
        if kb is None:return
        lossy=messagebox.askyesno('Lossy compression','Allow rasterizing pages if lossless compression cannot meet the target? This removes selectable text and vector quality.',parent=self)
        output=self.output('compressed.pdf')
        if output:self.submit([path],{'action':'compress','output':output,'target_bytes':kb*1024,'allow_raster':lossy})
    def review(self):
        try:path,ref=self.source()
        except ValueError:return
        window=tk.Toplevel(self);window.title('Text / OCR review');window.geometry('1050x720')
        ttk.Label(window,text='Review extracted Unicode text. For scans, run OCR first with eng+ara in the main conversion screen.').pack(fill='x',padx=8,pady=8)
        panes=ttk.Panedwindow(window,orient='horizontal');panes.pack(fill='both',expand=True)
        image=ttk.Label(panes);text=tk.Text(panes,wrap='word',undo=True,font=('Arial',12));panes.add(image,weight=1);panes.add(text,weight=2)
        text.tag_configure('rtl',justify='right');text.insert('end','Extracting…')
        def loaded(value):
            if not window.winfo_exists():return
            raw,preview=value;text.delete('1.0','end');text.insert('1.0',raw)
            if any('\u0600'<=c<='\u06ff' for c in raw):text.tag_add('rtl','1.0','end')
            window.preview=ImageTk.PhotoImage(preview,master=window);image.configure(image=window.preview)
        def work():
            reader=documents.read_pdf(path,self.passwords[str(path)]);raw='\n\n'.join(p.extract_text() or '' for p in reader.pages)
            preview=documents.render(path,ref['page'],width=350,password=self.passwords[str(path)]);preview.thumbnail((350,580));return raw,preview
        self.background(work,loaded)
        def save():
            output=filedialog.asksaveasfilename(parent=window,defaultextension='.txt',filetypes=[('UTF-8 text','*.txt')])
            if output:self.submit([path],{'action':'text','output':output,'reviewed_text':text.get('1.0','end-1c')})
        ttk.Button(window,text='Save reviewed UTF-8 text',command=save).pack(pady=8);self.app.localize_window(window)
