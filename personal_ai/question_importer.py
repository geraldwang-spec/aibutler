from __future__ import annotations

import base64
import re
from pathlib import Path

from .llm_provider import LLMError, get_parser_llm
from .parsers import parse_file
from .question_layout import ANSWER_HEADING, ANSWER_LABEL, OPTION, answer_text, split_fields, extract_layout, LAYOUT_BOUNDARY_RULES

QUESTION_TYPES = {'單選', '多選', '是非', '填空'}

_CN_NUM = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
}


def _number(value: str):
    value = (value or '').strip()
    if value.isdigit():
        return int(value)
    if value in _CN_NUM:
        return _CN_NUM[value]
    if value.startswith('十') and len(value) == 2 and value[1] in _CN_NUM:
        return 10 + _CN_NUM[value[1]]
    if value.endswith('十') and len(value) == 2 and value[0] in _CN_NUM:
        return _CN_NUM[value[0]] * 10
    return None


def _question_start(line: str):
    s = re.sub(r'^\s*(?:#{1,6}\s*)?', '', line).strip().translate(str.maketrans('０１２３４５６７８９．', '0123456789.'))
    patterns = [
        # PDF may put the opening answer box on the previous line: "(\n)1.".
        # Require a numbered punctuation prefix, not any closing parenthesis.
        r'^[）)]\s*(\d{1,4})\s*[.、:：]',
        r'^(?:（\s*[A-D]?\s*）|\(\s+[A-D]?\s*\))\s*(\d{1,4})(?!\d)\s*[.、:：]?',
        r'^(?:題目|問題|Question)\s*(\d{1,4})\s*[:：.、)]?',
        r'^[（(]\s*(\d{1,4})\s*[）)]',
        r'^(?:Q\s*)?0*(\d{1,3})\s*(?:[\)\.、>:：]|\s+(?=(?:單選|多選|是非|填空)))',
        r'^【\s*0*(\d{1,3})\s*】',
        r'^第\s*([一二三四五六七八九十\d]+)\s*題',
    ]
    for p in patterns:
        m = re.search(p, s, re.I)
        if m:
            return _number(m.group(1))
    return None


def _strip_question_prefix(line: str):
    s = re.sub(r'^\s*#{1,6}\s*', '', line).strip()
    for p in [
        r'^[）)]\s*[0-9０-９]{1,4}\s*[.．、:：]\s*',
        r'^(?:（\s*[A-D]?\s*）|\(\s+[A-D]?\s*\))\s*[0-9０-９]{1,4}(?![0-9０-９])\s*[.．、:：]?\s*',
        r'^(?:題目|問題|Question)\s*[0-9０-９]{1,4}\s*[:：.．、)]?\s*',
        r'^[（(]\s*[0-9０-９]{1,4}\s*[）)]\s*',
        r'^[０-９]{1,4}\s*[．.、:：)]\s*',
        r'^(?:Q\s*)?0*\d{1,3}\s*(?:[\)\.、>:：]|\s{2,})\s*',
        r'^【\s*0*\d{1,3}\s*】\s*',
        r'^第\s*[一二三四五六七八九十\d]+\s*題\s*(?:[\/（(][^）)]*[）)]?)?\s*[:：]?\s*',
    ]:
        ns = re.sub(p, '', s, count=1, flags=re.I)
        if ns != s:
            return ns.strip()
    return s


