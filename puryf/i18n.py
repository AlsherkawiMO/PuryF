# SPDX-License-Identifier: MIT
"""Primary interface translations. File paths, logs and document contents stay logical Unicode."""
AR={'Operation':'العملية','Outputs':'النتائج','Job':'المهمة',
'Convert':'تحويل','PDF tools':'أدوات PDF','Dependencies':'المتطلبات','Shortcuts':'الاختصارات',
'Your files. Simply PDF.':'ملفاتك. ببساطة PDF.','Local PDF toolkit':'أدوات PDF على جهازك','Make room for simpler files.':'ملفات أبسط، عمل أسهل.',
'Convert documents and media to PDF, locally on your computer.':'حوّل المستندات والوسائط إلى PDF على جهازك.',
'File queue':'قائمة الملفات','Add files':'إضافة ملفات','Add folder':'إضافة مجلد','Retry failed':'إعادة المحاولة','Queue actions':'إجراءات القائمة',
'File name':'اسم الملف','File location':'موقع الملف','Status':'الحالة','Output':'النتيجة','Details':'التفاصيل',
'Conversion settings':'إعدادات التحويل','Browse':'استعراض','Open folder':'فتح المجلد','Light theme':'المظهر الفاتح','Dark theme':'المظهر الداكن',
'Output folder (leave blank to save beside each source)':'مجلد النتائج (اتركه فارغاً للحفظ بجانب المصدر)',
'Merge converted PDFs':'دمج ملفات PDF الناتجة','Lossless PDF compression':'ضغط PDF دون فقدان','Overwrite existing PDFs':'استبدال النتائج الموجودة',
'OCR PDFs and images':'التعرّف الضوئي على النصوص','Advanced settings — images, Office, OCR and protection':'إعدادات متقدمة: الصور وOffice والتعرّف والحماية',
'Image paper size':'حجم ورق الصور','Excel: fit columns to one page':'Excel: ملاءمة الأعمدة لصفحة واحدة','OCR languages':'لغات التعرّف الضوئي',
"Example: eng+ara. Install matching Tesseract language packs.":'مثال: eng+ara. ثبّت حزم اللغات المناسبة في Tesseract.',
'PowerPoint export':'تصدير PowerPoint','PowerPoint date':'تاريخ PowerPoint','Password protect PDFs':'حماية PDF بكلمة مرور','Show password':'إظهار كلمة المرور',
'Show activity log':'إظهار سجل النشاط','Activity log':'سجل النشاط','Save log':'حفظ السجل','Clear log':'مسح السجل','Reports folder':'مجلد التقارير',
'Stop  ·  F8':'إيقاف  ·  F8','Start conversion  ·  F5':'بدء التحويل  ·  F5','Pause between files':'توقّف مؤقت بين الملفات','Resume queue':'استئناف القائمة',
'PDF Studio':'استوديو PDF','Automation':'الأتمتة','History':'المحفوظات','Preset':'الإعداد المحفوظ','Apply preset':'تطبيق الإعداد',
'Save preset':'حفظ الإعداد','Naming / folders':'التسمية والمجلدات','Find duplicates':'كشف التكرار','Preflight':'فحص مسبق','Recent folders':'المجلدات الأخيرة',
'Diagnostics':'التشخيص','README / tutorials':'التعليمات والدروس','Completion notifications':'إشعارات الإكمال',
'Add PDFs':'إضافة PDF','Up':'أعلى','Down':'أسفل','Rotate':'تدوير','Delete':'حذف','Undo':'تراجع','Save arrangement':'حفظ الترتيب',
'Extract selection':'استخراج المحدد','Course pack':'حزمة تدريبية','Stamp source PDF':'ختم ملف المصدر','Metadata':'البيانات الوصفية',
'Export images':'تصدير الصور','Text / OCR review':'مراجعة النص والتعرّف','Target compression':'ضغط لحجم مستهدف','Preview':'معاينة',
'Bookmarks / Contents':'العلامات والمحتويات','Bookmark':'العلامة المرجعية','Page':'الصفحة','Save new PDF':'حفظ PDF جديد',
'Watermark':'علامة مائية','Header':'رأس الصفحة','Footer':'تذييل الصفحة','Logo':'الشعار','Choose logo':'اختيار الشعار','Page numbers':'أرقام الصفحات',
'Title':'العنوان','Author':'المؤلف','Subject':'الموضوع','Keywords':'الكلمات المفتاحية','Remove document metadata':'إزالة البيانات الوصفية',
'Save reviewed UTF-8 text':'حفظ النص المصحح UTF-8','Select all':'تحديد الكل','Invert selection':'عكس التحديد','Remove selected':'إزالة المحدد',
'Duplicate selected':'نسخ المحدد','Retry selected':'إعادة محاولة المحدد','Move up':'نقل لأعلى','Move down':'نقل لأسفل','Move to top':'نقل للبداية','Move to bottom':'نقل للنهاية',
'Remove completed':'إزالة المكتمل','Remove failed':'إزالة الفاشل','Clear queue':'مسح القائمة','Refresh':'تحديث','Repeat selected':'إعادة المحدد',
'Load trusted extension':'تحميل إضافة موثوقة','Open automation config':'فتح إعداد الأتمتة','Start background queue':'بدء قائمة الخلفية',
'Pause':'توقّف مؤقت','Resume':'استئناف','Stop':'إيقاف','Retry failed watches':'إعادة محاولات المراقبة',
'Your queue is empty. Add files to get started.':'القائمة فارغة. أضف ملفات للبدء.',
'Drop files, folders or ZIP archives here':'اسحب الملفات أو المجلدات أو أرشيف ZIP هنا',
'Drag/drop unavailable; use Add files or Add folder':'السحب غير متاح؛ استخدم إضافة ملفات أو مجلد',
'Naming pattern':'نمط التسمية','Source root':'مجلد المصدر الأساسي','Preserve source folders':'الحفاظ على بنية المجلدات','Save':'حفظ',
}

def text(value,language):
    if language!='ar':return value
    raw=AR.get(value)
    if raw is None:return value
    # Tk 8 builds vary in bidi support; visual ordering is applied to static labels only.
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(raw))
    except ImportError:return raw

def label_image(app,key,size=16,color=None):
    """Rasterize static Arabic labels once, avoiding Tk platform-specific double bidi."""
    from PIL import Image,ImageDraw,ImageFont,ImageTk,features
    raw=AR[key];scale=float(app.tk.call('tk','scaling'))/1.333333
    face=ImageFont.truetype(str(app.asset_path('DejaVuSans.ttf')),max(12,int(size*scale)))
    options={'direction':'rtl','language':'ar'} if features.check_feature('raqm') else {}
    if not options:raw=text(key,'ar')
    probe=ImageDraw.Draw(Image.new('RGBA',(1,1)))
    box=probe.textbbox((0,0),raw,font=face,**options)
    image=Image.new('RGBA',(max(1,box[2]-box[0]+6),max(1,box[3]-box[1]+8)),(0,0,0,0))
    ImageDraw.Draw(image).text((3-box[0],4-box[1]),raw,font=face,fill=color or app.colors['text'],**options)
    return ImageTk.PhotoImage(image,master=app)
