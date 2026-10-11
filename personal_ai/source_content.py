"""Source-field hygiene shared by OCR, visual repair, and answer enrichment."""
import re
from difflib import SequenceMatcher
from .question_layout import split_fields


def _normalized(text):
    return re.sub(r'\s+','',text)


def material_only(text, item):
    """Remove copied choices/question tails, never summarize real material."""
    options,stem,_,_=split_fields(text)
    if options:
        # context is never allowed to contain answer choices, even imperfect OCR.
        text=stem
    question=item.get('_question_stem') or item.get('content','')
    question_options,question_stem,_,_=split_fields(question)
    if question_options: question=question_stem
    if len(_normalized(question))>=12:
        target=_normalized(question)
        # A repeated question tail can follow newly extracted article text.
        best=None
        for start in range(len(text)):
            if text[start].isspace(): continue
            tail=_normalized(text[start:])
            if len(tail)<len(target)*.8: break
            if len(tail)>len(target)*1.2: continue
            score=SequenceMatcher(None,tail,target).ratio()
            if score>=.95 and (best is None or score>best[0]): best=(score,start)
        if best is not None: text=text[:best[1]].rstrip()
    return text.strip()


def clean_visual_stem(content, choices):
    options,stem,_,_=split_fields(content)
    if not options: return content.strip()
    if len(options)>=2 and all(k in choices and SequenceMatcher(None,_normalized(value),_normalized(choices[k])).ratio()>=.8 for k,value in options.items()):
        return stem
    from .llm_provider import LLMError
    raise LLMError('圖片題幹混入未能對應的選項，不採用；原文保留。')