def _answer_key(text: str):
    answers = {}
    explanations = {}
    answer_section = re.split(ANSWER_HEADING, text, maxsplit=1)
    if len(answer_section) < 2:
        return answers, explanations
    for raw in answer_section[1].splitlines():
        line = raw.strip()
        if not line or line.upper().startswith('END'):
            continue
        qn = _question_start(line)
        if qn is None:
            # Answer lines may have a simple "1 答案: B" prefix that the general question
            # detector intentionally ignores.
            m = re.match(r'^(?:Q\s*)?0*(\d{1,3})\b', line, re.I)
            if m:
                qn = int(m.group(1))
            else:
                m = re.match(r'^第\s*([一二三四五六七八九十\d]+)\s*題', line)
                if m:
                    qn = _number(m.group(1))
        if qn is None:
            continue
        tail = re.sub(r'^(?:Q\s*)?0*\d{1,3}\s*', '', line, count=1, flags=re.I)
        tail = re.sub(r'^第\s*[一二三四五六七八九十\d]+\s*題\s*', '', tail)
        tail = re.sub(r'^[\.\-:：=/→>\s]+', '', tail)
        tail = re.sub(r'^(?:答案|ans)\s*[:：=→\-]*\s*', '', tail, flags=re.I)
        m = re.search(r'(?i)\b(True|False)\b|\b([A-D](?:\s*[,，]\s*[A-D])*)\b|\b(DROP|CREATE|ALTER|DELETE|SELECT|INSERT|UPDATE)\b', tail)
        if not m:
            continue
        ans = next((g for g in m.groups() if g), '')
        if re.fullmatch(r'(?i)true', ans):
            ans = '是'
        elif re.fullmatch(r'(?i)false', ans):
            ans = '否'
        else:
            ans = ans.upper().replace('，', ',').replace(' ', '')
        answers[qn] = ans
        note = (tail[:m.start()] + ' ' + tail[m.end():]).strip(' |；;()（）-:：')
        if note:
            explanations[qn] = note
    return answers, explanations


def _split_options(text: str):
    # Works with lines such as "A. foo", "A foo", and "A) foo    B) bar".
    marker = re.compile(r'(?<![A-Za-z0-9_])([A-D])(?:[\.\)]\s*|\s+)(?=\S)', re.M)
    hits = list(marker.finditer(text))
    if len(hits) < 2:
        return {}, text.strip()
    options = {}
    first = hits[0].start()
    stem = text[:first].strip()
    for i, hit in enumerate(hits):
        label = hit.group(1)
        start = hit.end()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        value = re.sub(r'\s+', ' ', text[start:end]).strip()
        if value:
            options[label] = value
    return options, stem


def _guess_type(header_and_body: str, answer: str, options: dict):
    text = header_and_body
    if '多選' in text or (',' in answer and len(answer) > 1):
        return '多選'
    if '是非' in text or answer in {'是', '否'} or re.search(r'(?i)True\s*/\s*False|正確\s*.*錯誤', text):
        return '是非'
    if '單選' in text or options:
        return '單選'
    if '填空' in text or '____' in text:
        return '填空'
    return '填空'


# A passage instruction can be extracted by PDF as the tail of option D.
# Require an explicit question range: ordinary prose mentioning reading is not
# a boundary. Keep the complete heading and passage for its own questions.
from .question_ranges import READING_RANGE as PASSAGE_INSTRUCTION, reading_ranges


