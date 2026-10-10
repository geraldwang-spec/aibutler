import json


def bounded_json(payload, limit=9000):
    """Compact optional history only; never cut a question or source passage.

    The byte target is soft: large required evidence may exceed it. Callers
    splitting source/question batches remain responsible for complete units.
    """
    data=dict(payload) if isinstance(payload,dict) else payload
    def encode():
        return json.dumps(data,ensure_ascii=False,separators=(',',':'))
    if isinstance(data,dict) and isinstance(data.get('history'),list):
        data['history']=list(data['history'][-2:])
        while data['history'] and len(encode().encode('utf-8'))>limit:
            data['history'].pop(0)
    return encode()


def source_blocks(text, marker, target=6000):
    """Select complete ranked source blocks; never cut off within a passage."""
    import re
    blocks=re.split(r'(?m)(?=^'+re.escape(marker)+')',text)
    selected=[]
    for block in blocks:
        if not block.strip(): continue
        candidate=''.join(selected)+block
        if selected and len(candidate.encode('utf-8'))>target: break
        selected.append(block)
    return ''.join(selected)
