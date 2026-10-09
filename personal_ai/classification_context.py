"""Bound long classification inputs without silently discarding the source tail."""
import json
from .llm_provider import LLMError


def prepare(item, model):
    if item.get('_long_classification_context'):
        return item
    source = json.dumps({k:item.get(k,'') for k in
                         ('content','option_A','option_B','option_C','option_D','answer_key','explanation')},
                        ensure_ascii=False)
    if len(source.encode('utf-8')) <= 6500 or getattr(model,'provider','') == 'mock' or not model.enabled:
        return item
    # These hints are classification context only. Stored question text stays original.
    hints = []
    for start in range(0, len(source), 1500):
        fragment = source[start:start+1500]
        data = model.complete_json(
            '這是長考題的原文片段，可能跨欄位、句子或選項。只描述片段明確呈現的知識與技能，'
            '不要作答、不要推測省略內容。不要建立正式概念。每個 hint 最多 100 字，只回 JSON。',
            '原文片段：\n'+fragment+'\n回傳 {"hint":"原文明確呈現的知識／技能，若僅排版則填空字串"}')
        hint = data.get('hint') if isinstance(data,dict) else None
        if not isinstance(hint,str) or len(hint)>100:
            raise LLMError('長題概念脈絡整理格式不完整，已保留原文，請重試。')
        if hint.strip():
            hints.append(hint.strip())
    if not hints:
        raise LLMError('長題原文無法取得分類脈絡，請人工確認題目後重試。')
    text = '\n'.join(hints)
    if len(text.encode('utf-8'))>8000:
        raise LLMError('長題分類脈絡仍超過單次額度，請拆成題組；原文未截短。')
    prepared = dict(item, content='以下是完整原文逐段整理的分類脈絡，仍需人工複核：\n'+text,
                    explanation='', **{'option_'+k:'' for k in 'ABCD'})
    prepared['_long_classification_context'] = True
    return prepared


def mark_review(classification):
    classification['confidence'] = min(float(classification.get('confidence',.5)), .65)
    classification['reason'] = ('長題已分段提供全文分類脈絡；分類需人工複核。 '+
                                str(classification.get('reason') or ''))[:1000]
    return classification