def extract_by_rules(sections, default_chapter: str, allow_missing_answers=False):
    from .parsers import exam_sections
    sections=exam_sections(sections)
    image_passages={}
    for section in sections:
        for context in section.get('image_context',[]):
            if context.get('status')=='unresolved': continue
            if context.get('kind')=='choices': continue
            limits=context.get('range')
            if limits and 0<limits[0]<=limits[1]:
                for number in range(limits[0],limits[1]+1):
                    image_passages.setdefault(number,[]).append(context['text'])
    text = '\n'.join(sec.get('text', '') for sec in sections)
    answers, explanations = _answer_key(text)
    question_text = re.split(ANSWER_HEADING, text, maxsplit=1)[0]
    # A line-wrapped empty answer box belongs to the next numbered question,
    # not the previous question's final option.
    question_text=re.sub(r'(?m)^[ \t]*[（(][ \t]*\r?\n(?=[ \t]*[）)]\s*\d+[.．、:：])','',question_text)
    # Unnumbered question/answer blocks are common in pasted worksheets.
    if not any(_question_start(line) is not None for line in question_text.splitlines()):
        candidates = re.split(r'\n\s*\n+', question_text.strip())
        if candidates and all(re.search(ANSWER_LABEL+r'\s*[:：]|【'+ANSWER_LABEL+r'】', c, re.I) for c in candidates):
            question_text = '\n'.join(f'{i}. {c}' for i,c in enumerate(candidates,1))
    question_text=PASSAGE_INSTRUCTION.sub(lambda m:'\n'+m.group(0),question_text)
    lines = question_text.splitlines()
    blocks = []
    current = None
    passage = []
    passage_range = None
    for line in lines:
        instruction=PASSAGE_INSTRUCTION.match(line.strip())
        if instruction:
            limits=[x for x in instruction.groups() if x is not None]
            start,end=(int(x.translate(str.maketrans('０１２３４５６７８９','0123456789'))) for x in limits)
            if 0<start<=end:
                if current:
                    blocks.append(current)
                    current=None
                passage_range=(start,end)
                passage=[line]
                continue
        group = re.match(r'^\s*[（(【]?\s*(\d+)\s*[-–~～至]\s*(\d+)\s*[)）】]?\s*(?:題.*)?$', line)
        if group:
            if current:
                blocks.append(current)
                current = None
            passage_range = (int(group[1]), int(group[2]))
            passage = []
            continue
        qn = _question_start(line)
        if qn is not None:
            if current:
                blocks.append(current)
            shared = list(passage) if passage_range and passage_range[0] <= qn <= passage_range[1] else []
            current = {'number': qn, 'lines': [_strip_question_prefix(line)], 'passage': shared,
                       'box_answer': (re.match(r'^\s*[（(]\s*([A-D])\s*[）)]',line) or [None,''])[1]}
        elif current:
            current['lines'].append(line)
        elif passage_range:
            passage.append(line)
    if current:
        blocks.append(current)

    parsed = []
    for block in blocks:
        qn = block['number']
        body = '\n'.join(x for x in block['lines'] if x.strip()).strip()
        body = re.sub(r'(?im)^\s*(?:第[一二三四五六七八九十0-9]+頁|Page\s*\d+)(?:[^\n]*)$', '', body).strip()
        ans = answers.get(qn, '') or block.get('box_answer','')
        # Editor-friendly format: each question can carry its own answer/explanation.
        options, stem, inline_answer, inline_note = split_fields(body)
        if not options and len(list(OPTION.finditer(body))) >= 2:
            # Ambiguous/repeated choices must not be misclassified as fill-in.
            continue
        if not ans and inline_answer:
            ans = inline_answer
        if inline_note:
            explanations[qn] = inline_note
        ans = answer_text(ans)
        shared = '\n'.join(block.get('passage',[])+image_passages.get(qn,[])).strip()
        if shared:
            stem = shared + ('\n\n' + stem if stem else '')
        qtype = _guess_type(body, ans, options)

        # Remove type-only headings left at the beginning.
        stem = re.sub(r'^[\s\[【]*(?:單選題?|多選題?|是非題?|填空題?)[\]】\s:：/（）()]*', '', stem).strip()
        if not stem and allow_missing_answers and options:
            stem = f'第 {qn} 題：依題組文章選出空格的正確選項。'
        if not stem:
            continue
        if qtype in {'單選', '多選'} and (len(options) < 2 or (not ans and not allow_missing_answers)):
            continue
        if qtype in {'是非', '填空'} and not ans and not allow_missing_answers:
            continue

        item = {
            'chapter_name': default_chapter,
            'q_type': qtype,
            'content': stem,
            'answer_key': ans,
            'explanation': explanations.get(qn, ''),
            'difficulty': 2,
            'option_A': options.get('A', ''),
            'option_B': options.get('B', ''),
            'option_C': options.get('C', ''),
            'option_D': options.get('D', ''),
            '_question_no': qn,
            '_parser': 'rules',
        }
        ranges=reading_ranges(shared)
        if ranges:
            item['_shared_passage']=True
            item['_passage_range']=[ranges[0]['question_from'],ranges[0]['question_to']]
        if shared:
            item['_shared_text']=shared
            item['_question_stem']=stem[len(shared):].lstrip() if stem.startswith(shared) else stem
        # Source references, not PDF extension or question-number thresholds,
        # determine whether an answer needs the original image.
        visual_reference=re.search(r'下圖|右圖|左圖|圖中|圖示|漫畫|照片|地圖|右列資料|左列資料|\b(?:picture|comic|diagram|graph|map|photograph|figure)\b',stem,re.I)
        if visual_reference: item['_requires_vision']=True
        if ranges:
            material=shared
            for anchor in reversed(reading_ranges(material)):
                material=material[:anchor['start']]+material[anchor['end']:]
            if not material.strip(' ：:，,\n\r\t'):
                item['_requires_vision']=True
        parsed.append(item)
    return parsed


