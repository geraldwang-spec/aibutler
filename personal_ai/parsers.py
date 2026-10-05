from __future__ import annotations
from pathlib import Path
import base64
import zipfile

def parse_file(path:Path):
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
                text=page.get_text('text').strip()
                if len(text)<40:
                    scanned+=1
                    if scanned>20: raise RuntimeError('每批最多 OCR 20 頁，請拆分掃描檔。')
                    from .exam_modules import cpu
                    pixels=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False)
                    text=cpu('ocr',image=base64.b64encode(pixels.tobytes('png')).decode('ascii'))
                if text: sections.append({'locator':f'page:{i}','title':f'第 {i} 頁','text':text})
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
        for p in doc.paragraphs:
            t=p.text.strip()
            if not t: continue
            if p.style and str(p.style.name).lower().startswith('heading') and buf:
                sections.append({'locator':f'section:{sec}','title':buf[0][:80],'text':'\n'.join(buf)}); sec+=1; buf=[]
            buf.append(t)
        if buf: sections.append({'locator':f'section:{sec}','title':buf[0][:80],'text':'\n'.join(buf)})
        for i,table in enumerate(doc.tables,1):
            rows=['\t'.join(cell.text for cell in row.cells) for row in table.rows]
            sections.append(dict(locator=f'table:{i}',title=f'表格 {i}',text='\n'.join(rows)))
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
