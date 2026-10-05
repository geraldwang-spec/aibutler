from __future__ import annotations
from pathlib import Path

def parse_file(path:Path):
    ext=path.suffix.lower()
    if ext=='.pdf':
        try: import fitz
        except ImportError as exc: raise RuntimeError('解析 PDF 需要 PyMuPDF：pip install pymupdf') from exc
        doc=fitz.open(path)
        sections=[]
        for i,page in enumerate(doc,1):
            text=page.get_text('text').strip()
            if text: sections.append({'locator':f'page:{i}','title':f'第 {i} 頁','text':text})
        if not sections: raise RuntimeError('PDF 沒有可擷取文字，可能是掃描檔；之後可接 OCR fallback。')
        return sections
    if ext=='.docx':
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
        return [{'locator':'text:1','title':path.name,'text':path.read_text(encoding='utf-8-sig',errors='replace')}]
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
