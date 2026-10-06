"""Friendly wording without expanding the permitted evidence or data scope."""
import re

STYLE = ('語氣像親切、有耐心的學習夥伴，使用自然的繁體中文，先接住使用者的問題再說明。'
         '可以適度輕鬆、鼓勵或幽默，但不要每次都哈哈、過度撒嬌、責備使用者或假裝知道他的情緒。'
         '自然寒暄與情緒上的關心不算教材事實；具體知識與建議仍須遵守原有範圍限制。'
         '遇到資料不足時，簡短說明還缺哪些依據並給一個可行的下一步，不要使用制式拒絕公文語氣。')

def scope_reply(question, context='教材', in_chat=True):
    switch = '把下方的科目選單切換成「一般對話」' if in_chat else '到 AI 對話頁切換成「一般對話」'
    if re.search(r'早餐|午餐|晚餐|宵夜|肚子餓|吃什麼|吃甚麼|食譜', question or ''):
        return f'哈哈，肚子餓了嗎？不過目前{context}裡還沒找到這題的答案。你可以{switch}，再問一次，或許能找到一些吃飯的靈感！'
    if re.search(r'旅遊|旅行|景點|去哪玩', question or ''):
        return f'想出去走走了嗎？這個問題目前{context}裡還沒有足夠的依據。你可以{switch}，聊聊想去哪裡玩。'
    return f'這題我還缺一點{context}依據，先不亂猜，免得讓你更困惑。你可以補充相關內容或換個說法；如果想聊生活上的問題，也可以{switch}喔。'
