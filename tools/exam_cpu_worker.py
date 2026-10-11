"""Local JSON-lines worker; ONNX sessions explicitly use CPU, never CUDA."""
import json
import sys
from collections import OrderedDict
from pathlib import Path
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sessions = {}
cache = OrderedDict()
heads = {}
ocr_engine = None


def model(name):
    if name not in sessions:
        path = ROOT / 'models' / 'exam' / name / 'onnx'
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        session = ort.InferenceSession(str(path / 'model.onnx'), options,
                                       providers=['CPUExecutionProvider'])
        tokenizer = Tokenizer.from_file(str(path / 'tokenizer.json'))
        tokenizer.enable_truncation(max_length=256)
        config = json.loads((path / 'config.json').read_text(encoding='utf-8'))
        pad_id=tokenizer.token_to_id('<pad>')
        tokenizer.enable_padding(pad_id=pad_id if pad_id is not None else config.get('pad_token_id',0), pad_token='<pad>')
        sessions[name] = session, tokenizer, config
    return sessions[name]


def infer(name, texts):
    session, tokenizer, config = model(name)
    encoded = tokenizer.encode_batch(texts)
    tensors = {'input_ids': np.array([e.ids for e in encoded], dtype=np.int64),
               'attention_mask': np.array([e.attention_mask for e in encoded], dtype=np.int64),
               'token_type_ids': np.array([e.type_ids for e in encoded], dtype=np.int64)}
    inputs = {i.name: tensors[i.name] for i in session.get_inputs()}
    return session.run(None, inputs)[0], tensors['attention_mask'], config


def embeddings(texts):
    missing = list(dict.fromkeys(t for t in texts if t not in cache))
    for start in range(0, len(missing), 8):
        batch = missing[start:start + 8]
        hidden, mask, _ = infer('embedding', batch)
        weights = mask[..., None]
        vectors = (hidden * weights).sum(axis=1) / weights.sum(axis=1).clip(min=1)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True).clip(min=1e-12)
        for text, vector in zip(batch, vectors):
            cache[text] = vector.tolist()
    result = [cache[t] for t in texts]
    while len(cache) > 2048:
        cache.popitem(last=False)
    return result


def nli(pairs):
    result = []
    for start in range(0, len(pairs), 8):
        batch = [tuple(p) for p in pairs[start:start + 8]]
        logits, _, config = infer('nli', batch)
        probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        names = {int(k): v.lower() for k, v in config['id2label'].items()}
        if 'entailment' not in names.values():
            raise RuntimeError('NLI label mapping does not declare entailment.')
        result.extend([{names[i]: float(p) for i, p in enumerate(row)} for row in probabilities])
    return result


for line in sys.stdin:
    try:
        request = json.loads(line)
        if request['op'] == 'embed':
            result = embeddings(request['texts'])
        elif request['op'] == 'nli':
            result = nli(request['pairs'])
        elif request['op'] == 'ocr':
            import base64
            from rapidocr_onnxruntime import RapidOCR
            if ocr_engine is None:
                ocr_engine=RapidOCR(det_use_cuda=False,cls_use_cuda=False,rec_use_cuda=False,
                    intra_op_num_threads=2,inter_op_num_threads=1)
            detected,_=ocr_engine(base64.b64decode(request['image']))
            result='\n'.join(row[1] for row in (detected or []))
        elif request['op'] == 'heads':
            import joblib
            result={}
            scopes=['global','subject_'+str(int(request['subject_id']))]
            for scope in scopes:
                for field in ('q_type','concept_name','skill','cognitive_level'):
                    path=ROOT/'models'/'exam'/'trained'/scope/(field+'.joblib')
                    if path.is_file():
                        key=str(path)
                        if key not in heads:
                            heads[key]=joblib.load(path)
                        estimator=heads[key]
                        probabilities=estimator.predict_proba([request['text']])[0]
                        index=int(probabilities.argmax())
                        result[field]={'label':str(estimator.classes_[index]),'raw_score':float(probabilities[index]),
                                       'status':'trained_unvalidated'}
        else:
            raise ValueError('Unsupported CPU operation')
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), flush=True)
