"""Manual cloud smoke test; sends synthetic text only, never user materials."""
import json
from dotenv import dotenv_values
from personal_ai.llm_provider import get_tutor_llm
from personal_ai.chat import GROUNDED_SCOPE, _grounded_payload, _citation_ids, _review_grounding
from personal_ai.response_style import STYLE

if __name__ == '__main__':
    model = get_tutor_llm(dotenv_values('.env'))
    # Intentionally contains no letters: test pedagogical notation, not a
    # convenient synthetic excerpt that already states the requested answer.
    chunks=[dict(id=55,material_title='合成教材',section_title='變數',
                 content='可以改變的數稱為變數。例如買一瓶水要十二元，買兩瓶水要二十四元；瓶數是自變數，總價是應變數。')]
    system=GROUNDED_SCOPE+STYLE+'通常以 250 字內說明。只回有效 JSON：'+json.dumps(
        dict(answer='回答內容',supported=True,evidence_chunk_ids=[55]),ensure_ascii=False)
    cases=[('數學好難 為什麼英文字母會變成數字',chunks,True),
           ('程式怎麼一直做一樣的事，不用一行行重寫嗎？',
            [dict(id=55,material_title='合成程式教材',section_title='迴圈',content='迴圈會重複執行一段程式。for 迴圈可逐一處理清單中的項目。例如清單含蘋果和梨子時，程式依序處理蘋果、梨子。')],True),
           ('同樣都在說過去的事，為什麼有些句子裡面是 went？',
            [dict(id=55,material_title='合成英文教材',section_title='過去式',content='一般過去式描述過去的動作。動詞 go 的過去式是 went。例如 I went to school yesterday. 表示昨天去學校。')],True),
           ('請依教材說明葉綠素如何吸收光能',chunks,False)]
    for question,evidence,expected in cases:
        result=model.complete_json(system,_grounded_payload(question,evidence,[]))
        if result.get('supported') is True:
            result=_review_grounding(model,result,_grounded_payload(question,evidence,[]))
        print(json.dumps(result,ensure_ascii=True))
        assert result.get('supported') is expected
        if expected:
            assert _citation_ids(result,{55})==[55]
            assert isinstance(result.get('answer'),str) and result['answer'].strip()
        else:
            assert result.get('evidence_chunk_ids')==[]
