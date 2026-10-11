# -*- coding: utf-8 -*-
"""共用的文件轉換：把各種格式的上傳檔案轉成統一的段落，給 RAG 切段與 embedding 使用。

    sections = DocumentParser.parse('教練課表.xlsx', data)   # data 是 bytes，不需要先存成檔案
    # → [{'locator': '工作表「週課表」', 'title': '週課表', 'text': '星期：一；動作：臥推；組數：4；次數：8'}, ...]

支援的格式（副檔名 → 轉換方式）：
    .txt .md   直接讀取；編碼依序試 UTF-8、Big5（cp950）
    .csv       每一列轉成「欄名：值」的句子
    .pdf       逐頁擷取文字（保留頁碼），去掉每頁重複的頁首頁尾；掃描檔會回傳清楚的錯誤
    .docx      依段落樣式轉成 Markdown 標題與清單；表格轉成「欄名：值」的句子，順序與原文件相同
    .xlsx      每個工作表一段，每一列轉成「欄名：值」的句子

輸出的 text 保留 Markdown 標題（# …），切段程式可以依標題分段。
失敗時丟 DocumentParseError，訊息可以直接顯示給使用者。

這個模組只做轉換：不碰資料庫、不呼叫 LLM、不碰 HTTP，任何模組都可以使用。
需要的套件（requirements.txt 已經有）：PyMuPDF、python-docx、openpyxl。
"""
import csv
import io
import re
from collections import Counter


class DocumentParseError(Exception):
    """可以直接顯示給使用者的轉換錯誤。"""


