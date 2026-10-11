# -*- coding: utf-8 -*-
"""教練文章 RAG 的純計算部分：切段與向量搜尋。

    TextChunker().split(text)                      依標題與段落切段（每段約 300～500 字，前後重疊約 50 字）
    TextChunker().split_sections(sections)         切 modules.document_parser 轉出的多個段落，保留出處位置
    VectorIndex.to_blob(vector) / from_blob(blob)  向量 ↔ 資料庫 BLOB（float32）
    VectorIndex.search(query, rows, k, min_score)  用 numpy 一次算完所有餘弦相似度，只回傳超過門檻的前 k 段

不碰資料庫、不呼叫 LLM；資料量小（每人幾篇文章），不另外架向量資料庫。
"""
import re

import numpy as np


class TextChunker:
    MAX_CHARS = 500          # 每段最多幾個字
    TARGET_CHARS = 400       # 累積到這個長度就切
    OVERLAP_CHARS = 50       # 前後重疊，避免一句話被切斷後找不到
    _HEADING = re.compile(r'^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$')

    def split(self, text):
        """回傳 [{index, section, content}]；section 是所屬的標題（沒有標題時是空字串）。

        每段開頭會帶上一段結尾的約 50 字（同一個標題底下才重疊），避免一句話被切斷後找不到。
        """
        chunks, section, overlap, buffer = [], '', '', ''

        def flush():
            nonlocal overlap, buffer
            if not buffer.strip():                        # 沒有新內容就不另外成段
                return
            content = (overlap + buffer).strip()
            chunks.append(dict(index=len(chunks), section=section, content=content))
            overlap = content[-self.OVERLAP_CHARS:] + '\n' if len(content) > self.OVERLAP_CHARS else ''
            buffer = ''

        for paragraph in self._paragraphs(text):
            heading = self._HEADING.match(paragraph)
            if heading:                                   # 新標題：前一段結束，不跨標題重疊
                flush()
                overlap, section = '', heading.group(1).strip()[:120]
                continue
            for piece in self._pieces(paragraph):
                if buffer.strip() and len(overlap) + len(buffer) + len(piece) > self.MAX_CHARS:
                    flush()
                buffer += piece + '\n'
                if len(overlap) + len(buffer) >= self.TARGET_CHARS:
                    flush()
        flush()
        return chunks

    def split_sections(self, sections):
        """切 DocumentParser 轉出來的多個段落（例如 PDF 的每一頁、Excel 的每個工作表）。

        回傳 [{index, section, locator, content}]；locator 是出處位置（第 3 頁、工作表「週課表」…）。
        """
        chunks = []
        for part in sections:
            for chunk in self.split(part['text']):
                chunks.append(dict(index=len(chunks), section=chunk['section'] or part.get('title') or '',
                                   locator=part.get('locator') or '', content=chunk['content']))
        return chunks

    @staticmethod
    def _paragraphs(text):
        text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
        lines, out, block = text.split('\n'), [], []
        for line in lines:
            if TextChunker._HEADING.match(line):
                if block:
                    out.append(' '.join(block))
                    block = []
                out.append(line.strip())
            elif line.strip():
                block.append(line.strip())
            elif block:
                out.append(' '.join(block))
                block = []
        if block:
            out.append(' '.join(block))
        return out

    def _pieces(self, paragraph):
        """太長的段落依句號切開，再不行就硬切，確保每塊不超過 MAX_CHARS。"""
        if len(paragraph) <= self.MAX_CHARS:
            return [paragraph]
        pieces, current = [], ''
        for sentence in re.split(r'(?<=[。！？!?；;])', paragraph):
            if len(current) + len(sentence) > self.MAX_CHARS and current:
                pieces.append(current)
                current = ''
            while len(sentence) > self.MAX_CHARS:
                pieces.append(sentence[:self.MAX_CHARS])
                sentence = sentence[self.MAX_CHARS:]
            current += sentence
        if current:
            pieces.append(current)
        return pieces


class VectorIndex:
    DEFAULT_K = 4
    DEFAULT_MIN_SCORE = 0.35   # 起始值；步驟 5 的評估會依結果調整

    @staticmethod
    def to_blob(vector):
        return np.asarray(vector, dtype=np.float32).tobytes()

    @staticmethod
    def from_blob(blob):
        return np.frombuffer(bytes(blob), dtype=np.float32)

    @classmethod
    def search(cls, query_vector, rows, k=None, min_score=None):
        """rows: [{'id', 'embedding'(BLOB), ...}]；回傳 [(row, score)]，依分數由高到低，只保留 >= min_score 的前 k 筆。

        向量維度和查詢不一致的段落（例如換過 embedding 模型）會略過。
        """
        k = k or cls.DEFAULT_K
        min_score = cls.DEFAULT_MIN_SCORE if min_score is None else min_score
        query = np.asarray(query_vector, dtype=np.float32)
        usable = [(row, cls.from_blob(row['embedding'])) for row in rows if row.get('embedding')]
        usable = [(row, vec) for row, vec in usable if vec.shape == query.shape]
        if not usable or not np.any(query):
            return []
        matrix = np.vstack([vec for _, vec in usable])
        norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)
        scores = np.divide(matrix @ query, norms, out=np.zeros(len(usable), dtype=np.float32), where=norms > 0)
        order = np.argsort(-scores)[:k]
        return [(usable[i][0], round(float(scores[i]), 4)) for i in order if scores[i] >= min_score]