def _normalize_llm_item(item, default_chapter):
    qtype = str(item.get('q_type') or item.get('type') or '').strip()
    if qtype not in QUESTION_TYPES:
        return None
    content = str(item.get('content') or item.get('question') or '').strip()
    answer = str(item.get('answer_key') or item.get('answer') or '').strip()
    if not content or not answer:
        return None
    options = item.get('options') or {}
    if isinstance(options, list):
        options = {chr(65+i): str(v) for i, v in enumerate(options[:4])}
    result = {
        'chapter_name': str(item.get('chapter_name') or default_chapter).strip()[:120],
        'q_type': qtype,
        'content': content,
        'answer_key': answer,
        'explanation': str(item.get('explanation') or '').strip(),
        'difficulty': max(1, min(5, int(item.get('difficulty') or 2))),
    }
    for label in 'ABCD':
        result['option_'+label] = str(options.get(label) or '').strip()
    result['_parser'] = 'llm'
    return result


def extract_with_llm(sections, default_chapter: str, config, allow_missing_answers=False):
    llm = get_parser_llm(config)
    if not llm.enabled or getattr(llm, 'provider', '') == 'mock':
        raise LLMError('目前沒有可用的真實 LLM 題庫解析器；DEV Mock 只測流程，不拿來判讀題庫。')
    source='\n'.join(section.get('text','') for section in sections)
    # Answer-key rows are not question boundaries. Reattach official answers
    # by number after semantic layout, without asking the model to guess them.
    source=re.split(ANSWER_HEADING,source,maxsplit=1)[0]
    # Copy wording from source via bounded layout windows instead of asking the
    # model to reproduce long questions under an 800-token output ceiling.
    return extract_layout(source, llm, default_chapter, allow_missing_answers=allow_missing_answers)


def extract_pdf_with_vision(path: Path, default_chapter: str, config):
    """Visual fallback for PDFs whose text layer is missing or badly encoded."""
    if path.suffix.lower() != '.pdf':
        return []
    llm = get_parser_llm(config)
    if not llm.enabled or getattr(llm, 'provider', '') == 'mock':
        raise LLMError('Vision 解析需要真實模型。')
    if getattr(llm, 'provider', '') != 'ollama':
        raise LLMError('目前的 Groq GPT-OSS 使用文字輸入。掃描 PDF 請先轉為可選取文字的 PDF 或文字題庫再匯入。')
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('PDF Vision 解析需要 PyMuPDF。') from exc
    doc = fitz.open(path)
    images = []
    try:
        matrix = fitz.Matrix(1.35, 1.35)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            images.append(base64.b64encode(pix.tobytes('png')).decode('ascii'))
    finally:
        doc.close()
    system = ('你是題庫文件視覺解析器。直接閱讀 PDF 頁面圖片，忠實擷取既有考題；'
              '不得創作新題或改寫答案。答案區必須依題號對回題目。只回 JSON。'+LAYOUT_BOUNDARY_RULES+
              '此處回傳 questions，不回 parts：將適用的共用文章原文完整放入各子題 content，不放 options。')
    user = ('請擷取所有完整考題。預設章節：' + default_chapter + '\n'
            '支援單選、多選、是非、填空。\n'
            'JSON 格式：{"questions":[{"chapter_name":"...","q_type":"單選|多選|是非|填空",'
            '"content":"...","options":{"A":"...","B":"...","C":"...","D":"..."},'
            '"answer_key":"...","explanation":"","difficulty":2}]}')
    data = llm.complete_json_with_images(system, user, images)
    result = []
    for raw in (data.get('questions') if isinstance(data, dict) else []) or []:
        item = _normalize_llm_item(raw, default_chapter)
        if item:
            item['_parser'] = 'vision'
            result.append(item)
    return result

