from __future__ import annotations
from pathlib import Path
import base64
import zipfile
import re


def needs_ocr(text):
    if len(text.strip()) < 40:
        return True
    broken = sum(ch == '\ufffd' or '\ue000' <= ch <= '\uf8ff' for ch in text)
    return broken / max(1, len(text)) > .15 or len(re.findall(r'\(cid:\d+\)', text)) >= 3

def parse_file(path:Path, include_pdf_images=False):
    ext=path.suffix.lower()
    if ext=='.pdf':
        try: import fitz
        except ImportError as exc: raise RuntimeError('解析 PDF 需要 PyMuPDF：pip install pymupdf') from exc
        doc=fitz.open(path)
        sections=[]
        try:
            if len(doc)>100: raise RuntimeError('每份 PDF 最多 100 頁，請拆分。')
            scanned=0
            for i,page in enumerate(doc,1):
                image_context=[]
                text=page.get_text('text').strip()
                if needs_ocr(text):
                    scanned+=1
                    if scanned>20: raise RuntimeError('每批最多 OCR 20 頁，請拆分掃描檔。')
                    from .exam_modules import cpu
                    pixels=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False)
                    text=cpu('ocr',image=base64.b64encode(pixels.tobytes('png')).decode('ascii'))
                elif include_pdf_images and page.get_image_info():
                    # Keep image OCR separate from numbered question text and
                    # attach it to its explicitly labelled reading group.
                    from .exam_modules import cpu
                    last_range=None
                    infos=sorted(page.get_image_info(),key=lambda x:(int((x['bbox'][0]+x['bbox'][2])/2>=page.rect.width/2),x['bbox'][1]))
                    for info in infos:
                        rect=fitz.Rect(info['bbox']) & page.rect
                        if rect.width<35 or rect.height<25: continue
                        scanned+=1
                        if scanned>40: raise RuntimeError('每批最多 OCR 40 張圖片／掃描頁，請拆分。')
                        pixels=page.get_pixmap(matrix=fitz.Matrix(2,2),clip=rect,alpha=False)
                        image_text=cpu('ocr',image=base64.b64encode(pixels.tobytes('png')).decode('ascii'))
                        # OCR list numbers/time values must never become exam
                        # question numbers. Keep image text in separate metadata.
                        group=re.search(r'[（(]\s*(\d+)\s*[-–~～至]\s*(\d+)\s*[)）]',image_text[:160])
                        if group: last_range=(int(group[1]),int(group[2]))
                        if image_text.strip(): image_context.append({'range':last_range,'text':image_text})
                if text: sections.append({'locator':f'page:{i}','title':f'第 {i} 頁','text':text,'image_context':image_context})
        finally:
            doc.close()
        if not sections: raise RuntimeError('PDF 文字與 CPU OCR 均未取得文字，請檢查掃描品質。')
        return sections
    if ext=='.docx':
        with zipfile.ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist())>50*1024*1024:
                raise RuntimeError('Word 解壓後不可超過 50 MB。')
        try: from docx import Document
        except ImportError as exc: raise RuntimeError('解析 Word 需要 python-docx。') from exc
        doc=Document(path); sections=[]; buf=[]; sec=1
        from docx.table import Table
        table_no = 0
        for p in doc.iter_inner_content():
            if isinstance(p, Table):
                if buf:
                    sections.append({'locator':f'section:{sec}','title':buf[0][:80],'text':'\n'.join(buf)}); sec+=1; buf=[]
                table_no += 1
                rows=['\t'.join(cell.text for cell in row.cells) for row in p.rows]
                sections.append(dict(locator=f'table:{table_no}',title=f'表格 {table_no}',text='\n'.join(rows)))
                continue
            t=p.text.strip()
            if not t: continue
            if p.style and str(p.style.name).lower().startswith('heading') and buf:
                sections.append({'locator':f'section:{sec}','title':buf[0][:80],'text':'\n'.join(buf)}); sec+=1; buf=[]
            buf.append(t)
        if buf: sections.append({'locator':f'section:{sec}','title':buf[0][:80],'text':'\n'.join(buf)})
        return sections
    if ext in ('.xlsx','.xlsm'):
        from openpyxl import load_workbook
        wb=load_workbook(path,read_only=True,data_only=True)
        out=[]
        for ws in wb.worksheets:
            rows=[]
            for row in ws.iter_rows(values_only=True):
                vals=['' if v is None else str(v) for v in row]
                if any(vals): rows.append('\t'.join(vals))
            if rows: out.append({'locator':f'sheet:{ws.title}','title':ws.title,'text':'\n'.join(rows)})
        wb.close(); return out
    if ext in ('.txt','.md','.csv'):
        raw=path.read_bytes()
        text=None
        for encoding in ('utf-8-sig','utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'cp950'):
            try:
                text=raw.decode(encoding); break
            except UnicodeError:
                pass
        if text is None: raise RuntimeError('無法辨識文字編碼，請以 UTF-8 儲存後重試。')
        return [{'locator':'text:1','title':path.name,'text':text}]
    raise RuntimeError('目前支援 PDF、DOCX、XLSX、TXT、MD、CSV。')

def chunk_sections(sections, size=1400, overlap=180):
    chunks=[]
    for sec in sections:
        text=' '.join(sec['text'].split())
        start=0
        while start < len(text):
            end=min(len(text),start+size)
            part=text[start:end].strip()
            if part: chunks.append({'text':part,'locator':sec['locator'],'title':sec['title']})
            if end>=len(text): break
            start=max(start+1,end-overlap)
    return chunks
