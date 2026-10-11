"""Friendly wording without expanding the permitted evidence or data scope."""
import re
from .data_safety import normalized

STYLE = ('語氣像親切、有耐心的學習夥伴，使用自然的繁體中文，先接住使用者的問題再說明。'
         '可以適度輕鬆、鼓勵或幽默，但不要每次都哈哈、過度撒嬌、責備使用者或假裝知道他的情緒。'
         '自然寒暄與情緒上的關心不算教材事實；具體知識與建議仍須遵守原有範圍限制。'
         '遇到資料不足時，簡短說明還缺哪些依據並給一個可行的下一步，不要使用制式拒絕公文語氣。')

def interaction_reply(question, subject_mode=False, history=None):
    """UI help and brief social turns need no textbook evidence or model call."""
    text=normalized(question).strip()
    compact=re.sub(r'\s+', '', text).strip('。！？!?～~，,')
    if len(compact)>100:
        return None
    previous=next((str(row.get('content','')) for row in reversed(history or []) if row.get('role')=='assistant'),'')
    mode_question=('一般對話' in compact and re.search(r'什麼|甚麼|啥|意思|怎麼|如何|哪裡|在哪|切換|差別|不同',compact))
    mode_followup=('一般對話' in previous and re.fullmatch(r'(?:那|所以)?(?:要)?(?:怎麼切|怎麼切換|在哪裡|在哪|怎麼選|如何切換)',compact))
    if mode_question or mode_followup:
        from .conversation_fallback import curated_reply
        if re.search(r'切換|怎麼切|怎麼選|在哪|哪裡',compact):
            return curated_reply(question,history,scenario_id='switch_help')
        return curated_reply(question,history,scenario_id='mode_help')
    if re.fullmatch(r'(?:你好|嗨|哈囉|哈啰|hello|hi|早安|午安|晚安)(?:呀|啊|喔|哦|老師|老師好)?',compact,re.I):
        from .conversation_fallback import curated_reply
        return curated_reply(question,history,scenario_id='greeting')
    if re.fullmatch(r'(?:謝謝|谢谢|感謝|感恩|thanks|thankyou)(?:你|老師|妳|啦|喔|哦|了|幫忙)?',compact,re.I):
        from .conversation_fallback import curated_reply
        return curated_reply(question,history,scenario_id='thanks')
    if not subject_mode:
        return None
    if re.fullmatch(r'(?:你|妳|老師)(?:是誰|可以做什麼|能做什麼|會什麼|有什麼功能)',compact):
        from .conversation_fallback import curated_reply
        return curated_reply(question,history,scenario_id='capabilities')
    return None

def scope_reply(question, context='教材', in_chat=True):
    if in_chat:
        reply=interaction_reply(question,subject_mode=True)
        if reply:
            return reply
    from .conversation_fallback import curated_reply
    return curated_reply(question,in_chat=in_chat)