class DocumentParser:
    SUPPORTED = ('txt', 'md', 'csv', 'pdf', 'docx', 'xlsx', 'xlsm')
    ENCODINGS = ('utf-8-sig', 'cp950', 'big5hkscs')     # 台灣的舊文字檔常是 Big5
    MIN_PDF_CHARS_PER_PAGE = 20                         # 平均每頁少於這麼多字 → 視為掃描檔
    MAX_TABLE_ROWS = 2000                               # 每個表格最多讀幾列

    # ------------------------------------------------------------------ 對外
    @classmethod
    def extension(cls, filename):
        name = str(filename or '')
        return name.rsplit('.', 1)[-1].lower() if '.' in name else ''

    @classmethod
    def parse(cls, filename, data):
        """回傳 [{locator, title, text}]；至少有一段有文字，否則丟 DocumentParseError。"""
        ext = cls.extension(filename)
        handler = {
            'txt': cls._plain, 'md': cls._plain, 'csv': cls._csv, 'pdf': cls._pdf,
            'docx': cls._docx, 'xlsx': cls._xlsx, 'xlsm': cls._xlsx,
        }.get(ext)
        if handler is None:
            raise DocumentParseError(f"目前支援的格式：{'、'.join(f'.{e}' for e in cls.SUPPORTED if e != 'xlsm')}。")
        if not data:
            raise DocumentParseError('檔案是空的。')
        sections = [dict(s, text=cls.clean(s['text'])) for s in handler(data, filename)]
        sections = [s for s in sections if s['text']]
        if not sections:
            raise DocumentParseError('檔案裡沒有可以使用的文字。')
        return sections

    @staticmethod
    def clean(text):
        """統一換行、去掉控制字元與多餘空白，最多保留一個空行。"""
        text = (text or '').replace('\r\n', '\n').replace('\r', '\n').replace('\u3000', ' ')
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = '\n'.join(line.strip() for line in text.split('\n'))
        return re.sub(r'\n{3,}', '\n\n', text).strip()

    # ------------------------------------------------------------------ 表格 → 句子
    @classmethod
    def table_to_text(cls, rows):
        """表格轉成句子：有標題列就寫成「欄名：值；欄名：值」，沒有就用「｜」連接。

        直接用 Tab 串起來的話，「週一 臥推 4 8」檢索時很難對到「臥推 4 組 8 下」這種問題。
        """
        rows = [['' if v is None else ' '.join(str(v).split()) for v in row] for row in rows]
        rows = [row for row in rows if any(row)][:cls.MAX_TABLE_ROWS]
        if not rows:
            return ''
        header, body = rows[0], rows[1:]
        filled = [h for h in header if h]
        looks_like_header = len(filled) >= 2 and body and \
            sum(1 for h in filled if re.fullmatch(r'[\d.,%\-+ ]+', h)) <= len(filled) // 3
        if not looks_like_header:
            return '\n'.join('｜'.join(v for v in row if v) for row in rows)
        names = [h or f'第{i + 1}欄' for i, h in enumerate(header)]
        lines = []
        for row in body:
            pairs = [f'{names[i]}：{v}' for i, v in enumerate(row) if v and i < len(names)]
            extra = [v for v in row[len(names):] if v]
            if pairs or extra:
                lines.append('；'.join(pairs + extra))
        return '\n'.join(lines)

    # ------------------------------------------------------------------ 各格式
    @classmethod
    def decode(cls, data):
        for encoding in cls.ENCODINGS:
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise DocumentParseError('無法辨識文字編碼，請用 UTF-8 儲存後再上傳。')

    @classmethod
    def _plain(cls, data, filename):
        return [dict(locator='全文', title='', text=cls.decode(data))]

    @classmethod
    def _csv(cls, data, filename):
        rows = list(csv.reader(io.StringIO(cls.decode(data))))
        return [dict(locator='表格', title='', text=cls.table_to_text(rows))]

    @classmethod
    def _pdf(cls, data, filename):
        try:
            import pymupdf
        except ImportError:                                   # 舊版 PyMuPDF 的名稱
            try:
                import fitz as pymupdf
            except ImportError:
                raise DocumentParseError('伺服器沒有安裝 PyMuPDF，無法讀取 PDF。') from None
        try:
            document = pymupdf.open(stream=data, filetype='pdf')
        except Exception:
            raise DocumentParseError('PDF 檔案無法開啟，可能已損毀或有密碼保護。') from None
        with document:
            if document.needs_pass:
                raise DocumentParseError('PDF 有密碼保護，請先解除後再上傳。')
            pages = [page.get_text('text') for page in document]
        if not pages:
            raise DocumentParseError('PDF 沒有任何頁面。')
        if sum(len(p.strip()) for p in pages) < cls.MIN_PDF_CHARS_PER_PAGE * len(pages):
            raise DocumentParseError('這個 PDF 幾乎擷取不到文字，可能是掃描檔或圖片，請改上傳文字版（Word、TXT 或可選取文字的 PDF）。')
        repeated = cls._repeated_lines(pages)
        sections = []
        for number, page in enumerate(pages, 1):
            lines = [line for line in page.split('\n') if line.strip() and line.strip() not in repeated]
            sections.append(dict(locator=f'第 {number} 頁', title='', text='\n'.join(lines)))
        return sections

    @staticmethod
    def _repeated_lines(pages):
        """出現在一半以上頁面開頭或結尾的行（頁首、頁尾、頁碼格式）視為重複，不放進內容。"""
        if len(pages) < 3:
            return set()
        counter = Counter()
        for page in pages:
            lines = [line.strip() for line in page.split('\n') if line.strip()]
            counter.update(set(lines[:2] + lines[-2:]))
        return {line for line, count in counter.items() if count > len(pages) / 2}

    @classmethod
    def _docx(cls, data, filename):
        try:
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError:
            raise DocumentParseError('伺服器沒有安裝 python-docx，無法讀取 Word 檔。') from None
        try:
            document = Document(io.BytesIO(data))
        except Exception:
            raise DocumentParseError('Word 檔案無法開啟，請確認是 .docx 格式（不是舊版 .doc）。') from None
        parts = []
        for element in document.element.body.iterchildren():      # 依原文件順序走過段落與表格
            tag = element.tag.rsplit('}', 1)[-1]
            if tag == 'p':
                paragraph = Paragraph(element, document)
                text = paragraph.text.strip()
                if not text:
                    continue
                style = (paragraph.style.name if paragraph.style is not None else '').lower()
                level = re.search(r'heading\s*(\d)', style) or re.search(r'標題\s*(\d)', style)
                if level or style == 'title':
                    parts.append('#' * (int(level.group(1)) if level else 1) + ' ' + text)
                elif 'list' in style or '清單' in style:
                    parts.append('- ' + text)
                else:
                    parts.append(text)
            elif tag == 'tbl':
                table = Table(element, document)
                rows = [[cell.text for cell in row.cells] for row in table.rows]
                text = cls.table_to_text(rows)
                if text:
                    parts.append(text)
        return [dict(locator='全文', title='', text='\n\n'.join(parts))]

    @classmethod
    def _xlsx(cls, data, filename):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise DocumentParseError('伺服器沒有安裝 openpyxl，無法讀取 Excel 檔。') from None
        try:
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise DocumentParseError('Excel 檔案無法開啟，請確認是 .xlsx 格式。') from None
        try:
            sections = []
            for sheet in workbook.worksheets:
                rows = []
                for row in sheet.iter_rows(values_only=True):
                    rows.append(list(row))
                    if len(rows) > cls.MAX_TABLE_ROWS:
                        break
                text = cls.table_to_text(rows)
                if text:
                    sections.append(dict(locator=f'工作表「{sheet.title}」', title=sheet.title, text=text))
            return sections
        finally:
            workbook.close()
