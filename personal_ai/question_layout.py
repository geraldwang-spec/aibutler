"""Source-preserving question layout parsing for long and irregular documents."""
import re
from .llm_provider import LLMError

ANSWER_LABEL = r'(?:正確答案|參考答案|答案|Answer|Ans\.?)'
NOTE_LABEL = r'(?:答案解析|解析|詳解|Explanation)'
ANSWER_HEADING = r'(?im)^\s*(?:#{1,6}\s*)?(?:答案區|答案表|參考答案表|Answer\s*Key)\s*[:：]?\s*$'
OPTION = re.compile(r'(?<![A-Za-z0-9_])(?:[（(]\s*([A-Da-dＡ-Ｄａ-ｄ])\s*[）)]|([A-Da-dＡ-Ｄａ-ｄ])[.．、:：)]\s*)')


def clean_label(value):
    return str(value).translate(str.maketrans('ＡＢＣＤａｂｃｄ', 'ABCDABCD')).upper()


def answer_text(value):
    value = re.sub(r'^\s*[【\[]?'+ANSWER_LABEL+r'[】\]]?\s*[:：=]?\s*', '', str(value), flags=re.I).strip()
    value = value.strip(' （）()')
    if re.fullmatch(r'(?i)true|正確|對|是', value):
        return '是'
    if re.fullmatch(r'(?i)false|錯誤|錯|否', value):
        return '否'
    upper = clean_label(value)
    if re.fullmatch(r'[A-D](?:[\s,，、;/／]*[A-D])*', upper):
        return ','.join(dict.fromkeys(re.findall('[A-D]', upper)))
    return value


def split_fields(body):
    """Recognize explicit answer/notes before splitting choices, not English prose."""
    fields = re.compile(r'(?im)(?:^|\n)\s*(?:[【\[]('+ANSWER_LABEL+'|'+NOTE_LABEL+r')[】\]]\s*[:：]?|('+ANSWER_LABEL+'|'+NOTE_LABEL+r')\s*[:：])\s*')
    hits = list(fields.finditer(body))
    answer, notes = '', ''
    question = body[:hits[0].start()] if hits else body
    for i, hit in enumerate(hits):
        text = body[hit.end():hits[i+1].start() if i+1 < len(hits) else len(body)].strip()
        label = hit.group(1) or hit.group(2)
        if re.fullmatch(ANSWER_LABEL, label, re.I):
            answer = answer_text(text)
        else:
            notes = text
    option_hits = list(OPTION.finditer(question))
    # Prefer parenthesized choices when present; A. in code/text is otherwise ambiguous.
    paren = [h for h in option_hits if h.group(1)]
    if len({clean_label(h.group(1)) for h in paren}) >= 2:
        option_hits = paren
    options = {}
    if len(option_hits) >= 2:
        labels = [clean_label(h.group(1) or h.group(2)) for h in option_hits]
        # Repeated labels imply merged questions or ambiguous content; do not silently overwrite.
        if len(labels) != len(set(labels)) or labels[0] != 'A':
            return {}, question.strip(), answer, notes
        stem = question[:option_hits[0].start()].strip()
        for i, hit in enumerate(option_hits):
            options[labels[i]] = question[hit.end():option_hits[i+1].start() if i+1 < len(option_hits) else len(question)].strip()
        return options, stem, answer, notes
    return {}, question.strip(), answer, notes


def source_fragments(text, width=160):
    """Keep exact source segments including newlines; splitting never drops a tail."""
    parts = []
    for line in text.splitlines(keepends=True):
        # Give inline choices and answer labels their own source segments too.
        boundaries = sorted({0, len(line)} | {m.start() for m in OPTION.finditer(line)} |
                            {m.start() for m in re.finditer(ANSWER_LABEL+r'\s*[:：]|'+NOTE_LABEL+r'\s*[:：]',line,re.I)})
        for start, end in zip(boundaries, boundaries[1:]):
            part = line[start:end]
            parts.extend(part[i:i+width] for i in range(0, len(part), width))
    return parts


