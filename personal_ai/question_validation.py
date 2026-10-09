"""One format contract for manual, imported and generated questions."""
import re
import unicodedata

MAX_QUESTION_CHARS = 20000
MAX_OPTION_CHARS = 10000
MAX_TEXT_BYTES = 60000  # Fits the team's existing MariaDB TEXT columns.


def normalize_answer(kind, value):
    value = unicodedata.normalize('NFKC', str(value or '')).strip()
    if kind in ('單選', '多選'):
        return ','.join(sorted(set(x.strip().upper() for x in value.replace('，', ',').split(',') if x.strip())))
    return value


def validate(data, options):
    data = dict(data)
    kind = data.get('q_type')
    if kind not in ('單選','多選','是非','填空'):
        raise ValueError('題型不正確。')
    content = str(data.get('content') or '').strip()
    answer = normalize_answer(kind,data.get('answer_key'))
    if not content or len(content) > MAX_QUESTION_CHARS or not answer or len(answer) > 50:
        raise ValueError('題目需為 1–20000 字，答案需為 1–50 字。')
    explanation = str(data.get('explanation') or '').strip()
    if len(explanation) > MAX_QUESTION_CHARS:
        raise ValueError('解析不可超過 20000 字。')
    if any(len(value.encode('utf-8')) > MAX_TEXT_BYTES for value in (content, explanation)):
        raise ValueError('單題或解析超過資料庫 60000 bytes 上限，請拆成題組；內容未截短。')
    difficulty = int(data.get('difficulty') or 2)
    if not 1 <= difficulty <= 5:
        raise ValueError('難度需為 1–5。')
    pairs = [(label,str(options.get(label) or '').strip()) for label in 'ABCD']
    pairs = [(label,text) for label,text in pairs if text]
    if any(len(text)>MAX_OPTION_CHARS or len(text.encode('utf-8'))>MAX_TEXT_BYTES for _,text in pairs):
        raise ValueError('每個選項不可超過 10000 字或 60000 bytes。')
    if kind in ('單選','多選'):
        labels = set(answer.split(','))
        if len(pairs)<2 or not labels.issubset({k for k,_ in pairs}) or (kind=='單選' and len(labels)!=1):
            raise ValueError('選擇題至少兩個選項，單選答案只能一個代號；多選使用 A,C。')
        if len({v.casefold() for _,v in pairs}) != len(pairs):
            raise ValueError('選項文字不可重複。')
    else:
        pairs=[]
        if kind=='是非' and answer not in ('是','否'):
            raise ValueError('是非題答案需為「是」或「否」。')
    data.update(content=content,answer_key=answer,explanation=explanation,difficulty=difficulty)
    return data,pairs


def correct(kind, submitted, expected):
    # Fill-in alternatives are explicit, not guessed: answer1|answer2.
    if kind=='填空':
        return normalize_answer(kind,submitted) in [normalize_answer(kind,x) for x in str(expected).split('|')]
    return normalize_answer(kind,submitted)==normalize_answer(kind,expected)


def fingerprint(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC',str(text)))