def extract_questions(path: Path, default_chapter: str, config, mode='auto'):
    from . import import_checkpoints as checkpoints
    sections=checkpoints.get('source_sections')
    if sections is None or (path.suffix.lower()=='.pdf' and mode!='rules'
                            and checkpoints.get('source_range_version')!=7):
        if path.suffix.lower()=='.pdf' and mode!='rules':
            # Preserve text-layer drafts BEFORE optional image OCR can fail.
            native=parse_file(path,include_pdf_images=False)
            drafts=extract_by_rules(native,default_chapter,allow_missing_answers=True)
            checkpoints.put('parsed_questions',drafts)
            checkpoints.put('total',len(drafts))
            checkpoints.put('stage',f'本機文字層已保存 {len(drafts)} 題草稿；CPU 圖片 OCR 中')
        sections = parse_file(path, include_pdf_images=path.suffix.lower()=='.pdf' and mode!='rules')
        checkpoints.put('source_sections',sections)
        checkpoints.put('source_range_version',7)
    checkpoints.put('stage','文件文字／OCR 已完成')
    from .parsers import exam_sections
    sections=exam_sections(sections)
    by_rules = extract_by_rules(sections, default_chapter,allow_missing_answers=mode!='rules')
    is_pdf = path.suffix.lower() == '.pdf'

    # Never accept a partial parse just because it passed a percentage threshold.
    joined = '\n'.join(sec.get('text', '') for sec in sections)
    if re.search(r'(?im)^\s*(?:[（(]\s*[E-FＥ-Ｆ]\s*[）)]|[E-FＥ-Ｆ][.．、:：)])\s*\S', joined):
        raise ValueError('偵測到 E／F 選項。目前題庫與評分只支援 A–D，請調整題型；不會捨棄額外選項。')
    if re.search(r'(?m)^\s*(?:第.{1,8}題\s*)?[【\[]?(?:申論題|問答題|簡答題|配合題|連連看)', joined):
        raise ValueError('偵測到申論／簡答／配合題，目前評分尚未支援，不會誤轉成填空題。')
    answer_count = len(_answer_key(joined)[0])
    rule_reliable = bool(by_rules)
    main = re.split(ANSWER_HEADING, joined, maxsplit=1)[0]
    numbered = {_question_start(line) for line in main.splitlines()} - {None}
    expected = max(answer_count, len(numbered))
    checkpoints.put('parsed_questions',by_rules)
    checkpoints.put('total',max(expected,len(by_rules)))
    checkpoints.put('stage',f'本機解析已保存 {len(by_rules)} 題草稿；核對題目結構')
    explicit_answer = (answer_count or
                       re.search(ANSWER_LABEL+r'\s*[:：=]|【'+ANSWER_LABEL+r'】', joined, re.I) or
                       re.search(r'(?m)^\s*[（(]\s*[A-D]\s*[）)]\s*\d', main))
    if mode!='rules':
        if mode=='llm':
            # Full-file AI review is opt-in, never an automatic fallback.
            items=extract_with_llm(sections,default_chapter,config,allow_missing_answers=True)
            parser_name='AI 全文版面核對（使用者指定）'
        else:
            from .import_routing import repair_local_questions
            items=repair_local_questions(sections,by_rules,default_chapter,config,path=path)
            parser_name='本機優先解析；AI 僅補修異常題／題組'
        if not items:
            return [],'AI 版面解析（未辨識完整題目）'
        if expected and len(items)!=expected:
            raise LLMError('AI 版面題數與原文題號不一致，請核對題組與子題；尚未推定答案。')
        official_answers,official_notes=_answer_key(joined)
        for item in items:
            number=item['_question_no']
            if number in official_answers:
                item['answer_key']=answer_text(official_answers[number])
                if number in official_notes: item['explanation']=official_notes[number]
            if item.get('_layout_needs_review'):
                item['_provided_answer']=item.get('answer_key','')
                item['answer_key']=''
        # Preserve OCR image passages for their range even if not in the text layer.
        for item in items:
            for section in sections:
                for context in section.get('image_context',[]):
                    if context.get('status')=='unresolved': continue
                    if context.get('kind')=='choices': continue
                    bounds=context.get('range')
                    if bounds and bounds[0]<=item['_question_no']<=bounds[1] and context['text'] not in item['content']:
                        item['content']=context['text']+'\n\n'+item['content']
                        item['_shared_passage']=True
                        item['_passage_range']=list(bounds)
        if any(not x.get('answer_key') for x in items):
            from .question_answering import infer_missing_answers
            items=infer_missing_answers(items,sections,path,config)
        return items,parser_name
    if numbered and not by_rules and not explicit_answer:
        raise ValueError(
            f'已辨識到 {len(numbered)} 個題號，但文件未找到明確的標準答案。'
            '題本不等於附答案的題庫，系統不會由 AI 猜答案。'
            '請將答案表與題目合併後重試（答案區下逐行填寫，例如「1. B」）。'
            + ('若文章、漫畫或地圖是圖片，還需補上題組圖片／OCR 內容；單純文字擷取可能漏掉閱讀材料。' if is_pdf else ''))
    if expected:
        rule_reliable = len(by_rules) == expected

    if not rule_reliable:
        return [], '快速規則解析（完整度不足）'
    return by_rules, '快速規則解析'