def extract_layout(text, llm, chapter):
    """Ask only for field locations. Recover all wording from original fragments.

    Each bounded window must classify every fragment exactly once. No generated
    question wording or guessed answer is accepted as imported source data.
    """
    import json
    fragments = source_fragments(text)
    if not fragments:
        return []
    system = ('你是題庫版面辨識器。只標記原文片段屬於哪個欄位，不改寫、不作答。'
              '依原文順序完整涵蓋本批每個片段，同欄位連續片段合併成範圍。'
              'field 只能 content/A/B/C/D/answer/explanation/ignore。'
              '只有新題開始的 content 設 new=true，其餘 false。跨批的同一題請延續。'
              '題組文章屬於 content，不要 ignore。答案必須在原文明确給出。只回 JSON。')
    budget = max(2000, min(6500, int(getattr(llm, 'max_input_bytes', 16000)) - 2500))
    output, current = [], None
    offset = 0
    while offset < len(fragments):
        batch, byte_count = [], 0
        while offset + len(batch) < len(fragments) and len(batch) < 24:
            fragment = fragments[offset+len(batch)]
            cost = len(json.dumps(fragment, ensure_ascii=False).encode('utf-8')) + 20
            if batch and byte_count + cost > budget:
                break
            batch.append(fragment)
            byte_count += cost
        context = (current or {}).get('content', '')[-240:]
        payload = {'continuing_question_tail': context,
                   'continuing_question_has_answer': bool((current or {}).get('answer')),
                   'fragments': dict(enumerate(batch))}
        prompt = (json.dumps(payload, ensure_ascii=False) +
                  '\n回傳 JSON 物件 parts 陣列，每項有 s/e/field/new/type。'
                  's/e 是本批含首尾的片段編號，不是字數或題號。'
                  f'本批共 {len(batch)} 個片段，必須完整覆蓋 0 到 {len(batch)-1}；最後一項 e 必須是 {len(batch)-1}。'
                  '括號 A/B/C/D 開始的片段是選項；答案與解析標記後的片段分別是 answer 與 explanation。'
                  '同一題跨批延續時 new=false。背景文章後的提問句也是同一題 content，不能另設 new=true。'
                  '若 continuing_question_has_answer=false，不能只因出現提問句而開始新題。'
                  'type 只能單選/多選/是非/填空或 null。不得因片段內容相似而省略任何編號。')
        data = llm.complete_json(system, prompt)
        runs = data.get('parts') if isinstance(data, dict) else None
        if not isinstance(runs, list) or not runs:
            raise LLMError('版面辨識未回傳原文欄位，請重試或在文字工作區補上答案標記。')
        next_index = 0
        for run in runs:
            if not isinstance(run, dict):
                raise LLMError('版面辨識格式不完整。')
            start, end = run.get('s'), run.get('e')
            field = run.get('field')
            if (type(start) is not int or type(end) is not int or start != next_index
                    or end < start or end >= len(batch)
                    or field not in ('content','A','B','C','D','answer','explanation','ignore')):
                raise LLMError('版面辨識漏掉或重複原文片段，已停止匯入，原文保留。')
            next_index = end + 1
            source = ''.join(batch[start:end+1])
            if field == 'ignore':
                continue
            starts_new = run.get('new') is True
            if starts_new and current is not None and not current['answer'].strip():
                # Models often split a background passage from its final question.
                # Only honor that split before an answer if an explicit question
                # number exists; missing-answer numbered questions still fail.
                from .question_importer import _question_start
                starts_new = any(_question_start(line) is not None for line in source.splitlines())
            if field == 'content' and (starts_new or current is None):
                if current is not None:
                    output.append(current)
                current = {'content':'', 'answer':'', 'explanation':'', 'type':run.get('type'),
                           'A':'', 'B':'', 'C':'', 'D':''}
            if current is None:
                raise LLMError('版面辨識在題目之前回傳選項／答案，請檢查原文順序。')
            current[field] += source
        if next_index != len(batch):
            raise LLMError('版面辨識漏掉原文尾段，已停止匯入。')
        offset += len(batch)
    if current is not None:
        output.append(current)
    items = []
    from .question_importer import _strip_question_prefix, _guess_type
    for row in output:
        content = _strip_question_prefix(row['content']).strip()
        options = {}
        for k in 'ABCD':
            value = row[k].strip()
            marker = OPTION.match(value)
            if marker and clean_label(marker.group(1) or marker.group(2)) == k:
                value = value[marker.end():]
            options[k] = value.strip()
        answer = answer_text(row['answer'])
        qtype = row['type'] if row['type'] in ('單選','多選','是非','填空') else _guess_type(content, answer, {k:v for k,v in options.items() if v})
        if not content or not answer:
            raise LLMError('原文缺少題目或明確答案；已保留原文，請補上後重試，不會由模型猜答案。')
        if qtype in ('單選','多選') and not all(k in options and options[k] for k in answer.split(',')):
            raise LLMError('原文答案與選項未能對應，請在文字工作區確認。')
        item = dict(chapter_name=chapter,q_type=qtype,content=content,answer_key=answer,
                    explanation=re.sub(r'^\s*'+NOTE_LABEL+r'\s*[:：]?\s*','',row['explanation'],flags=re.I).strip(),difficulty=2,_parser='llm-layout')
        item.update({'option_'+k:v for k,v in options.items()})
        items.append(item)
    return items
