# SPDX-License-Identifier: MIT
"""V1 desktop integrations, reusing the existing conversion window and service."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from .state import Store,duplicates
from .sdk import Client
from .options import ConversionOptions

class WorkbenchMixin:
    def init_v1(self,root):
        self.v1_store=Store(root);self.sdk=Client(root,service=self.service)
        self.v1_options=self.v1_store.get('conversion_extra',{})
        self.language=tk.StringVar(value=self.v1_store.get('language','en'))
        self.preset_name=tk.StringVar(value='Original')
        self.notifications=tk.BooleanVar(value=self.v1_store.get('notifications',False))
    def build_v1(self,nav,header,run):
        # Keep the language control beside, rather than on top of, the theme toggle.
        # desktop.App owns column 3 for the Dark/Light theme button.
        ttk.Button(header,text='العربية / English',command=self.toggle_language).grid(row=0,column=4,rowspan=2,padx=5)
        for row,label,command in [(5,'PDF Studio',self.open_studio),(6,'Automation',self.automation_window),(7,'History',self.history_window),(8,'README / tutorials',self.open_readme)]:
            ttk.Button(nav,text=label,width=18,style='Nav.TButton',command=command).grid(row=row,column=0,sticky='ew',pady=3)
        self.pause_button=ttk.Button(run,text='Pause between files',command=self.toggle_pause);self.pause_button.grid(row=3,column=1,columnspan=2,sticky='e',pady=(7,0))
        panel=ttk.Frame(self.convert_body,padding=10,style='Card.TFrame');panel.grid(row=6,column=0,sticky='ew')
        ttk.Label(panel,text='Preset').grid(row=0,column=0,padx=4)
        self.preset_combo=ttk.Combobox(panel,textvariable=self.preset_name,values=self.v1_store.preset_names(),state='readonly',width=18);self.preset_combo.grid(row=0,column=1)
        for col,label,command in [(2,'Apply preset',self.apply_preset),(3,'Save preset',self.save_preset),(4,'Naming / folders',self.naming_window)]:ttk.Button(panel,text=label,command=command).grid(row=0,column=col,padx=3)
        for col,label,command in [(0,'Find duplicates',self.find_duplicates),(1,'Preflight',self.preflight),(2,'Recent folders',self.recent_folders),(3,'Diagnostics',self.export_diagnostics)]:ttk.Button(panel,text=label,command=command).grid(row=1,column=col,padx=3,pady=8)
        ttk.Checkbutton(panel,text='Completion notifications',variable=self.notifications,command=lambda:self.v1_store.set('notifications',self.notifications.get())).grid(row=1,column=4)
        self.localize_window(self)
    def toggle_pause(self):
        if self.service.paused:self.service.resume()
        else:self.service.pause()
        self.pause_button.configure(text='Resume queue' if self.service.paused else 'Pause between files')
        self.localize_window(self)
    def toggle_language(self):
        self.language.set('ar' if self.language.get()=='en' else 'en');self.v1_store.set('language',self.language.get());self.localize_window(self)
    def localize_window(self,root):
        if not hasattr(self,'language'):return
        from .i18n import AR,text,label_image
        language=self.language.get();rtl=language=='ar'
        def walk(widget):
            children=widget.winfo_children()
            if isinstance(widget,tk.Menu):
                try:
                    for n in range((widget.index('end') or -1)+1):
                        label=widget.entrycget(n,'label');key=getattr(widget,'_puryf_labels',{}).get(n,label)
                        if key in AR:
                            if not hasattr(widget,'_puryf_labels'):widget._puryf_labels={}
                            widget._puryf_labels[n]=key
                            if not hasattr(widget,'_puryf_menu_images'):widget._puryf_menu_images={}
                            photo=label_image(self,key) if rtl else ''
                            widget._puryf_menu_images[n]=photo;widget.entryconfigure(n,label='' if rtl else key,image=photo)
                except tk.TclError:pass
            try:
                current=widget.cget('text');key=getattr(widget,'_puryf_label',current)
                if current in AR:key=current
                if key in AR:
                    widget._puryf_label=key
                    style=str(widget.cget('style')) if 'style' in widget.keys() else ''
                    size=26 if 'Title.' in style else 19 if 'Section.' in style else 16
                    color='#202124' if style=='Accent.TButton' else None
                    widget._puryf_ar_image=label_image(self,key,size,color) if rtl else ''
                    widget.configure(text='' if rtl else key,image=widget._puryf_ar_image)
                if isinstance(widget,(ttk.Label,ttk.Button,ttk.Checkbutton,ttk.Menubutton)):widget.configure(anchor='e' if rtl else 'w')
            except tk.TclError:pass
            if isinstance(widget,ttk.Treeview):
                if not hasattr(widget,'_puryf_headings'):widget._puryf_headings={}
                for column in ['#0',*widget['columns']]:
                    value=widget.heading(column,'text');key=widget._puryf_headings.get(column,value)
                    if key in AR:
                        widget._puryf_headings[column]=key
                        if not hasattr(widget,'_puryf_heading_images'):widget._puryf_heading_images={}
                        photo=label_image(self,key) if rtl else '';widget._puryf_heading_images[column]=photo
                        widget.heading(column,text='' if rtl else key,image=photo)
            if isinstance(widget,ttk.Notebook):
                if not hasattr(widget,'_puryf_tabs'):widget._puryf_tabs={}
                for tab in widget.tabs():
                    key=widget._puryf_tabs.get(tab,widget.tab(tab,'text'));widget._puryf_tabs[tab]=key
                    if key in AR:
                        if not hasattr(widget,'_puryf_tab_images'):widget._puryf_tab_images={}
                        photo=label_image(self,key) if rtl else '';widget._puryf_tab_images[tab]=photo
                        widget.tab(tab,text='' if rtl else key,image=photo)
            if isinstance(widget,ttk.Panedwindow) and getattr(widget,'_puryf_pane_rtl',False)!=rtl:
                panes=list(widget.panes());weights={pane:widget.pane(pane,'weight') for pane in panes}
                for pane in panes:widget.forget(pane)
                for pane in reversed(panes):widget.add(pane,weight=weights[pane])
                widget._puryf_pane_rtl=rtl
            grid=[child for child in children if child.winfo_manager()=='grid']
            if grid and getattr(widget,'_puryf_rtl',False)!=rtl:
                maximum=max(int(c.grid_info()['column'])+int(c.grid_info()['columnspan']) for c in grid)-1
                weights=[widget.grid_columnconfigure(n) for n in range(maximum+1)]
                for child in grid:
                    info=child.grid_info();sticky=str(info['sticky']).translate(str.maketrans('ew','we'))
                    child.grid_configure(column=maximum-int(info['column'])-int(info['columnspan'])+1,sticky=sticky)
                for n,values in enumerate(reversed(weights)):
                    widget.columnconfigure(n,weight=values.get('weight',0),minsize=values.get('minsize',0),uniform=values.get('uniform',''))
                widget._puryf_rtl=rtl
            for child in children:
                if child.winfo_manager()=='pack':
                    info=child.pack_info();side=str(info['side'])
                    if side in ('left','right') and getattr(child,'_puryf_pack_rtl',False)!=rtl:
                        child.pack_configure(side='right' if side=='left' else 'left');child._puryf_pack_rtl=rtl
                walk(child)
        walk(root)
        if root is self and hasattr(self,'tree'):
            columns=list(self.tree['columns']);self.tree.configure(displaycolumns=list(reversed(columns)) if rtl else columns)

    def open_studio(self):
        from .studio import Studio
        paths=[]
        for _,item in self._selected_queue_items():
            path=Path(item.output) if item.output and Path(item.output).is_file() else item.source
            if path.suffix.lower()=='.pdf':paths.append(path)
        window=Studio(self,paths)
        window.lift()
        window.focus_set()
    def apply_preset(self):
        if self.is_running():return
        try:
            options=self.v1_store.preset(self.preset_name.get());extras={}
            for key,value in options.items():
                variable=getattr(self,key,None)
                if isinstance(variable,tk.Variable):variable.set(value)
                elif key in ('naming_pattern','source_root','preserve_folders','image_max_edge','command_timeout'):extras[key]=value
            self.password_pdf.set(False);self.pdf_password.set('');self.v1_options.update(extras)
            self.v1_store.set('conversion_extra',self.v1_options);self.update_password_controls();self.status.set('Applied preset '+self.preset_name.get())
        except Exception as error:messagebox.showerror('Preset',str(error))
    def save_preset(self):
        name=simpledialog.askstring('Save preset','Preset name',parent=self)
        if name:
            try:self.v1_store.save_preset(name,self.settings());self.preset_combo.configure(values=self.v1_store.preset_names());self.preset_name.set(name)
            except ValueError as error:messagebox.showerror('Preset',str(error))
    def naming_window(self):
        if self.is_running():return
        window=tk.Toplevel(self);window.title('Naming / folders');pattern=tk.StringVar(value=self.v1_options.get('naming_pattern','{stem}'));root=tk.StringVar(value=self.v1_options.get('source_root',''));preserve=tk.BooleanVar(value=self.v1_options.get('preserve_folders',False))
        ttk.Label(window,text='Naming pattern').grid(row=0,column=0,padx=8,pady=8);ttk.Entry(window,textvariable=pattern,width=45).grid(row=0,column=1,padx=8)
        ttk.Label(window,text='{stem} {ext} {index} {parent} {date} {hash8}').grid(row=1,column=1)
        ttk.Label(window,text='Source root').grid(row=2,column=0,padx=8,pady=8);ttk.Entry(window,textvariable=root,width=45).grid(row=2,column=1)
        ttk.Button(window,text='Browse',command=lambda:root.set(filedialog.askdirectory(parent=window))).grid(row=2,column=2)
        ttk.Checkbutton(window,text='Preserve source folders',variable=preserve).grid(row=3,column=1)
        def save():
            values={**self.v1_options,'naming_pattern':pattern.get(),'source_root':root.get(),'preserve_folders':preserve.get()}
            try:ConversionOptions.from_mapping({**self.settings(),**values})
            except ValueError as error:messagebox.showerror('Naming / folders',str(error));return
            self.v1_options=values;self.v1_store.set('conversion_extra',values);window.destroy()
        ttk.Button(window,text='Save',command=save).grid(row=4,column=1,pady=12);self.localize_window(window)
    def find_duplicates(self):
        if self.is_running():return
        items=list(self.items)
        def worker():
            try:
                groups=duplicates([i.source for i in items]);paths={p for group in groups for p in group[1:]}
                def done():
                    self.tree.selection_set([i.uid for i in self.items if str(i.source) in paths]);self.status.set(f'{len(paths)} content duplicates selected; review before removing.')
                self.q.put(('ui',done))
            except Exception as error:self.log('Duplicate scan: '+str(error))
        threading.Thread(target=worker,daemon=True).start()
    def preflight(self):
        try:
            checks=self.service.check_dependencies([i.source for i in self.items],self.settings())
            messagebox.showinfo('Preflight','\n'.join(Path(c['source']).name+': '+('; '.join(c['issues']) or 'Ready') for c in checks) or 'Queue empty')
        except ValueError as error:messagebox.showerror('Preflight',str(error))
    def recent_folders(self):
        window=tk.Toplevel(self);window.title('Recent folders')
        for folder in self.v1_store.get('recent_output_folders',[]):ttk.Button(window,text=folder,command=lambda p=folder:self.open_local(p)).pack(fill='x',padx=10,pady=4)
    def export_diagnostics(self):
        from .documents import commit_bytes
        path=filedialog.asksaveasfilename(defaultextension='.json',initialfile='PuryF-diagnostics.json')
        if path:
            try:commit_bytes(json.dumps(self.v1_store.diagnostic(),indent=2).encode(),path,[i.source for i in self.items],threading.Event());self.status.set('Saved redacted diagnostics')
            except Exception as error:messagebox.showerror('Diagnostics',str(error))
    def history_window(self):
        window=tk.Toplevel(self);window.title('History');window.geometry('850x500')
        tree=ttk.Treeview(window,columns=('operation','status','outputs'),show='tree headings');tree.heading('#0',text='Job');tree.heading('operation',text='Operation');tree.heading('status',text='Status');tree.heading('outputs',text='Outputs');tree.pack(fill='both',expand=True)
        def refresh():
            tree.delete(*tree.get_children())
            for job in self.v1_store.history():tree.insert('','end',iid=job['id'],text=job['id'][:8],values=(job['operation'],job['status'],len(job['outputs'])))
        def repeat():
            if tree.selection():
                try:handle=self.sdk.repeat(tree.selection()[0]);self.status.set('Repeated job '+handle.id)
                except ValueError as error:messagebox.showerror('History',str(error),parent=window)
        ttk.Button(window,text='Refresh',command=refresh).pack(side='left',padx=8,pady=8);ttk.Button(window,text='Repeat selected',command=repeat).pack(side='left',padx=8);refresh();self.localize_window(window)
    def automation_window(self):
        window=tk.Toplevel(self);window.title('Automation');path=tk.StringVar()
        ttk.Label(window,text='Automation config JSON (watch folders, schedules, presets and trusted plugins)').pack(padx=12,pady=12)
        ttk.Entry(window,textvariable=path,width=80).pack(padx=12,pady=8)
        ttk.Button(window,text='Open automation config',command=lambda:path.set(filedialog.askopenfilename(filetypes=[('JSON','*.json')],parent=window))).pack()
        def start():
            if not Path(path.get()).is_file():return
            command=[str(Path(sys.executable).with_name('PuryF-cli.exe'))] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve().parent.parent/'PuryF_CLI.py')]
            subprocess.Popen([*command,'background','--config',path.get()]);self.status.set('Background queue launched')
        ttk.Button(window,text='Start background queue',command=start).pack(pady=8)
        def control(action):
            try:
                from .automation import control as send
                config=json.loads(Path(path.get()).read_text());send(config['state_dir'],action)
            except Exception as error:messagebox.showerror('Automation',str(error),parent=window)
        bar=ttk.Frame(window);bar.pack(pady=8)
        for label,action in [('Pause','pause'),('Resume','resume'),('Stop','stop'),('Retry failed watches','retry')]:ttk.Button(bar,text=label,command=lambda a=action:control(a)).pack(side='left',padx=3)
        def plugin():
            file=filedialog.askopenfilename(parent=window,title='Load trusted extension — runs Python code',filetypes=[('Python extension','*.py')])
            if file:
                try:
                    from .extensions import load
                    value=load(file);messagebox.showinfo('Extension',str(value),parent=window)
                except Exception as error:messagebox.showerror('Extension',str(error),parent=window)
        ttk.Button(window,text='Load trusted extension',command=plugin).pack(pady=8);self.localize_window(window)
    def notify_complete(self,job):
        self.v1_store.record(job)
        if not self.notifications.get():return
        self.bell();popup=tk.Toplevel(self);popup.title('PuryF v1');popup.geometry('360x100+60+60')
        ttk.Label(popup,text=f"Job {job['status']} · {len(job['outputs'])} output(s)",padding=20).pack();timer=popup.after(5000,popup.destroy)
        popup.bind('<Destroy>',lambda event:popup.after_cancel(timer) if event.widget is popup else None)
    def open_readme(self):
        path=Path(sys.executable).parent/'README.md' if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent/'README.md'
        if not path.exists():path=Path(__file__).resolve().parent/"assets/README.md"
        self.open_local(path)
