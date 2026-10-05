import json


def bounded_json(payload, limit=9000):
    """Keep valid JSON and the latest question; shorten only optional context."""
    payload=dict(payload)
    optional=('evidence','conversation','history','lesson_steps','weakness')
    for key in optional:
        encoded=json.dumps(payload,ensure_ascii=False)
        if len(encoded.encode('utf-8'))<=limit: return encoded
        item=payload.get(key)
        if isinstance(item,str): payload[key]=item[:max(200,len(item)//3)]
        elif isinstance(item,list): payload[key]=item[-2:]
        elif isinstance(item,dict): payload[key]={}
    while len(json.dumps(payload,ensure_ascii=False).encode('utf-8'))>limit:
        candidates=[k for k in optional if isinstance(payload.get(k),str) and len(payload[k])>100]
        if not candidates: raise ValueError('問題內容太長，請縮短；系統不會截斷你的問題。')
        key=max(candidates,key=lambda k:len(payload[k])); payload[key]=payload[key][:len(payload[key])//2]
    payload['context_note']='教材或歷史可能已縮短；證據不足時請明說。'
    return json.dumps(payload,ensure_ascii=False)
