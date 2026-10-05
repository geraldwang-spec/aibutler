"""Audited introductory templates; answers are computed by code, not guessed."""
import random


def build(concepts, count, q_types, focus='', difficulty=1):
    # Templates are explicitly basic practice, never advertised as new scenario questions.
    if count <= 0 or '單選' not in q_types or difficulty > 2 or focus:
        return []
    result, used = [], set()
    for _ in range(count * 15):
        if len(result) >= count:
            break
        for concept in concepts:
            name = concept['name'].lower()
            if any(k in name for k in ('串列','迴圈','range','list')):
                n = random.randint(3, 30)
                stem = f'執行 list(range({n})) 後，最後一個元素與串列長度分別是多少？'
                answer = f'{n-1}、{n}'
                wrong = [f'{n}、{n}',f'{n-1}、{n-1}',f'{n}、{n+1}']
                explanation = f'range({n}) 從 0 到 {n-1}，不包含終點，所以共有 {n} 個元素。'
                expert = 'Python range／長度計算'
            elif any(k in name for k in ('條件','比較')):
                a,b = random.sample(range(2,40),2)
                stem = f'x = {a}、y = {b}，Python 運算式 x > y 的結果為何？'
                answer = 'True' if a>b else 'False'
                wrong = ['False' if a>b else 'True','None',str(a)]
                explanation = f'{a} {"大於" if a>b else "不大於"} {b}，比較結果為 {answer}。'
                expert = 'Python 比較運算'
            elif any(k in name for k in ('排序','order by')):
                values = random.sample(range(10,99),3)
                stem = f'資料表 scores 的 score 值為 {values}。SELECT score FROM scores ORDER BY score DESC 的結果順序為何？'
                answer = ', '.join(map(str,sorted(values,reverse=True)))
                wrong = [', '.join(map(str,sorted(values))),str(max(values)),str(min(values))]
                explanation = 'DESC 是降冪排序，依分數由大到小列出全部資料。'
                expert = 'SQL ORDER BY 等價排序規則'
            else:
                continue
            if stem in used:
                continue
            used.add(stem)
            choices = [answer,*wrong]
            random.shuffle(choices)
            result.append(dict(concept_id=concept['id'],concept_name=concept['name'],q_type='單選',
                content=stem,options=dict(zip('ABCD',choices)),answer_key='ABCD'[choices.index(answer)],
                explanation=explanation,evidence_chunk_ids=[],skill='基礎計算與判讀',cognitive_level='apply',
                _origin='verified_template',_expert=expert))
            if len(result) >= count:
                break
    return result
